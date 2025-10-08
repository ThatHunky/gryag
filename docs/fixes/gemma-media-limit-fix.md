# Gemma Media Limit Fix

**Date:** October 7, 2025  
**Issue:** `google.api_core.exceptions.InvalidArgument: 400 Please use fewer than 32 images in your request to models/gemma-3-27b-it`

## Problem

The Gemma 3 models have a hard limit of 32 images per API request. When using multi-level context, the bot was including media from historical messages in the context assembly, which could easily exceed this limit in media-heavy conversations.

## Root Cause

The `MultiLevelContextManager.format_for_gemini()` method was combining immediate and recent context messages without checking the total number of media items (images, videos, audio files) across all messages in the history.

## Solution

Added a `_limit_media_in_history()` method to the `MultiLevelContextManager` class that:

1. **Counts total media items** across all messages in the assembled history
2. **Sets a conservative limit** of 28 media items (leaving room for the current message's media)
3. **Removes media from oldest messages first**, preserving recent media
4. **Replaces removed media with text placeholders** like `[media: image/jpeg]` to maintain context
5. **Logs the action** for debugging and monitoring

### Changes Made

**File:** `app/services/context/multi_level_context.py`

1. Added `_limit_media_in_history()` method (lines ~620-682)
2. Modified `format_for_gemini()` to call the limiter before returning history
3. Set `MAX_MEDIA_ITEMS = 28` (conservative, below the 32 limit)

## Implementation Details

```python
def _limit_media_in_history(
    self, history: list[dict[str, Any]], max_media: int
) -> list[dict[str, Any]]:
    """
    Limit total number of media items in history to prevent API errors.
    
    Removes media from older messages first, keeping recent media.
    """
    # Count media items (inline_data and file_data)
    # Remove oldest media first if over limit
    # Replace with text placeholders like "[media: image/jpeg]"
```

The method uses `copy.deepcopy()` to avoid modifying the original history and preserves message structure.

## Configuration

The limit is currently hardcoded to 28. Future enhancement: Add to `.env` as:

```env
GEMINI_MAX_MEDIA_ITEMS=28
```

## How to Verify

1. **Before fix:** Bot would crash with `InvalidArgument: 400 Please use fewer than 32 images` in media-heavy chats
2. **After fix:** Bot gracefully handles media-heavy conversations by limiting historical media
3. **Check logs:** Look for `"Limited media in history: removed X of Y items (max: 28)"` entries

### Test Scenario

1. Send multiple messages with images (e.g., 40+ images across 20 messages)
2. Mention the bot with a new message containing images
3. Bot should respond successfully, with logs showing media limitation

### Verification Command

```bash
docker compose logs bot | grep "Limited media in history"
```

## Related Issues

- **Gemini API error**: 400 Invalid Argument (too many images)
- **Model limitations**: Gemma 3 models max 32 images, other models may have different limits
- **Phase 3 multi-level context**: This fix is specific to the multi-level context system

## Future Improvements

1. Make `MAX_MEDIA_ITEMS` configurable per model
2. Add telemetry counter for media limiting events
3. Consider smart media selection (keep higher quality/larger images)
4. Document model-specific limits in a central config

## Compatibility

- **Gemma 3 models**: 1B, 4B, 12B, 27B (all have 32 image limit)
- **Other Gemini models**: May have different limits (verify before use)
- **Fallback mode**: Simple history retrieval not affected (uses recent messages only)

## Notes

- The fix is **backward compatible** - no breaking changes
- Media from the **current message** is never removed (only historical media)
- Text content is **always preserved** (only media blobs removed)
- The placeholder format helps the model understand media was present
