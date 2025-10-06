# Fix: Asterisks in Responses and Media in Reply Context

**Date**: 2025-10-06

**Issues**:

1. Bot responses contained too many asterisks (`*`) making messages look broken
2. Bot couldn't see media when someone replied to a message with media

## Changes Made

### 1. Asterisks Fix

**Problem**: The bot was using asterisks for emphasis despite instructions not to. When escaped by `_escape_markdown()`, they showed as literal `\*` in Telegram, making messages ugly and broken.

**Solution**:

- **Strengthened persona instructions** (`app/persona.py`): Made the "no asterisks" rule more explicit and urgent
- **Improved markdown escaping** (`app/handlers/chat.py`): Changed `_escape_markdown()` to **remove** asterisks and underscores entirely instead of escaping them, since the bot should never use them for formatting

**Code changes**:

```python
# app/persona.py - Made the rule more explicit
**CRITICAL FORMATTING RULE: Write ONLY plain text. NEVER EVER use asterisks (*), 
underscores (_), or any markdown/formatting symbols. Don't emphasize words with 
special characters. Write naturally like you're texting a friend - no formatting 
symbols at all. This is non-negotiable. If you use asterisks or underscores, 
your messages will look broken and ugly.**

# app/handlers/chat.py - Remove instead of escape
def _escape_markdown(text: str) -> str:
    # Remove asterisks and underscores completely
    text = re.sub(r'\*+', '', text)  # Remove all asterisks
    text = re.sub(r'_+', '', text)   # Remove all underscores
    # ... rest of function
```

### 2. Media in Reply Context Fix

**Problem**: When a user replied to a message with media (photo, video, etc.), the bot couldn't see that media because it only looked in the cached `_RECENT_CONTEXT`. If the message wasn't in cache or cache didn't have media, the context was incomplete.

**Solution**: Added fallback logic to collect media directly from `message.reply_to_message` using Telegram API when:

- Reply context is not in cache, OR
- Cached context exists but has no media

**Code changes** (`app/handlers/chat.py`):

```python
reply_context = None
if message.reply_to_message:
    reply = message.reply_to_message
    # ... existing cache lookup ...
    
    # NEW: If we have a reply but no cached context, or cached context has no media,
    # try to collect media directly from the reply message
    if not reply_context or not reply_context.get("media_parts"):
        try:
            reply_media_raw = await collect_media_parts(bot, reply)
            if reply_media_raw:
                reply_media_parts = gemini_client.build_media_parts(reply_media_raw, logger=LOGGER)
                if reply_media_parts:
                    # Create or update reply_context with media
                    if not reply_context:
                        # Build complete context
                        reply_text = _extract_text(reply)
                        reply_context = {
                            "ts": ...,
                            "message_id": reply.message_id,
                            # ... other fields ...
                            "media_parts": reply_media_parts,
                        }
                    else:
                        # Update existing context with media
                        reply_context["media_parts"] = reply_media_parts
        except Exception:
            LOGGER.exception("Failed to collect media from reply message %s", reply.message_id)
```

## How to Verify

### Test Asterisks Fix

1. Send messages that would trigger emphasis/formatting from the bot
2. Check that responses contain NO asterisks or underscores
3. Messages should be plain text, naturally written

### Test Media Fix

1. Send a message with a photo/video
2. Reply to that message with "@gryag что на фото?" (or similar)
3. Bot should now see the media and be able to describe it
4. Check logs for: `Collected N media part(s) from reply message`

## Files Modified

- `app/persona.py` - Strengthened formatting rules
- `app/handlers/chat.py`:
  - Modified `_escape_markdown()` to remove asterisks/underscores
  - Enhanced reply context collection to fetch media from Telegram API

## Notes

- The media collection uses `collect_media_parts()` which handles all Telegram media types (photos, videos, audio, stickers, documents, etc.)
- Media parts are converted to Gemini format via `build_media_parts()`
- Error handling ensures failures don't break the flow - they're logged but don't crash
- Debug logging helps track when media is successfully collected from replies

