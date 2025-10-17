# Context Retrieval Fix

**Date:** 2025-10-17  
**Issue:** Bot context not working properly - unable to see previous messages in conversation  
**Root Cause:** `ContextStore.recent()` method treating `max_turns` parameter as message count instead of turn count

## Problem

The `recent()` method in `ContextStore` was incorrectly interpreting the `max_turns` parameter:

- **Expected:** `max_turns` represents conversation **turns**, where 1 turn = 1 user message + 1 bot response = 2 messages
- **Actual behavior:** The method was treating `max_turns` as a raw message count
- **Impact:** With `MAX_TURNS=20` (default), the bot only saw 20 messages instead of 40, cutting context in half

### Example

With the old code:
```python
# Request 20 turns
history = await store.recent(chat_id, thread_id, max_turns=20)
# Got: 20 messages total (could be 10 user + 10 bot, or any mix)
# Expected: 40 messages (20 user + 20 bot)
```

## Solution

Updated `ContextStore.recent()` to multiply `max_turns` by 2 when querying the database:

```python
async def recent(
    self,
    chat_id: int,
    thread_id: int | None,
    max_turns: int,
) -> list[dict[str, Any]]:
    # Each turn = 1 user message + 1 bot response = 2 messages
    message_limit = max_turns * 2
    
    # Query with doubled limit to get full conversation turns
    query = "SELECT ... LIMIT ?"
    params = (chat_id, message_limit)
```

## Multi-Level Context Adjustment

The multi-level context manager was also affected because it calls `recent()` with message counts from config settings:

- `immediate_context_size=5` (messages) → converted to `(5+1)//2 = 3` turns → fetches 6 messages
- `recent_context_size=30` (messages) → converted to `(30+1)//2 = 16` turns → fetches 32 messages

Updated `MultiLevelContextManager` to convert message counts to turn counts before calling `recent()`:

```python
# Convert message count to turn count (divide by 2, round up)
limit = (self.settings.immediate_context_size + 1) // 2
messages = await self.context_store.recent(chat_id, thread_id, limit)
```

## Files Changed

1. `/home/thathunky/gryag/app/services/context_store.py`
   - Modified `recent()` method to multiply `max_turns` by 2
   - Added comments explaining turn vs message semantics

2. `/home/thathunky/gryag/app/services/context/multi_level_context.py`
   - Updated `_get_immediate_context()` to convert message count to turn count
   - Updated `_get_recent_context()` to convert message count to turn count

## Verification

Created verification script: `scripts/verification/verify_context_fix.py`

Test results:
- ✓ Requesting 2 turns returns 4 messages
- ✓ Requesting 5 turns returns 10 messages  
- ✓ Requesting more turns than available returns all messages
- ✓ Messages returned in correct chronological order

Integration test passed: `tests/integration/test_context_store.py::test_add_and_retrieve_turn`

## Impact

After this fix:
- Bot can see **2x more conversation history** with the same `MAX_TURNS` setting
- Default `MAX_TURNS=20` now correctly fetches 40 messages (20 user + 20 bot)
- Multi-level context properly respects configured message counts
- Conversation continuity significantly improved

## Configuration Reference

From `.env.example`:
```bash
# MAX_TURNS: Number of conversation turns to include in history (default: 20)
# Each turn = 1 user message + 1 bot response = 2 messages total
# WARNING: Higher values can cause token overflow errors!
# Recommended: 15-20 for normal use, 30-40 for long conversations
MAX_TURNS=20
```

With this fix, `MAX_TURNS=20` will now correctly fetch up to 40 messages as documented.

## How to Verify

Run the verification script:
```bash
cd /home/thathunky/gryag
source .venv/bin/activate
python scripts/verification/verify_context_fix.py
```

Or run integration tests:
```bash
PYTHONPATH=/home/thathunky/gryag pytest tests/integration/test_context_store.py -v
```

## Related Documentation

- `.github/copilot-instructions.md` - Section on context assembly (line 79)
- `docs/overview/CURRENT_CONVERSATION_PATTERN.md` - Multi-level context format
- `docs/architecture/SYSTEM_OVERVIEW.md` - Context layers (Immediate/Recent)
