"""
Weather tool for GRYAG bot.

Provides weather information using OpenWeatherMap API.
Includes current weather and forecast capabilities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
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
tool_logger = ToolLogger("weather") if ToolLogger else None


class WeatherService:
    """Service for fetching weather data from OpenWeatherMap API."""

    def __init__(
        self, api_key: str, base_url: str = "https://api.openweathermap.org/data/2.5"
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger(f"{__name__}.WeatherService")

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

    async def get_current_weather(self, location: str) -> dict[str, Any]:
        """
        Get current weather for a location.

        Args:
            location: City name, optionally with country code (e.g., "Kyiv" or "Kyiv,UA")

        Returns:
            Dictionary with current weather data

        Raises:
            ValueError: If location is not found or API error occurs
            aiohttp.ClientError: If network error occurs
        """
        if not location.strip():
            raise ValueError("Location cannot be empty")

        session = await self._get_session()
        url = f"{self.base_url}/weather"
        params = {
            "q": location,
            "appid": self.api_key,
            "units": "metric",  # Celsius, m/s, etc.
            "lang": "uk",  # Ukrainian language for descriptions
        }

        self.logger.debug(f"Fetching current weather for: {location}")

        start_time = time.time()
        try:
            async with session.get(url, params=params) as response:
                api_duration = time.time() - start_time

                if tool_logger:
                    tool_logger.performance(
                        "api_call", api_duration, endpoint="current_weather"
                    )

                if response.status == 404:
                    self.logger.warning(f"Location not found: {location}")
                    raise ValueError("Не вдалося знайти місто")
                elif response.status == 401:
                    self.logger.error("Invalid API key for OpenWeatherMap")
                    raise ValueError("Помилка автентифікації API")
                elif response.status == 429:
                    self.logger.warning("API rate limit exceeded")
                    raise ValueError("Перевищено ліміт запитів погоди")
                elif response.status != 200:
                    self.logger.error(f"OpenWeatherMap API error: {response.status}")
                    raise ValueError("Помилка отримання даних погоди")

                data = await response.json()
                self.logger.debug(f"Successfully fetched weather for: {location}")

                return self._format_current_weather(data)

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error fetching weather: {e}")
            raise ValueError("Помилка з'єднання з сервісом погоди")

    async def get_forecast(self, location: str, days: int = 3) -> dict[str, Any]:
        """
        Get weather forecast for a location.

        Args:
            location: City name, optionally with country code
            days: Number of days for forecast (1-5)

        Returns:
            Dictionary with forecast data

        Raises:
            ValueError: If location is not found or API error occurs
            aiohttp.ClientError: If network error occurs
        """
        if not location.strip():
            raise ValueError("Location cannot be empty")

        if days < 1 or days > 5:
            raise ValueError("Forecast days must be between 1 and 5")

        session = await self._get_session()
        url = f"{self.base_url}/forecast"
        params = {
            "q": location,
            "appid": self.api_key,
            "units": "metric",
            "lang": "uk",
            "cnt": days * 8,  # 8 forecasts per day (every 3 hours)
        }

        self.logger.debug(f"Fetching {days}-day forecast for: {location}")

        start_time = time.time()
        try:
            async with session.get(url, params=params) as response:
                api_duration = time.time() - start_time

                if tool_logger:
                    tool_logger.performance(
                        "api_call", api_duration, endpoint="forecast", days=days
                    )

                if response.status == 404:
                    self.logger.warning(f"Location not found for forecast: {location}")
                    raise ValueError("Не вдалося знайти місто")
                elif response.status == 401:
                    self.logger.error("Invalid API key for OpenWeatherMap forecast")
                    raise ValueError("Помилка автентифікації API")
                elif response.status == 429:
                    self.logger.warning("API rate limit exceeded for forecast")
                    raise ValueError("Перевищено ліміт запитів погоди")
                elif response.status != 200:
                    self.logger.error(
                        f"OpenWeatherMap forecast API error: {response.status}"
                    )
                    raise ValueError("Помилка отримання прогнозу погоди")

                data = await response.json()
                self.logger.debug(
                    f"Successfully fetched {days}-day forecast for: {location}"
                )

                return self._format_forecast(data, days)

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error fetching forecast: {e}")
            raise ValueError("Помилка з'єднання з сервісом погоди")

    def _format_current_weather(self, data: dict[str, Any]) -> dict[str, Any]:
        """Format current weather API response."""
        main = data.get("main", {})
        weather = data.get("weather", [{}])[0]
        wind = data.get("wind", {})
        sys = data.get("sys", {})

        return {
            "location": f"{data.get('name', 'Unknown')}, {sys.get('country', 'XX')}",
            "temperature": round(main.get("temp", 0)),
            "feels_like": round(main.get("feels_like", 0)),
            "description": weather.get("description", "Unknown").title(),
            "humidity": main.get("humidity", 0),
            "pressure": main.get("pressure", 0),
            "wind_speed": round(wind.get("speed", 0), 1),
            "wind_direction": wind.get("deg", 0),
            "cloudiness": data.get("clouds", {}).get("all", 0),
            "visibility": (
                data.get("visibility", 0) // 1000 if data.get("visibility") else None
            ),
            "weather_icon": weather.get("icon", ""),
        }

    def _format_forecast(self, data: dict[str, Any], days: int) -> dict[str, Any]:
        """Format forecast API response."""
        city = data.get("city", {})
        forecasts = data.get("list", [])

        # Group forecasts by day (take one per day, preferably around noon)
        daily_forecasts = []
        current_day = None

        for forecast in forecasts:
            forecast_date = forecast.get("dt_txt", "").split(" ")[0]
            forecast_time = forecast.get("dt_txt", "").split(" ")[1]

            # Take the forecast closest to 12:00 for each day
            if forecast_date != current_day and len(daily_forecasts) < days:
                if forecast_time in [
                    "12:00:00",
                    "15:00:00",
                    "09:00:00",
                ]:  # Prefer midday
                    main = forecast.get("main", {})
                    weather = forecast.get("weather", [{}])[0]
                    wind = forecast.get("wind", {})

                    daily_forecasts.append(
                        {
                            "date": forecast_date,
                            "temperature": round(main.get("temp", 0)),
                            "feels_like": round(main.get("feels_like", 0)),
                            "temp_min": round(main.get("temp_min", 0)),
                            "temp_max": round(main.get("temp_max", 0)),
                            "description": weather.get(
                                "description", "Unknown"
                            ).title(),
                            "humidity": main.get("humidity", 0),
                            "wind_speed": round(wind.get("speed", 0), 1),
                            "cloudiness": forecast.get("clouds", {}).get("all", 0),
                            "weather_icon": weather.get("icon", ""),
                        }
                    )
                    current_day = forecast_date

        return {
            "location": f"{city.get('name', 'Unknown')}, {city.get('country', 'XX')}",
            "forecast_days": len(daily_forecasts),
            "forecasts": daily_forecasts,
        }


# Global weather service instance (will be initialized with config)
_weather_service: WeatherService | None = None


def _get_weather_service() -> WeatherService:
    """Get or create weather service instance."""
    global _weather_service

    if _weather_service is None:
        # Import here to avoid circular imports
        try:
            from app.config import Settings

            settings = Settings()

            if not settings.openweather_api_key:
                raise ValueError("OpenWeatherMap API key not configured")

            _weather_service = WeatherService(
                api_key=settings.openweather_api_key,
                base_url=settings.openweather_base_url,
            )
        except ImportError:
            raise ValueError("Settings not available")

    return _weather_service


@log_tool_execution("weather")
async def weather_tool(params: dict[str, Any]) -> str:
    """
    Weather tool function for GRYAG bot.

    Fetches current weather or forecast for a specified location.
    Throttled: 10 requests/hour + 30 second cooldown per user.

    Args:
        params: Tool parameters containing 'location' and optional 'forecast_days'
                         '_user_id' (internal): User ID for throttling
                         '_feature_limiter' (internal): FeatureRateLimiter instance

    Returns:
        JSON string with weather data or error
    """
    location = params.get("location", "").strip()
    forecast_days = params.get("forecast_days")

    # Extract throttling metadata (injected by chat handler)
    user_id = params.get("_user_id")
    feature_limiter = params.get("_feature_limiter")

    # Check throttling if enabled
    if user_id and feature_limiter:
        from app.config import Settings
        settings = Settings()

        if settings.enable_feature_throttling:
            # Check rate limit (requests per hour)
            allowed, retry_after, should_show_error = await feature_limiter.check_rate_limit(
                user_id=user_id,
                feature="weather",
                limit_per_hour=settings.weather_limit_per_hour,
            )

            if not allowed and should_show_error:
                minutes = retry_after // 60
                return json.dumps({
                    "error": f"⏱ Ліміт запитів погоди вичерпано. Спробуй за {minutes} хв.",
                    "throttled": True,
                    "retry_after_seconds": retry_after,
                })
            elif not allowed:
                # Silently throttled (error already shown recently)
                return json.dumps({"throttled": True, "silent": True})

            # Check cooldown (minimum time between requests)
            allowed, retry_after, should_show_error = await feature_limiter.check_cooldown(
                user_id=user_id,
                feature="weather",
            )

            if not allowed and should_show_error:
                return json.dumps({
                    "error": f"⏱ Почекай {retry_after} секунд перед наступним запитом погоди.",
                    "throttled": True,
                    "retry_after_seconds": retry_after,
                })
            elif not allowed:
                # Silently throttled
                return json.dumps({"throttled": True, "silent": True})

    if not location:
        return json.dumps(
            {
                "error": "Потрібно вказати місто або населений пункт",
                "location": location,
            }
        )

    try:
        if tool_logger:
            tool_logger.debug(
                "Fetching weather", location=location, forecast_days=forecast_days
            )

        weather_service = _get_weather_service()

        forecast_days_value: int | None = None
        if forecast_days is not None:
            try:
                if isinstance(forecast_days, str):
                    stripped = forecast_days.strip()
                    if stripped == "":
                        forecast_days_value = None
                    else:
                        forecast_days_value = int(stripped)
                elif isinstance(forecast_days, float):
                    if not forecast_days.is_integer():
                        raise ValueError
                    forecast_days_value = int(forecast_days)
                else:
                    forecast_days_value = int(forecast_days)
            except (TypeError, ValueError):
                return json.dumps(
                    {
                        "error": "Кількість днів прогнозу повинна бути цілим числом від 1 до 5",
                        "location": location,
                        "forecast_days": forecast_days,
                    }
                )

            if forecast_days_value is not None and not 1 <= forecast_days_value <= 5:
                return json.dumps(
                    {
                        "error": "Кількість днів прогнозу повинна бути в діапазоні від 1 до 5",
                        "location": location,
                        "forecast_days": forecast_days_value,
                    }
                )

        if forecast_days_value:
            # Get forecast
            result = await weather_service.get_forecast(location, forecast_days_value)
            result["type"] = "forecast"
        else:
            # Get current weather
            result = await weather_service.get_current_weather(location)
            result["type"] = "current"

        if tool_logger:
            tool_logger.debug(
                "Weather data retrieved successfully", location=result.get("location")
            )

        return json.dumps(result)

    except ValueError as e:
        if tool_logger:
            tool_logger.warning(f"Weather error: {e}", location=location)
        return json.dumps({"error": str(e), "location": location})
    except Exception as e:
        if tool_logger:
            tool_logger.error(
                f"Unexpected weather error: {e}", location=location, exc_info=True
            )
        return json.dumps(
            {"error": f"Помилка отримання погоди: {e}", "location": location}
        )


# Tool definition for registration
WEATHER_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "weather",
            "description": "Отримати поточну погоду або прогноз для міста",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Назва міста або населеного пункту (наприклад: 'Київ', 'Львів', 'Одеса')",
                    },
                    "forecast_days": {
                        "type": "integer",
                        "description": "Кількість днів прогнозу (від 1 до 5), якщо не вказано — показується поточна погода",
                    },
                },
                "required": ["location"],
            },
        }
    ]
}


# Cleanup function for proper shutdown
async def cleanup_weather_service():
    """Close weather service session."""
    global _weather_service
    if _weather_service:
        await _weather_service.close()
        _weather_service = None


if __name__ == "__main__":
    # Test the weather tool
    import os

    # Set test API key (you need to provide this)
    test_api_key = os.getenv("OPENWEATHER_API_KEY")

    if not test_api_key:
        print("Please set OPENWEATHER_API_KEY environment variable for testing")
        exit(1)

    async def test():
        # Create test service
        global _weather_service
        assert test_api_key is not None
        _weather_service = WeatherService(test_api_key)

        try:
            print("Testing weather tool...")

            # Test current weather
            result1 = await weather_tool({"location": "Kyiv"})
            print(f"Current weather in Kyiv: {result1}")

            # Test forecast
            result2 = await weather_tool({"location": "Lviv", "forecast_days": 3})
            print(f"3-day forecast for Lviv: {result2}")

            # Test error case
            result3 = await weather_tool({"location": "NonexistentCity12345"})
            print(f"Error case: {result3}")

        finally:
            await cleanup_weather_service()

    asyncio.run(test())
