"""Pytest configuration and shared fixtures."""

import asyncio
import pytest
from pathlib import Path
from typing import AsyncGenerator
import aiosqlite


# Configure asyncio for tests
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db() -> AsyncGenerator[Path, None]:
    """Create temporary test database with schema.

    Yields:
        Path to test database file

    Example:
        @pytest.mark.asyncio
        async def test_something(test_db):
            async with aiosqlite.connect(test_db) as db:
                # use database
    """
    from app.services.context_store import SCHEMA_PATH

    db_path = Path("/tmp/test_gryag.db")

    # Initialize schema
    async with aiosqlite.connect(db_path) as db:
        schema_sql = SCHEMA_PATH.read_text()
        await db.executescript(schema_sql)
        await db.commit()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def sample_message():
    """Sample Telegram message for testing.

    Returns:
        Mock Message object with common fields populated
    """
    from unittest.mock import Mock
    from aiogram.types import Message, User, Chat

    user = User(
        id=123456,
        is_bot=False,
        first_name="Test",
        last_name="User",
        username="testuser",
    )

    chat = Chat(id=789012, type="group", title="Test Chat")

    message = Mock(spec=Message)
    message.message_id = 1001
    message.date = 1234567890
    message.chat = chat
    message.from_user = user
    message.text = "@gryag_bot hello"
    message.caption = None
    message.reply_to_message = None
    message.message_thread_id = None

    return message


@pytest.fixture
def mock_settings():
    """Mock settings for testing.

    Returns:
        Settings object with test values
    """
    from app.config import Settings

    return Settings(
        telegram_token="test_token",
        gemini_api_key="test_key",
        db_path=Path("/tmp/test.db"),
        max_turns=10,
        per_user_per_hour=5,
        admin_user_ids="123,456",
    )


@pytest.fixture
def mock_gemini_client():
    """Mock Gemini client for testing.

    Returns:
        AsyncMock of GeminiClient
    """
    from unittest.mock import AsyncMock
    from app.services.gemini import GeminiClient

    client = AsyncMock(spec=GeminiClient)
    client.generate.return_value = "Test response"
    client.embed_text.return_value = [0.1, 0.2, 0.3]

    return client


@pytest.fixture
async def context_store(test_db):
    """Context store with test database.

    Returns:
        Initialized ContextStore
    """
    from app.services.context_store import ContextStore

    store = ContextStore(test_db)
    await store.init()
    return store


@pytest.fixture
async def profile_store(test_db):
    """Profile store with test database.

    Returns:
        Initialized UserProfileStore
    """
    from app.services.user_profile import UserProfileStore

    store = UserProfileStore(test_db)
    await store.init()
    return store
