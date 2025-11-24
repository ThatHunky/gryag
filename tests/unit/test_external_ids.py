"""Unit tests for external ID storage (Phase A implementation)."""

import json
import time

import asyncpg
import pytest

from app.services.context_store import ContextStore


@pytest.mark.asyncio
async def test_add_turn_stores_external_ids(test_db):
    """Test that add_turn correctly stores external IDs in dedicated columns."""
    store = ContextStore(test_db)
    await store.init()

    chat_id = 12345
    user_id = 67890
    message_id = 9876543210  # Large Telegram message ID
    reply_to_message_id = 1234567890
    reply_to_user_id = 11111

    # Build metadata with external IDs (as they appear in production)
    metadata = {
        "message_id": str(message_id),
        "user_id": str(user_id),
        "reply_to_message_id": str(reply_to_message_id),
        "reply_to_user_id": str(reply_to_user_id),
    }

    # Add a turn with metadata
    await store.add_message(
        chat_id=chat_id,
        thread_id=None,
        user_id=user_id,
        role="user",
        text="Test message",
        media=[],
        metadata=metadata,
    )

    # Verify external IDs are stored in dedicated columns
    conn = await asyncpg.connect(test_db)
    try:
        row = await conn.fetchrow(
            """SELECT external_message_id, external_user_id,
                      reply_to_external_message_id, reply_to_external_user_id,
                      media
               FROM messages
               WHERE chat_id = $1""",
            chat_id,
        )
    finally:
        await conn.close()

    assert row is not None, "Message should be stored"
    ext_msg_id, ext_user_id, ext_reply_msg, ext_reply_user, media_json = row

    # Verify external columns are populated
    assert ext_msg_id == str(message_id), "external_message_id should match"
    assert ext_user_id == str(user_id), "external_user_id should match"
    assert ext_reply_msg == str(
        reply_to_message_id
    ), "reply_to_external_message_id should match"
    assert ext_reply_user == str(
        reply_to_user_id
    ), "reply_to_external_user_id should match"

    # Verify JSON metadata also contains stringified IDs
    media = json.loads(media_json)
    assert media["meta"]["message_id"] == str(message_id)
    assert media["meta"]["user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_delete_by_external_id_uses_new_columns(test_db):
    """Test that delete_message_by_external_id prefers the new external_message_id column."""
    store = ContextStore(test_db)
    await store.init()

    chat_id = 12345
    user_id = 67890
    message_id = 9876543210

    # Add a message with external ID
    metadata = {"message_id": str(message_id), "user_id": str(user_id)}
    await store.add_message(
        chat_id=chat_id,
        thread_id=None,
        user_id=user_id,
        role="user",
        text="Test message to delete",
        media=[],
        metadata=metadata,
    )

    # Delete using external ID
    result = await store.delete_message_by_external_id(chat_id, message_id)
    assert result is True, "Deletion should succeed"

    # Verify message is gone
    conn = await asyncpg.connect(test_db)
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE chat_id = $1 AND external_message_id = $2",
            chat_id, str(message_id),
        )
    finally:
        await conn.close()

    assert count == 0, "Message should be deleted"


@pytest.mark.asyncio
async def test_large_telegram_ids_preserved_as_strings(test_db):
    """Test that large Telegram IDs (>2^53) are correctly stored as strings."""
    store = ContextStore(test_db)
    await store.init()

    # Use a Telegram ID larger than JavaScript's MAX_SAFE_INTEGER (2^53 - 1 = 9007199254740991)
    large_message_id = 9876543210987654  # Way beyond 2^53
    large_user_id = 1234567890123456
    chat_id = 12345

    metadata = {
        "message_id": str(large_message_id),
        "user_id": str(large_user_id),
    }

    await store.add_message(
        chat_id=chat_id,
        thread_id=None,
        user_id=123,  # Internal user_id is different from external
        role="user",
        text="Large ID test",
        media=[],
        metadata=metadata,
    )

    # Retrieve and verify no precision loss
    conn = await asyncpg.connect(test_db)
    try:
        row = await conn.fetchrow(
            "SELECT external_message_id, external_user_id FROM messages WHERE chat_id = $1",
            chat_id,
        )
    finally:
        await conn.close()

    ext_msg_id, ext_user_id = row

    # Critical: Verify exact string match (no precision loss)
    assert ext_msg_id == str(
        large_message_id
    ), f"Expected {large_message_id}, got {ext_msg_id}"
    assert ext_user_id == str(
        large_user_id
    ), f"Expected {large_user_id}, got {ext_user_id}"

    # Verify full precision is preserved (convert back to int and compare)
    assert int(ext_msg_id) == large_message_id, "Message ID should round-trip perfectly"
    assert int(ext_user_id) == large_user_id, "User ID should round-trip perfectly"


@pytest.mark.asyncio
async def test_backward_compatibility_json_fallback(test_db):
    """Test that delete_message_by_external_id falls back to JSON extraction for legacy data."""
    store = ContextStore(test_db)
    await store.init()

    chat_id = 12345
    message_id = 9876543210

    # Simulate legacy data: insert directly without populating external_* columns
    conn = await asyncpg.connect(test_db)
    try:
        await conn.execute(
            """INSERT INTO messages
               (chat_id, thread_id, user_id, role, text, media, ts)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            chat_id,
            None,
            123,
            "user",
            "Legacy message",
            json.dumps(
                {
                    "media": [],
                    "meta": {"message_id": str(message_id), "user_id": "123"},
                }
            ),
            int(time.time()),
        )
    finally:
        await conn.close()

    # Verify fallback deletion works
    result = await store.delete_message_by_external_id(chat_id, message_id)
    assert result is True, "Deletion should succeed via JSON fallback"

    # Verify message is deleted
    conn = await asyncpg.connect(test_db)
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE chat_id = $1", chat_id
        )
    finally:
        await conn.close()

    assert count == 0, "Legacy message should be deleted via JSON fallback"
