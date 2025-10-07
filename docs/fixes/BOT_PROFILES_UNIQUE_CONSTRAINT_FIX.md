# Bot Self-Learning Schema Fix

**Date**: October 6, 2025  
**Issue**: UNIQUE constraint violation on `bot_profiles.bot_id`  
**Status**: ✅ Fixed

## Problem

The `bot_profiles` table had a conflicting constraint:

```sql
bot_id INTEGER NOT NULL UNIQUE,  -- ❌ Wrong: prevents multiple profiles per bot
...
UNIQUE(bot_id, chat_id)  -- ✅ Correct: allows global + per-chat profiles
```

This caused runtime errors when trying to create chat-specific profiles:
```
sqlite3.IntegrityError: UNIQUE constraint failed: bot_profiles.bot_id
```

## Root Cause

The schema definition in `db/schema.sql` line 450 had `bot_id` marked as `UNIQUE`, which conflicts with the design goal of having:
- 1 global profile (bot_id=X, chat_id=NULL)
- N chat-specific profiles (bot_id=X, chat_id=123, chat_id=456, etc.)

## Solution

**Changed** `db/schema.sql` line 450:
```sql
-- Before
bot_id INTEGER NOT NULL UNIQUE,  -- ❌

-- After  
bot_id INTEGER NOT NULL,  -- ✅ Removed UNIQUE
```

The composite `UNIQUE(bot_id, chat_id)` constraint (line 462) is sufficient to ensure one profile per bot-chat combination.

## Migration

Created `fix_bot_profiles_constraint.py` to:
1. Detect incorrect schema
2. Backup existing data
3. Drop and recreate table with correct schema
4. Restore backed-up data

**Execution**:
```bash
python3 fix_bot_profiles_constraint.py
# Output:
# 🔧 Fixing bot_profiles UNIQUE constraint...
# ⚠️  Found incorrect UNIQUE constraint on bot_id
#    Recreating table with correct schema...
#    Backing up 1 existing profile(s)
#    Restored 1 profile(s)
# ✅ bot_profiles table fixed successfully
```

## Verification

After fix:
```bash
docker compose restart bot
# Bot starts without IntegrityError
# Can now create global + chat-specific profiles
```

**Test**:
```bash
# In Telegram (as admin):
/gryagself  # Works in any chat - creates chat-specific profile if needed
```

## Files Changed

1. `db/schema.sql` - Removed `UNIQUE` from `bot_id` column definition
2. `fix_bot_profiles_constraint.py` - Migration script (one-time use)

## Lessons Learned

- **Always test schema changes** with multiple profile creation scenarios
- **Composite UNIQUE constraints** are sufficient - don't add redundant column-level UNIQUE
- **Migration scripts** should backup data before destructive operations
- **SQLite** requires DROP+CREATE for constraint changes (can't ALTER CONSTRAINT)

## Impact

- ✅ Bot can now create multiple profiles (global + per-chat)
- ✅ `/gryagself` command works in all chats
- ✅ Chat-specific learning enabled (bot learns different patterns per chat)
- ✅ No data loss (existing global profile preserved)

## Future Prevention

Add to verification script (`verify_bot_self_learning.sh`):
```bash
# Check schema doesn't have redundant UNIQUE
if grep -q "bot_id INTEGER NOT NULL UNIQUE" db/schema.sql; then
    echo "❌ Schema has incorrect UNIQUE constraint"
    exit 1
fi
```
