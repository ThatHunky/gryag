# Fix: Production Errors - October 9, 2025

**Date**: 2025-10-09  
**Status**: ✅ Fixed  
**Impact**: Multiple production errors resolved

## Summary

Fixed three categories of production errors identified in logs:
1. **UserProfileStoreAdapter missing methods** (20+ errors)
2. **Unclosed aiohttp client sessions** (resource leaks on shutdown)
3. **High CPU usage warnings** (115 occurrences, monitoring issue)

## Problem 1: UserProfileStoreAdapter Missing Methods

### Errors

```
AttributeError: 'UserProfileStoreAdapter' object has no attribute 'get_or_create_profile'
AttributeError: 'UserProfileStoreAdapter' object has no attribute 'get_user_summary'
AttributeError: 'UserProfileStoreAdapter' object has no attribute 'get_fact_count'
```

### Root Cause

The `UserProfileStoreAdapter` was created as a compatibility layer during the unified fact storage migration (2025-10-08), but it only implemented `add_fact()` and `get_facts()`. Many other methods from the original `UserProfileStore` were still being called by:
- `app/handlers/chat.py` - user profile background updates
- `app/services/context/multi_level_context.py` - background context assembly
- `app/handlers/profile_admin.py` - admin commands

### Solution

Added 5 missing methods to `UserProfileStoreAdapter`:

1. **`get_fact_count(user_id, chat_id)`** - Count active facts for a user
2. **`get_or_create_profile(user_id, chat_id, display_name, username)`** - Get/create user profile
3. **`get_profile(user_id, chat_id, limit)`** - Get user profile
4. **`get_relationships(user_id, chat_id, min_strength)`** - Get user relationships  
5. **`get_user_summary(user_id, chat_id, ...)`** - Generate text summary of user profile

All methods use direct SQLite queries since they involve tables other than `facts` (user_profiles, user_relationships).

### Files Modified

- `app/services/user_profile_adapter.py` - Added 5 methods (~150 lines), added imports for `aiosqlite` and `time`

## Problem 2: Unclosed aiohttp Client Sessions

### Errors

```
ERROR - asyncio - Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x7fd4a575e900>
ERROR - asyncio - Unclosed connector
connections: ['deque([(<aiohttp.client_proto.ResponseHandler object...
```

### Root Cause

`WeatherService` and `CurrencyService` both maintain persistent aiohttp sessions for API calls. These services have `close()` methods and cleanup functions (`cleanup_weather_service()`, `cleanup_currency_service()`), but they were never being called on bot shutdown.

### Solution

Added cleanup calls in `app/main.py` shutdown handler (finally block):

```python
# Cleanup: Close aiohttp sessions for external services
from app.services.weather import cleanup_weather_service
from app.services.currency import cleanup_currency_service

try:
    await cleanup_weather_service()
    await cleanup_currency_service()
    logging.info("External service clients closed")
except Exception as e:
    logging.warning(f"Error closing external service clients: {e}")
```

### Files Modified

- `app/main.py` - Added cleanup calls in finally block

## Problem 3: High CPU Usage Warnings

### Observations

```
2025-10-09 17:00:29 - ERROR - app.services.resource_monitor - CRITICAL: CPU usage at 100.0%
2025-10-09 17:03:01 - ERROR - app.services.resource_monitor - CRITICAL: CPU usage at 100.0%
```

- 115 critical CPU warnings in logs
- Thresholds: WARNING at 85%, CRITICAL at 95%
- CPU spikes appear to be system-wide (not just bot process)
- Bot process shows 0.0% CPU in monitoring logs during system spikes

### Analysis

This is **NOT a bot bug**. The resource monitor is correctly detecting and logging high system CPU usage. The bot itself uses minimal CPU (0.0% during spikes). The warnings help trigger resource optimization (throttling, cache adjustments).

### Action

No code changes needed. This is the resource monitor working as designed. High system CPU may be due to:
- Other processes on the server
- Database queries (SQLite FTS5 searches can be CPU-intensive)
- External factors (VM oversubscription, etc.)

Consider:
- Increasing thresholds if warnings are too noisy: `CPU_CRITICAL_THRESHOLD = 98.0`
- Monitoring server-level CPU with external tools
- Optimizing database queries if bot CPU usage increases

### Files Reviewed

- `app/services/resource_monitor.py` - Verified thresholds are reasonable
- `app/services/resource_optimizer.py` - Confirmed it responds to CPU pressure

## Backward Compatibility

✅ **All changes are backward compatible**:
- New adapter methods use same signatures as original `UserProfileStore`
- Cleanup functions are wrapped in try/except to avoid breaking shutdown
- No breaking changes to existing code

## Testing

### Syntax Validation

```bash
# Both files compile successfully
python3 -m py_compile app/services/user_profile_adapter.py  # ✓
python3 -m py_compile app/main.py  # ✓
```

### Verification After Deployment

1. **Check for AttributeError in logs**:

   ```bash
   grep "AttributeError.*UserProfileStoreAdapter" logs/gryag.log
   ```

   Should return no new errors after deployment

2. **Check for unclosed sessions**:

   ```bash
   grep "Unclosed client session" logs/gryag.log
   ```

   Should stop appearing after bot restarts

3. **Monitor CPU warnings**:

   ```bash
   tail -f logs/gryag.log | grep "CPU usage"
   ```

   Warnings will continue (system-level issue), but no adapter errors

4. **Test profile commands**:

   ```text
   /gryagprofile @username
   /gryagfacts @username
   /gryagfacts @username location
   ```

   Should work without errors

## Related Issues

- **2025-10-09** - Fixed `TypeError: get_facts() got unexpected keyword argument 'fact_type'` (separate fix in same session)
- **2025-10-08** - Unified Fact Storage migration created the adapter that needed these methods

## Files Changed

1. `app/services/user_profile_adapter.py` - Added 5 missing methods
2. `app/main.py` - Added aiohttp session cleanup
3. `docs/fixes/production_errors_2025-10-09.md` - This document
