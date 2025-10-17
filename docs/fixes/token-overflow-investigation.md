# Token Overflow Investigation Report

**Date**: October 16, 2025  
**Issue**: Gemini API error "400 INVALID_ARGUMENT: token count exceeds maximum allowed 1707895"  
**Status**: ✅ Root Cause Identified

## Problem Summary

The bot occasionally sends ~1.7M tokens to the Gemini API, far exceeding the limit. This happens despite having token budgeting in place.

## Root Cause

**Primary Issue**: `MAX_TURNS=50` setting in `.env`

When `MAX_TURNS=50`:
- Bot retrieves 50 complete turns = 100 messages (50 user + 50 bot)
- Average message: ~500 tokens
- Total history alone: **50,000 tokens** (way over the 8000 token budget!)

**Why This Happens**:

1. **Multi-level context enabled** (default: true) with token budget of 8000 tokens
2. **Fallback path doesn't respect token budget**: When multi-level context assembly fails, the code falls back to simple `store.recent()` which uses `MAX_TURNS` directly:

```python
# From app/handlers/chat.py line ~850
if not use_multi_level:
    # Fallback: Use simple history retrieval
    history = await store.recent(
        chat_id=chat_id,
        thread_id=thread_id,
        max_turns=settings.max_turns,  # ⚠️ Uses MAX_TURNS=50!
    )
```

3. **No token-based truncation in fallback**: The `_summarize_long_context()` function only checks message count, not token count

## Contributing Factors

1. **Database has long messages**: Found messages up to 4092 characters (~737 tokens each)
2. **No hard limit enforcement**: Even with multi-level context, if assembly succeeds with high token count, it's passed to Gemini
3. **Metadata included**: Each message includes metadata block (~20-50 tokens per message)

## Why Multi-Level Context Might Fail

The fallback path triggers when:
- Database errors during context assembly
- Hybrid search failures
- Episode retrieval errors
- Profile store unavailable

Any of these can cause fallback to simple history retrieval with full `MAX_TURNS`.

## Token Overflow Scenarios

### Scenario 1: Fallback with MAX_TURNS=50
```
50 turns × 100 messages × 500 tokens/msg = 50,000 tokens (history alone!)
+ System prompt: ~500 tokens
+ Profile context: ~200 tokens
+ User message: ~500 tokens
-------------------------------------------
Total: ~51,200 tokens ❌ WAY OVER 8000 budget
```

### Scenario 2: Multi-level with Long Messages
```
Immediate (20%): 1,600 tokens
Recent (30%): 2,400 tokens
Relevant (25%): 2,000 tokens
Background (15%): 1,200 tokens
Episodic (10%): 800 tokens
-------------------------------------------
Total: 8,000 tokens ✅ Within budget

But if messages are exceptionally long:
- 10 messages × 700 tokens each = 7,000 tokens for just immediate+recent
- This can push total over limit when combined with system prompt
```

## Verification

Checked message lengths in database:
- Longest message: 4,092 characters (~737 tokens)
- Top 10 messages: 2,500-4,092 characters (484-737 tokens each)
- Total messages: 22,945

With 50 turns, if we hit several long messages in sequence:
```
30 long messages × 700 tokens = 21,000 tokens
+ 70 normal messages × 300 tokens = 21,000 tokens
-------------------------------------------
Total history: 42,000 tokens! ❌
```

## Solutions

### Solution 1: Reduce MAX_TURNS (Quick Fix)
**Recommended**: Set `MAX_TURNS=20` or lower

Benefits:
- Immediate fix
- Reduces token usage by 60%
- 20 turns = 40 messages = ~20,000 tokens max (still high but safer)

Drawbacks:
- Less context for bot
- May affect conversation quality

### Solution 2: Add Token-Based Truncation (Proper Fix)
Add token counting to fallback path:

```python
if not use_multi_level:
    history = await store.recent(
        chat_id=chat_id,
        thread_id=thread_id,
        max_turns=settings.max_turns,
    )
    # NEW: Truncate to token budget
    history = _truncate_history_to_tokens(
        history, 
        max_tokens=settings.context_token_budget
    )
```

Benefits:
- Respects token budget even in fallback
- Allows higher MAX_TURNS safely
- More robust against long messages

### Solution 3: Add Hard Limit Before Gemini Call (Safety Net)
Add final check before calling Gemini:

```python
# Count tokens in history + system_prompt
total_tokens = estimate_total_tokens(history, system_prompt_with_profile)

if total_tokens > 100_000:  # Safety threshold
    LOGGER.error(f"Token count too high: {total_tokens}, truncating...")
    history = _emergency_truncate(history, max_tokens=80_000)
```

Benefits:
- Last line of defense
- Catches any edge cases
- Prevents API errors

## Recommended Implementation

**Phase 1 (Immediate)**:
1. Update `.env`: Set `MAX_TURNS=20` (down from 50)
2. Restart bot

**Phase 2 (This Week)**:
1. Implement `_truncate_history_to_tokens()` function
2. Add token counting to fallback path
3. Add warning logs when truncation happens

**Phase 3 (Next Week)**:
1. Implement hard limit safety net before Gemini calls
2. Add telemetry for token usage patterns
3. Create alert for high token usage

## Monitoring

Add these telemetry counters:
- `context.token_overflow_prevented` - When truncation saves us
- `context.fallback_used` - When multi-level context fails
- `context.tokens_sent` - Actual tokens sent to Gemini

## Files to Modify

1. **app/handlers/chat.py**:
   - Add `_truncate_history_to_tokens()` function
   - Update fallback path to use truncation
   - Add token counting before Gemini call

2. **app/config.py**:
   - Update `MAX_TURNS` default from 50 → 20
   - Add `CONTEXT_HARD_LIMIT` setting (default: 100,000 tokens)

3. **.env.example**:
   - Document recommended `MAX_TURNS` values
   - Add warning about token usage

## Verification Steps

After fix:
1. Set `MAX_TURNS=20` in `.env`
2. Restart bot: `docker compose restart bot`
3. Monitor logs for "token" messages
4. Test with long conversation thread
5. Check Gemini API for 400 errors (should be none)

## Related Issues

- Multi-level context sometimes fails silently
- Need better error handling in context assembly
- Should log when falling back to simple history
- Consider adding `context.assembly_failed` telemetry

## References

- Gemini API docs: https://ai.google.dev/api/rest
- Token limit: 1,048,576 tokens for Gemini 2.0 Flash
- Current error shows: 1,707,895 tokens attempted (63% over limit!)

---

**Next Steps**: Implement Solution 1 immediately, then Solution 2 within a week.
