"""Custom exception hierarchy for gryag bot.

This module provides semantic exception types for better error handling
and debugging throughout the application.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class GryagException(Exception):
    """Base exception for all gryag errors.

    All custom exceptions should inherit from this class to enable
    consistent error handling and context preservation.

    Attributes:
        message: Human-readable error message
        context: Additional context about the error (dict)
        cause: Original exception that caused this error

    Example:
        >>> try:
        ...     # some operation
        ... except SomeError as e:
        ...     raise DatabaseError(
        ...         "Failed to save profile",
        ...         context={"user_id": 123},
        ...         cause=e
        ...     )
    """

    def __init__(
        self,
        message: str,
        *,
        context: Dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization.

        Returns:
            Dictionary with error details
        """
        result = {
            "error": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }

        if self.cause:
            result["cause"] = str(self.cause)

        return result

    def __str__(self) -> str:
        """String representation with context."""
        parts = [self.message]

        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"({ctx_str})")

        if self.cause:
            parts.append(f"caused by {self.cause.__class__.__name__}: {self.cause}")

        return " ".join(parts)


# Domain exceptions


class UserProfileNotFoundError(GryagException):
    """User profile doesn't exist in the database.

    Raised when attempting to retrieve or update a non-existent profile.
    """

    pass


class FactExtractionError(GryagException):
    """Failed to extract facts from conversation.

    Can be raised by rule-based, local model, or Gemini extractors.
    """

    pass


class ConversationWindowError(GryagException):
    """Conversation window processing failed.

    Raised during window creation, closure, or fact extraction.
    """

    pass


class ValidationError(GryagException):
    """Input validation failed.

    Raised when user input or configuration doesn't meet requirements.
    """

    pass


# Infrastructure exceptions


class DatabaseError(GryagException):
    """Database operation failed.

    Wraps underlying database errors (aiosqlite.Error) with additional context.
    """

    pass


class ExternalAPIError(GryagException):
    """External API call failed.

    Base class for all external service errors.
    """

    pass


class GeminiError(ExternalAPIError):
    """Gemini API error.

    Raised when Google Gemini API calls fail or return unexpected responses.
    This replaces the existing GeminiError in gemini.py for consistency.
    """

    pass


class TelegramError(ExternalAPIError):
    """Telegram API error.

    Raised when Telegram Bot API calls fail.
    """

    pass


class WeatherAPIError(ExternalAPIError):
    """Weather API error.

    Raised when OpenWeatherMap API calls fail.
    """

    pass


class CurrencyAPIError(ExternalAPIError):
    """Currency API error.

    Raised when exchange rate API calls fail.
    """

    pass


# Rate limiting and circuit breaker exceptions


class RateLimitExceededError(GryagException):
    """Rate limit exceeded.

    Raised when user or system exceeds configured rate limits.
    """

    pass


class CircuitBreakerOpenError(GryagException):
    """Circuit breaker is open.

    Raised when a service is temporarily unavailable due to repeated failures.
    """

    pass


# Cache exceptions


class CacheError(GryagException):
    """Cache operation failed.

    Raised when Redis or local cache operations fail.
    """

    pass
