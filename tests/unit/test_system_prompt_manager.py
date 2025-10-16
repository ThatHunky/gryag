import sqlite3
import time

import pytest

from app.services.system_prompt_manager import SystemPromptManager
from app.services.user_profile_adapter import UserProfileStoreAdapter


@pytest.mark.asyncio
async def test_get_active_prompt_uses_cache(test_db, monkeypatch):
    manager = SystemPromptManager(test_db)
    await manager.init()

    now = int(time.time())
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            """
            INSERT INTO system_prompts (
                admin_id, chat_id, scope, prompt_text,
                is_active, version, notes,
                created_at, updated_at, activated_at
            ) VALUES (?, NULL, 'global', ?, 1, 1, ?, ?, ?, ?)
            """,
            (42, "Test prompt", "note", now, now, now),
        )
        conn.commit()

    prompt_first = await manager.get_active_prompt()
    assert prompt_first is not None
    assert manager.last_cache_hit is False

    def explode():
        raise AssertionError("get_active_prompt should use cache")

    monkeypatch.setattr(manager, "_get_connection", explode, raising=False)

    prompt_second = await manager.get_active_prompt()
    assert prompt_second is prompt_first
    assert manager.last_cache_hit is True


@pytest.mark.asyncio
async def test_get_active_prompt_caches_absence(test_db, monkeypatch):
    manager = SystemPromptManager(test_db)
    await manager.init()

    result_first = await manager.get_active_prompt()
    assert result_first is None
    assert manager.last_cache_hit is False

    def explode():
        raise AssertionError("get_active_prompt should return cached None")

    monkeypatch.setattr(manager, "_get_connection", explode, raising=False)

    result_second = await manager.get_active_prompt()
    assert result_second is None
    assert manager.last_cache_hit is True


@pytest.mark.asyncio
async def test_user_profile_adapter_init_runs_once(tmp_path, monkeypatch):
    db_path = tmp_path / "adapter.db"
    db_path.touch()

    connect_calls = {"count": 0}

    class DummyConnection:
        async def __aenter__(self):
            connect_calls["count"] += 1
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, *args, **kwargs):
            return None

        async def commit(self):
            return None

    def fake_connect(*args, **kwargs):
        return DummyConnection()

    monkeypatch.setattr(
        "app.services.user_profile_adapter.aiosqlite.connect", fake_connect
    )

    adapter = UserProfileStoreAdapter(db_path)
    await adapter.init()
    await adapter.init()

    assert connect_calls["count"] == 1
