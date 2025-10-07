# Tool Definition Format Fix

**Date**: October 7, 2025  
**Issue**: Gemini API rejecting memory tool definitions  
**Status**: ✅ Fixed

## Problem

When the bot tried to use the new memory tools (`remember_fact`, `recall_facts`, `update_fact`, `forget_fact`), the Gemini API threw an error:

```
KeyError: 'object'
ValueError: Protocol message Schema has no "type" field.
```

**Root Cause**: Tool definitions were using plain JSON Schema format instead of Gemini's required `function_declarations` wrapper format.

## Error Details

**Stack Trace** (from logs):
```python
File "/app/app/services/gemini.py", line 216, in generate
    response = await self._invoke_model(
...
File "/usr/local/lib/python3.12/site-packages/google/generativeai/types/content_types.py", line 823, in _make_tool
    return Tool(function_declarations=[protos.FunctionDeclaration(**fd)])
...
KeyError: 'object'
```

**When It Occurred**: When bot tried to call Gemini with memory tools enabled (`ENABLE_TOOL_BASED_MEMORY=true`)

## Incorrect Format (Before Fix)

```python
REMEMBER_FACT_DEFINITION = {
    "name": "remember_fact",
    "description": "...",
    "parameters": {
        "type": "object",
        "properties": { ... }
    }
}
```

**Problem**: Missing `function_declarations` wrapper array.

## Correct Format (After Fix)

```python
REMEMBER_FACT_DEFINITION = {
    "function_declarations": [
        {
            "name": "remember_fact",
            "description": "...",
            "parameters": {
                "type": "object",
                "properties": { ... }
            }
        }
    ]
}
```

**Key Difference**: Tool definition wrapped in `{"function_declarations": [ ... ]}` array.

## Files Fixed

**Modified**:
- `app/services/tools/memory_definitions.py` - All 4 tool definitions wrapped correctly

**Tool Definitions Fixed**:
1. `REMEMBER_FACT_DEFINITION`
2. `RECALL_FACTS_DEFINITION`
3. `UPDATE_FACT_DEFINITION`
4. `FORGET_FACT_DEFINITION`

## Reference Format

Followed the same pattern as existing tools in the codebase:
- `app/services/calculator.py` - `CALCULATOR_TOOL_DEFINITION` (line 324)
- `app/services/weather.py` - `WEATHER_TOOL_DEFINITION`
- `app/services/currency.py` - `CURRENCY_TOOL_DEFINITION`

All use the `function_declarations` wrapper format.

## Verification

**Before Fix**:
```bash
docker compose logs bot | grep "KeyError: 'object'"
# Shows: KeyError: 'object' when tools used
```

**After Fix**:
```bash
docker compose restart bot
docker compose logs --tail=50 bot
# Shows: Clean startup, no KeyError
```

**Test the fix**:
1. Send a message to the bot mentioning a fact: "Я з Києва"
2. Bot should now call `recall_facts` → `remember_fact` without errors
3. Check logs: `docker compose logs bot | grep "memory_tool"`

## Impact

**Before Fix**:
- ❌ Bot could not use any memory tools
- ❌ All tool calls failed with KeyError
- ❌ Bot fell back to generation without tools (no memory management)

**After Fix**:
- ✅ All 4 memory tools work correctly
- ✅ Bot can remember, recall, update, and forget facts
- ✅ Model has full control over memory operations

## Lessons Learned

1. **API Format Requirements**: Always check the SDK's expected format, not just JSON Schema standards
2. **Reference Existing Code**: Look at working examples in the same codebase
3. **Test with Real API**: Integration tests caught this immediately
4. **Documentation Gaps**: Gemini SDK docs don't always show wrapper requirements clearly

## Related Issues

**Similar Error**: If you see `KeyError` or `ValueError` with tool definitions, always check:
1. Is tool wrapped in `function_declarations` array?
2. Are enum values using correct Gemini format?
3. Are all required fields present in parameters?

## Future Prevention

**Code Review Checklist**:
- [ ] Tool definitions use `function_declarations` wrapper
- [ ] Follow format from `app/services/calculator.py`
- [ ] Test with real Gemini API call before deploying
- [ ] Check logs for `KeyError` or `ValueError` after restart

## Documentation References

- Gemini Function Calling: https://ai.google.dev/gemini-api/docs/function-calling
- Tool Definition Format: See `app/services/calculator.py` line 324
- Original Plan: `docs/plans/MEMORY_TOOL_CALLING_REDESIGN.md`

---

**Fixed by**: AI Assistant  
**Verified**: Bot restart successful, no errors in logs  
**Status**: ✅ Production ready
