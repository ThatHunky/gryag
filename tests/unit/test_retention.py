"""Unit tests for retention and pruning logic."""

import json
import time

import pytest

from app.infrastructure.db_utils import get_db_connection
from app.services.context_store import ContextStore


@pytest.mark.asyncio
async def test_prune_respects_episodes(test_db):
    """Test that prune_old preserves messages referenced by episodes."""
    store = ContextStore(test_db)
    await store.init()

    now = int(time.time())
    old_ts = now - 10 * 86400  # 10 days old
    new_ts = now - 1 * 86400  # 1 day old

    # Seed messages: one old, one new
    async with get_db_connection(test_db) as conn:
        await conn.execute(
            """
            INSERT INTO messages (chat_id, thread_id, user_id, role, text, media, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            1,
            None,
            123,
            "user",
            "old message",
            json.dumps({"media": [], "meta": {}}),
            old_ts,
        )
        await conn.execute(
            """
            INSERT INTO messages (chat_id, thread_id, user_id, role, text, media, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            1,
            None,
            124,
            "user",
            "new message",
            json.dumps({"media": [], "meta": {}}),
            new_ts,
        )

        # Create an episode referencing the old message
        old_id = await conn.fetchval(
            "SELECT id FROM messages WHERE text = $1", "old message"
        )

        await conn.execute(
            """
            INSERT INTO episodes (chat_id, topic, summary, message_ids, participant_ids, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            1, "test", "summary", json.dumps([old_id]), json.dumps([123]), now
        )

    # Run prune with 7-day retention -> old message (10 days) should be protected by episode
    await store.prune_old(7)

    # Verify both messages still exist
    async with get_db_connection(test_db) as conn:
        rows = await conn.fetch("SELECT text FROM messages ORDER BY id")
        texts = [r["text"] for r in rows]

    assert (
        "old message" in texts
    ), "old message referenced by episode should not be deleted"
    assert "new message" in texts, "new message should not be deleted"


@pytest.mark.asyncio
async def test_prune_deletes_old_messages(test_db):
    """Test that prune_old deletes old messages not protected by episodes."""
    store = ContextStore(test_db)
    await store.init()

    now = int(time.time())
    old_ts = now - 10 * 86400  # 10 days old
    new_ts = now - 1 * 86400  # 1 day old

    # Seed messages without episode protection
    async with get_db_connection(test_db) as conn:
        await conn.execute(
            """
            INSERT INTO messages (chat_id, thread_id, user_id, role, text, media, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            1,
            None,
            123,
            "user",
            "old unprotected",
            json.dumps({"media": [], "meta": {}}),
            old_ts,
        )
        await conn.execute(
            """
            INSERT INTO messages (chat_id, thread_id, user_id, role, text, media, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            1,
            None,
            124,
            "user",
            "new message",
            json.dumps({"media": [], "meta": {}}),
            new_ts,
        )

    # Run prune with 7-day retention
    await store.prune_old(7)

    # Verify old message is deleted, new message remains
    async with get_db_connection(test_db) as conn:
        rows = await conn.fetch("SELECT text FROM messages ORDER BY id")
        texts = [r["text"] for r in rows]

    assert "old unprotected" not in texts, "old unprotected message should be deleted"
    assert "new message" in texts, "new message should not be deleted"
