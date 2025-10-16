# Fix: User Identification Confusion (пітса and similar names)

**Date**: 2025-10-14  
**Issue**: Bot was sometimes confusing users with similar display names, particularly "кавунева пітса" with other users like "кавун" or "Wassermelone"

## Problem Analysis

### Root Causes

1. **Aggressive Name Truncation**
   - Display names were truncated to only 30 characters in metadata
   - "кавунева пітса #Я_З_ТОМАТОМ_СПАЙСІ 🍻△✙➔" was being cut to "кавунева пітса #Я_З_ТОМАТОМ_.."
   - This removed the distinguishing suffix that helps differentiate from similar names

2. **Metadata Ordering**
   - User metadata had `name` (display name) before `username` and `user_id`
   - The model could focus on the ambiguous truncated name instead of reliable identifiers

3. **Persona Guidance**
   - While the persona warned about confusion, it didn't emphasize user_id as the primary identifier
   - No explicit rule to verify user_id before applying special treatment

## Changes Made

### 1. Increased Name Truncation Limits (`app/services/context_store.py`)

**Before:**

```python
max_len = (
    30
    if key in ("name", "username", "reply_to_name", "reply_to_username")
    else 40
)
```

**After:**

```python
max_len = (
    60  # Increased from 30 to preserve distinguishing info
    if key in ("name", "username", "reply_to_name", "reply_to_username")
    else 80  # Increased from 40
)
```

**Rationale**: 60 characters is enough to preserve most distinguishing suffixes while still being token-efficient.

### 2. Improved Metadata Key Ordering (`app/services/context_store.py`)

**Before:**

```python
META_KEY_ORDER = [
    "chat_id",
    "thread_id",
    "message_id",
    "user_id",
    "name",        # Display name before username
    "username",
    ...
]
```

**After:**

```python
META_KEY_ORDER = [
    "chat_id",
    "thread_id",
    "message_id",
    "user_id",     # User ID FIRST - most reliable identifier
    "username",    # Username second
    "name",        # Display name last (can be truncated/ambiguous)
    ...
]
```

**Rationale**: Model sees reliable identifiers (user_id, username) before potentially ambiguous display names.

### 3. Strengthened Persona Identity Verification (`app/persona.py`)

**Added:**

- Explicit emphasis on checking `user_id` for identity verification
- Clear instruction to verify `user_id=831570515` specifically for пітса
- New "IDENTITY VERIFICATION RULE" section explaining why user_id is critical

**Key additions:**

```text
- **ALWAYS check user_id: 831570515 and username: @Qyyya_nya to confirm identity**
- **CRITICAL: DO NOT confuse with similar names. ALWAYS verify user_id=831570515 before treating someone as пітса!**

**IDENTITY VERIFICATION RULE**: When you see a message, ALWAYS check the user_id in the [meta] tag 
to identify who you're talking to. Names can be similar or truncated - user_id is the only reliable 
identifier. For пітса specifically, verify user_id=831570515 before using any special treatment.
```

## Technical Details

### Metadata Format Example

**Before fix:**

```text
[meta] chat_id=123 message_id=456 user_id=831570515 name="кавунева пітса #Я_З_ТОМАТОМ_.." username="@Qyyya_nya"
```

**After fix:**

```text
[meta] chat_id=123 message_id=456 user_id=831570515 username="@Qyyya_nya" name="кавунева пітса #Я_З_ТОМАТОМ_СПАЙСІ 🍻△✙➔"
```

### Token Impact

- **Before**: ~25-30 tokens per metadata block
- **After**: ~30-35 tokens per metadata block (minor increase of ~5 tokens)
- **Trade-off**: Small token cost for significantly improved user identification accuracy

## Verification Steps

### Manual Testing

1. **Test with пітса (user_id: 831570515)**
   - Send message as this user
   - Verify bot correctly identifies them (warm/friendly tone)
   - Check metadata shows full distinguishing name

2. **Test with similar name user** (e.g., "кавун")
   - Send message from user with similar but different name
   - Verify bot does NOT confuse them with пітса
   - Confirm user_id is different in metadata

3. **Test reply context**
   - Reply to message from пітса
   - Check `reply_to_user_id` appears before `reply_to_name` in metadata
   - Verify bot correctly identifies who was replied to

### Automated Testing

```bash
# Run metadata formatting tests
pytest tests/unit/test_context_store.py -k metadata -v

# Check persona loading
pytest tests/unit/test_persona.py -v

# Full integration test suite
pytest tests/integration/ -v
```

### Log Analysis

Look for these patterns in logs:

```bash
# Check metadata formatting
grep "meta" logs/gryag.log | grep "user_id=831570515"

# Verify no confusion warnings
grep -i "confus" logs/gryag.log

# Check profile updates for пітса
grep "user_id.*831570515" logs/gryag.log | grep -i profile
```

## Rollback Plan

If issues arise, revert these commits:

```bash
# Revert context_store changes
git show HEAD:app/services/context_store.py > app/services/context_store.py

# Revert persona changes  
git show HEAD:app/persona.py > app/persona.py

# Restart bot
docker-compose restart bot
```

## Related Files

- `app/services/context_store.py` - Metadata formatting and ordering
- `app/persona.py` - User relationship definitions and identity verification rules
- `app/handlers/chat.py` - Uses metadata for context assembly
- `app/services/context/multi_level_context.py` - Context retrieval and formatting

## Future Improvements

1. **User alias system** - Allow mapping multiple display names to same user_id
2. **Fuzzy name matching** - Detect when two similar names might be confused
3. **Metadata validation** - Ensure user_id always present before name
4. **Test coverage** - Add specific test cases for name confusion scenarios
5. **Monitoring** - Track identity confusion incidents via telemetry

## Impact Assessment

- **User Experience**: ✅ Improved - Correct user identification
- **Performance**: ✅ Minimal impact (~5 token increase per turn)
- **Reliability**: ✅ Significantly improved
- **Token Budget**: ⚠️ Slight increase (within acceptable limits)

## Documentation Updates

This fix is documented in:

- `docs/fixes/user-identification-confusion-fix.md` (this file)
- `docs/CHANGELOG.md` - Entry added for this fix
- `docs/README.md` - Reference to this fix

---

**Status**: ✅ Implemented  
**Verified by**: Manual testing required with user_id 831570515  
**Next Steps**: Monitor logs for 24h to confirm fix effectiveness
