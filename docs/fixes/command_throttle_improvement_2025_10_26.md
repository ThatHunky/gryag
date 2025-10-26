# Command Throttle Improvement - October 26, 2025

## Summary

Improved command throttling system to provide better user experience while preventing spam. The system now uses a **smart warning approach** instead of always showing error messages.

## Changes Made

### 1. Smart Warning System

**Before:**
- Every throttled command showed an error message
- Could spam users with notifications if they kept trying

**After:**
- First violation: Shows warning with countdown
- Subsequent violations (within 10 min): Silently ignored
- Result: One warning per 10 minutes maximum

### 2. Updated Error Message Format

**Before:**
```
⏱ Зачекай трохи!

Команди можна використовувати раз на 5 хвилин.
Наступна команда через: 3 хв 45 сек
```

**After:**
```
Зачекай трохи!

Команди можна використовувати раз на 5 хвилин. Наступна команда через: ⏱ 4 хв 30 сек
```

Changes:
- Removed leading emoji (cleaner look)
- Condensed to single paragraph with inline timer
- Matches screenshot example provided by user

### 3. Verified Other Bot Command Filtering

**Existing implementation confirmed working:**
- Commands with `@other_bot` are ignored (not throttled, not processed)
- Commands with `@gryag_bot` or no mention are processed normally
- Bot-to-bot protection: Commands from bot users are completely dropped

**Code location:** `app/middlewares/command_throttle.py` lines 141-156

## User Experience Flow

### Scenario 1: Regular Spam (Shows Warning Once)

```
00:00 - /gryagfacts@gryag_bot      → ✅ Works
00:01 - /gryagprofile@gryag_bot    → ⚠️ Warning: "Зачекай трохи! ... 4 хв 30 сек"
00:02 - /gryagfacts@gryag_bot      → 🤫 Silent ignore (no message)
00:03 - /gryagban@gryag_bot        → 🤫 Silent ignore (no message)
00:05 - /gryagfacts@gryag_bot      → ✅ Works (cooldown expired)
```

### Scenario 2: Continued Spam (Warning After 10 Min)

```
00:00 - /gryagfacts@gryag_bot      → ✅ Works
00:01 - /gryagprofile@gryag_bot    → ⚠️ Warning shown
00:02 - /gryagfacts@gryag_bot      → 🤫 Silent ignore
00:03 - /gryagban@gryag_bot        → 🤫 Silent ignore
00:11 - /gryagprofile@gryag_bot    → ⚠️ Warning shown again (10 min passed)
00:12 - /gryagfacts@gryag_bot      → 🤫 Silent ignore
```

### Scenario 3: Commands to Other Bots

```
00:00 - /start@another_bot         → ✅ Ignored (not our command)
00:01 - /help@gryag_bot            → ✅ Works (if not throttled)
00:02 - /gryagfacts@gryag_bot      → ⚠️ Warning (throttled)
```

## Implementation Details

### Files Modified

1. **`app/middlewares/command_throttle.py`**
   - Updated error message format (lines 178-183)
   - Updated log messages to reflect "silent ignore" behavior (lines 185-195)
   - No changes to filtering logic (already correct)

### Files Verified (No Changes Needed)

1. **`app/middlewares/command_throttle.py`** (lines 141-156)
   - Other bot command filtering already implemented correctly
   - Bot-to-bot protection already implemented (lines 110-124)

2. **`app/services/feature_rate_limiter.py`**
   - Warning cooldown system already implemented (10 min)
   - `should_send_error_message()` method already correct

3. **`app/handlers/chat.py`** (line 990)
   - Bot message filtering already implemented
   - `if message.from_user is None or message.from_user.is_bot: return`

### Configuration

**Current settings (no changes needed):**
- `ENABLE_COMMAND_THROTTLING=true` - Throttling enabled
- `COMMAND_COOLDOWN_SECONDS=300` - 5 minutes between commands
- Warning cooldown: 10 minutes (hardcoded in `FeatureRateLimiter._error_message_cooldown`)

## Testing Steps

### 1. Basic Throttling
```bash
# Test command cooldown
/gryagprofile@gryag_bot  # Should work
# Wait < 5 min
/gryagfacts@gryag_bot    # Should show warning
# Wait < 5 min
/gryagprofile@gryag_bot  # Should silently ignore
# Wait 5+ min
/gryagfacts@gryag_bot    # Should work
```

### 2. Warning Cooldown
```bash
# Test warning suppression
/gryagfacts@gryag_bot    # Should work
# Wait < 5 min
/gryagprofile@gryag_bot  # Should show warning (first time)
# Wait < 10 min, still < 5 min from start
/gryagfacts@gryag_bot    # Should silently ignore (no warning)
# Wait 10+ min from first warning
/gryagprofile@gryag_bot  # Should show warning again
```

### 3. Other Bot Filtering
```bash
/start@another_bot       # Should be completely ignored
/help@gryag_bot         # Should work normally
```

### 4. Admin Bypass
```bash
# As admin user (in ADMIN_USER_IDS)
/gryagprofile@gryag_bot  # Should work
/gryagfacts@gryag_bot    # Should work immediately (no throttle)
```

## Verification

Run tests to verify behavior:
```bash
source .venv/bin/activate
pytest tests/unit/test_middlewares.py -k command_throttle -v
pytest tests/integration/ -k throttle -v
```

Check logs for correct behavior:
```bash
# Should see "warning shown" for first violation
grep "warning shown" logs/gryag_*.log

# Should see "silently ignored" for subsequent violations
grep "silently ignored" logs/gryag_*.log

# Should see "different bot" for other bot commands
grep "different bot" logs/gryag_*.log
```

## Benefits

### User Experience
- ✅ Clear feedback on first violation
- ✅ No notification spam from repeated attempts
- ✅ Commands to other bots don't interfere

### System Protection
- ✅ Prevents command spam (5 min cooldown)
- ✅ Prevents notification spam (10 min warning cooldown)
- ✅ Bot-to-bot loop protection

### Developer Experience
- ✅ Clear log messages differentiate warning vs silent ignore
- ✅ Telemetry tracks both scenarios separately
- ✅ Easy to debug throttle issues

## Related Documentation

- **Feature docs**: `docs/features/COMMAND_THROTTLING.md` (updated)
- **Architecture**: `app/middlewares/command_throttle.py`
- **Rate limiter**: `app/services/feature_rate_limiter.py`
- **Configuration**: `.env.example` and `app/config.py`

## Notes

- The implementation already had all the pieces in place
- Main change was updating the error message format
- Other bot filtering was already working correctly
- Warning cooldown system was already implemented in `FeatureRateLimiter`
- This is a UX improvement, not a functional change
