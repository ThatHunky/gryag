# Fix: UserProfileStoreAdapter.get_facts() TypeError

**Date**: 2025-10-09  
**Issue**: `TypeError: UserProfileStoreAdapter.get_facts() got an unexpected keyword argument 'fact_type'`  
**Status**: ✅ Fixed

## Problem

The `UserProfileStoreAdapter.get_facts()` method was missing the `fact_type` and `min_confidence` parameters that were being used by callers, specifically in `app/handlers/profile_admin.py`:

```python
# Line 250 in profile_admin.py
facts = await profile_store.get_facts(
    user_id=user_id,
    chat_id=chat_id,
    fact_type=fact_type_filter,  # ← This parameter was not supported
    limit=20,
)
```

This caused multiple errors in production logs (20+ occurrences).

## Root Cause

The `UserProfileStoreAdapter` was created as a compatibility layer between the old `UserProfileStore` API and the new `UnifiedFactRepository`, but it didn't include all the parameters that the old API supported:

- `fact_type` parameter for filtering by fact category
- `min_confidence` parameter for confidence threshold filtering

## Solution

Updated `app/services/user_profile_adapter.py` to add both missing parameters:

### Changes Made

1. **Added `fact_type` parameter** (optional, defaults to `None`)
   - Maps to `categories` parameter in `UnifiedFactRepository.get_facts()`
   - Converts single string to list format: `[fact_type]` if provided

2. **Added `min_confidence` parameter** (optional, defaults to `0.0`)
   - Passes through directly to `UnifiedFactRepository.get_facts()`
   - Filters facts below the confidence threshold

### Updated Method Signature

```python
async def get_facts(
    self,
    user_id: int,
    chat_id: int,
    fact_type: str | None = None,        # ← NEW
    limit: int = 100,
    min_confidence: float = 0.0,         # ← NEW
) -> list[dict[str, Any]]:
```

### Implementation

```python
# Convert fact_type to categories list if provided
categories = [fact_type] if fact_type else None

facts = await self._fact_repo.get_facts(
    entity_id=entity_id,
    chat_context=chat_context,
    categories=categories,              # ← Maps fact_type
    limit=limit,
    min_confidence=min_confidence,      # ← Pass through
)
```

## Backward Compatibility

✅ **All existing callers remain compatible** - both parameters are optional with safe defaults:

- `fact_type=None` → no filtering (all categories)
- `min_confidence=0.0` → no filtering (all confidence levels)

### Verified Callers

Checked all usages of `profile_store.get_facts()`:

1. **`app/handlers/profile_admin.py`** (line 250) - Now works with `fact_type` parameter
2. **`app/handlers/profile_admin.py`** (line 459) - Works (no `fact_type` used)
3. **`app/services/tools/memory_tools.py`** (multiple) - Works (no `fact_type` used)
4. **`app/services/context/multi_level_context.py`** (line 466) - Works (uses `min_confidence`)
5. **`app/services/monitoring/continuous_monitor.py`** (line 611) - Works (no extra params)

## Testing

- ✅ Syntax check passed: `python3 -m py_compile app/services/user_profile_adapter.py`
- ✅ All existing callers verified for compatibility
- ✅ No breaking changes introduced

## How to Verify

1. **Check logs for the error**:

   ```bash
   grep "TypeError.*get_facts.*fact_type" logs/gryag.log | wc -l
   ```

   Should return 0 after the fix is deployed

2. **Test the profile admin command**:

   ```text
   /gryagfacts @username location
   ```

   Should return facts filtered by the "location" type without errors

3. **Monitor for new occurrences**:

   ```bash
   tail -f logs/gryag.log | grep "TypeError"
   ```

   Should not show this error anymore

## Files Modified

- `app/services/user_profile_adapter.py` - Added `fact_type` and `min_confidence` parameters to `get_facts()` method

## Related

- **UnifiedFactRepository**: `app/repositories/fact_repository.py` (already supports filtering via `categories` parameter)
- **Admin Handler**: `app/handlers/profile_admin.py` (caller that exposed the bug)
- **Architecture**: Part of the migration from separate UserProfileStore/ChatProfileRepository to unified fact storage
