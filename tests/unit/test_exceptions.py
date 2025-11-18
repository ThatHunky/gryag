"""Unit tests for custom exception hierarchy."""

from app.core.exceptions import (
    DatabaseError,
    GeminiError,
    GryagException,
    UserProfileNotFoundError,
    ValidationError,
)


def test_gryag_exception_basic():
    """Test basic exception creation."""
    exc = GryagException("Test error")

    assert str(exc) == "Test error"
    assert exc.message == "Test error"
    assert exc.context == {}
    assert exc.cause is None


def test_gryag_exception_with_context():
    """Test exception with context."""
    exc = GryagException("Failed to process", context={"user_id": 123, "chat_id": 456})

    assert exc.context["user_id"] == 123
    assert exc.context["chat_id"] == 456
    assert "user_id=123" in str(exc)
    assert "chat_id=456" in str(exc)


def test_gryag_exception_with_cause():
    """Test exception with cause."""
    original = ValueError("Original error")
    exc = GryagException("Wrapped error", cause=original)

    assert exc.cause is original
    assert "ValueError" in str(exc)
    assert "Original error" in str(exc)


def test_gryag_exception_to_dict():
    """Test exception serialization to dict."""
    exc = DatabaseError(
        "Connection failed",
        context={"host": "localhost", "port": 5432},
        cause=Exception("Network error"),
    )

    result = exc.to_dict()

    assert result["error"] == "DatabaseError"
    assert result["message"] == "Connection failed"
    assert result["context"]["host"] == "localhost"
    assert "Network error" in result["cause"]


def test_database_error():
    """Test DatabaseError inheritance."""
    exc = DatabaseError("DB error")

    assert isinstance(exc, GryagException)
    assert isinstance(exc, DatabaseError)


def test_gemini_error():
    """Test GeminiError inheritance."""
    exc = GeminiError("API error")

    assert isinstance(exc, GryagException)
    assert isinstance(exc, GeminiError)


def test_user_profile_not_found():
    """Test UserProfileNotFoundError."""
    exc = UserProfileNotFoundError("Profile not found", context={"user_id": 999})

    assert exc.context["user_id"] == 999
    assert isinstance(exc, GryagException)


def test_validation_error():
    """Test ValidationError."""
    exc = ValidationError(
        "Invalid input", context={"field": "email", "value": "invalid"}
    )

    assert exc.context["field"] == "email"
    assert isinstance(exc, GryagException)


def test_exception_chaining():
    """Test exception chaining preserves context."""
    try:
        try:
            raise ValueError("Inner error")
        except ValueError as e:
            raise DatabaseError(
                "Outer error", context={"operation": "save"}, cause=e
            ) from None
    except DatabaseError as exc:
        assert exc.message == "Outer error"
        assert exc.context["operation"] == "save"
        assert isinstance(exc.cause, ValueError)
        assert str(exc.cause) == "Inner error"
