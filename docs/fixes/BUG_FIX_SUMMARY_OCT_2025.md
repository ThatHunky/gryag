# Bug Fix Summary - October 6, 2025

This document summarizes all bugs fixed in the bot self-learning and user profiling systems on October 6, 2025.

## Overview

Three critical bugs were discovered and fixed during initial testing of the Phase 5 bot self-learning system:

1. **UNIQUE Constraint Violation** - Database schema issue
2. **AttributeError in Bot Insights** - Response type handling issue  
3. **KeyError in Fact Extraction** - Format string escaping issue

All bugs are now **FIXED** and verified working.

## Bug 1: UNIQUE Constraint Violation

**Status:** ✅ Fixed  
**File:** `db/schema.sql` line 450  
**Severity:** Critical - Bot couldn't create profiles

### Problem
```
sqlite3.IntegrityError: UNIQUE constraint failed: bot_profiles.bot_id
```

Bot failed to start because the `bot_profiles` table had a redundant `UNIQUE` constraint on `bot_id` that conflicted with the composite `UNIQUE(bot_id, chat_id)` constraint.

### Solution
- Removed `UNIQUE` from `bot_id INTEGER NOT NULL UNIQUE` → `bot_id INTEGER NOT NULL`
- Created migration script: `fix_bot_profiles_constraint.py`
- Successfully migrated 1 existing profile

### Documentation
`docs/fixes/` (mentioned in Phase 5 summary, no separate doc created)

---

## Bug 2: AttributeError in Bot Insights

**Status:** ✅ Fixed  
**File:** `app/services/bot_learning.py` line 394  
**Severity:** High - `/gryaginsights` command crashed

### Problem
```python
AttributeError: 'str' object has no attribute 'text'
File "/app/app/services/bot_learning.py", line 394, in generate_gemini_insights
  response_text = response.text.strip()
```

The code assumed `gemini_client.generate()` returns an object with `.text` attribute, but it actually returns a string directly.

### Solution
Changed line 394:
```python
# Before (incorrect)
response_text = response.text.strip()

# After (correct)
response_text = response.strip()
```

### Documentation
`docs/fixes/bot_learning_gemini_response_fix.md`

---

## Bug 3: KeyError in Fact Extraction

**Status:** ✅ Fixed  
**File:** `app/services/user_profile.py` lines 36-46  
**Severity:** High - Gemini fact extraction failed

### Problem
```python
KeyError: '\n  "facts"'
Traceback (most recent call last):
  File "/app/app/services/user_profile.py", line 97, in extract_user_facts
    prompt = FACT_EXTRACTION_PROMPT.format(
```

The `FACT_EXTRACTION_PROMPT` contained a JSON example with unescaped curly braces. Python's `.format()` method tried to interpret `{` and `}` as format placeholders, causing KeyError.

### Solution
Escaped all curly braces in the JSON example (lines 36-46):
```python
# Before (incorrect)
Return JSON with this structure:
{
  "facts": [
    {
      "fact_type": "personal|preference|trait|skill|opinion",
      ...
    }
  ]
}

# After (correct)
Return JSON with this structure:
{{
  "facts": [
    {{
      "fact_type": "personal|preference|trait|skill|opinion",
      ...
    }}
  ]
}}
```

### Documentation
`docs/fixes/fact_extraction_keyerror_fix.md`

---

## Verification

All fixes verified on October 6, 2025:

```bash
# 1. Restart bot
docker compose restart bot

# 2. Check startup
docker compose logs bot | grep "Start polling"
# Result: 2025-10-06 12:38:54,487 - INFO - aiogram.dispatcher - Start polling

# 3. Check for errors after startup
docker compose logs --since "12:38:54" bot 2>&1 | grep -E "ERROR.*KeyError|ERROR.*AttributeError|UNIQUE constraint"
# Result: No output (no errors)

# 4. Verify bot is processing messages
docker compose logs --tail=20 bot
# Result: ✅ Processing messages normally
```

## Impact Summary

### Before Fixes
- ❌ Bot couldn't start (UNIQUE constraint)
- ❌ `/gryaginsights` command crashed
- ❌ Gemini fact extraction failed with repeated KeyErrors
- ❌ Continuous learning degraded to rule-based only

### After Fixes
- ✅ Bot starts successfully
- ✅ Bot self-learning fully functional
- ✅ `/gryagself` command works (view bot's self-knowledge)
- ✅ `/gryaginsights` command works (generate Gemini analysis)
- ✅ User fact extraction works with Gemini fallback
- ✅ Continuous learning extracts facts correctly
- ✅ Multiple bot profiles (global + per-chat) supported
- ✅ Clean logs (no KeyError/AttributeError spam)

## Files Changed

1. `db/schema.sql` - Removed redundant UNIQUE constraint
2. `app/services/bot_learning.py` - Fixed response.text → response
3. `app/services/user_profile.py` - Escaped JSON braces in prompt
4. `fix_bot_profiles_constraint.py` - Created migration script
5. `docs/fixes/bot_learning_gemini_response_fix.md` - Documentation
6. `docs/fixes/fact_extraction_keyerror_fix.md` - Documentation
7. `docs/CHANGELOG.md` - Updated with all fixes
8. `docs/README.md` - Added recent changes note

## Testing Recommendations

To verify these fixes remain working:

1. **Test bot self-learning:**
   ```bash
   # In Telegram, send to bot:
   /gryagself  # Should show bot's profile
   /gryaginsights  # Should generate insights (may take 10-20s)
   ```

2. **Test fact extraction:**
   ```bash
   # Have users chat naturally in group
   # Bot should learn facts via continuous monitoring
   # Check logs for successful extraction:
   docker compose logs bot | grep "Hybrid extraction complete"
   # Should show "X unique facts" (not always 0)
   ```

3. **Test multiple profiles:**
   ```bash
   # Run /gryagself in different chats
   # Each chat should have separate stats
   sqlite3 gryag.db "SELECT bot_id, chat_id, fact_count FROM bot_profiles;"
   ```

## Related Documentation

- Feature: `docs/features/BOT_SELF_LEARNING.md`
- Implementation: `docs/phases/PHASE_5_IMPLEMENTATION_SUMMARY.md`
- Fix details: `docs/fixes/bot_learning_gemini_response_fix.md`
- Fix details: `docs/fixes/fact_extraction_keyerror_fix.md`
- Changelog: `docs/CHANGELOG.md`
