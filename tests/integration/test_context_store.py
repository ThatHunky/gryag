"""Integration tests for context store."""

import pytest
from app.services.context_store import ContextStore, TurnSender


@pytest.mark.asyncio
async def test_context_store_init(test_db):
    """Test context store initialization."""
    store = ContextStore(test_db)
    await store.init()

    # Should not raise
    assert store._initialized


@pytest.mark.asyncio
async def test_add_and_retrieve_turn(context_store):
    """Test adding and retrieving conversation turns."""
    # Add user turn
    await context_store.add_turn(
        chat_id=123,
        thread_id=None,
        user_id=456,
        role="user",
        text="Hello bot",
        media=None,
        metadata={"test": "value"},
        embedding=[0.1, 0.2, 0.3],
    )

    # Retrieve history
    history = await context_store.recent(chat_id=123, thread_id=None, max_turns=10)

    assert len(history) == 1
    assert history[0]["role"] == "user"

    # Check parts contain text
    parts = history[0]["parts"]
    assert len(parts) > 0
    # Ensure speaker header is present and comes first
    assert parts[0]["text"].startswith("[speaker ")
    # Find text part containing original content
    text_values = [p["text"] for p in parts if "text" in p]
    assert any("Hello bot" in text for text in text_values)


@pytest.mark.asyncio
async def test_recent_includes_speaker_header(context_store):
    sender = TurnSender(
        role="assistant",
        name="gryag",
        username="gryag_bot",
        is_bot=True,
    )

    await context_store.add_turn(
        chat_id=555,
        thread_id=None,
        user_id=None,
        role="model",
        text="Відповідь від гряга",
        media=None,
        metadata={
            "message_id": "100",
            "name": "gryag",
            "username": "gryag_bot",
            "is_bot": True,
        },
        sender=sender,
    )

    history = await context_store.recent(chat_id=555, thread_id=None, max_turns=5)
    assert history, "Expected at least one history item"
    header_text = history[-1]["parts"][0]["text"]
    assert header_text.startswith("[speaker ")
    assert "role=assistant" in header_text
    assert 'username="gryag_bot"' in header_text
    assert "is_bot=1" in header_text


@pytest.mark.asyncio
async def test_ban_and_unban_user(context_store):
    """Test user ban/unban functionality."""
    chat_id = 123
    user_id = 456

    # Initially not banned
    assert not await context_store.is_banned(chat_id, user_id)

    # Ban user
    await context_store.ban_user(chat_id, user_id)
    assert await context_store.is_banned(chat_id, user_id)

    # Unban user
    await context_store.unban_user(chat_id, user_id)
    assert not await context_store.is_banned(chat_id, user_id)


@pytest.mark.asyncio
async def test_quota_tracking(context_store):
    """Test quota logging and counting."""
    chat_id = 123
    user_id = 456

    # Initially no requests
    count = await context_store.count_requests_last_hour(chat_id, user_id)
    assert count == 0

    # Log 3 requests
    for _ in range(3):
        await context_store.log_request(chat_id, user_id)

    # Should have 3 requests
    count = await context_store.count_requests_last_hour(chat_id, user_id)
    assert count == 3

    # Reset quotas
    await context_store.reset_quotas(chat_id)
    count = await context_store.count_requests_last_hour(chat_id, user_id)
    assert count == 0


@pytest.mark.asyncio
async def test_semantic_search(context_store, mock_gemini_client):
    """Test semantic search functionality."""
    # Add some turns with embeddings
    await context_store.add_turn(
        chat_id=123,
        thread_id=None,
        user_id=456,
        role="user",
        text="I love pizza",
        media=None,
        embedding=[0.1, 0.2, 0.3],
    )

    await context_store.add_turn(
        chat_id=123,
        thread_id=None,
        user_id=456,
        role="user",
        text="Weather is nice today",
        media=None,
        embedding=[0.9, 0.8, 0.7],
    )

    # Search for similar messages
    results = await context_store.semantic_search(
        chat_id=123,
        thread_id=None,
        query_embedding=[0.1, 0.2, 0.3],  # Similar to first message
        limit=5,
    )

    # Should find messages
    assert len(results) > 0
    # Most similar should be about pizza
    assert "pizza" in results[0]["text"].lower()
