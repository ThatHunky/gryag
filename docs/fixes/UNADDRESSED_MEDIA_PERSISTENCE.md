# Fix: Unaddressed Media Persistence

**Date**: 2025-10-06  
**Issue**: Bot couldn't see images in past messages when tagged in replies  
**Status**: ✅ Fixed

## Problem

When users sent messages with images without tagging the bot, and then someone later replied to those messages and tagged the bot, the bot couldn't see the images. For example:

1. User sends a forwarded message with an image (no bot mention)
2. Another user replies to that message and tags @gryag asking about the image
3. Bot responds without seeing the image context

## Root Cause

Unaddressed messages (messages without bot mentions) were only cached in memory via `_remember_context_message()` in the `_RECENT_CONTEXT` dictionary, but were **not persisted to the database**.

When the bot was later tagged in a reply:

- Multi-level context manager retrieved history from the database via `context_store.recent()`
- The unaddressed messages with media were not in the database
- Media parts were missing from the context sent to Gemini

## Solution

Modified `_remember_context_message()` to persist unaddressed messages to the database:

1. **Generate embeddings** for unaddressed message text (for semantic search)
2. **Build metadata** (chat_id, user_id, message_id, etc.)
3. **Persist to database** via `store.add_turn()` with media parts
4. **Graceful error handling** - persistence failures don't break message processing

### Code Changes

**File**: `app/handlers/chat.py`

```python
async def _remember_context_message(
    message: Message,
    bot: Bot,
    gemini_client: GeminiClient,
    store: ContextStore,          # NEW: Added parameter
    settings: Settings,             # NEW: Added parameter
) -> None:
    """Cache and persist unaddressed messages for potential context use."""
    # ... existing cache logic ...
    
    # NEW: Persist to database
    try:
        text_content = text or media_summary or ""
        
        # Generate embedding for semantic search
        user_embedding = None
        if text_content:
            user_embedding = await gemini_client.embed_text(text_content)
        
        # Build metadata
        user_meta = {
            "chat_id": message.chat.id,
            "thread_id": message.message_thread_id,
            "message_id": message.message_id,
            "user_id": message.from_user.id,
            "name": message.from_user.full_name,
            "username": _normalize_username(message.from_user.username),
        }
        
        # Store in database for later retrieval
        await store.add_turn(
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            user_id=message.from_user.id,
            role="user",
            text=text_content,
            media=media_parts,
            metadata=user_meta,
            embedding=user_embedding,
            retention_days=settings.retention_days,
        )
        
        LOGGER.debug(
            "Persisted unaddressed message %s with %d media part(s)",
            message.message_id,
            len(media_parts),
        )
    except Exception as e:
        # Don't fail the whole flow if persistence fails
        LOGGER.error(
            "Failed to persist unaddressed message %s: %s",
            message.message_id,
            e,
            exc_info=True,
        )
```

### Function Call Update

```python
# OLD
await _remember_context_message(message, bot, gemini_client)

# NEW
await _remember_context_message(message, bot, gemini_client, store, settings)
```

## Benefits

1. **Complete context**: Multi-level context now includes media from all past messages, not just addressed ones
2. **Semantic search**: Unaddressed messages are now searchable via embeddings
3. **Episode detection**: Unaddressed messages can contribute to episode boundary detection
4. **Fact extraction**: Images with captions can be used for user profiling

## Performance Considerations

- **Embedding generation**: Now generates embeddings for all messages (addressed + unaddressed)
  - Mitigated by `gemini_client._embed_semaphore` (8 concurrent max)
  - Rate limited by Google API quotas
  
- **Database writes**: More frequent writes for all messages
  - Existing pruning mechanism handles retention (30 days default)
  - Adaptive importance scoring prevents important context from being pruned

- **Storage**: Slight increase in database size
  - Media stored as JSON parts (references, not full data)
  - Same retention policy applies to all messages

## How to Verify

1. Send a message with an image without mentioning the bot
2. Wait a few seconds for processing
3. Reply to that message and tag the bot asking about the image
4. Bot should now reference the image in its response

Example test scenario:

```text
User A: [sends image of a painting] "Я народився у тисяча дев'ятсот..."
User B (replies): @gryag що на фото?
Bot: [responds with context about the painting in the image]
```

Check logs for:

```text
DEBUG - Persisted unaddressed message {message_id} with {N} media part(s)
```

## Related Code

- `app/handlers/chat.py::_remember_context_message()` - Main fix
- `app/services/context_store.py::add_turn()` - Persistence layer
- `app/services/context/multi_level_context.py::_get_immediate_context()` - Retrieval
- `app/services/context/multi_level_context.py::_get_recent_context()` - Retrieval

## Migration Notes

- No database schema changes required
- Existing messages table supports media and embedding columns
- No breaking changes to API or configuration
- Works with both multi-level context and simple history modes

## Future Improvements

1. **Batch embedding generation**: Group unaddressed messages for more efficient embedding
2. **Selective persistence**: Only persist media messages or messages above certain length
3. **Cache warming**: Pre-load recent unaddressed messages on startup
4. **Media deduplication**: Detect and deduplicate identical media across messages
