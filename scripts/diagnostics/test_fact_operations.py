#!/usr/bin/env python3
"""Test fact operations to debug the forget/remember issue."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.user_profile_adapter import UserProfileStoreAdapter


async def main():
    """Test fact operations."""
    db_path = Path(__file__).parent.parent.parent / "gryag.db"

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return

    print(f"✅ Using database: {db_path}")

    # Create adapter
    adapter = UserProfileStoreAdapter(db_path)
    await adapter.init()

    # Test user from logs
    user_id = 955364115
    chat_id = -1002604868951

    print(f"\n📊 Testing for user {user_id} in chat {chat_id}")

    # Test 1: Get facts via adapter
    print("\n1️⃣ Getting facts via adapter.get_facts()...")
    facts = await adapter.get_facts(
        user_id=user_id,
        chat_id=chat_id,
        limit=20,
    )
    print(f"   Found {len(facts)} facts")
    for fact in facts:
        print(
            f"   - [{fact['id']}] {fact['fact_type']}.{fact['fact_key']} = {fact['fact_value']}"
        )

    # Test 2: Get fact count
    print("\n2️⃣ Getting fact count via adapter.get_fact_count()...")
    count = await adapter.get_fact_count(user_id, chat_id)
    print(f"   Count: {count}")

    # Test 3: Check fact_repository is accessible
    print("\n3️⃣ Checking fact_repository property...")
    fact_repo = adapter.fact_repository
    print(f"   fact_repository: {fact_repo}")
    print(f"   _fact_repo: {adapter._fact_repo}")

    # Test 4: Get facts via fact_repository directly
    print("\n4️⃣ Getting facts via fact_repository.get_facts()...")
    repo_facts = await fact_repo.get_facts(
        entity_id=user_id,
        chat_context=chat_id,
        limit=20,
    )
    print(f"   Found {len(repo_facts)} facts")
    for fact in repo_facts:
        print(
            f"   - [{fact['id']}] {fact['fact_category']}.{fact['fact_key']} = {fact['fact_value']}"
        )

    # Test 5: Try adding a test fact
    print("\n5️⃣ Adding a test fact...")
    fact_id = await adapter.add_fact(
        user_id=user_id,
        chat_id=chat_id,
        fact_type="trait",
        fact_key="test_trait",
        fact_value="This is a test fact",
        confidence=0.9,
        evidence_text="Test evidence",
    )
    print(f"   Added fact with ID: {fact_id}")

    # Test 6: Verify it appears
    print("\n6️⃣ Verifying new fact appears...")
    facts_after = await adapter.get_facts(
        user_id=user_id,
        chat_id=chat_id,
        limit=20,
    )
    test_fact = next((f for f in facts_after if f["id"] == fact_id), None)
    if test_fact:
        print(
            f"   ✅ Test fact found: {test_fact['fact_key']} = {test_fact['fact_value']}"
        )
    else:
        print("   ❌ Test fact NOT found!")

    # Test 7: Delete the test fact
    print("\n7️⃣ Deleting test fact...")
    deleted = await fact_repo.delete_fact(fact_id=fact_id, soft=False)
    print(f"   Deleted: {deleted}")

    # Test 8: Verify it's gone
    print("\n8️⃣ Verifying fact is deleted...")
    facts_final = await adapter.get_facts(
        user_id=user_id,
        chat_id=chat_id,
        limit=20,
    )
    test_fact_after = next((f for f in facts_final if f["id"] == fact_id), None)
    if test_fact_after:
        print(
            f"   ❌ Test fact still exists! is_active={test_fact_after.get('is_active')}"
        )
    else:
        print("   ✅ Test fact successfully deleted")

    print("\n✅ All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())
