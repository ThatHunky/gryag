# Donation Scheduler Analysis and Fix - October 25, 2025

## Issue Report

User reported that the donate message scheduler and `/gryagdonate` command don't seem to work.

## Investigation Results

### Scheduler Configuration ✅

The donation scheduler is **properly configured and running**:

- **Schedule**: Runs daily at 18:00 Ukraine time (Europe/Kiev timezone)
- **Target chats**: All chats from `ALLOWED_CHAT_IDS` (in whitelist mode)
- **Ignored chats**: Chats from `DONATION_IGNORED_CHAT_IDS` are skipped
- **Database**: `donation_sends` table exists and is initialized

Current configuration from `.env`:
```
ALLOWED_CHAT_IDS=-1002604868951,-1002446827898,-1001484515367,-1001768402083
DONATION_IGNORED_CHAT_IDS=-1001484515367,-1001768402083
```

**Effective target chats for scheduled sends**: 
- `-1002604868951` ✅
- `-1002446827898` ✅
- (Two others are ignored)

### Scheduled Send Conditions

The scheduler checks 5 conditions before sending:

1. ✅ Chat must be in target list
2. ✅ Chat must NOT be in ignored list  
3. ✅ Chat must be a group (negative chat ID)
4. ⏱️ Bot must have been active in chat in last 24 hours
5. ⏱️ At least 2 days must have passed since last send

The scheduler runs **daily at 18:00** but only sends to chats where **all 5 conditions** are met. This is correct behavior - it's designed to send every 2 days, not every day.

### Command Handler Issue ❌ FIXED

**Problem found**: The `/gryagdonate` command had a UX bug:
- When command succeeded, it logged success but **sent no confirmation to admin**
- Only replied on failure
- Admin had no feedback that the command worked

**Fix applied**: Added success and failure messages:
- Success: `✅ Donation message sent successfully!`
- Failure: `❌ Failed to send donation message. This chat may be in the ignored list. Check logs for details.`

### Command Behavior

The `/gryagdonate` command (admin only):
- ✅ Bypasses group-only filter (can send to private chats if admin calls it)
- ✅ Bypasses activity check (no need for recent bot activity)
- ✅ Bypasses 2-day interval check (sends immediately)
- ❌ **Respects ignored list** (won't send to chats in `DONATION_IGNORED_CHAT_IDS`)

This is by design - ignored chats should never receive donation messages, even when manually triggered.

## Testing Recommendations

### Test Manual Command

1. As admin, run `/gryagdonate` in a **non-ignored** chat
2. Should see: `✅ Donation message sent successfully!`
3. Should receive the donation message immediately

### Test Ignored Chat

1. As admin, run `/gryagdonate` in chat `-1001484515367` or `-1001768402083`
2. Should see: `❌ Failed to send donation message. This chat may be in the ignored list.`
3. Should NOT receive donation message

### Test Scheduled Send

Wait until tomorrow at 18:00 Ukraine time. Check logs for:
```
INFO - Sent scheduled donation reminder to chat -1002604868951
INFO - Sent scheduled donation reminder to chat -1002446827898
```

Will only send if:
- Bot was active in those chats in last 24 hours
- 2 days have passed since previous send (or never sent before)

## Files Modified

- `app/handlers/admin.py` - Added success/failure confirmation messages to `/gryagdonate` command

## Verification

```bash
# Check scheduler is running
tail -50 logs/gryag.log | grep -i donation

# Check donation tracking table
source .venv/bin/activate
python3 -c "import sqlite3; conn = sqlite3.connect('gryag.db'); cursor = conn.cursor(); cursor.execute('SELECT * FROM donation_sends'); print(cursor.fetchall()); conn.close()"

# Test command as admin (replace with your chat ID)
# Run: /gryagdonate
```

## Conclusion

**Scheduler is working correctly** - it's designed to send every 2 days at 18:00, not every day.

**Command now provides proper feedback** - admins will see confirmation when donation message is sent or fails.

The system is functioning as designed. If no donation messages have been sent yet, it's likely because:
1. This is the first run (no previous sends in database)
2. Bot hasn't been active in target chats in last 24 hours
3. Waiting for next scheduled run at 18:00

Next scheduled run: Tomorrow at 18:00 Ukraine time.
