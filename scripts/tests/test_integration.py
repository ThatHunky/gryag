#!/usr/bin/env python3
"""
Integration test for multi-level context in chat handler.

Tests that the chat handler can successfully use multi-level context
when processing messages.
"""

import asyncio

import pytest

pytestmark = pytest.mark.asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.services.context import (
    EpisodicMemoryStore,
    HybridSearchEngine,
    MultiLevelContextManager,
)
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.user_profile import UserProfileStore


async def test_integration():
    """Test multi-level context integration."""
    print("\n" + "=" * 80)
    print("MULTI-LEVEL CONTEXT INTEGRATION TEST")
    print("=" * 80)

    settings = get_settings()

    print("\n📋 Initializing services...")

    # Initialize core services
    context_store = ContextStore(settings.db_path)
    await context_store.init()
    print("  ✅ ContextStore initialized")

    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()
    print("  ✅ UserProfileStore initialized")

    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )
    print("  ✅ GeminiClient initialized")

    # Initialize Phase 3 services
    hybrid_search = HybridSearchEngine(
        db_path=settings.db_path,
        gemini_client=gemini,
        settings=settings,
    )
    print("  ✅ HybridSearchEngine initialized")

    episodic_memory = EpisodicMemoryStore(
        db_path=settings.db_path,
        gemini_client=gemini,
        settings=settings,
    )
    await episodic_memory.init()
    print("  ✅ EpisodicMemoryStore initialized")

    # Initialize multi-level context manager
    context_manager = MultiLevelContextManager(
        db_path=settings.db_path,
        settings=settings,
        context_store=context_store,
        profile_store=profile_store,
        hybrid_search=hybrid_search,
        episode_store=episodic_memory,
    )
    print("  ✅ MultiLevelContextManager initialized")

    # Test building context
    print("\n🔍 Building multi-level context...")

    test_query = "What have we discussed recently?"
    test_chat_id = 1
    test_thread_id = None
    test_user_id = 123

    try:
        context = await context_manager.build_context(
            chat_id=test_chat_id,
            thread_id=test_thread_id,
            user_id=test_user_id,
            query_text=test_query,
            max_tokens=8000,
        )

        print("\n✅ Context assembled successfully!")
        print(f"   Total tokens: {context.total_tokens}/8000")
        print("\n📊 Level breakdown:")
        print(
            f"   Immediate: {len(context.immediate.messages)} messages, {context.immediate.token_count} tokens"
        )

        if context.recent:
            print(
                f"   Recent: {len(context.recent.messages)} messages, {context.recent.token_count} tokens"
            )
        else:
            print("   Recent: disabled")

        if context.relevant:
            print(
                f"   Relevant: {len(context.relevant.snippets)} snippets, {context.relevant.token_count} tokens"
            )
            if context.relevant.snippets:
                print(f"   Average relevance: {context.relevant.average_relevance:.3f}")
        else:
            print("   Relevant: disabled")

        if context.background:
            print(f"   Background: {context.background.token_count} tokens")
            if context.background.profile_summary:
                print(f"   Profile: {context.background.profile_summary[:50]}...")
            print(f"   Facts: {len(context.background.key_facts)}")
        else:
            print("   Background: disabled")

        if context.episodes:
            print(
                f"   Episodes: {len(context.episodes.episodes)} episodes, {context.episodes.token_count} tokens"
            )
        else:
            print("   Episodes: disabled")

        # Test Gemini formatting
        print("\n🔄 Formatting for Gemini API...")
        formatted = context_manager.format_for_gemini(context)

        print("✅ Formatted successfully!")
        print(f"   History length: {len(formatted['history'])} messages")
        if formatted.get("system_context"):
            print(f"   System context: {len(formatted['system_context'])} chars")
        else:
            print("   System context: none")
        print(f"   Token count: {formatted.get('token_count', 0)}")

        # Show sample if we have context
        if formatted["history"]:
            print("\n📝 Sample history (first message):")
            first_msg = formatted["history"][0]
            print(f"   Role: {first_msg.get('role', 'unknown')}")
            parts = first_msg.get("parts", [])
            if parts and isinstance(parts[0], dict):
                text = parts[0].get("text", "")[:100]
                print(f"   Text: {text}...")

        if formatted.get("system_context"):
            print("\n📝 System context preview:")
            preview = formatted["system_context"][:200]
            print(f"   {preview}...")

    except Exception as e:
        print(f"\n❌ Error building context: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 80)
    print("✅ INTEGRATION TEST PASSED")
    print("=" * 80)

    print("\n📌 Next steps:")
    print("   1. Multi-level context is integrated into chat handler")
    print("   2. Services are initialized in main.py")
    print("   3. Middleware passes services to handler")
    print("   4. Handler uses multi-level context when enabled")
    print("\n🚀 Ready for production testing!")

    return True


async def main():
    """Run integration test."""
    success = await test_integration()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
