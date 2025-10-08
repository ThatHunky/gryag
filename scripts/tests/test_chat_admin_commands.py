#!/usr/bin/env python3
"""
Test script for chat admin commands.

Simulates the chat admin command flow without requiring a live Telegram bot.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.repositories.chat_profile import ChatProfileRepository, ChatFact


async def test_chat_admin_commands():
    """Test chat admin command functionality."""
    print("🧪 Testing Chat Admin Commands\n")

    # Initialize settings and repository
    settings = get_settings()
    repo = ChatProfileRepository(db_path=str(settings.db_path))

    test_chat_id = -1001234567890  # Fake group chat ID

    print("1️⃣ Creating test chat profile...")
    profile = await repo.get_or_create_profile(
        chat_id=test_chat_id, chat_type="supergroup", chat_title="Test Group Chat"
    )
    print(f"   ✅ Profile created: {profile.chat_title}")

    print("\n2️⃣ Adding test facts...")
    test_facts = [
        {
            "category": "language",
            "key": "preferred_language",
            "value": "Ukrainian",
            "description": "We prefer Ukrainian in this chat",
            "confidence": 0.9,
            "evidence": "User said: we prefer Ukrainian here",
        },
        {
            "category": "culture",
            "key": "emoji_usage",
            "value": "high",
            "description": "Chat uses lots of emojis 🎉",
            "confidence": 0.8,
            "evidence": "Statistical: 45% of messages contain emojis",
        },
        {
            "category": "norms",
            "key": "formality",
            "value": "informal",
            "description": "Chat is very informal and friendly",
            "confidence": 0.85,
            "evidence": "Analysis of 50 messages",
        },
        {
            "category": "preferences",
            "key": "topic_tech",
            "value": "true",
            "description": "Group often discusses tech topics",
            "confidence": 0.75,
            "evidence": "20% of conversations are about technology",
        },
    ]

    for fact_data in test_facts:
        fact_id = await repo.add_chat_fact(
            chat_id=test_chat_id,
            category=fact_data["category"],
            fact_key=fact_data["key"],
            fact_value=fact_data["value"],
            fact_description=fact_data["description"],
            confidence=fact_data["confidence"],
            evidence_text=fact_data["evidence"],
        )
        print(f"   ✅ Added fact: {fact_data['description']} (ID: {fact_id})")

    print("\n3️⃣ Testing get_all_facts...")
    all_facts = await repo.get_all_facts(chat_id=test_chat_id)
    print(f"   ✅ Retrieved {len(all_facts)} facts")

    for fact in all_facts:
        print(
            f"      • [{fact.fact_category}] {fact.fact_description or fact.fact_key}"
        )
        print(
            f"        Confidence: {int(fact.confidence * 100)}%, Evidence: {fact.evidence_count}"
        )

    print("\n4️⃣ Testing get_chat_summary...")
    summary = await repo.get_chat_summary(
        chat_id=test_chat_id,
        max_facts=8,
    )
    print(f"   ✅ Summary generated:")
    print(f"   {summary[:200]}..." if len(summary) > 200 else f"   {summary}")

    print("\n5️⃣ Testing get_top_chat_facts...")
    top_facts = await repo.get_top_chat_facts(
        chat_id=test_chat_id,
        max_facts=3,
        min_confidence=0.7,
    )
    print(f"   ✅ Top {len(top_facts)} facts:")
    for i, fact in enumerate(top_facts, 1):
        print(f"      {i}. {fact.fact_description} ({int(fact.confidence * 100)}%)")

    print("\n6️⃣ Testing delete_all_facts (simulated /gryadchatreset)...")
    deleted_count = await repo.delete_all_facts(chat_id=test_chat_id)
    print(f"   ✅ Deleted {deleted_count} facts")

    print("\n7️⃣ Verifying deletion...")
    remaining_facts = await repo.get_all_facts(chat_id=test_chat_id)
    print(f"   ✅ Remaining facts: {len(remaining_facts)}")

    if len(remaining_facts) == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ Test failed: Expected 0 facts, found {len(remaining_facts)}")

    print("\n🎉 Chat admin command testing complete!")


if __name__ == "__main__":
    asyncio.run(test_chat_admin_commands())
