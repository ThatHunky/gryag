#!/usr/bin/env python3
"""
Verify context retrieval fix.

This script verifies that the context store correctly interprets max_turns
as conversation turns (user+bot pairs) rather than raw message counts.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.context_store import ContextStore


async def main():
    """Test context retrieval with turns vs messages."""
    print("=== Context Retrieval Fix Verification ===\n")

    # Use a temporary test database
    test_db = project_root / "test_context_verify.db"
    if test_db.exists():
        test_db.unlink()

    store = ContextStore(test_db)
    await store.init()

    chat_id = 12345
    thread_id = None
    user_id = 67890

    # Add 5 conversation turns (10 messages total: 5 user + 5 bot)
    print("Adding 5 conversation turns (10 messages total)...")
    for i in range(5):
        # User message
        await store.add_turn(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=user_id,
            role="user",
            text=f"User message {i+1}",
            media=None,
            metadata={"turn": i + 1},
            embedding=[0.1] * 768,
        )

        # Bot response
        await store.add_turn(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=None,
            role="model",
            text=f"Bot response {i+1}",
            media=None,
            metadata={"turn": i + 1},
            embedding=[0.2] * 768,
        )

    print("✓ Added 10 messages (5 user + 5 bot)\n")

    # Test 1: Request 2 turns, should get 4 messages
    print("Test 1: Request 2 turns (max_turns=2)")
    history = await store.recent(chat_id, thread_id, max_turns=2)
    print("  Expected: 4 messages (2 turns × 2 messages/turn)")
    print(f"  Got: {len(history)} messages")

    if len(history) == 4:
        print("  ✓ PASS\n")
    else:
        print("  ✗ FAIL\n")
        print("  Messages received:")
        for msg in history:
            print(f"    - {msg['role']}: {msg['parts'][0]['text']}")

    # Test 2: Request 5 turns, should get all 10 messages
    print("Test 2: Request 5 turns (max_turns=5)")
    history = await store.recent(chat_id, thread_id, max_turns=5)
    print("  Expected: 10 messages (5 turns × 2 messages/turn)")
    print(f"  Got: {len(history)} messages")

    if len(history) == 10:
        print("  ✓ PASS\n")
    else:
        print("  ✗ FAIL\n")

    # Test 3: Request more turns than available
    print("Test 3: Request 10 turns (more than available)")
    history = await store.recent(chat_id, thread_id, max_turns=10)
    print("  Expected: 10 messages (all available)")
    print(f"  Got: {len(history)} messages")

    if len(history) == 10:
        print("  ✓ PASS\n")
    else:
        print("  ✗ FAIL\n")

    # Test 4: Verify chronological order (oldest to newest)
    print("Test 4: Verify chronological order")
    history = await store.recent(chat_id, thread_id, max_turns=5)

    # Check that messages alternate user/model and increment
    correct_order = True
    for i in range(0, len(history), 2):
        if history[i]["role"] != "user" or history[i + 1]["role"] != "model":
            correct_order = False
            break

        # Extract turn number from text
        user_text = history[i]["parts"][0]["text"] if history[i]["parts"] else ""
        bot_text = history[i + 1]["parts"][0]["text"] if history[i + 1]["parts"] else ""

        expected_turn = (i // 2) + 1
        if (
            f"message {expected_turn}" not in user_text
            or f"response {expected_turn}" not in bot_text
        ):
            correct_order = False
            break

    if correct_order:
        print("  ✓ PASS - Messages in correct chronological order\n")
    else:
        print("  ✗ FAIL - Messages not in correct order\n")

    # Cleanup
    test_db.unlink()

    print("=== Verification Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
