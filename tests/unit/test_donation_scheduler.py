"""Tests for donation scheduler with ignored chat IDs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.donation_scheduler import DonationScheduler


@pytest.fixture
def mock_bot():
    """Create a mock Bot instance."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_context_store():
    """Create a mock ContextStore instance."""
    return MagicMock()


@pytest.fixture
def donation_scheduler(mock_bot, mock_context_store, test_db):
    """Create a donation scheduler instance with test configuration."""
    return DonationScheduler(
        bot=mock_bot,
        db_path=test_db,
        context_store=mock_context_store,
        target_chat_ids=[-100123456789, -100987654321, -100555555555],
        ignored_chat_ids=[-100987654321],  # Ignore second chat
    )


def test_ignored_chat_ids_initialization(donation_scheduler):
    """Test that ignored chat IDs are properly initialized."""
    assert -100987654321 in donation_scheduler.ignored_chat_ids
    assert len(donation_scheduler.ignored_chat_ids) == 1


def test_ignored_chat_ids_empty_list():
    """Test initialization with no ignored chats."""
    scheduler = DonationScheduler(
        bot=AsyncMock(),
        db_path="postgresql://user:pass@localhost/db",
        context_store=MagicMock(),
        target_chat_ids=[],
        ignored_chat_ids=None,
    )
    assert len(scheduler.ignored_chat_ids) == 0


@pytest.mark.asyncio
async def test_send_now_respects_ignored_list(donation_scheduler, mock_bot):
    """Test that send_now refuses to send to ignored chats when bypass_ignored=False."""
    await donation_scheduler.init()

    # Try to send to ignored chat with bypass_ignored=False
    result = await donation_scheduler.send_now(-100987654321, bypass_ignored=False)

    # Should return False and not send message
    assert result is False
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_now_allows_non_ignored_chats(donation_scheduler, mock_bot):
    """Test that send_now works for non-ignored chats."""
    await donation_scheduler.init()

    # Send to non-ignored chat
    result = await donation_scheduler.send_now(-100123456789)

    # Should return True and send message
    assert result is True
    mock_bot.send_message.assert_called_once()
    call_args = mock_bot.send_message.call_args
    assert call_args[0][0] == -100123456789  # First positional arg is chat_id


@pytest.mark.asyncio
async def test_scheduled_reminders_skip_ignored_chats(
    donation_scheduler, mock_bot, monkeypatch
):
    """Test that scheduled reminders skip ignored chats."""
    await donation_scheduler.init()

    # Mock the activity check to always return True
    async def mock_check_activity(*args):
        return True

    monkeypatch.setattr(
        donation_scheduler, "_check_recent_activity", mock_check_activity
    )

    # Mock the should_send check to always return True
    async def mock_should_send(*args):
        return True

    monkeypatch.setattr(donation_scheduler, "_should_send_to_chat", mock_should_send)

    # Run scheduled reminders for groups (all test chat IDs are negative/groups)
    await donation_scheduler._send_scheduled_reminders_groups()

    # Should only send to non-ignored chats (2 out of 3)
    assert mock_bot.send_message.call_count == 2

    # Verify it didn't send to the ignored chat
    sent_chat_ids = [call[0][0] for call in mock_bot.send_message.call_args_list]
    assert -100987654321 not in sent_chat_ids
    assert -100123456789 in sent_chat_ids
    assert -100555555555 in sent_chat_ids
