"""
Integration tests for token budget enforcement.

Tests to ensure context layers respect token budgets and
that token optimization features work correctly.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.context.multi_level_context import MultiLevelContextManager
from app.services.context_store import ContextStore


@pytest.fixture
async def test_db(tmp_path: Path) -> Path:
    """Create a temporary test database."""
    db_path = tmp_path / "test_token_budget.db"

    # Initialize schema
    store = ContextStore(db_path)
    await store.init()

    return db_path


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with strict token budgets."""
    return Settings(
        telegram_token="test:token",
        gemini_api_key="test_api_key",
        context_token_budget=1000,  # Strict budget for testing
        immediate_context_size=3,
        recent_context_size=10,
        relevant_context_size=5,
        enable_token_tracking=True,
        enable_semantic_deduplication=True,
        deduplication_similarity_threshold=0.85,
    )


@pytest.mark.asyncio
async def test_immediate_context_respects_budget(
    test_db: Path, test_settings: Settings
):
    """Test that immediate context stays within token budget."""
    store = ContextStore(test_db)
    await store.init()

    # Add some messages
    chat_id = 123
    thread_id = None

    # Add messages with varying lengths
    for i in range(10):
        text = f"Message {i}: " + " ".join(
            [f"word{j}" for j in range(50)]
        )  # ~50 words each
        await store.add_turn(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=i,
            role="user",
            text=text,
            media=None,
        )

    # Create context manager
    manager = MultiLevelContextManager(
        db_path=test_db,
        settings=test_settings,
        context_store=store,
    )

    # Build context with strict budget
    context = await manager.build_context(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=1,
        query_text="test query",
        max_tokens=200,  # Very strict
        include_recent=False,
        include_relevant=False,
        include_background=False,
        include_episodes=False,
    )

    # Verify immediate context respects budget
    assert (
        context.immediate.token_count <= 200
    ), f"Immediate context exceeded budget: {context.immediate.token_count} > 200"

    assert len(context.immediate.messages) > 0, "Should have at least one message"
    assert (
        len(context.immediate.messages) <= test_settings.immediate_context_size
    ), "Should not exceed max immediate context size"


@pytest.mark.asyncio
async def test_total_context_respects_budget(test_db: Path, test_settings: Settings):
    """Test that total context from all layers stays within budget."""
    store = ContextStore(test_db)
    await store.init()

    chat_id = 456
    thread_id = None

    # Add many messages
    for i in range(50):
        text = f"Test message {i}: " + " ".join([f"content{j}" for j in range(30)])
        await store.add_turn(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=i % 5,
            role="user" if i % 2 == 0 else "model",
            text=text,
            media=None,
        )

    manager = MultiLevelContextManager(
        db_path=test_db,
        settings=test_settings,
        context_store=store,
    )

    # Build full context with budget
    max_tokens = test_settings.context_token_budget
    context = await manager.build_context(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=1,
        query_text="test query for search",
        max_tokens=max_tokens,
    )

    # Verify total stays within budget (allow small overage for metadata)
    overage_allowance = 1.1  # 10% allowance for metadata overhead
    assert (
        context.total_tokens <= max_tokens * overage_allowance
    ), f"Total context exceeded budget: {context.total_tokens} > {max_tokens}"


@pytest.mark.asyncio
async def test_semantic_deduplication_reduces_tokens(
    test_db: Path, test_settings: Settings
):
    """Test that semantic deduplication reduces redundant content."""
    # This test requires hybrid search implementation
    # For now, test the deduplication logic directly

    store = ContextStore(test_db)
    await store.init()

    manager = MultiLevelContextManager(
        db_path=test_db,
        settings=test_settings,
        context_store=store,
    )

    # Create duplicate snippets
    snippets = [
        {"text": "This is a test message about Python programming", "score": 0.9},
        {
            "text": "This is a test message about Python coding",
            "score": 0.85,
        },  # Similar, should be deduplicated
        {"text": "Completely different topic about cooking pasta", "score": 0.8},
        {
            "text": "This is a test message about Python programming language",
            "score": 0.75,
        },  # Similar to first
    ]

    deduplicated = manager._deduplicate_snippets(snippets)

    # Should remove similar snippets
    assert len(deduplicated) < len(
        snippets
    ), "Deduplication should remove similar snippets"
    assert len(deduplicated) >= 2, "Should keep at least distinct topics"

    # Highest scored snippet should always be kept
    assert deduplicated[0] == snippets[0], "Highest scored snippet must be kept"


@pytest.mark.asyncio
async def test_token_estimation_accuracy(test_db: Path, test_settings: Settings):
    """Test that token estimation is reasonably accurate."""
    store = ContextStore(test_db)
    await store.init()

    manager = MultiLevelContextManager(
        db_path=test_db,
        settings=test_settings,
        context_store=store,
    )

    # Test various message lengths
    test_cases = [
        ("Short message", 2),  # ~2-3 tokens
        ("This is a medium length message with several words", 10),  # ~10-13 tokens
        (" ".join(["word"] * 100), 130),  # ~130 tokens for 100 words
    ]

    for text, expected_min_tokens in test_cases:
        message = {"role": "user", "parts": [{"text": text}]}
        estimated = manager._estimate_tokens([message])

        # Estimation should be within reasonable range
        # (words * 1.3 is the heuristic)
        word_count = len(text.split())
        expected = int(word_count * 1.3)

        assert (
            estimated == expected
        ), f"Token estimation mismatch for '{text[:50]}...': {estimated} != {expected}"


@pytest.mark.asyncio
async def test_budget_allocation_percentages(test_db: Path, test_settings: Settings):
    """Test that token budget is allocated correctly across layers."""
    store = ContextStore(test_db)
    await store.init()

    chat_id = 789

    # Add enough messages to fill each layer
    for i in range(100):
        await store.add_turn(
            chat_id=chat_id,
            thread_id=None,
            user_id=i % 3,
            role="user" if i % 2 == 0 else "model",
            text=f"Message content number {i} with some padding words here",
            media=None,
        )

    manager = MultiLevelContextManager(
        db_path=test_db,
        settings=test_settings,
        context_store=store,
    )

    max_tokens = 1000
    context = await manager.build_context(
        chat_id=chat_id,
        thread_id=None,
        user_id=1,
        query_text="test",
        max_tokens=max_tokens,
    )

    # Verify allocation percentages (from build_context):
    # immediate: 20%, recent: 30%, relevant: 25%, background: 15%, episodic: 10%

    # Immediate should be roughly 20% (allow variance)
    expected_immediate = max_tokens * 0.20
    assert (
        context.immediate.token_count <= expected_immediate * 1.2
    ), f"Immediate context exceeds expected budget: {context.immediate.token_count} > {expected_immediate * 1.2}"


@pytest.mark.asyncio
async def test_empty_metadata_not_included(test_db: Path):
    """Test that empty metadata blocks are not added to messages."""
    from app.services.context_store import format_metadata

    # Empty metadata should return empty string
    assert format_metadata({}) == ""
    assert format_metadata(None) == ""

    # Metadata with only None/empty values should return empty
    assert format_metadata({"thread_id": None, "username": ""}) == ""

    # Non-empty metadata should return formatted string
    result = format_metadata({"chat_id": 123, "user_id": 456})
    assert result.startswith("[meta]")
    assert "chat_id=123" in result
    assert "user_id=456" in result


def test_compact_json_utility():
    """Test compact_json utility for tool responses."""
    from app.services.tools.base import compact_json

    # Test basic compaction
    data = {"result": 42, "status": "ok", "data": "test"}
    result = compact_json(data)

    # Should have no whitespace
    assert "\n" not in result
    assert "  " not in result

    # Should be valid JSON
    import json

    parsed = json.loads(result)
    assert parsed == data

    # Test truncation
    long_data = {"text": "x" * 1000}
    truncated = compact_json(long_data, max_length=50)
    assert len(truncated) <= 50
    assert truncated.endswith("...")


def test_truncate_text_utility():
    """Test text truncation utility."""
    from app.services.tools.base import truncate_text

    # Short text should not be truncated
    short = "This is short"
    assert truncate_text(short, max_tokens=100) == short

    # Long text should be truncated
    long = " ".join([f"word{i}" for i in range(1000)])
    truncated = truncate_text(long, max_tokens=50)

    # Should end with ellipsis
    assert truncated.endswith("...")

    # Should be shorter than original
    assert len(truncated) < len(long)

    # Word count should be roughly max_tokens * 0.75
    word_count = len(truncated.split())
    assert word_count <= 50 * 0.75 + 1  # +1 for "..."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
