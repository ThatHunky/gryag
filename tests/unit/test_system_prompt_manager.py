import time

import pytest

from app.infrastructure.db_utils import get_db_connection
from app.services.system_prompt_manager import SystemPromptManager
from app.services.user_profile_adapter import UserProfileStoreAdapter


@pytest.mark.asyncio
async def test_get_active_prompt_uses_cache(test_db, monkeypatch):
    manager = SystemPromptManager(test_db)
    await manager.init()

    now = int(time.time())
    async with get_db_connection(test_db) as conn:
        await conn.execute(
            """
            INSERT INTO system_prompts (
                admin_id, chat_id, scope, prompt_text,
                is_active, version, notes,
                created_at, updated_at, activated_at
            ) VALUES ($1, NULL, 'global', $2, 1, 1, $3, $4, $5, $6)
            """,
            42, "Test prompt", "note", now, now, now
        )

    prompt_first = await manager.get_active_prompt()
    assert prompt_first is not None
    assert manager.last_cache_hit is False

    # Mock _get_connection to fail if called
    def explode(*args, **kwargs):
        raise AssertionError("get_active_prompt should use cache")

    monkeypatch.setattr(manager, "_get_connection", explode, raising=False)

    prompt_second = await manager.get_active_prompt()
    assert prompt_second.id == prompt_first.id
    assert manager.last_cache_hit is True


@pytest.mark.asyncio
async def test_get_active_prompt_caches_absence(test_db, monkeypatch):
    manager = SystemPromptManager(test_db)
    await manager.init()

    result_first = await manager.get_active_prompt()
    assert result_first is None
    assert manager.last_cache_hit is False

    def explode(*args, **kwargs):
        raise AssertionError("get_active_prompt should return cached None")

    monkeypatch.setattr(manager, "_get_connection", explode, raising=False)

    result_second = await manager.get_active_prompt()
    assert result_second is None
    assert manager.last_cache_hit is True


@pytest.mark.asyncio
async def test_user_profile_adapter_init_runs_once(test_db, monkeypatch):
    # This test ensures init logic is idempotent and efficient
    # We can check if the lock is acquired or if DB calls are minimized
    # But since we are using real DB in tests now, we can just verify it doesn't crash
    # and maybe check logs if we could capture them.

    # Alternatively, we can mock get_db_connection to count calls

    connect_calls = {"count": 0}
    real_get_db_connection = get_db_connection

    class SpyConnection:
        def __init__(self, url):
            self.url = url
            self.conn = None

        async def __aenter__(self):
            connect_calls["count"] += 1
            # We need a real connection for init to work (checking tables)
            # But here we just want to count calls.
            # If we use real connection, it will work.
            self.conn_ctx = real_get_db_connection(self.url)
            self.conn = await self.conn_ctx.__aenter__()
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            await self.conn_ctx.__aexit__(exc_type, exc, tb)

    def spy_get_db_connection(url):
        return SpyConnection(url)

    # We need to patch where it is imported in user_profile_adapter
    monkeypatch.setattr(
        "app.services.user_profile_adapter.get_db_connection", spy_get_db_connection
    )

    adapter = UserProfileStoreAdapter(test_db)
    await adapter.init()
    await adapter.init()

    # init calls get_db_connection to check/create columns
    # If it runs once, it should be called once (or twice if it does multiple checks)
    # But the logic is: if self._initialized: return
    # So second call should not trigger DB connection

    first_run_count = connect_calls["count"]
    assert first_run_count > 0 # Should be at least 1

    await adapter.init()
    assert connect_calls["count"] == first_run_count # Should not increase
