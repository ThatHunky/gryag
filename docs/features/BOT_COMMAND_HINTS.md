# Bot Command Hints

**Date:** October 6, 2025  
**Status:** ✅ Implemented

## Overview

Added context hints (command descriptions) for all bot commands to improve user experience. These hints appear in Telegram's command menu when users type `/` in the chat.

## Implementation

### Files Modified

1. **`app/handlers/admin.py`**
   - Added `ADMIN_COMMANDS` list with command descriptions
   - Imported `Bot` and `BotCommand` types
   - Commands: `/gryagban`, `/gryagunban`, `/gryagreset`

2. **`app/handlers/profile_admin.py`**
   - Added `PROFILE_COMMANDS` list with command descriptions
   - Added `setup_profile_commands()` helper function
   - Commands: `/gryagprofile`, `/gryagfacts`, `/gryagremovefact`, `/gryagforget`, `/gryagexport`

3. **`app/main.py`**
   - Added `setup_bot_commands()` function
   - Imported command lists from handlers
   - Calls `setup_bot_commands()` before starting polling
   - Registers all 9 commands globally

## Registered Commands

### General Commands
- `/gryag` - Запитати бота (альтернатива @mention або reply)

### Admin Commands (🔒 admins only)
- `/gryagban` - Забанити користувача (у відповідь або ID)
- `/gryagunban` - Розбанити користувача (у відповідь або ID)
- `/gryagreset` - Скинути ліміти повідомлень у чаті

### Profile Management Commands
- `/gryagprofile` - Показати профіль користувача (свій або у відповідь)
- `/gryagfacts` - Список фактів про користувача (свої або у відповідь)
- `/gryagremovefact` - 🔒 Видалити конкретний факт за ID (тільки адміни)
- `/gryagforget` - 🔒 Видалити всі факти про користувача (тільки адміни, потребує підтвердження)
- `/gryagexport` - 🔒 Експортувати профіль у JSON (тільки адміни)

## Technical Details

### Command Registration
Commands are registered using Telegram Bot API's `set_my_commands` method:
```python
await bot.set_my_commands(commands=all_commands)
```

### Command Structure
Each command is defined as a `BotCommand` object:
```python
BotCommand(
    command="command_name",
    description="User-visible description (Ukrainian)"
)
```

### Visibility
- **Global scope**: All users see all commands in the menu
- **Admin-only indicators**: 🔒 emoji marks commands that require admin privileges
- **Runtime checks**: Admin permissions are validated when commands are executed

## User Experience Benefits

1. **Discoverability**: Users can see all available commands by typing `/`
2. **Context**: Command descriptions explain what each command does
3. **Usage hints**: Descriptions include basic usage patterns (e.g., "у відповідь або ID")
4. **Admin clarity**: 🔒 emoji clearly marks admin-only commands
5. **Language**: All descriptions in Ukrainian for consistency with bot persona

## Verification

### Log Output
```
2025-10-06 10:52:33,192 - INFO - root - Bot commands registered: 9 commands
```

### Testing
1. Open Telegram chat with @gryag_bot
2. Type `/` to see command menu
3. Verify all 9 commands appear with Ukrainian descriptions
4. Verify 🔒 emoji appears on admin-only commands

## Future Improvements

- [ ] Add per-chat command scopes (hide admin commands for non-admins)
- [ ] Add command aliases (e.g., `/profile` → `/gryagprofile`)
- [ ] Add inline query hints
- [ ] Add command auto-completion for parameters
- [ ] Translate commands to English for international users (optional)

## Related Issues

- Fixed telemetry bug in `/gryagforget` command (TypeError with dict labels)
- Commands now work correctly and display helpful hints

## Rollback

To remove command hints:
1. Remove `setup_bot_commands()` call from `app/main.py`
2. Run: `docker compose restart bot`
3. Commands will still work but won't appear in the menu
