"""Test script for Phase 5.1 memory tools implementation."""

import asyncio
import pytest

pytestmark = pytest.mark.asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import Settings
from app.services.user_profile import UserProfileStore
from app.services.tools import (
    remember_fact_tool,
    recall_facts_tool,
    update_fact_tool,
    forget_fact_tool,
)


async def test_memory_tools():
    """Test the core memory tools."""
    print("🧪 Testing Phase 5.1 Memory Tools\n")

    # Initialize settings
    settings = Settings()
    print(f"✓ Settings loaded")
    print(f"  - enable_tool_based_memory: {settings.enable_tool_based_memory}")
    print(f"  - memory_tool_async: {settings.memory_tool_async}\n")

    # Initialize profile store
    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()
    print(f"✓ Profile store initialized\n")

    # Test user and chat
    test_user_id = 999999
    test_chat_id = -888888

    # Clean up any existing test data
    import aiosqlite

    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "DELETE FROM user_facts WHERE user_id = ? AND chat_id = ?",
            (test_user_id, test_chat_id),
        )
        await db.commit()

    facts = await profile_store.get_facts(test_user_id, test_chat_id)
    print(f"📊 Existing facts for test user (after cleanup): {len(facts)}\n")

    # Test 1: recall_facts (should be empty initially)
    print("Test 1: recall_facts (initial state)")
    result = await recall_facts_tool(
        user_id=test_user_id,
        chat_id=test_chat_id,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}, Count: {data['count']}")
    assert data["status"] == "success"
    print("  ✅ PASSED\n")

    # Test 2: remember_fact (store location)
    print("Test 2: remember_fact (location)")
    result = await remember_fact_tool(
        user_id=test_user_id,
        fact_type="personal",
        fact_key="location",
        fact_value="Київ",
        confidence=0.95,
        source_excerpt="Я з Києва",
        chat_id=test_chat_id,
        message_id=12345,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Fact ID: {data.get('fact_id')}")
    print(f"  Message: {data.get('message')}")
    assert data["status"] == "success"
    assert "fact_id" in data
    fact_id_location = data["fact_id"]
    print("  ✅ PASSED\n")

    # Test 3: recall_facts (should find the location)
    print("Test 3: recall_facts (after storing location)")
    result = await recall_facts_tool(
        user_id=test_user_id,
        chat_id=test_chat_id,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}, Count: {data['count']}")
    assert data["status"] == "success"
    assert data["count"] == 1
    assert data["facts"][0]["key"] == "location"
    assert data["facts"][0]["value"] == "Київ"
    print(
        f"  Found fact: {data['facts'][0]['type']}.{data['facts'][0]['key']} = {data['facts'][0]['value']}"
    )
    print("  ✅ PASSED\n")

    # Test 4: remember_fact (duplicate detection)
    print("Test 4: remember_fact (duplicate detection)")
    result = await remember_fact_tool(
        user_id=test_user_id,
        fact_type="personal",
        fact_key="location",
        fact_value="Київ",  # Same value
        confidence=0.9,
        chat_id=test_chat_id,
        message_id=12346,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Reason: {data.get('reason')}")
    assert data["status"] == "skipped"
    assert data["reason"] == "duplicate"
    print("  ✅ PASSED (duplicate correctly detected)\n")

    # Test 5: remember_fact (different fact type)
    print("Test 5: remember_fact (skill)")
    result = await remember_fact_tool(
        user_id=test_user_id,
        fact_type="skill",
        fact_key="programming_language",
        fact_value="Python",
        confidence=0.9,
        source_excerpt="Я програмую на Python",
        chat_id=test_chat_id,
        message_id=12347,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Fact ID: {data.get('fact_id')}")
    assert data["status"] == "success"
    print("  ✅ PASSED\n")

    # Test 6: recall_facts with filter
    print("Test 6: recall_facts (filter by type)")
    result = await recall_facts_tool(
        user_id=test_user_id,
        fact_types=["skill"],
        chat_id=test_chat_id,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}, Count: {data['count']}")
    assert data["status"] == "success"
    assert data["count"] == 1
    assert data["facts"][0]["type"] == "skill"
    print(
        f"  Found: {data['facts'][0]['type']}.{data['facts'][0]['key']} = {data['facts'][0]['value']}"
    )
    print("  ✅ PASSED\n")

    # Test 7: update_fact (change location)
    print("Test 7: update_fact (location Київ → Львів)")
    result = await update_fact_tool(
        user_id=test_user_id,
        fact_type="personal",
        fact_key="location",
        new_value="Львів",
        confidence=0.95,
        change_reason="update",
        source_excerpt="Тепер я в Львові",
        chat_id=test_chat_id,
        message_id=12348,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Old value: {data.get('old_value')}")
    print(f"  New value: {data.get('new_value')}")
    print(f"  Change reason: {data.get('change_reason')}")
    assert data["status"] == "success"
    assert data["old_value"] == "Київ"
    assert data["new_value"] == "Львів"
    print("  ✅ PASSED\n")

    # Test 8: recall_facts (verify update)
    print("Test 8: recall_facts (verify location updated)")
    result = await recall_facts_tool(
        user_id=test_user_id,
        fact_types=["personal"],
        chat_id=test_chat_id,
        profile_store=profile_store,
    )
    data = json.loads(result)
    location_fact = next(f for f in data["facts"] if f["key"] == "location")
    print(f"  Current location: {location_fact['value']}")
    assert location_fact["value"] == "Львів"
    print("  ✅ PASSED\n")

    # Test 9: update_fact (non-existent fact)
    print("Test 9: update_fact (non-existent fact)")
    result = await update_fact_tool(
        user_id=test_user_id,
        fact_type="preference",
        fact_key="hobby",
        new_value="Reading",
        confidence=0.8,
        change_reason="update",
        chat_id=test_chat_id,
        message_id=12349,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Suggestion: {data.get('suggestion')}")
    assert data["status"] == "not_found"
    assert data["suggestion"] == "remember_fact"
    print("  ✅ PASSED (correctly suggests remember_fact)\n")

    # Test 10: forget_fact (remove skill)
    print("Test 10: forget_fact (remove skill)")
    result = await forget_fact_tool(
        user_id=test_user_id,
        fact_type="skill",
        fact_key="programming_language",
        reason="user_requested",
        chat_id=test_chat_id,
        message_id=12350,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Forgotten value: {data.get('forgotten_value')}")
    print(f"  Reason: {data.get('reason')}")
    assert data["status"] == "success"
    assert data["forgotten_value"] == "Python"
    assert data["reason"] == "user_requested"
    print("  ✅ PASSED\n")

    # Test 11: recall_facts (verify skill forgotten)
    print("Test 11: recall_facts (verify skill forgotten)")
    result = await recall_facts_tool(
        user_id=test_user_id,
        fact_types=["skill"],
        chat_id=test_chat_id,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}, Count: {data['count']}")
    assert data["status"] == "success"
    assert data["count"] == 0  # Should be empty after forgetting
    print("  ✅ PASSED (skill successfully forgotten)\n")

    # Test 12: forget_fact (non-existent fact)
    print("Test 12: forget_fact (non-existent fact)")
    result = await forget_fact_tool(
        user_id=test_user_id,
        fact_type="preference",
        fact_key="favorite_color",
        reason="outdated",
        chat_id=test_chat_id,
        message_id=12351,
        profile_store=profile_store,
    )
    data = json.loads(result)
    print(f"  Result: {data['status']}")
    print(f"  Suggestion: {data.get('suggestion')}")
    assert data["status"] == "not_found"
    assert data["suggestion"] == "Use recall_facts to check existing facts"
    print("  ✅ PASSED (correctly handles non-existent fact)\n")

    print("=" * 60)
    print("🎉 All tests passed!")
    print("=" * 60)
    print("\nPhase 5.1+ Memory Tools are working correctly!")
    print(f"  - 4 tools implemented: remember, recall, update, forget")
    print(f"  - 12 tests passed")
    print("\nNext steps:")
    print("  1. Integration testing with real Gemini calls")
    print("  2. Test in Telegram with real conversations")
    print("  3. Monitor telemetry for tool usage patterns")
    print("  4. Phase 5.2: Add episode tools (create, update, archive)")


if __name__ == "__main__":
    asyncio.run(test_memory_tools())
