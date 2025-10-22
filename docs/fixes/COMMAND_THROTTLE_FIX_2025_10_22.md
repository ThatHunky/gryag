# Command Throttle Fix - Multi-Bot Groups Support

**Date**: October 22, 2025  
**Issue**: Bot was throttling ALL commands, including those meant for other bots  
**Status**: ✅ Fixed

## Problem

In Telegram groups with multiple bots, gryag was incorrectly sending throttle messages to users who used commands for OTHER bots. For example:

- User types `/dban` (command for a different bot)
- gryag throttles it and replies: "⏱ Зачекай трохи! Команди можна використовувати раз на 5 хвилин..."
- User is confused - they weren't talking to gryag!

### Root Cause

The `CommandThrottleMiddleware` was checking if a message started with `/` but:
1. ❌ Didn't verify if the command was registered to gryag
2. ❌ Didn't check if the command was addressed to a different bot via `@bot_username`

## Solution

Implemented a **whitelist-based approach** with two layers of filtering:

### Layer 1: Command Whitelist

Only throttle commands that are registered to gryag:

```python
KNOWN_COMMANDS = {
    "gryag",  # USER_COMMANDS
    "gryagban", "gryagunban", "gryagreset", "gryagchatinfo",  # ADMIN_COMMANDS
    "gryagprofile", "gryagfacts", "gryagremovefact", "gryagforget",
    "gryagexport", "gryagusers", "gryagself", "gryaginsights",  # PROFILE_COMMANDS
    "gryagchatfacts", "gryagchatreset",  # CHAT_COMMANDS
    "gryagprompt", "gryagsetprompt", "gryagresetprompt",
    "gryagprompthistory", "gryagactivateprompt",  # PROMPT_COMMANDS
}
```

### Layer 2: Bot Mention Detection

If a command is in the whitelist but has `@other_bot` suffix, skip throttling:

```python
# Extract command: /gryag@other_bot -> "gryag"
command_base = command_text.split("@")[0].lstrip("/").lower()

# Check if in whitelist
if command_base not in KNOWN_COMMANDS:
    return  # Pass through - not our command

# Check if for different bot
if "@" in command_text:
    mentioned_bot = command_text.split("@")[1]
    if mentioned_bot.lower() != our_bot_username.lower():
        return  # Pass through - for different bot
```

## Behavior Matrix

| Command | Result | Reason |
|---------|--------|--------|
| `/gryag` | ✅ Throttle | Gryag's command |
| `/gryagban` | ✅ Throttle | Gryag's command |
| `/gryag@gryag_bot` | ✅ Throttle | Explicitly for this bot |
| `/gryag@GRYAG_BOT` | ✅ Throttle | Case-insensitive match |
| `/gryag@other_bot` | ❌ Pass through | For different bot |
| `/dban` | ❌ Pass through | Unknown command (not gryag's) |
| `/start` | ❌ Pass through | Generic Telegram command |
| `/help` | ❌ Pass through | Generic Telegram command |
| `/ban` | ❌ Pass through | Unknown command |

## Implementation Details

### Files Modified

1. **`app/middlewares/command_throttle.py`**
   - Added `KNOWN_COMMANDS` class variable with all registered commands
   - Added command parsing logic to extract base command name
   - Added whitelist check before throttling
   - Added bot mention detection with case-insensitive matching

2. **`tests/unit/test_command_throttle_middleware.py`**
   - Added tests for unknown commands (should pass through)
   - Added tests for generic commands like `/start` (should pass through)
   - Added tests for gryag commands (should throttle)
   - Added tests for `@bot_username` mention handling
   - Added comprehensive test for all registered commands

3. **`scripts/verification/verify_command_throttle_fix.py`**
   - Updated verification script to test whitelist approach
   - Added tests for unknown commands like `/dban`
   - Verifies 20 different command scenarios

### Key Changes

```python
# Before (BAD - throttles everything)
if not event.text.startswith("/"):
    return await handler(event, data)

# After (GOOD - only throttles known commands)
command_base = event.text.split("@")[0].lstrip("/").lower()
if command_base not in self.KNOWN_COMMANDS:
    logger.debug(f"Unknown command '{command_base}', not throttling")
    return await handler(event, data)
```

## Testing

### Automated Tests

```bash
# Run verification script
python3 scripts/verification/verify_command_throttle_fix.py
# Result: 20/20 tests pass ✓
```

### Manual Testing

Test in a group with multiple bots:

1. **Test unknown command**: `/dban` → No throttle message from gryag ✓
2. **Test generic command**: `/start` → No throttle message from gryag ✓
3. **Test gryag command**: `/gryag hello` → May be throttled ✓
4. **Test gryag command for other bot**: `/gryag@other_bot` → No throttle ✓
5. **Test spam gryag commands**: Multiple `/gryagban` in quick succession → Throttled correctly ✓

## Edge Cases Handled

1. **Empty command**: `/` → Treated as unknown, passes through
2. **Command with params**: `/gryagprofile user123` → Correctly extracted and throttled
3. **Case sensitivity**: `/GRYAG@gryag_bot` → Case-insensitive match works
4. **Multiple @ symbols**: Handles edge cases in parsing
5. **Missing bot_username in data**: Gracefully handles missing context

## Performance Impact

- **Minimal**: O(1) set lookup for command whitelist
- **No database queries**: All logic is in-memory
- **No latency increase**: Same async flow as before

## Backward Compatibility

✅ Fully backward compatible:
- Existing gryag commands continue to work
- Admin bypass still functions
- Rate limiting logic unchanged
- Only affects unknown/external commands (now passes them through)

## Future Improvements

Potential enhancements (not critical):

1. **Dynamic command list**: Auto-generate `KNOWN_COMMANDS` from router registration
2. **Per-command cooldowns**: Different cooldowns for different commands
3. **Group-specific whitelists**: Allow/block specific commands per group
4. **Rate limit sharing**: Consider if generic commands should share cooldown with gryag commands

## Related Issues

- Original bug report: "Bot sends throttle message to commands for other bots"
- Related: Command routing in multi-bot groups
- See also: `app/handlers/` for command handler registration

## Verification Checklist

- [x] Gryag commands are still throttled correctly
- [x] Unknown commands pass through without throttling
- [x] Commands for other bots are ignored
- [x] Admin bypass still works
- [x] Case-insensitive bot mention matching
- [x] Commands with parameters handled correctly
- [x] All 20 test scenarios pass
- [x] No performance degradation
- [x] Backward compatible with existing behavior

---

**Changelog entry**: See `docs/CHANGELOG.md` - 2025-10-22
