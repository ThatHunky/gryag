#!/usr/bin/env python3
"""
Test unified fact storage implementation.

Verifies:
1. UnifiedFactRepository can query facts
2. Chat facts are accessible
3. User facts still work
4. UserProfileStoreAdapter works correctly
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.repositories.fact_repository import UnifiedFactRepository
from app.services.user_profile_adapter import UserProfileStoreAdapter


async def test_unified_repo():
    """Test UnifiedFactRepository directly."""
    print("=" * 80)
    print("TEST 1: UnifiedFactRepository Direct Access")
    print("=" * 80)

    repo = UnifiedFactRepository("gryag.db")

    # Test 1: Get chat facts
    print("\n1. Testing chat facts retrieval...")
    chat_id = -1002604868951
    chat_facts = await repo.get_facts(entity_id=chat_id)

    print(f"   Found {len(chat_facts)} chat facts:")
    for fact in chat_facts:
        print(f"   ✓ {fact['fact_category']}.{fact['fact_key']}: {fact['fact_value']}")

    assert len(chat_facts) >= 1, "Should have at least 1 chat fact"
    assert chat_facts[0]["entity_type"] == "chat", "Entity type should be 'chat'"
    print("   ✅ Chat facts working!")

    # Test 2: Get user facts
    print("\n2. Testing user facts retrieval...")
    user_facts = await repo.get_facts(
        entity_id=659225732, limit=5  # A user ID from the database
    )

    print(f"   Found {len(user_facts)} user facts:")
    for fact in user_facts[:3]:
        print(
            f"   ✓ {fact['fact_category']}.{fact['fact_key']}: {fact['fact_value'][:50]}..."
        )

    assert len(user_facts) > 0, "Should have user facts"
    assert user_facts[0]["entity_type"] == "user", "Entity type should be 'user'"
    print("   ✅ User facts working!")

    # Test 3: Get stats
    print("\n3. Testing repository stats...")
    stats = await repo.get_stats()

    print(f"   Total facts: {stats['total_facts']}")
    print(f"   User facts: {stats['user_facts']}")
    print(f"   Chat facts: {stats['chat_facts']}")
    print(f"   Avg confidence: {stats['avg_confidence']}")
    print(f"   Categories: {', '.join(stats['categories'].keys())}")

    assert stats["total_facts"] > 0, "Should have facts"
    assert stats["chat_facts"] >= 1, "Should have at least 1 chat fact"
    print("   ✅ Stats working!")

    print("\n✅ UnifiedFactRepository: ALL TESTS PASSED\n")


async def test_adapter():
    """Test UserProfileStoreAdapter compatibility."""
    print("=" * 80)
    print("TEST 2: UserProfileStoreAdapter Compatibility")
    print("=" * 80)

    adapter = UserProfileStoreAdapter("gryag.db")
    await adapter.init()

    # Test 1: Get user facts via adapter
    print("\n1. Testing get_facts via adapter...")
    user_id = 659225732
    chat_id = -1002604868951

    facts = await adapter.get_facts(user_id=user_id, chat_id=chat_id, limit=5)

    print(f"   Found {len(facts)} facts via adapter:")
    for fact in facts[:3]:
        print(
            f"   ✓ {fact['fact_type']}.{fact['fact_key']}: {fact['fact_value'][:50]}..."
        )

    assert len(facts) > 0, "Adapter should return facts"
    assert "fact_type" in facts[0], "Should map fact_category to fact_type"
    print("   ✅ Adapter get_facts working!")

    # Test 2: Add a test fact via adapter
    print("\n2. Testing add_fact via adapter...")
    fact_id = await adapter.add_fact(
        user_id=user_id,
        chat_id=chat_id,
        fact_type="trait",
        fact_key="test_key",
        fact_value="test_value",
        confidence=0.8,
        evidence_text="Test evidence",
    )

    print(f"   Added fact with ID: {fact_id}")
    assert fact_id > 0, "Should return fact ID"
    print("   ✅ Adapter add_fact working!")

    # Cleanup test fact
    repo = UnifiedFactRepository("gryag.db")
    await repo.delete_fact(fact_id, soft=False)
    print("   🧹 Cleaned up test fact")

    print("\n✅ UserProfileStoreAdapter: ALL TESTS PASSED\n")


async def test_chat_fact_visibility():
    """Test that chat facts are actually visible."""
    print("=" * 80)
    print("TEST 3: Chat Fact Visibility (The Original Bug)")
    print("=" * 80)

    repo = UnifiedFactRepository("gryag.db")

    chat_id = -1002604868951

    # The fact that was reported as missing
    print("\n1. Looking for 'любити кавунову пітсу' fact...")

    chat_facts = await repo.get_facts(entity_id=chat_id)

    target_fact = None
    for fact in chat_facts:
        if "кавунову пітсу" in fact["fact_value"]:
            target_fact = fact
            break

    if target_fact:
        print("   ✅ FOUND IT!")
        print(f"   Entity type: {target_fact['entity_type']}")
        print(f"   Entity ID: {target_fact['entity_id']}")
        print(f"   Category: {target_fact['fact_category']}")
        print(f"   Key: {target_fact['fact_key']}")
        print(f"   Value: {target_fact['fact_value']}")
        print(f"   Confidence: {target_fact['confidence']}")

        assert target_fact["entity_type"] == "chat", "Should be chat fact"
        assert target_fact["entity_id"] == chat_id, "Should be for correct chat"
        assert target_fact["fact_category"] == "rule", "Should be rule category"

        print("\n   🎉 THE BUG IS FIXED!")
        print("   Chat fact is now correctly stored and accessible!")
    else:
        print("   ❌ FACT NOT FOUND - Bug still exists!")
        raise AssertionError("Chat fact should be visible")

    print("\n✅ Chat Fact Visibility: BUG FIXED!\n")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("UNIFIED FACT STORAGE - INTEGRATION TESTS")
    print("=" * 80 + "\n")

    try:
        await test_unified_repo()
        await test_adapter()
        await test_chat_fact_visibility()

        print("\n" + "=" * 80)
        print("🎉 ALL TESTS PASSED! IMPLEMENTATION SUCCESSFUL!")
        print("=" * 80)
        print("\n✅ UnifiedFactRepository works")
        print("✅ UserProfileStoreAdapter provides compatibility")
        print("✅ Chat facts are now visible")
        print("✅ User facts still work")
        print("\n📝 Next steps:")
        print("   1. Test with live bot")
        print("   2. Verify /gryagchatfacts command works")
        print("   3. Monitor for issues")
        print("   4. Drop *_old tables after 30 days\n")

        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
