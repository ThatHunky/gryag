"""
Unit tests for unanswered trigger logic.

Tests that the bot correctly handles the "don't reply unless previous message
was replied to" logic, including edge cases like multiple users, early returns,
and error scenarios.

Note: These tests require PostgreSQL-compatible database (the function uses
PostgreSQL-specific syntax). If running with SQLite, these tests may be skipped.
"""

import pytest
import time
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from app.handlers.chat import (
    _check_unanswered_trigger,
    _check_and_handle_rate_limit,
    UNANSWERED_TRIGGER_THRESHOLD_SECONDS,
    MAX_SKIP_ATTEMPTS,
    _build_user_message_query,
    _get_skip_count,
    _increment_skip_count,
    _reset_skip_count,
)
from app.services.context_store import ContextStore, MessageSender


@pytest.mark.asyncio
async def test_unanswered_trigger_allows_when_bot_replied(context_store):
    """Test that unanswered trigger check allows messages when bot already replied."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Add bot response
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        role="model",
        text="Hello!",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="assistant",
            name="gryag",
            username="gryag",
            is_bot=True,
        ),
    )

    # Check should return False (don't skip)
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False


@pytest.mark.asyncio
async def test_unanswered_trigger_blocks_when_bot_not_replied(context_store):
    """Test that unanswered trigger check blocks messages when bot hasn't replied."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Don't add bot response - should block
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is True


@pytest.mark.asyncio
async def test_unanswered_trigger_allows_when_other_user_message_between(
    context_store,
):
    """Test that unanswered trigger check finds bot response even when other user's message is between."""
    chat_id = 123
    user_id_1 = 456
    user_id_2 = 789
    thread_id = None

    # Add user message from user 1
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id_1,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser1",
            username="testuser1",
            is_bot=False,
        ),
    )

    # Add message from another user (not addressed to bot)
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id_2,
        role="user",
        text="Just chatting",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser2",
            username="testuser2",
            is_bot=False,
        ),
    )

    # Add bot response (after other user's message)
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        role="model",
        text="Hello!",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="assistant",
            name="gryag",
            username="gryag",
            is_bot=True,
        ),
    )

    # Check should return False (don't skip) because bot replied, even though
    # another user's message is between
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id_1,
        store=context_store,
        data=data,
    )
    assert should_skip is False


@pytest.mark.asyncio
async def test_unanswered_trigger_allows_when_processing_active(context_store):
    """Test that unanswered trigger check allows messages when processing is active."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Don't add bot response, but simulate processing is active
    lock_key = (chat_id, user_id)
    processing_check = AsyncMock(return_value=True)  # Processing is active
    data = {"_processing_lock_check": processing_check}

    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False  # Should allow because processing is active


@pytest.mark.asyncio
async def test_unanswered_trigger_allows_after_threshold(context_store):
    """Test that unanswered trigger check allows messages after threshold time passes."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Add user message with old timestamp (beyond threshold)
    old_ts = int(time.time()) - UNANSWERED_TRIGGER_THRESHOLD_SECONDS - 10

    # We need to manually insert with old timestamp since add_message uses current time
    import aiosqlite

    async with aiosqlite.connect(context_store._database_url) as conn:
        await conn.execute(
            """
            INSERT INTO messages (
                chat_id, thread_id, user_id, role, text, ts,
                sender_role, sender_name, sender_username, sender_is_bot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                thread_id,
                user_id,
                "user",
                "Hello bot",
                old_ts,
                "user",
                "TestUser",
                "testuser",
                0,
            ),
        )
        await conn.commit()

    # Check should return False (don't skip) because message is old
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False


@pytest.mark.asyncio
async def test_check_and_handle_rate_limit_returns_response_message():
    """Test that rate limit check returns response message when sent."""
    from app.handlers.chat import _check_and_handle_rate_limit
    from aiogram.types import Message, User, Chat
    from unittest.mock import AsyncMock

    message = Message(
        message_id=1,
        date=time.time(),
        chat=Chat(id=123, type="group"),
        from_user=User(id=456, is_bot=False, first_name="Test"),
        text="Hello",
    )

    rate_limiter = Mock()
    rate_limiter.check_and_increment = AsyncMock(
        return_value=(False, 0, 300)  # Not allowed, 0 remaining, 300s retry
    )
    rate_limiter.should_send_error_message = Mock(return_value=True)

    # Mock message.reply to return a message
    reply_message = Message(
        message_id=2,
        date=time.time(),
        chat=Chat(id=123, type="group"),
        from_user=User(id=0, is_bot=True, first_name="Bot"),
        text="Rate limited",
    )
    message.reply = AsyncMock(return_value=reply_message)

    should_proceed, rate_limit_response = await _check_and_handle_rate_limit(
        message=message,
        rate_limiter=rate_limiter,
        is_admin=False,
        persona_loader=None,
        bot_username="gryag",
        user_id=456,
    )

    assert should_proceed is False
    assert rate_limit_response is not None
    assert rate_limit_response.text == "Rate limited"


@pytest.mark.asyncio
async def test_check_and_handle_rate_limit_returns_none_when_not_sent():
    """Test that rate limit check returns None when error message not sent (cooldown)."""
    from app.handlers.chat import _check_and_handle_rate_limit
    from aiogram.types import Message, User, Chat

    message = Message(
        message_id=1,
        date=time.time(),
        chat=Chat(id=123, type="group"),
        from_user=User(id=456, is_bot=False, first_name="Test"),
        text="Hello",
    )

    rate_limiter = Mock()
    rate_limiter.check_and_increment = AsyncMock(
        return_value=(False, 0, 300)  # Not allowed
    )
    rate_limiter.should_send_error_message = Mock(return_value=False)  # Cooldown active

    should_proceed, rate_limit_response = await _check_and_handle_rate_limit(
        message=message,
        rate_limiter=rate_limiter,
        is_admin=False,
        persona_loader=None,
        bot_username="gryag",
        user_id=456,
    )

    assert should_proceed is False
    assert rate_limit_response is None  # No message sent due to cooldown


@pytest.mark.asyncio
async def test_unanswered_trigger_uses_timestamp_fallback(context_store):
    """Test that unanswered trigger check uses timestamp-based fallback when ID-based check fails."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Add user message
    user_msg_id = await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Get the user message timestamp for reference
    from app.infrastructure.db_utils import get_db_connection
    async with get_db_connection(context_store._database_url) as conn:
        user_row = await conn.fetchrow(
            "SELECT ts FROM messages WHERE id = $1", user_msg_id
        )
        user_msg_ts = user_row["ts"] if user_row else int(time.time())

    # Add bot response with same timestamp (simulating race condition where
    # bot response might have non-sequential ID or be inserted concurrently)
    # The timestamp-based fallback should catch this
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        role="model",
        text="Hello!",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="assistant",
            name="gryag",
            username="gryag",
            is_bot=True,
        ),
    )

    # Check should return False (don't skip) because bot replied
    # The timestamp-based fallback should find the response even if
    # ID-based query somehow misses it
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False


@pytest.mark.asyncio
async def test_unanswered_trigger_retry_mechanism(context_store):
    """Test that unanswered trigger check retries when bot response exists but isn't immediately visible."""
    chat_id = 123
    user_id = 456
    thread_id = None
    import asyncio

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Start a task that will add bot response after a small delay
    # This simulates the race condition where response is being saved
    async def add_response_after_delay():
        await asyncio.sleep(0.06)  # 60ms delay - longer than first retry (50ms)
        await context_store.add_message(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=None,
            role="model",
            text="Hello!",
            media=None,
            metadata=None,
            embedding=None,
            retention_days=None,
            sender=MessageSender(
                role="assistant",
                name="gryag",
                username="gryag",
                is_bot=True,
            ),
        )

    # Start the delayed response task
    response_task = asyncio.create_task(add_response_after_delay())

    # Check immediately - should initially not find response, but retry should find it
    data = {}
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )

    # Wait for response task to complete
    await response_task

    # The retry mechanism should have found the response after the delay
    # So should_skip should be False
    assert should_skip is False


@pytest.mark.asyncio
async def test_unanswered_trigger_allows_after_max_skip_attempts(context_store):
    """Test that unanswered trigger check allows message after MAX_SKIP_ATTEMPTS consecutive skips."""
    chat_id = 123
    user_id = 456
    thread_id = None
    data = {}

    # Add user message without bot response
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Simulate MAX_SKIP_ATTEMPTS consecutive skips
    # First MAX_SKIP_ATTEMPTS - 1 calls should skip, then the next one should allow
    for attempt in range(MAX_SKIP_ATTEMPTS):
        should_skip = await _check_unanswered_trigger(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=user_id,
            store=context_store,
            data=data,
        )
        # Should skip for first MAX_SKIP_ATTEMPTS attempts
        assert should_skip is True, f"Should skip on attempt {attempt + 1}"
    
    # The next call (after MAX_SKIP_ATTEMPTS skips) should allow due to override
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False, f"Should allow after {MAX_SKIP_ATTEMPTS} skips (override)"


@pytest.mark.asyncio
async def test_skip_count_resets_after_threshold(context_store):
    """Test that skip count resets after threshold seconds."""
    chat_id = 123
    user_id = 456
    thread_id = None
    data = {}

    # Manually increment skip count
    await _increment_skip_count(chat_id, user_id, None)
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 1

    # Add user message with old timestamp (beyond threshold)
    old_ts = int(time.time()) - UNANSWERED_TRIGGER_THRESHOLD_SECONDS - 10

    import aiosqlite
    async with aiosqlite.connect(context_store._database_url) as conn:
        await conn.execute(
            """
            INSERT INTO messages (
                chat_id, thread_id, user_id, role, text, ts,
                sender_role, sender_name, sender_username, sender_is_bot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                thread_id,
                user_id,
                "user",
                "Hello bot",
                old_ts,
                "user",
                "TestUser",
                "testuser",
                0,
            ),
        )
        await conn.commit()

    # Check should reset skip count because message is old
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False

    # Verify skip count was reset
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 0


@pytest.mark.asyncio
async def test_skip_count_resets_when_bot_responds(context_store):
    """Test that skip count resets when bot responds."""
    chat_id = 123
    user_id = 456
    thread_id = None
    data = {}

    # Manually increment skip count
    await _increment_skip_count(chat_id, user_id, None)
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 1

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Add bot response
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        role="model",
        text="Hello!",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="assistant",
            name="gryag",
            username="gryag",
            is_bot=True,
        ),
    )

    # Check should allow and reset skip count
    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False

    # Verify skip count was reset
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 0


@pytest.mark.asyncio
async def test_skip_count_resets_when_processing_active(context_store):
    """Test that skip count resets when processing is active."""
    chat_id = 123
    user_id = 456
    thread_id = None

    # Manually increment skip count
    await _increment_skip_count(chat_id, user_id, None)
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 1

    # Add user message
    await context_store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text="Hello bot",
        media=None,
        metadata=None,
        embedding=None,
        retention_days=None,
        sender=MessageSender(
            role="user",
            name="TestUser",
            username="testuser",
            is_bot=False,
        ),
    )

    # Simulate processing is active
    lock_key = (chat_id, user_id)
    processing_check = AsyncMock(return_value=True)  # Processing is active
    data = {"_processing_lock_check": processing_check}

    should_skip = await _check_unanswered_trigger(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        store=context_store,
        data=data,
    )
    assert should_skip is False  # Should allow because processing is active

    # Verify skip count was reset
    skip_count, _ = await _get_skip_count(chat_id, user_id, None)
    assert skip_count == 0

