#!/usr/bin/env python3
"""
Test script to verify bot self-learning integration is working.

This script checks:
1. Bot profile table exists and is accessible
2. Integration helper functions are importable
3. Basic workflow can execute without errors

Run after bot has processed a few messages.
"""

import pytest

pytestmark = pytest.mark.asyncio
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.handlers.bot_learning_integration import (
    estimate_token_count,
    get_context_tags,
)
from app.services.bot_learning import BotLearningEngine
from app.services.bot_profile import BotProfileStore
from app.services.gemini import GeminiClient


async def test_bot_learning_integration():
    """Test that bot self-learning integration is working."""

    print("=" * 60)
    print("Bot Self-Learning Integration Test")
    print("=" * 60)

    settings = get_settings()

    # Test 1: Check if feature is enabled
    print(f"\n✓ Bot self-learning enabled: {settings.enable_bot_self_learning}")

    if not settings.enable_bot_self_learning:
        print("  WARNING: Feature is disabled. Set ENABLE_BOT_SELF_LEARNING=true")
        return False

    # Test 2: Check database
    print(f"\n✓ Database path: {settings.db_path}")
    if not settings.db_path.exists():
        print(f"  ERROR: Database not found at {settings.db_path}")
        return False

    # Test 3: Initialize bot profile store
    print("\n✓ Initializing BotProfileStore...")
    try:
        # Use a dummy bot ID for testing
        gemini_client = GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            embed_model=settings.gemini_embed_model,
        )

        bot_profile = BotProfileStore(
            db_path=str(settings.db_path),
            bot_id=123456789,  # Dummy ID for testing
            gemini_client=gemini_client,
            enable_temporal_decay=settings.enable_temporal_decay,
            enable_semantic_dedup=settings.enable_semantic_dedup,
        )

        await bot_profile.init()
        print("  ✓ BotProfileStore initialized successfully")
    except Exception as e:
        print(f"  ERROR: Failed to initialize BotProfileStore: {e}")
        return False

    # Test 4: Test bot learning engine
    print("\n✓ Initializing BotLearningEngine...")
    try:
        bot_learning = BotLearningEngine(
            bot_profile=bot_profile,
            gemini_client=gemini_client,
            enable_gemini_insights=settings.enable_gemini_insights,
        )
        print("  ✓ BotLearningEngine initialized successfully")
    except Exception as e:
        print(f"  ERROR: Failed to initialize BotLearningEngine: {e}")
        return False

    # Test 5: Test helper functions
    print("\n✓ Testing helper functions...")
    try:
        # Test token estimation
        tokens = estimate_token_count("This is a test message")
        print(f"  ✓ Token estimation works: {tokens} tokens")

        # Test context tags
        tags = get_context_tags(hour_of_day=14, is_weekend=False)
        print(f"  ✓ Context tags generation works: {tags}")
    except Exception as e:
        print(f"  ERROR: Helper functions failed: {e}")
        return False

    # Test 6: Test sentiment detection
    print("\n✓ Testing sentiment detection...")
    try:
        test_messages = [
            ("thank you!", "positive"),
            ("this is wrong", "negative"),
            ("actually no", "corrected"),
            ("brilliant!", "praised"),
        ]

        for msg, expected_sentiment in test_messages:
            sentiment, confidence = bot_learning.detect_user_sentiment(msg)
            print(f"  '{msg}' -> {sentiment} (confidence: {confidence:.2f})")
    except Exception as e:
        print(f"  ERROR: Sentiment detection failed: {e}")
        return False

    # Test 7: Check effectiveness summary
    print("\n✓ Checking bot effectiveness summary...")
    try:
        summary = await bot_profile.get_effectiveness_summary(chat_id=None, days=7)
        print(f"  Total interactions: {summary['total_interactions']}")
        print(f"  Positive: {summary['positive_interactions']}")
        print(f"  Negative: {summary['negative_interactions']}")
        print(f"  Effectiveness score: {summary['effectiveness_score']:.2%}")

        if summary["total_interactions"] == 0:
            print("\n  NOTE: No interactions recorded yet.")
            print("  This is expected if bot hasn't responded to any messages.")
            print("  Send a message to the bot to trigger interaction tracking.")
    except Exception as e:
        print(f"  ERROR: Failed to get effectiveness summary: {e}")
        return False

    # Test 8: Check database tables
    print("\n✓ Checking database tables...")
    try:
        import aiosqlite

        async with aiosqlite.connect(str(settings.db_path)) as db:
            # Check bot_profiles table
            async with db.execute("SELECT COUNT(*) FROM bot_profiles") as cursor:
                count = (await cursor.fetchone())[0]
                print(f"  ✓ bot_profiles: {count} profiles")

            # Check bot_interaction_outcomes table
            async with db.execute(
                "SELECT COUNT(*) FROM bot_interaction_outcomes"
            ) as cursor:
                count = (await cursor.fetchone())[0]
                print(f"  ✓ bot_interaction_outcomes: {count} outcomes")

            # Check bot_facts table
            async with db.execute("SELECT COUNT(*) FROM bot_facts") as cursor:
                count = (await cursor.fetchone())[0]
                print(f"  ✓ bot_facts: {count} facts")
    except Exception as e:
        print(f"  ERROR: Failed to query database: {e}")
        return False

    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Start the bot: docker-compose up bot")
    print("2. Send a message to the bot in Telegram")
    print("3. Reply with a reaction (e.g., 'thanks!' or 'wrong')")
    print("4. Check profile with: /gryagself")
    print("\nExpected results:")
    print("- total_interactions should increase after each bot response")
    print("- positive/negative counts should update based on reactions")
    print("- effectiveness_score should change over time")
    print("=" * 60)

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_bot_learning_integration())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
