#!/usr/bin/env python3
"""
Test script for multi-level context manager.

Tests:
1. Context assembly with all levels
2. Token budget management
3. Parallel retrieval
4. Cache behavior
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.services.gemini import GeminiClient
from app.services.context_store import ContextStore
from app.services.user_profile import UserProfileStore
from app.services.context import (
    MultiLevelContextManager,
    HybridSearchEngine,
    EpisodicMemoryStore,
)


async def test_basic_assembly():
    """Test basic context assembly with all levels."""
    print("\n" + "=" * 80)
    print("TEST 1: Basic Context Assembly")
    print("=" * 80)

    settings = get_settings()

    # Initialize services
    context_store = ContextStore(settings.db_path)
    await context_store.init()

    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()

    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    hybrid_search = HybridSearchEngine(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    episode_store = EpisodicMemoryStore(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    # Initialize context manager
    manager = MultiLevelContextManager(
        db_path=settings.db_path,
        settings=settings,
        context_store=context_store,
        profile_store=profile_store,
        hybrid_search=hybrid_search,
        episode_store=episode_store,
    )

    # Build context
    print("\nBuilding context for query: 'What features have been implemented?'")
    print(f"Token budget: {settings.context_token_budget}")

    context = await manager.build_context(
        chat_id=1,  # Adjust based on your test data
        thread_id=None,
        user_id=1,
        query_text="What features have been implemented?",
        max_tokens=settings.context_token_budget,
    )

    print(f"\n✅ Context assembled in {context.assembly_time_ms:.1f}ms")
    print(f"   Total tokens: {context.total_tokens}/{settings.context_token_budget}")
    print(f"\n📊 Level breakdown:")
    print(
        f"   - Immediate: {context.immediate.token_count} tokens, {len(context.immediate.messages)} messages"
    )

    if context.recent:
        print(
            f"   - Recent: {context.recent.token_count} tokens, {len(context.recent.messages)} messages"
        )

    if context.relevant:
        print(
            f"   - Relevant: {context.relevant.token_count} tokens, {len(context.relevant.snippets)} snippets"
        )
        print(f"     Average relevance: {context.relevant.average_relevance:.3f}")

    if context.background:
        print(f"   - Background: {context.background.token_count} tokens")
        print(f"     Profile: {len(context.background.profile_summary or '')} chars")
        print(f"     Facts: {len(context.background.key_facts)}")

    if context.episodes:
        print(
            f"   - Episodic: {context.episodes.token_count} tokens, {len(context.episodes.episodes)} episodes"
        )

    return context


async def test_token_budgeting():
    """Test that token budgets are respected."""
    print("\n" + "=" * 80)
    print("TEST 2: Token Budget Management")
    print("=" * 80)

    settings = get_settings()

    context_store = ContextStore(settings.db_path)
    await context_store.init()

    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    manager = MultiLevelContextManager(
        db_path=settings.db_path,
        settings=settings,
        context_store=context_store,
        profile_store=None,  # Disable to test budgeting
        hybrid_search=None,
        episode_store=None,
    )

    # Test with different budgets
    budgets = [1000, 2000, 4000, 8000]

    for budget in budgets:
        context = await manager.build_context(
            chat_id=1,
            thread_id=None,
            user_id=1,
            query_text="test query",
            max_tokens=budget,
            include_recent=True,
            include_relevant=False,
            include_background=False,
            include_episodes=False,
        )

        print(f"\nBudget: {budget:5d} → Used: {context.total_tokens:5d} tokens", end="")

        if context.total_tokens <= budget:
            print(" ✅")
        else:
            print(f" ❌ OVER BUDGET by {context.total_tokens - budget}")


async def test_selective_levels():
    """Test enabling/disabling specific levels."""
    print("\n" + "=" * 80)
    print("TEST 3: Selective Level Loading")
    print("=" * 80)

    settings = get_settings()

    context_store = ContextStore(settings.db_path)
    await context_store.init()

    manager = MultiLevelContextManager(
        db_path=settings.db_path,
        settings=settings,
        context_store=context_store,
        profile_store=None,
        hybrid_search=None,
        episode_store=None,
    )

    # Test different combinations
    test_cases = [
        ("Immediate only", False, False, False, False),
        ("Immediate + Recent", True, False, False, False),
        ("All disabled except immediate", False, False, False, False),
    ]

    for name, recent, relevant, background, episodes in test_cases:
        context = await manager.build_context(
            chat_id=1,
            thread_id=None,
            user_id=1,
            query_text="test",
            include_recent=recent,
            include_relevant=relevant,
            include_background=background,
            include_episodes=episodes,
        )

        levels_loaded = []
        if context.immediate:
            levels_loaded.append("immediate")
        if context.recent:
            levels_loaded.append("recent")
        if context.relevant:
            levels_loaded.append("relevant")
        if context.background:
            levels_loaded.append("background")
        if context.episodes:
            levels_loaded.append("episodic")

        print(f"\n{name}:")
        print(f"  Loaded: {', '.join(levels_loaded)}")
        print(f"  Tokens: {context.total_tokens}")


async def test_gemini_formatting():
    """Test formatting context for Gemini API."""
    print("\n" + "=" * 80)
    print("TEST 4: Gemini API Formatting")
    print("=" * 80)

    settings = get_settings()

    context_store = ContextStore(settings.db_path)
    await context_store.init()

    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()

    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    hybrid_search = HybridSearchEngine(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    manager = MultiLevelContextManager(
        db_path=settings.db_path,
        settings=settings,
        context_store=context_store,
        profile_store=profile_store,
        hybrid_search=hybrid_search,
        episode_store=None,
    )

    # Build context
    context = await manager.build_context(
        chat_id=1,
        thread_id=None,
        user_id=1,
        query_text="What's the status of the project?",
        max_tokens=4000,
    )

    # Format for Gemini
    formatted = manager.format_for_gemini(context)

    print(f"\n✅ Formatted context for Gemini:")
    print(f"   History messages: {len(formatted['history'])}")
    print(f"   System context: {len(formatted.get('system_context') or '')} chars")
    print(f"   Total tokens: {formatted['token_count']}")

    if formatted.get("system_context"):
        print(f"\n📝 System context preview:")
        preview = formatted["system_context"][:200]
        print(f"   {preview}...")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("MULTI-LEVEL CONTEXT MANAGER TESTS")
    print("=" * 80)

    try:
        await test_basic_assembly()
        await test_token_budgeting()
        await test_selective_levels()
        await test_gemini_formatting()

        print("\n" + "=" * 80)
        print("✅ All tests completed!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Test failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
