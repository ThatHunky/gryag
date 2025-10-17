# Media Context Bug Fix

**Date:** October 17, 2025  
**Issue:** Bot doesn't see media in conversation  
**Status:** ✅ Fixed

## Problem

The bot was not seeing media (photos, videos, audio, documents) in conversation context, even though:
1. Media was being correctly collected via `collect_media_parts()`
2. Media was being stored in the database with the message
3. Media was being retrieved from the database by `context_store.recent()`

## Root Cause

In `app/services/context/multi_level_context.py`, the `_estimate_tokens()` method only counted parts with `"text"` field:

```python
def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        parts = msg.get("parts", [])
        for part in parts:
            if isinstance(part, dict) and "text" in part:  # ❌ Ignores media!
                text = part["text"]
                words = len(text.split())
                total += int(words * 1.3)
    return total
```

This caused two issues:
1. **Incorrect token budgeting**: Media parts consumed 0 tokens in estimates
2. **Context truncation**: Messages with media might be incorrectly prioritized/excluded

Media parts use `"inline_data"` (for images/audio/video) or `"file_data"` (for URLs like YouTube) instead of `"text"`, so they were completely invisible to the token estimator.

## Solution

Updated `_estimate_tokens()` to account for all part types:

```python
def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
    """
    Estimate token count for messages.
    
    Rough heuristic:
    - Text: words * 1.3 (accounts for tokenization)
    - Media (inline_data): ~258 tokens per item (Gemini's image token cost)
    - Media (file_data/URI): ~100 tokens per item (YouTube URLs, etc.)
    """
    total = 0
    for msg in messages:
        parts = msg.get("parts", [])
        for part in parts:
            if isinstance(part, dict):
                if "text" in part:
                    text = part["text"]
                    words = len(text.split())
                    total += int(words * 1.3)
                elif "inline_data" in part:
                    # Images/audio/video consume significant tokens
                    # Gemini uses ~258 tokens per image
                    total += 258
                elif "file_data" in part:
                    # File URIs (e.g., YouTube URLs) are cheaper
                    total += 100
    return total
```

Token costs based on [Gemini API documentation](https://ai.google.dev/gemini-api/docs/vision#technical-details-image):
- Images: ~258 tokens per image
- Videos/Audio: Similar cost per item
- File URIs: ~100 tokens (text representation)

## Additional Changes

Added debug logging to track media flow through context assembly:

- `_get_immediate_context()`: Logs media count before/after truncation
- `_get_recent_context()`: Logs media count before/after truncation

Example log output:
```
DEBUG Retrieved 10 messages with 3 media items
DEBUG After truncation: 8 messages with 2 media items (lost 1)
```

## Testing

Created `tests/unit/test_multi_level_context_media.py` to verify:
1. ✅ Text-only messages work as before (backward compatibility)
2. ✅ Media with `inline_data` correctly adds 258 tokens
3. ✅ Media with `file_data` correctly adds 100 tokens
4. ✅ Multiple media items accumulate correctly

## Verification

To verify the fix is working in production:

1. Send a message with an image to the bot
2. Check logs for media tracking:
   ```bash
   grep "media items" logs/gryag.log
   ```
3. Verify bot responds acknowledging the image content

## Files Changed

- `app/services/context/multi_level_context.py`:
  - Fixed `_estimate_tokens()` to count media parts
  - Added debug logging to `_get_immediate_context()`
  - Added debug logging to `_get_recent_context()`
- `tests/unit/test_multi_level_context_media.py`:
  - New test file verifying media token estimation

## Related Issues

This fix ensures media is properly accounted for in:
- Token budget allocation (Phase 3 multi-level context)
- Context truncation decisions
- Hybrid search relevance scoring (media-rich messages won't be under-weighted)

## References

- **Architecture doc**: `.github/copilot-instructions.md` (Message Flow section)
- **Phase 3 report**: `docs/phases/PHASE_3_COMPLETION_REPORT.md`
- **Token optimization**: `app/services/context/token_optimizer.py`
