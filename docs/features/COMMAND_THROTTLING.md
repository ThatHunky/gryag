# Command Throttling System - Updated October 26, 2025

## Overview

Smart command throttling system that prevents spam while maintaining good UX. **Only bot commands** (slash commands) are throttled - regular messages are never throttled.

**Key Behavior:**
- First violation: Shows warning message with time remaining
- Continued spam: Silently ignores commands (no notification spam)
- Commands to other bots: Completely ignored (not processed)
- Admin bypass: Admin users bypass all throttling

---

## Features

### 1. Smart Warning System
- **First throttle violation**: User sees warning with countdown
- **Subsequent violations**: Silently ignored (no spam)
- **Warning cooldown**: Max one warning per 10 minutes
- **User experience**: Clear feedback without notification spam

### 2. Universal Command Cooldown
- **All commands** starting with `/` are throttled
- Default: **5 minutes** cooldown between commands
- Configurable: 1 minute to 1 hour via `COMMAND_COOLDOWN_SECONDS`
- **Admins exempt**: Users in `ADMIN_USER_IDS` bypass throttling

### 3. Other Bot Command Filtering
- Commands with `@other_bot` mention are completely ignored
- Commands with `@gryag_bot` or no mention are processed
- Bot-to-bot protection: Commands from bot users are dropped

### 3. Per-User Tracking
- Each user has independent cooldown timer
- Stored in database (`feature_cooldowns` table)
- Automatic cleanup of old records

---

## How It Works

### Flow Diagram

```
User sends command (/gryagfacts)
         ↓
Is user an admin? → YES → Allow immediately ✅
         ↓ NO
### Flow Diagram

```text
User sends command (/gryagfacts)
         ↓
Is command for other bot (@other_bot)? → YES → Ignore completely ✅
         ↓ NO
Is user from bot account? → YES → Drop completely ✅
         ↓ NO
Is user an admin? → YES → Allow immediately ✅
         ↓ NO
Check last command time
         ↓
< 5 minutes ago? → YES → Check warning cooldown
         ↓                        ↓
         NO                  > 10 min since warning? → YES → Show warning ⚠️
         ↓                        ↓                            ↓
Allow command ✅                NO                    Silently ignore 🤫
Update last_used                     ↓
                          Silently ignore 🤫
```

### Example Timeline

```text
00:00 - User: /gryagfacts@gryag_bot           → ✅ Allowed (first command)
00:02 - User: /gryagprofile@gryag_bot         → ⚠️ Warning shown (wait 4m 58s)
00:03 - User: /gryagfacts@gryag_bot           → 🤫 Silent ignore (warning shown recently)
00:04 - User: /gryagban@gryag_bot             → 🤫 Silent ignore (warning shown recently)
00:05 - User: /gryagfacts@gryag_bot           → ✅ Allowed (cooldown expired)
00:06 - User: /gryagprofile@gryag_bot         → ⚠️ Warning shown (wait 4m 59s)
00:07 - User: /start@other_bot                → ✅ Ignored (not our command)
00:16 - User: /gryagfacts@gryag_bot           → ⚠️ Warning shown again (10 min passed since first warning)
```

### Throttle Message

When blocked (first time or after 10 min cooldown), user sees:

```text
Зачекай трохи!

Команди можна використовувати раз на 5 хвилин. Наступна команда через: ⏱ 4 хв 30 сек
```

**Note**: The message format matches Telegram's natural style (no extra formatting like `<b>` or `<code>` in display).

---

## Configuration

### Environment Variables

```env
# Enable/disable command throttling
ENABLE_COMMAND_THROTTLING=true

# Cooldown duration (seconds)
COMMAND_COOLDOWN_SECONDS=300    # 5 minutes (default)
                                # Min: 60 (1 minute)
                                # Max: 3600 (1 hour)

# Admin users (bypass throttling)
ADMIN_USER_IDS=123456789,987654321
```

### Examples

**Lenient (1 minute cooldown)**:
```env
COMMAND_COOLDOWN_SECONDS=60
```

**Strict (10 minute cooldown)**:
```env
COMMAND_COOLDOWN_SECONDS=600
```

**Disable throttling**:
```env
ENABLE_COMMAND_THROTTLING=false
```

---

## Database Schema

### feature_cooldowns Table

```sql
CREATE TABLE feature_cooldowns (
    user_id INTEGER NOT NULL,
    feature_name TEXT NOT NULL,        -- "bot_commands"
    last_used INTEGER NOT NULL,        -- Unix timestamp
    cooldown_seconds INTEGER NOT NULL, -- Duration
    PRIMARY KEY (user_id, feature_name)
);
```

### Sample Data

```sql
SELECT * FROM feature_cooldowns WHERE feature_name = 'bot_commands';

user_id   | feature_name  | last_used  | cooldown_seconds
----------|---------------|------------|------------------
12345     | bot_commands  | 1729500000 | 300
67890     | bot_commands  | 1729500120 | 300
```

---

## Implementation Details

### Files Created/Modified

**New Files** (1):
- `app/middlewares/command_throttle.py` - Middleware implementation (114 lines)

**Modified Files** (3):
1. `app/main.py` - Initialize and attach middleware
2. `app/config.py` - Add throttling config fields
3. `.env.example` - Document configuration

### Code Statistics
- **New Code**: 114 lines (middleware)
- **Modified Code**: ~50 lines
- **Total Impact**: 164 lines

### Integration Points

```python
# app/main.py

# Initialize feature rate limiter
feature_limiter = FeatureRateLimiter(db_path, admin_ids)
await feature_limiter.init()

# Attach middleware
dispatcher.message.middleware(
    CommandThrottleMiddleware(settings, feature_limiter)
)
```

### Middleware Logic

```python
async def __call__(self, handler, event, data):
    # 1. Check if throttling is enabled
    if not self.enabled:
        return await handler(event, data)

    # 2. Only process commands
    if not event.text.startswith("/"):
        return await handler(event, data)

    # 3. Admins bypass
    if user_id in admin_list:
        return await handler(event, data)

    # 4. Check cooldown
    allowed, retry_after = await limiter.check_cooldown(
        user_id, "bot_commands", cooldown_seconds
    )

    # 5. Block or allow
    if not allowed:
        await event.reply(throttle_message)
        return None  # Stop processing

    return await handler(event, data)
```

---

## Benefits

### For Users
- **Fair access**: Prevents individual users from monopolizing bot
- **Clear feedback**: Exact wait time displayed
- **Consistent**: All commands treated equally

### For Administrators
- **No spam**: Can't flood bot with commands
- **Configurable**: Adjust cooldown based on needs
- **Admin bypass**: Unrestricted access for admins
- **Visibility**: Logs show throttled attempts

### For System
- **Resource protection**: Reduces database load
- **API cost savings**: Fewer unnecessary API calls
- **Performance**: Less processing overhead
- **Scalability**: Handles more users without degradation

---

## Testing

### Manual Testing

```bash
# 1. Normal user (throttled)
User: /gryagfacts
Bot: [Shows facts]

User: /gryagprofile  (immediately after)
Bot: ⏱ Зачекай трохи! Команди можна використовувати раз на 5 хвилин.

# Wait 5 minutes

User: /gryagfacts
Bot: [Shows facts]

# 2. Admin user (not throttled)
Admin: /gryagfacts
Bot: [Shows facts]

Admin: /gryagprofile  (immediately after)
Bot: [Shows profile]  ✅ No throttle!

# 3. Disabled throttling
# Set ENABLE_COMMAND_THROTTLING=false
User: /gryagfacts
Bot: [Shows facts]

User: /gryagprofile  (immediately after)
Bot: [Shows profile]  ✅ No throttle!
```

### Database Verification

```bash
# Check cooldown records
sqlite3 gryag.db "SELECT * FROM feature_cooldowns WHERE feature_name = 'bot_commands';"

# Check if user is throttled
sqlite3 gryag.db "
SELECT
    user_id,
    datetime(last_used, 'unixepoch') as last_used_time,
    cooldown_seconds,
    (strftime('%s', 'now') - last_used) as seconds_elapsed,
    (cooldown_seconds - (strftime('%s', 'now') - last_used)) as seconds_remaining
FROM feature_cooldowns
WHERE feature_name = 'bot_commands'
  AND user_id = 12345;
"
```

### Log Verification

```bash
# Check throttle events in logs
grep "Command throttled" logs/gryag.log

# Example output:
# 2025-10-21 14:30:45 INFO Command throttled for user 12345, retry after 245s
```

---

## Troubleshooting

### Issue: Commands not throttled

**Check**:
1. Is `ENABLE_COMMAND_THROTTLING=true`?
2. Is middleware attached? (`grep CommandThrottleMiddleware app/main.py`)
3. Is user an admin? (`grep ADMIN_USER_IDS .env`)

### Issue: Cooldown too long/short

**Solution**:
```env
# Adjust cooldown duration
COMMAND_COOLDOWN_SECONDS=180  # 3 minutes instead of 5
```

### Issue: Need to reset user's cooldown

**SQL Command**:
```sql
-- Reset specific user
DELETE FROM feature_cooldowns
WHERE user_id = 12345 AND feature_name = 'bot_commands';

-- Reset all command cooldowns
DELETE FROM feature_cooldowns WHERE feature_name = 'bot_commands';
```

**Future**: Will add admin command `/gryagresetthrottle <user_id>`

---

## Future Enhancements

### Planned Features

1. **Admin Commands** (Priority: High)
   - `/gryagthrottle <user_id>` - View user's cooldown status
   - `/gryagresetthrottle <user_id>` - Reset user's cooldown
   - `/gryagsetcooldown <seconds>` - Dynamically adjust cooldown

2. **Per-Command Granularity** (Priority: Medium)
   - Different cooldowns for different commands
   - Example: `/gryagfacts` = 5 min, `/gryagban` = no cooldown

3. **Adaptive Cooldowns** (Priority: Low)
   - Good users: Shorter cooldowns
   - Spammy users: Longer cooldowns
   - Based on reputation system

4. **Whitelist Commands** (Priority: Low)
   - Exempt certain commands from throttling
   - Example: `/start`, `/help` always allowed

### Roadmap

- **Phase 1** (Complete): Basic command throttling ✅
- **Phase 2** (1 day): Admin commands for throttle management
- **Phase 3** (2 days): Per-command granular limits
- **Phase 4** (3 days): Integration with adaptive reputation system

---

## Related Documentation

- [Feature Rate Limiter](../services/feature_rate_limiter.py) - Underlying service
- [Comprehensive Improvements](COMPREHENSIVE_IMPROVEMENTS_2025_10_21.md) - Full improvements doc
- [Configuration Guide](../guides/CONFIGURATION.md) - All config settings (to be updated)

---

## Changelog Entry

```markdown
**October 21, 2025**: **⏱ Command Throttling Implemented** - Added universal command
throttling to prevent spam. All bot commands limited to 1 per 5 minutes per user
(configurable via `COMMAND_COOLDOWN_SECONDS=300`). Admins bypass restrictions. Clear
error messages show exact wait time. Created `CommandThrottleMiddleware` (114 lines),
integrated with `FeatureRateLimiter`. Database: `feature_cooldowns` table tracks
per-user cooldowns. Configuration: `ENABLE_COMMAND_THROTTLING=true` (default),
`COMMAND_COOLDOWN_SECONDS=300` (range: 60-3600). See
`docs/features/COMMAND_THROTTLING.md`. Verification: Send 2 commands within 5 minutes,
second should be blocked with wait time message.
```

---

## Summary

✅ **Implemented**: Universal command throttling (1 per 5 min)
✅ **Configurable**: Cooldown duration and enable/disable flag
✅ **Admin bypass**: Admins unrestricted
✅ **User-friendly**: Clear error messages with exact wait times
✅ **Database-backed**: Persistent cooldown tracking
✅ **Production-ready**: Tested and documented
✅ **Error message cooldown**: Shows throttle message once per 10 minutes, then silently blocks

**Status**: Complete and deployed
**Impact**: Prevents command spam, protects resources, reduces error message spam
**User Experience**: Minimal friction, clear feedback without repetitive error messages
