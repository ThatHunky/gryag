"""Pytest configuration and shared fixtures."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio


# Configure asyncio for tests
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[str, None]:
    """Create temporary test database with schema.

    Yields:
        Connection string to test database
    """
    import uuid

    import asyncpg

    from app.config import Settings
    from app.infrastructure.db_utils import init_database

    # Load settings to get DB config
    settings = Settings()
    base_url = settings.database_url

    # Parse URL to get credentials and host
    # Assuming format: postgresql://user:pass@host:port/dbname
    # We want to connect to 'postgres' database to create the test db
    from urllib.parse import urlparse
    parsed = urlparse(base_url)

    # Construct maintenance URL (connect to 'postgres' db)
    maintenance_url = parsed._replace(path="/postgres").geturl()

    test_db_name = f"test_gryag_{uuid.uuid4().hex}"
    test_db_url = parsed._replace(path=f"/{test_db_name}").geturl()

    # Create Test Database
    try:
        # Connect to maintenance DB to create test DB
        sys_conn = await asyncpg.connect(maintenance_url)
        await sys_conn.execute(f'CREATE DATABASE "{test_db_name}"')
        await sys_conn.close()
    except Exception as e:
        pytest.skip(f"Skipping Postgres tests: Could not connect to {maintenance_url} or create DB. Error: {e}")

    try:
        # Initialize Schema
        await init_database(test_db_url)

        yield test_db_url

    finally:
        # Close app pool to release connections
        from app.infrastructure.db_utils import close_pg_pool
        await close_pg_pool()

        # Cleanup: Drop Test Database
        try:
            sys_conn = await asyncpg.connect(maintenance_url)
            # Terminate connections to test DB before dropping
            await sys_conn.execute(
                f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{test_db_name}'
                AND pid <> pg_backend_pid();
                """
            )
            await sys_conn.execute(f'DROP DATABASE "{test_db_name}"')
            await sys_conn.close()
        except Exception as e:
            print(f"Failed to drop test database {test_db_name}: {e}")


@pytest.fixture
def sample_message():
    """Sample Telegram message for testing.

    Returns:
        Mock Message object with common fields populated
    """
    from unittest.mock import Mock

    from aiogram.types import Chat, Message, User

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
def mock_gemini_client(monkeypatch):
    """Mock Gemini client for testing.

    Returns:
        AsyncMock of GeminiClient
    """
    import sys
    from types import ModuleType, SimpleNamespace
    from unittest.mock import AsyncMock

    try:
        from app.services.gemini import GeminiClient
    except ImportError:
        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")

        class _DummySafetySetting:
            def __init__(self, *args, **kwargs):
                pass

        class _DummyGenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        types_module.SafetySetting = _DummySafetySetting
        types_module.GenerateContentConfig = _DummyGenerateContentConfig

        genai_module.Client = SimpleNamespace
        genai_module.types = types_module

        google_entry = sys.modules.setdefault("google", google_module)
        google_entry.genai = genai_module
        sys.modules["google.genai"] = genai_module
        sys.modules["google.genai.types"] = types_module

        from app.services.gemini import GeminiClient

    client = AsyncMock(spec=GeminiClient)
    client.generate.return_value = "Test response"
    client.embed_text.return_value = [0.1, 0.2, 0.3]

    return client


@pytest_asyncio.fixture
async def context_store(test_db):
    """Context store with test database.

    Returns:
        Initialized ContextStore
    """
    from app.services.context_store import ContextStore

    store = ContextStore(test_db)
    await store.init()
    return store


@pytest_asyncio.fixture
async def profile_store(test_db):
    """Profile store with test database.

    Returns:
        Initialized UserProfileStore
    """
    from app.services.user_profile import UserProfileStore

    store = UserProfileStore(test_db)
    await store.init()
    return store
