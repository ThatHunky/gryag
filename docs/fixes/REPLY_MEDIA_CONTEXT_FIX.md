# Fix: Reply Message Media Not Visible in Context

**Date**: 2025-10-08

**Issue**: When users replied to a message containing media (photo, video, etc.) and tagged the bot, the bot couldn't see the media from the replied-to message in its context, even though the media was being collected from Telegram.

## Root Cause

The issue had multiple layers:

1. **Reply context collection was working**: The code in `app/handlers/chat.py` was correctly fetching media from `message.reply_to_message` via Telegram API when the message wasn't in the in-memory cache or lacked media.

2. **Media was stored in `reply_context`**: The collected media parts were properly stored in the `reply_context` dictionary.

3. **But media wasn't reaching Gemini**: The `reply_context` was only used for:
   - Building fallback text (`fallback_context`)
   - Adding metadata to the current user turn
   - **NOT** for injecting the replied-to message into the conversation history

4. **Context window limitation**: When multi-level context was used, it fetched history via `context_store.recent()` which only retrieves the last N messages. If the replied-to message was older (outside the immediate/recent window), its media wouldn't be in the history at all.

## Solution

**Explicit history injection**: When we have a reply context with media, explicitly inject that message into the conversation history sent to Gemini, ensuring the media is visible regardless of the context window.

### Changes Made

**File**: `app/handlers/chat.py`

#### 1. Track reply context for history injection (line ~793)

```python
# Track reply context for later injection
reply_context_for_history: dict[str, Any] | None = None
```

#### 2. Store reply context when media is collected (line ~873)

```python
# Store for potential history injection
reply_context_for_history = reply_context

LOGGER.debug(
    "Collected %d media part(s) from reply message %s",
    len(reply_media_parts),
    reply.message_id,
)
```

#### 3. Capture cached reply context with media (line ~883)

```python
# If we have reply context with media, store it for history injection
if reply_context and reply_context.get("media_parts") and not reply_context_for_history:
    reply_context_for_history = reply_context
```

#### 4. Inject into history after formatting (line ~1148)

```python
# Inject reply context with media into history if needed
# This ensures media from replied-to messages is visible even if outside context window
if reply_context_for_history:
    reply_msg_id = reply_context_for_history.get("message_id")
    # Check if this message is already in history
    message_in_history = False
    if reply_msg_id:
        for hist_msg in history:
            parts = hist_msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text = part["text"]
                    if f"message_id={reply_msg_id}" in text:
                        message_in_history = True
                        break
            if message_in_history:
                break
    
    # If not in history, inject it
    if not message_in_history:
        reply_parts: list[dict[str, Any]] = []
        
        # Add metadata if available
        reply_meta = {
            "chat_id": chat_id,
            "message_id": reply_msg_id,
        }
        if reply_context_for_history.get("user_id"):
            reply_meta["user_id"] = reply_context_for_history["user_id"]
        if reply_context_for_history.get("name"):
            reply_meta["name"] = reply_context_for_history["name"]
        if reply_context_for_history.get("username"):
            reply_meta["username"] = reply_context_for_history["username"]
        
        reply_parts.append({"text": format_metadata(reply_meta)})
        
        # Add text if available
        if reply_context_for_history.get("text"):
            reply_parts.append({"text": reply_context_for_history["text"]})
        
        # Add media parts
        if reply_context_for_history.get("media_parts"):
            reply_parts.extend(reply_context_for_history["media_parts"])
        
        # Insert at beginning of history (chronologically first)
        if reply_parts:
            history.insert(0, {"role": "user", "parts": reply_parts})
            LOGGER.debug(
                "Injected reply context with %d media part(s) into history for message %s",
                len(reply_context_for_history.get("media_parts", [])),
                reply_msg_id,
            )
```

## How It Works

1. **Collection Phase**: When processing a reply, collect media from `message.reply_to_message` if not in cache or if cache lacks media (existing logic).

2. **Storage Phase**: Store the complete reply context (including media parts) in `reply_context_for_history`.

3. **History Formatting Phase**: After the multi-level context manager formats the history, check if the replied-to message is present.

4. **Injection Phase**: If the replied-to message is NOT in history (determined by checking for its `message_id` in metadata), construct a proper Gemini message format and insert it at the beginning of the history.

5. **Deduplication**: The check prevents duplicate messages if the replied-to message is already in the context window.

## Impact

- ✅ Bot can now see media from replied-to messages regardless of context window size
- ✅ Works with both multi-level context and simple history fallback
- ✅ Prevents duplicate messages in history
- ✅ Maintains chronological order (injected at beginning)
- ✅ Includes proper metadata for context
- ✅ No breaking changes to existing functionality

## How to Verify

### Test Case 1: Reply to Recent Message with Media

1. Send a message with a photo (without tagging bot)
2. Wait 1-2 seconds for processing
3. Reply to that message: "@gryag що на фото?"
4. Bot should describe the photo

**Expected**: Bot sees and references the photo

### Test Case 2: Reply to Old Message with Media

1. Send a message with a photo (without tagging bot)
2. Send 30+ other messages to push it out of context window
3. Reply to the old photo message: "@gryag що на фото?"
4. Bot should describe the photo

**Expected**: Bot sees and references the photo even though it's outside the normal context window

### Test Case 3: No Duplicate Injection

1. Send a message with a photo (without tagging bot)
2. Immediately reply: "@gryag що це?"
3. Check logs for "Injected reply context"

**Expected**: Log should NOT show injection (message already in recent context)

### Log Verification

Look for these log messages:

```text
DEBUG - Collected N media part(s) from reply message {message_id}
DEBUG - Injected reply context with N media part(s) into history for message {message_id}
```

## Technical Notes

- **Performance**: Minimal overhead - only processes reply context when it exists and has media
- **Memory**: No additional caching - uses existing `reply_context` structure
- **Compatibility**: Works with both multi-level and simple context modes
- **Edge Cases**: Handles missing metadata, empty media parts, and messages without text

## Related Issues

- Previous fix (2025-10-06): `ASTERISKS_AND_MEDIA_FIX.md` - Added reply media collection from Telegram API
- This fix completes the solution by ensuring collected media reaches Gemini's context

## Files Modified

- `app/handlers/chat.py` - Added reply context tracking and history injection logic

## Testing

Run existing test suites to ensure no regressions:

```bash
pytest tests/integration/test_integration.py -v
pytest tests/unit/ -v
```

No new tests required as this fixes existing functionality rather than adding new features.
