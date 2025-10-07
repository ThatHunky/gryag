# Fact Extraction KeyError Fix

**Date:** 2025-10-06  
**Issue:** KeyError in Gemini fact extraction prompt  
**Status:** ✅ Fixed

## Problem

User profile fact extraction was failing with repeated KeyErrors:

```text
ERROR - app.services.user_profile - Fact extraction failed for user XXXXXX: '\n  "facts"'
Traceback (most recent call last):
  File "/app/app/services/user_profile.py", line 97, in extract_user_facts
    prompt = FACT_EXTRACTION_PROMPT.format(
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyError: '\n  "facts"'
```

## Root Cause

The `FACT_EXTRACTION_PROMPT` constant in `app/services/user_profile.py` contained a JSON example with unescaped curly braces `{` and `}`. Python's `.format()` method interprets these as format placeholders, causing it to look for variables like `\n  "facts"` (from the JSON structure).

**Problematic code (lines 36-46):**

```python
Return JSON with this structure:
{
  "facts": [
    {
      "fact_type": "personal|preference|trait|skill|opinion",
      "fact_key": "standardized_key",
      "fact_value": "the actual fact",
      "confidence": 0.7-1.0,
      "evidence": "quote supporting this"
    }
  ]
}
```

## Solution

Escaped all curly braces in the JSON example by doubling them (`{{` and `}}`), which tells Python's `.format()` to treat them as literal characters rather than format placeholders.

**Fixed code:**

```python
Return JSON with this structure:
{{
  "facts": [
    {{
      "fact_type": "personal|preference|trait|skill|opinion",
      "fact_key": "standardized_key",
      "fact_value": "the actual fact",
      "confidence": 0.7-1.0,
      "evidence": "quote supporting this"
    }}
  ]
}}
```

**File:** `app/services/user_profile.py`  
**Lines:** 36-46  
**Change:** Doubled all `{` → `{{` and `}` → `}}` in JSON example

## Verification

```bash
# Restart bot
docker compose restart bot

# Check for KeyError after restart (get timestamp first)
docker compose logs bot | grep "Start polling"  # Note the timestamp

# Check for errors after that timestamp
docker compose logs --since <timestamp> bot 2>&1 | grep -E "KeyError.*facts"

# Expected: No output (no errors)
# Result: ✅ No KeyError since fix
```

## Impact

- Gemini-based fact extraction now works correctly when rule-based extraction fails
- Continuous learning system can properly extract user facts from conversations
- No more repeated KeyError spam in logs
- Fact extraction coverage improved for complex sentences

## Related

- Previous fix: [Gemini Response AttributeError](bot_learning_gemini_response_fix.md)
- Feature: [User Profiling](../features/USER_PROFILING_PLAN.md)
- Learning: [Continuous Learning Improvements](../plans/CONTINUOUS_LEARNING_IMPROVEMENTS.md)
