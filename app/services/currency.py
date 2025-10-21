"""
Currency exchange tool for GRYAG bot.

Provides currency exchange rates using ExchangeRate-API.
Includes conversion and rate lookup capabilities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import aiohttp

# Import logging framework
try:
    from app.services.tool_logging import log_tool_execution, ToolLogger
except ImportError:
    # Fallback if logging framework not available
    log_tool_execution = lambda name: lambda f: f  # No-op decorator
    ToolLogger = None

# Setup tool logger
tool_logger = ToolLogger("currency") if ToolLogger else None


class CurrencyService:
    """Service for fetching currency exchange rates from ExchangeRate-API."""

    def __init__(
        self, api_key: str = None, base_url: str = "https://v6.exchangerate-api.com"
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger(f"{__name__}.CurrencyService")

        # Simple in-memory cache for rates (to avoid excessive API calls)
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_duration = timedelta(hours=1)  # Cache for 1 hour

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _is_cache_valid(self, base_currency: str) -> bool:
        """Check if cached data is still valid."""
        if base_currency not in self._cache:
            return False

        cached_time = self._cache[base_currency].get("timestamp")
        if not cached_time:
            return False

        return datetime.now() - cached_time < self._cache_duration

    def _get_cached_rates(self, base_currency: str) -> dict[str, float] | None:
        """Get cached exchange rates if valid."""
        if self._is_cache_valid(base_currency):
            return self._cache[base_currency].get("rates")
        return None

    def _cache_rates(self, base_currency: str, rates: dict[str, float]):
        """Cache exchange rates with timestamp."""
        self._cache[base_currency] = {"rates": rates, "timestamp": datetime.now()}

    async def get_exchange_rates(self, base_currency: str = "USD") -> dict[str, float]:
        """
        Get exchange rates for a base currency.

        Args:
            base_currency: Currency code to use as base (e.g., "USD", "EUR", "UAH")

        Returns:
            Dictionary mapping currency codes to exchange rates

        Raises:
            ValueError: If currency is not supported or API error occurs
            aiohttp.ClientError: If network error occurs
        """
        base_currency = base_currency.upper().strip()

        if not base_currency:
            raise ValueError("Currency code cannot be empty")

        # Check cache first
        cached_rates = self._get_cached_rates(base_currency)
        if cached_rates:
            self.logger.debug(f"Using cached rates for {base_currency}")
            if tool_logger:
                tool_logger.debug("Cache hit", base_currency=base_currency)
            return cached_rates

        session = await self._get_session()

        # Use API key if available, otherwise use free endpoint
        if self.api_key:
            url = f"{self.base_url}/v6/{self.api_key}/latest/{base_currency}"
        else:
            url = f"{self.base_url}/v6/latest/{base_currency}"

        self.logger.debug(f"Fetching exchange rates for: {base_currency}")

        start_time = time.time()
        try:
            async with session.get(url) as response:
                api_duration = time.time() - start_time

                if tool_logger:
                    tool_logger.performance(
                        "api_call",
                        api_duration,
                        endpoint="exchange_rates",
                        base_currency=base_currency,
                    )

                if response.status == 404:
                    self.logger.warning(f"Currency not supported: {base_currency}")
                    raise ValueError(f"Валюта {base_currency} не підтримується")
                elif response.status == 401:
                    self.logger.error("Invalid API key for ExchangeRate-API")
                    raise ValueError("Помилка автентифікації API")
                elif response.status == 429:
                    self.logger.warning("API rate limit exceeded")
                    raise ValueError("Перевищено ліміт запитів курсу валют")
                elif response.status != 200:
                    self.logger.error(f"ExchangeRate-API error: {response.status}")
                    raise ValueError("Помилка отримання курсу валют")

                data = await response.json()

                if data.get("result") != "success":
                    error_type = data.get("error-type", "unknown")
                    self.logger.error(f"API returned error: {error_type}")

                    if error_type == "unsupported-code":
                        raise ValueError(f"Валюта {base_currency} не підтримується")
                    elif error_type == "quota-reached":
                        raise ValueError("Вичерпано ліміт запитів API")
                    else:
                        raise ValueError("Помилка API курсу валют")

                rates = data.get("conversion_rates", {})
                self.logger.debug(f"Successfully fetched rates for: {base_currency}")

                # Cache the rates
                self._cache_rates(base_currency, rates)

                return rates

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error fetching exchange rates: {e}")
            raise ValueError("Помилка з'єднання з сервісом курсу валют")

    async def convert_currency(
        self, amount: float, from_currency: str, to_currency: str
    ) -> dict[str, Any]:
        """
        Convert amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Dictionary with conversion details

        Raises:
            ValueError: If currencies are not supported or amount is invalid
        """
        if amount <= 0:
            raise ValueError("Сума повинна бути більше нуля")

        from_currency = from_currency.upper().strip()
        to_currency = to_currency.upper().strip()

        if not from_currency or not to_currency:
            raise ValueError("Коди валют не можуть бути порожніми")

        if from_currency == to_currency:
            return {
                "amount": amount,
                "from_currency": from_currency,
                "to_currency": to_currency,
                "converted_amount": amount,
                "exchange_rate": 1.0,
                "is_same_currency": True,
            }

        try:
            # Get exchange rates with from_currency as base
            rates = await self.get_exchange_rates(from_currency)

            if to_currency not in rates:
                raise ValueError(f"Валюта {to_currency} не знайдена в курсах")

            exchange_rate = rates[to_currency]
            converted_amount = round(amount * exchange_rate, 2)

            return {
                "amount": amount,
                "from_currency": from_currency,
                "to_currency": to_currency,
                "converted_amount": converted_amount,
                "exchange_rate": exchange_rate,
                "is_same_currency": False,
            }

        except Exception as e:
            if "валюта" in str(e).lower() or "currency" in str(e).lower():
                raise  # Re-raise currency-specific errors
            raise ValueError(f"Помилка конвертації валют: {e}")

    def get_popular_currencies(self) -> list[str]:
        """Get list of popular currency codes."""
        return [
            "USD",  # US Dollar
            "EUR",  # Euro
            "UAH",  # Ukrainian Hryvnia
            "GBP",  # British Pound
            "JPY",  # Japanese Yen
            "CHF",  # Swiss Franc
            "CAD",  # Canadian Dollar
            "AUD",  # Australian Dollar
            "CNY",  # Chinese Yuan
            "RUB",  # Russian Ruble
            "PLN",  # Polish Zloty
            "CZK",  # Czech Koruna
            "HUF",  # Hungarian Forint
            "RON",  # Romanian Leu
            "BGN",  # Bulgarian Lev
            "SEK",  # Swedish Krona
            "NOK",  # Norwegian Krone
            "DKK",  # Danish Krone
        ]


# Global currency service instance
_currency_service: CurrencyService | None = None


def _get_currency_service() -> CurrencyService:
    """Get or create currency service instance."""
    global _currency_service

    if _currency_service is None:
        # Import here to avoid circular imports
        try:
            from app.config import Settings

            settings = Settings()

            _currency_service = CurrencyService(
                api_key=settings.exchange_rate_api_key,  # Can be None for free tier
                base_url=settings.exchange_rate_base_url,
            )
        except ImportError:
            # Fallback to free tier without API key
            _currency_service = CurrencyService()

    return _currency_service


@log_tool_execution("currency")
async def currency_tool(params: dict[str, Any]) -> str:
    """
    Currency tool function for GRYAG bot.

    Provides currency conversion and exchange rate information.
    Throttled: 20 requests/hour + 15 second cooldown per user.

    Args:
        params: Tool parameters containing conversion details or rate request
                '_user_id' (internal): User ID for throttling
                '_feature_limiter' (internal): FeatureRateLimiter instance

    Returns:
        JSON string with currency data or error
    """
    action = params.get("action", "convert").lower()

    # Extract throttling metadata
    user_id = params.get("_user_id")
    feature_limiter = params.get("_feature_limiter")

    # Check throttling if enabled
    if user_id and feature_limiter:
        from app.config import Settings
        settings = Settings()

        if settings.enable_feature_throttling:
            # Check rate limit
            allowed, retry_after, should_show_error = await feature_limiter.check_rate_limit(
                user_id=user_id,
                feature="currency",
                limit_per_hour=settings.currency_limit_per_hour,
            )

            if not allowed and should_show_error:
                minutes = retry_after // 60
                return json.dumps({
                    "error": f"⏱ Ліміт конвертацій валют вичерпано. Спробуй за {minutes} хв.",
                    "throttled": True,
                    "retry_after_seconds": retry_after,
                })
            elif not allowed:
                # Silently throttled
                return json.dumps({"throttled": True, "silent": True})

            # Check cooldown
            allowed, retry_after, should_show_error = await feature_limiter.check_cooldown(
                user_id=user_id,
                feature="currency",
            )

            if not allowed and should_show_error:
                return json.dumps({
                    "error": f"⏱ Почекай {retry_after} секунд перед наступною конвертацією.",
                    "throttled": True,
                    "retry_after_seconds": retry_after,
                })
            elif not allowed:
                # Silently throttled
                return json.dumps({"throttled": True, "silent": True})

    try:
        if tool_logger:
            tool_logger.debug("Currency tool called", action=action, params=params)

        currency_service = _get_currency_service()

        if action == "convert":
            # Currency conversion
            amount = params.get("amount")
            from_currency = params.get("from_currency", "").strip().upper()
            to_currency = params.get("to_currency", "").strip().upper()

            if not amount or not isinstance(amount, (int, float)):
                return json.dumps(
                    {"error": "Потрібно вказати суму для конвертації", "params": params}
                )

            if not from_currency or not to_currency:
                return json.dumps(
                    {
                        "error": "Потрібно вказати коди валют (наприклад: USD, EUR, UAH)",
                        "params": params,
                    }
                )

            result = await currency_service.convert_currency(
                amount, from_currency, to_currency
            )
            result["action"] = "convert"

            if tool_logger:
                tool_logger.debug(
                    "Currency conversion completed",
                    from_currency=from_currency,
                    to_currency=to_currency,
                    amount=amount,
                )

            return json.dumps(result)

        elif action == "rates":
            # Get exchange rates
            base_currency = params.get("base_currency", "USD").strip().upper()
            target_currencies = params.get("target_currencies", [])

            rates = await currency_service.get_exchange_rates(base_currency)

            # Filter to target currencies if specified
            if target_currencies:
                target_currencies = [c.upper().strip() for c in target_currencies]
                filtered_rates = {
                    curr: rate
                    for curr, rate in rates.items()
                    if curr in target_currencies
                }
                if not filtered_rates:
                    return json.dumps(
                        {
                            "error": f"Жодна з запитаних валют не знайдена: {target_currencies}",
                            "base_currency": base_currency,
                        }
                    )
                rates = filtered_rates
            else:
                # Return only popular currencies for cleaner output
                popular = currency_service.get_popular_currencies()
                rates = {curr: rate for curr, rate in rates.items() if curr in popular}

            result = {
                "action": "rates",
                "base_currency": base_currency,
                "rates": rates,
                "rate_count": len(rates),
            }

            if tool_logger:
                tool_logger.debug(
                    "Exchange rates retrieved",
                    base_currency=base_currency,
                    rate_count=len(rates),
                )

            return json.dumps(result)

        else:
            return json.dumps(
                {
                    "error": f"Невідома дія: {action}. Доступні: 'convert', 'rates'",
                    "params": params,
                }
            )

    except ValueError as e:
        if tool_logger:
            tool_logger.warning(f"Currency error: {e}", params=params)
        return json.dumps({"error": str(e), "params": params})
    except Exception as e:
        if tool_logger:
            tool_logger.error(
                f"Unexpected currency error: {e}", params=params, exc_info=True
            )
        return json.dumps(
            {"error": f"Помилка роботи з валютами: {e}", "params": params}
        )


# Tool definition for registration
CURRENCY_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "currency",
            "description": "Конвертувати валюти або отримати курси валют",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Дія: 'convert' для конвертації або 'rates' для курсів (за замовчуванням 'convert')",
                        "enum": ["convert", "rates"],
                    },
                    "amount": {
                        "type": "number",
                        "description": "Сума для конвертації (потрібна для action='convert', повинна бути більше 0)",
                    },
                    "from_currency": {
                        "type": "string",
                        "description": "Код валюти з якої конвертувати (наприклад: USD, EUR, UAH)",
                    },
                    "to_currency": {
                        "type": "string",
                        "description": "Код валюти в яку конвертувати (наприклад: USD, EUR, UAH)",
                    },
                    "base_currency": {
                        "type": "string",
                        "description": "Базова валюта для отримання курсів (за замовчуванням USD, для action='rates')",
                    },
                    "target_currencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список валют для отримання курсів (для action='rates')",
                    },
                },
                "required": [],
            },
        }
    ]
}


# Cleanup function for proper shutdown
async def cleanup_currency_service():
    """Close currency service session."""
    global _currency_service
    if _currency_service:
        await _currency_service.close()
        _currency_service = None


if __name__ == "__main__":
    # Test the currency tool
    async def test():
        try:
            print("Testing currency tool...")

            # Test currency conversion
            result1 = await currency_tool(
                {
                    "action": "convert",
                    "amount": 100,
                    "from_currency": "USD",
                    "to_currency": "EUR",
                }
            )
            print(f"Convert 100 USD to EUR: {result1}")

            # Test exchange rates
            result2 = await currency_tool(
                {
                    "action": "rates",
                    "base_currency": "USD",
                    "target_currencies": ["EUR", "UAH", "GBP"],
                }
            )
            print(f"USD exchange rates: {result2}")

            # Test error case
            result3 = await currency_tool(
                {
                    "action": "convert",
                    "amount": 50,
                    "from_currency": "XXX",
                    "to_currency": "YYY",
                }
            )
            print(f"Error case: {result3}")

        finally:
            await cleanup_currency_service()

    asyncio.run(test())
