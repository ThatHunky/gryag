# Reply Chain Context Inclusion - Implementation Summary

**Date**: October 19, 2025  
**Status**: ✅ COMPLETE  
**Plan**: [docs/plans/REPLY_CHAIN_CONTEXT_FIX_PLAN.md](../plans/REPLY_CHAIN_CONTEXT_FIX_PLAN.md)

## Problem

When users reply to a message in Telegram (a chain/quote), gryag often ignored the replied message's content. The model only saw minimal metadata (reply IDs) and, in compact mode, only the arrow (A → B) without the original text, causing answers to miss the referenced content.

## Solution Implemented

### 1. Configuration (app/config.py)
- Added `INCLUDE_REPLY_EXCERPT=true` (default) - Feature flag
- Added `REPLY_EXCERPT_MAX_CHARS=200` (default) - Excerpt length limit

### 2. Conversation Formatter (app/services/conversation_formatter.py)
**Enhanced `format_message_compact()`**:
- Added `reply_excerpt` parameter
- Prepends `[↩︎ Username: excerpt]` when reply is present
- Truncates long excerpts to ~120 chars for compact readability

**Enhanced `format_history_compact()`**:
- Reads `reply_excerpt` from message metadata
- Passes to `format_message_compact()` for rendering

### 3. Chat Handler - JSON Path (app/handlers/chat.py)
**Always include reply context**:
- Sets `reply_context_for_history` unconditionally when reply exists (not just for media)
- Creates minimal reply context even if not in cache
- Adds inline `[↩︎ Відповідь на: excerpt]` part to `user_parts` after metadata
- Injects replied message into history if not already present

**History Injection**:
- Checks if replied message already in history (avoids duplication)
- Injects synthetic user message with metadata + text + media
- Limits media to prevent token bloat
- Tracks via telemetry

### 4. Chat Handler - Compact Path (app/handlers/chat.py)
**Extract reply info**:
- Gets `reply_to_user_id`, `reply_to_username` from `message.reply_to_message`
- Extracts `reply_excerpt` from reply context or directly from message
- Uses shorter excerpts (160 chars) for compact format efficiency

**Pass to formatter**:
- Calls `format_message_compact()` with all reply parameters
- Result includes inline `[↩︎ Username: excerpt]` automatically

### 5. Telemetry
**New counters**:
- `context.reply_included_text` - Incremented when text excerpt added to user_parts
- `context.reply_included_media` - Incremented when media injected into history

### 6. Tests (tests/unit/test_reply_context.py)
**14 comprehensive tests**:
- Compact formatter with/without reply
- Reply excerpt truncation
- History formatting with reply metadata
- Configuration defaults
- Excerpt sanitization (newlines, special chars)
- History injection scenarios

## Benefits

✅ **Model always sees reply context** - No more "what are you talking about?" responses  
✅ **Works in both formats** - JSON and Compact conversation formats  
✅ **Compact and safe** - Excerpts capped to prevent token bloat  
✅ **User-transparent** - No visible changes in bot output  
✅ **Backward compatible** - Feature flag allows disabling if needed  

## Token Impact

- **Inline excerpt**: ~15-25 tokens per reply (depends on length)
- **History injection**: ~50-100 tokens per missing replied message (one-time)
- **Total overhead**: <50 tokens per addressed turn on average
- **Within budget**: Well under 8000 token context budget

## Files Changed

| File | Lines Changed | Description |
|------|---------------|-------------|
| `app/config.py` | +7 | Added 2 new settings |
| `app/services/conversation_formatter.py` | +13 | Enhanced formatter functions |
| `app/handlers/chat.py` | +58 | Reply context handling logic |
| `tests/unit/test_reply_context.py` | +341 | New test file |

**Total**: 4 files modified, 1 file added, 419 lines added

## Verification

### Unit Tests
```bash
source .venv/bin/activate
python -m pytest tests/unit/test_reply_context.py -v
# Result: 14 passed in 3.24s ✅
```

### Manual Testing
1. **Reply to old message** (outside recent context):
   - Send message in chat
   - Wait 10 minutes
   - Reply to that message
   - Check DEBUG logs for:
     - `"Added inline reply excerpt to user parts"`
     - `"Injected reply context into history"`

2. **Check Gemini payload**:
   - Set `LOG_LEVEL=DEBUG`
   - Look for `[↩︎ ...]` snippet in user_parts preview

3. **Verify telemetry**:
   - Monitor for `context.reply_included_text` increments
   - Check if `context.reply_included_media` fires when replying to images

## Known Limitations

1. **No automatic excerpt for non-text replies**: If replied message has only stickers/GIFs, excerpt will be empty (media description not included in inline snippet, only in history injection)
2. **Character limit is strict**: Long multi-paragraph replies truncated to configured limit
3. **Metadata not cleaned from excerpts**: If user's original message contained `[meta]` blocks, they'll be in excerpt (unlikely in practice)

## Future Enhancements (Optional)

- [ ] Include media summary in inline excerpt for non-text replies
- [ ] Smart excerpt selection (first + last sentence for long texts)
- [ ] Language-aware truncation (don't cut in middle of Ukrainian word)
- [ ] Compress multiple consecutive replies into single context block

## Rollback Plan

If issues arise:
1. Set `INCLUDE_REPLY_EXCERPT=false` in `.env`
2. Restart bot
3. Feature will be disabled, falling back to old behavior
4. No database changes needed (feature is runtime-only)

## Related Documentation

- **Plan**: [docs/plans/REPLY_CHAIN_CONTEXT_FIX_PLAN.md](../plans/REPLY_CHAIN_CONTEXT_FIX_PLAN.md)
- **Changelog**: [docs/CHANGELOG.md](../CHANGELOG.md) (2025-10-19 entry)
- **README**: [docs/README.md](./README.md) (Recent Changes section)

---

**Implementation completed**: October 19, 2025  
**Tests passing**: ✅ 14/14  
**Ready for production**: ✅ Yes
