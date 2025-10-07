# Time Awareness Feature

**Added**: October 7, 2025  
**Status**: ✅ Implemented and production-ready

## Overview

The bot now receives the current timestamp with every message it processes. This enables time-aware responses and context-appropriate greetings.

## Implementation

### What Changed

The system prompt now includes a dynamic timestamp section that updates for each message:

```python
current_time = datetime.now().strftime("%A, %B %d, %Y at %H:%M:%S")
timestamp_context = f"\n\n# Current Time\n\nThe current time is: {current_time}"
```

This is injected into the system prompt before every Gemini API call, ensuring the bot always knows the current time.

### Format

The timestamp follows this format:
```
The current time is: Tuesday, October 07, 2025 at 10:54:14
```

Components:
- **Day of week**: Full name (e.g., "Tuesday")
- **Month**: Full name (e.g., "October")
- **Date**: Two-digit day (e.g., "07")
- **Year**: Four-digit year (e.g., "2025")
- **Time**: 24-hour format HH:MM:SS (e.g., "10:54:14")

### Integration Points

The timestamp is added in three code paths to ensure coverage:

1. **Base case** (line 1024): Always added to `SYSTEM_PERSONA`
2. **Multi-level context** (line 1032): Added between persona and multi-level system context
3. **Profile fallback** (line 1046): Added between persona and profile context

## Use Cases

### Time-Aware Greetings

The bot can now respond contextually based on the time of day:

**User**: "Hey gryag!"  
**Bot** (at 08:00): "Доброго ранку!"  
**Bot** (at 20:00): "Добрий вечір!"

### Current Time Queries

Users can ask about the current time:

**User**: "What time is it?"  
**Bot**: "Зараз 14:30."

### Date Awareness

The bot knows the current date:

**User**: "What day is today?"  
**Bot**: "Сьогодні вівторок, 7 жовтня 2025."

### Time-Sensitive Context

Responses can be tailored to the time of day:

**User**: "Should I have coffee?"  
**Bot** (morning): "Ага, ранок без кави - це злочин."  
**Bot** (evening): "Надто пізно вже, не зможеш заснути."

## Technical Details

### Performance

- **Overhead**: <1ms per message (negligible)
- **Format generation**: Uses stdlib `datetime.strftime()`
- **No caching**: Fresh timestamp for every message (intentional)

### Timezone

- Uses **system local time** (not UTC)
- Matches the server's configured timezone
- For deployment, ensure server timezone is set correctly

### Token Impact

- Adds ~25 tokens to system prompt
- Format: `"\n\n# Current Time\n\nThe current time is: {timestamp}"`
- Negligible impact on context budget (8000 token default)

## Files Modified

- `app/handlers/chat.py`:
  - Added `from datetime import datetime` (line 8)
  - Added timestamp generation (lines 1020-1021)
  - Injected into system prompt (lines 1024, 1032, 1046)

## Testing

### Verification Script

Run the test script to see the timestamp format:

```bash
python3 test_timestamp_feature.py
```

Expected output:
```
✓ Timestamp context generated successfully:

# Current Time

The current time is: Tuesday, October 07, 2025 at 10:54:14

✓ Format verification:
  - Day of week: included
  - Date: included
  - Time: included (24-hour format)
```

### Manual Testing

In Telegram, test with these queries:

1. **Direct time query**:
   - User: "What time is it?"
   - Expected: Bot responds with current time

2. **Date query**:
   - User: "What day is today?"
   - Expected: Bot responds with current day/date

3. **Contextual greeting**:
   - User: "Hey!" (test at different times of day)
   - Expected: Time-appropriate greeting (morning/afternoon/evening)

## Configuration

**No configuration changes required** - this feature is always enabled.

The timestamp uses the system's local time automatically. To change the timezone:

1. **Docker**: Set `TZ` environment variable in `docker-compose.yml`
   ```yaml
   environment:
     - TZ=Europe/Kiev
   ```

2. **Bare metal**: Configure system timezone
   ```bash
   sudo timedatectl set-timezone Europe/Kiev
   ```

## Backward Compatibility

✅ **Fully backward compatible**
- No breaking changes
- No database changes
- No API changes
- Works with all existing context modes

## Future Enhancements

Potential improvements (not currently planned):

- [ ] User-specific timezones (per-chat or per-user)
- [ ] Relative time display ("2 hours ago" vs absolute time)
- [ ] Calendar integration (holidays, events)
- [ ] Scheduled responses based on time
- [ ] Time-zone aware conversations (multi-timezone chats)

## Related Documentation

- Main persona: `app/persona.py`
- Chat handler: `app/handlers/chat.py`
- Changelog: `docs/CHANGELOG.md` (2025-10-07 entry)
- Copilot instructions: `.github/copilot-instructions.md`
