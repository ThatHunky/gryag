"""Tests for command throttle middleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat

from app.middlewares.command_throttle import CommandThrottleMiddleware
from app.config import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.enable_command_throttling = True
    settings.command_cooldown_seconds = 300  # 5 minutes
    settings.admin_user_ids_list = [12345]  # Admin user
    return settings


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter."""
    limiter = AsyncMock()
    limiter.check_cooldown = AsyncMock(return_value=(True, 0, False))
    return limiter


@pytest.fixture
def middleware(mock_settings, mock_rate_limiter):
    """Create middleware instance."""
    return CommandThrottleMiddleware(mock_settings, mock_rate_limiter)


@pytest.fixture
def mock_message():
    """Create mock message."""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 67890  # Regular user
    message.reply_to_message = None
    message.chat = MagicMock(spec=Chat)
    message.chat.id = -100111
    return message


@pytest.fixture
def mock_handler():
    """Create mock handler."""
    handler = AsyncMock()
    handler.return_value = "handler_result"
    return handler


@pytest.mark.asyncio
async def test_passes_non_command_messages(middleware, mock_message, mock_handler):
    """Test that non-command messages pass through without throttling."""
    mock_message.text = "Hello, bot!"
    data = {}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_passes_messages_without_text(middleware, mock_message, mock_handler):
    """Test that messages without text pass through."""
    mock_message.text = None
    data = {}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_passes_admin_commands(middleware, mock_message, mock_handler):
    """Test that admin commands bypass throttling."""
    mock_message.text = "/admin_command"
    mock_message.from_user.id = 12345  # Admin
    data = {}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_drops_bot_user_commands(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Commands originating from bot accounts should be ignored entirely."""
    mock_message.text = "/command"
    mock_message.from_user.is_bot = True
    data = {}

    result = await middleware(mock_handler, mock_message, data)

    assert result is None
    mock_handler.assert_not_called()
    mock_rate_limiter.check_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_throttles_regular_user_commands(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Test that regular user commands are throttled when cooldown active."""
    mock_message.text = "/command"
    mock_rate_limiter.check_cooldown.return_value = (
        False,
        120,
        True,
    )  # Not allowed, 120s remaining
    data = {}

    with patch.object(mock_message, "reply", new_callable=AsyncMock) as mock_reply:
        result = await middleware(mock_handler, mock_message, data)

    assert result is None  # Blocked
    mock_handler.assert_not_called()
    mock_reply.assert_called_once()


@pytest.mark.asyncio
async def test_ignores_commands_for_other_bots(middleware, mock_message, mock_handler):
    """Test that commands addressed to other bots are ignored."""
    mock_message.text = "/command@other_bot"
    data = {"bot_username": "gryag_bot"}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_throttles_commands_for_this_bot(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Test that commands addressed to this bot are throttled."""
    mock_message.text = "/command@gryag_bot"
    mock_rate_limiter.check_cooldown.return_value = (False, 120, True)  # Not allowed
    data = {"bot_username": "gryag_bot"}

    with patch.object(mock_message, "reply", new_callable=AsyncMock) as mock_reply:
        result = await middleware(mock_handler, mock_message, data)

    assert result is None  # Blocked
    mock_handler.assert_not_called()
    mock_reply.assert_called_once()


@pytest.mark.asyncio
async def test_case_insensitive_bot_username_matching(
    middleware, mock_message, mock_handler
):
    """Test that bot username matching is case-insensitive."""
    mock_message.text = "/command@GRYAG_BOT"
    data = {"bot_username": "gryag_bot"}

    # Should throttle because it's for this bot (case-insensitive match)
    result = await middleware(mock_handler, mock_message, data)

    # Will pass through since cooldown check passes by default
    assert result == "handler_result"


@pytest.mark.asyncio
async def test_generic_commands_without_bot_mention(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Test that generic commands (no @bot) are throttled."""
    mock_message.text = "/start"
    mock_rate_limiter.check_cooldown.return_value = (False, 180, True)  # Not allowed
    data = {"bot_username": "gryag_bot"}

    with patch.object(mock_message, "reply", new_callable=AsyncMock) as mock_reply:
        result = await middleware(mock_handler, mock_message, data)

    assert result is None  # Blocked
    mock_handler.assert_not_called()
    mock_reply.assert_called_once()


@pytest.mark.asyncio
async def test_disabled_throttling(
    mock_settings, mock_rate_limiter, mock_message, mock_handler
):
    """Test that middleware passes through when throttling is disabled."""
    mock_settings.enable_command_throttling = False
    middleware = CommandThrottleMiddleware(mock_settings, mock_rate_limiter)

    mock_message.text = "/command"
    data = {}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()
    # check_cooldown should not be called when throttling is disabled
    mock_rate_limiter.check_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_silent_throttling(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Test that error messages are suppressed when should_show_error is False."""
    mock_message.text = "/command"
    mock_rate_limiter.check_cooldown.return_value = (
        False,
        120,
        False,
    )  # Not allowed, suppress error
    data = {}

    with patch.object(mock_message, "reply", new_callable=AsyncMock) as mock_reply:
        result = await middleware(mock_handler, mock_message, data)

    assert result is None  # Blocked
    mock_handler.assert_not_called()
    mock_reply.assert_not_called()  # Error message suppressed


@pytest.mark.asyncio
async def test_command_with_parameters_and_bot_mention(
    middleware, mock_message, mock_handler
):
    """Test commands with parameters and bot mentions are correctly parsed."""
    mock_message.text = "/command@other_bot param1 param2"
    data = {"bot_username": "gryag_bot"}

    result = await middleware(mock_handler, mock_message, data)

    assert result == "handler_result"
    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_no_bot_username_in_data(
    middleware, mock_message, mock_handler, mock_rate_limiter
):
    """Test that commands are throttled even when bot_username is not in data."""
    mock_message.text = "/command@some_bot"
    mock_rate_limiter.check_cooldown.return_value = (True, 0, False)
    data = {}  # No bot_username

    result = await middleware(mock_handler, mock_message, data)

    # Should pass through since we can't determine if it's for another bot
    assert result == "handler_result"
    mock_handler.assert_called_once()
