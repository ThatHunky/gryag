# Fix: Admin Rate Limit Bypass

**Date**: 2025-10-14  
**Issue**: Admins were being subject to the same hourly message rate limits as regular users

## Problem

The rate limiter check was happening before the admin status check in the chat handler flow. This meant that admin users (defined in `ADMIN_USER_IDS` config) could be throttled and receive "Занадто багато повідомлень. Почекай X хв." messages even though they should have unlimited access.

### Original Flow

```python
# Line ~707 (BEFORE FIX)
if rate_limiter is not None:
    allowed, remaining, retry_after = await rate_limiter.check_and_increment(
        user_id=message.from_user.id
    )
    if not allowed:
        # ... throttle admin too!
        return

# Line ~733
is_admin = user_id in settings.admin_user_ids_list  # Too late!
```

## Solution

Moved the admin status check to happen **before** rate limiting, and added `not is_admin` condition to the rate limiter check.

### New Flow

```python
# Line ~707 (AFTER FIX)
user_id = message.from_user.id

# Check admin status first (admins bypass rate limiting)
is_admin = user_id in settings.admin_user_ids_list

# Rate limiting (skip for admins)
if not is_admin and rate_limiter is not None:
    allowed, remaining, retry_after = await rate_limiter.check_and_increment(
        user_id=message.from_user.id
    )
    if not allowed:
        # ... only throttle non-admins
        return
```

## Changes Made

**File**: `app/handlers/chat.py`

1. Moved `user_id` assignment earlier (before rate limiting)
2. Moved `is_admin` check to happen before rate limiting
3. Added `not is_admin` condition to rate limiter check
4. Added clear comments explaining the admin bypass

## Impact

- **Admins**: No longer subject to rate limits (unlimited messages per hour)
- **Regular users**: No change (still limited by `RATE_LIMIT_PER_USER_PER_HOUR` config)
- **Performance**: No impact (admin check is O(1) set membership test)
- **Security**: No change (admin list still controlled via config)

## Verification

### Manual Testing

1. **Test as admin user** (user_id in `ADMIN_USER_IDS`):
   ```bash
   # Send 50+ messages in an hour
   # Should NOT receive throttle message
   # Should NOT see any "chat.rate_limited" telemetry for this user
   ```

2. **Test as regular user**:
   ```bash
   # Send messages exceeding RATE_LIMIT_PER_USER_PER_HOUR
   # Should receive "Занадто багато повідомлень. Почекай X хв."
   # Should see "chat.rate_limited" telemetry
   ```

### Log Verification

```bash
# Check that admins are NOT being rate limited
grep "chat.rate_limited" logs/gryag.log | grep "user_id.*831570515"  # Should be empty for admin

# Check that regular users ARE being rate limited (if they exceed limit)
grep "chat.rate_limited" logs/gryag.log | grep -v "user_id.*831570515"  # Should show throttled users
```

### Telemetry Check

```bash
# Admin requests should show "chat.addressed" but NOT "chat.rate_limited"
# Regular user requests beyond limit should show "chat.rate_limited"
```

## Configuration

Admins are defined in `.env`:

```bash
# Comma-separated list of admin user IDs (no rate limits, can use admin commands)
ADMIN_USER_IDS=831570515,392817811
```

Rate limit is configurable:

```bash
# Max messages per user per hour (0 = unlimited for everyone)
RATE_LIMIT_PER_USER_PER_HOUR=30
```

## Related Code

- `app/services/rate_limiter.py` - Rate limiter implementation
- `app/config.py` - Settings for `admin_user_ids_list` and rate limit
- `app/handlers/chat.py` - Main chat handler with rate limiting
- `db/schema.sql` - `rate_limits` table schema

## Future Improvements

1. **Admin bypass logging** - Add debug log when admin bypasses rate limit
2. **Telemetry counter** - Track "chat.admin_bypass" for monitoring
3. **Per-admin limits** - Allow different limits for different admin levels
4. **Dynamic admin list** - Store admin list in database instead of config

---

**Status**: ✅ Implemented  
**Tested**: Manual testing required  
**Breaking Changes**: None
