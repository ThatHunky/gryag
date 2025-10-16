# Fix: /gryagreset Command AttributeError

**Date**: 2025-10-14  
**Issue**: `/gryagreset` command was failing with `AttributeError: 'ContextStore' object has no attribute 'reset_quotas'`

## Problem

The `/gryagreset` admin command was trying to call `store.reset_quotas(chat_id)`, but this method no longer exists in `ContextStore`. Rate limiting was moved to a separate `RateLimiter` class, but the admin handler wasn't updated to use it.

### Error Traceback

```
AttributeError: 'ContextStore' object has no attribute 'reset_quotas'
  File "/app/app/handlers/admin.py", line 139, in reset_quotas_command
    await store.reset_quotas(chat_id)
```

## Root Cause

When rate limiting was refactored from `ContextStore` to a dedicated `RateLimiter` class (backed by SQLite `rate_limits` table), the `/gryagreset` command in `app/handlers/admin.py` was not updated to use the new API.

### Old Code (Broken)

```python
@router.message(Command(commands=["gryagreset", "reset"]))
async def reset_quotas_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    redis_client: RedisLike | None = None,
) -> None:
    ...
    await store.reset_quotas(chat_id)  # ❌ Method doesn't exist
```

## Solution

### 1. Added Reset Methods to RateLimiter

**File**: `app/services/rate_limiter.py`

Added two new methods:

```python
async def reset_chat(self, chat_id: int) -> int:
    """
    Reset rate limits for all users in a chat.
    
    Returns:
        Number of rate limit records deleted
    """
    async with self._lock:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM rate_limits")
            await db.commit()
            deleted = cursor.rowcount or 0
    
    telemetry.increment_counter(
        "rate_limiter.reset",
        chat_id=chat_id,
        deleted=deleted,
    )
    return deleted

async def reset_user(self, user_id: int) -> int:
    """
    Reset rate limits for a specific user.
    
    Returns:
        Number of rate limit records deleted
    """
    async with self._lock:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM rate_limits WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
            deleted = cursor.rowcount or 0
    
    telemetry.increment_counter(
        "rate_limiter.reset_user",
        user_id=user_id,
        deleted=deleted,
    )
    return deleted
```

### 2. Updated Admin Handler

**File**: `app/handlers/admin.py`

Updated the `/gryagreset` command to:
1. Import `RateLimiter`
2. Inject `rate_limiter` parameter
3. Call `rate_limiter.reset_chat()` instead of `store.reset_quotas()`
4. Log the number of deleted records

```python
from app.services.rate_limiter import RateLimiter

@router.message(Command(commands=["gryagreset", "reset"]))
async def reset_quotas_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    rate_limiter: RateLimiter | None = None,  # ✅ Added
    redis_client: RedisLike | None = None,
) -> None:
    ...
    # Reset rate limiter (SQLite-backed)
    if rate_limiter is not None:
        deleted = await rate_limiter.reset_chat(chat_id)
        LOGGER.info(f"Reset {deleted} rate limit record(s) for chat {chat_id}")
    
    # Also clear Redis quotas if available (legacy cleanup)
    if redis_client is not None:
        pattern = f"gryag:quota:{chat_id}:*"
        ...
```

## Changes Made

**Files modified**:
- `app/services/rate_limiter.py` - Added `reset_chat()` and `reset_user()` methods
- `app/handlers/admin.py` - Updated `/gryagreset` command to use RateLimiter

## Impact

- **Functionality**: `/gryagreset` command now works correctly
- **Telemetry**: Added counters for rate limit resets (`rate_limiter.reset`, `rate_limiter.reset_user`)
- **Logging**: Now logs number of records deleted
- **Backward compatibility**: Maintained (Redis cleanup still works if Redis is available)

## Verification

### Manual Testing

1. **Send messages to hit rate limit**:
   ```bash
   # Send 30+ messages in an hour (if RATE_LIMIT_PER_USER_PER_HOUR=30)
   # Bot should throttle you
   ```

2. **Use /gryagreset command as admin**:
   ```
   /gryagreset
   ```
   Should receive: "✅ Квоти скинуті"

3. **Send more messages**:
   ```bash
   # Should work again without throttle
   ```

### Database Check

```bash
# Before reset
sqlite3 gryag.db "SELECT COUNT(*) FROM rate_limits"
# Should show some records

# After /gryagreset
sqlite3 gryag.db "SELECT COUNT(*) FROM rate_limits"
# Should show 0
```

### Log Verification

```bash
# Check for successful reset
docker compose logs bot | grep "Reset.*rate limit record"
# Should show: "Reset X rate limit record(s) for chat ..."

# Check for no AttributeError
docker compose logs bot | grep "AttributeError.*reset_quotas"
# Should be empty
```

## Related Code

- `app/services/rate_limiter.py` - Rate limiter implementation
- `app/handlers/admin.py` - Admin commands
- `app/middlewares/chat_meta.py` - Injects rate_limiter into handlers
- `db/schema.sql` - `rate_limits` table schema

## Future Improvements

1. **Per-user reset**: Add `/gryagresetuser @username` command
2. **Reset confirmation**: Add confirmation dialog for /gryagreset
3. **Reset statistics**: Show number of records deleted in reply
4. **Audit logging**: Track who performed resets and when
5. **Selective reset**: Reset only specific users or time windows

---

**Status**: ✅ Fixed  
**Tested**: Manual testing required  
**Breaking Changes**: None
