# Improved Media Handling

**Date:** October 6, 2025  
**Status:** Complete ✅

## Overview

Enhanced the bot's media handling capabilities to properly support all Telegram media types, especially animated stickers, and improved error logging for media processing failures.

## Changes Made

### 1. Sticker Type Detection (`app/services/media.py`)

**Problem:** The bot treated all stickers as WebP images, but Telegram has three sticker types:
- Static stickers (WebP format)
- Animated stickers (TGS/Lottie format - **not supported by Gemini**)
- Video stickers (WebM format)

**Solution:**
- Added detection for `sticker.is_animated` and `sticker.is_video`
- For animated stickers (TGS): Use the JPEG thumbnail instead (Gemini doesn't support Lottie)
- For video stickers: Properly label as `video/webm`
- For static stickers: Continue using `image/webp`

**Code:**
```python
if sticker.is_animated:
    # Use thumbnail for TGS stickers
    if sticker.thumbnail:
        data = await _download(bot, sticker.thumbnail.file_id)
        mime = "image/jpeg"  # Thumbnails are JPEG
elif sticker.is_video:
    # Video stickers are WebM
    data = await _download(bot, sticker.file_id)
    mime = "video/webm"
else:
    # Static stickers are WebP
    data = await _download(bot, sticker.file_id)
    mime = "image/webp"
```

### 2. Enhanced Media Logging (`app/services/gemini.py`)

**Problem:** When media processing failed, there was no information about which media type or format caused the issue.

**Solution:**
- Added optional `logger` parameter to `build_media_parts()`
- Log each media item being added with details: MIME type, kind, size, and base64 length
- Added media error detection in exception handling
- Specific error messages for media-related failures

**Code:**
```python
if logger:
    logger.debug(
        "Added inline media: mime=%s, kind=%s, size=%d bytes, base64_len=%d",
        mime, kind, size, len(data)
    )

# In error handling:
is_media_error = any(
    keyword in err_text.lower() 
    for keyword in ["image", "video", "audio", "media", "inline_data"]
)
if is_media_error:
    self._logger.error(
        "Gemini media processing failed: %s. "
        "This may be due to unsupported format or corrupted media.",
        err_text
    )
```

### 3. Updated Call Sites (`app/handlers/chat.py`)

Updated both locations where `build_media_parts()` is called to pass the logger:
```python
media_parts = gemini_client.build_media_parts(media_raw, logger=LOGGER)
```

## Media Type Support Matrix

| Media Type | Format | Supported by Gemini | Bot Handling |
|------------|--------|-------------------|--------------|
| Photos | JPEG | ✅ Yes | Direct download |
| Static Stickers | WebP | ✅ Yes | Direct download |
| Animated Stickers | TGS (Lottie) | ❌ No | Use JPEG thumbnail |
| Video Stickers | WebM | ✅ Yes | Direct download |
| Voice Messages | OGG/Opus | ✅ Yes | Direct download |
| Audio Files | MP3/OGG/etc | ✅ Yes | Direct download |
| Video Files | MP4/etc | ✅ Yes | Direct download |
| Video Notes | MP4 | ✅ Yes | Direct download |
| Animations/GIFs | MP4 | ✅ Yes | Direct download as video |
| Documents (media) | Various | ✅ Varies | Only image/audio/video |
| YouTube URLs | - | ✅ Yes | File URI reference |

## Testing

To verify the changes:

1. **Send an animated sticker** - Should use thumbnail instead of TGS file
2. **Send a video sticker** - Should be processed as video/webm
3. **Send a static sticker** - Should work as before (image/webp)
4. **Check logs with DEBUG level** - Should see detailed media processing info

Example log output:
```
DEBUG - app.services.media - Collected animated sticker thumbnail: 4523 bytes, image/jpeg
DEBUG - app.services.gemini - Added inline media: mime=image/jpeg, kind=image, size=4523 bytes, base64_len=6032
```

## Error Recovery

The bot has multiple fallback layers:
1. **Media collection failure** - Caught and logged, continues without media
2. **Gemini API rejection** - Retries without tools, then without media if needed
3. **Unsupported formats** - Skipped with warning log (e.g., TGS without thumbnail)

## Known Limitations

1. **Animated stickers (TGS):** Only the static thumbnail is sent to Gemini, not the animation
2. **Large files:** Files >20MB may fail (Gemini inline data limit)
3. **Non-media documents:** PDF, ZIP, etc. are not processed

## Future Improvements

- Implement Gemini Files API for large media (>20MB)
- Add pre-validation for media size and format
- Consider converting TGS to GIF/WebM for full animation support
- Add user-facing error messages when media fails to process

## Verification Commands

```bash
# Check if bot is running
docker compose ps

# View logs with media debugging
docker compose logs bot --tail=50 | grep -i "media\|sticker"

# Restart bot to apply changes
docker compose restart bot
```

## Related Files

- `app/services/media.py` - Media collection and type detection
- `app/services/gemini.py` - Media format conversion and error handling
- `app/handlers/chat.py` - Message processing and media integration
- `.dockerignore` - Excludes runtime data from Docker builds

## References

- [Gemini API Media Support](https://ai.google.dev/gemini-api/docs/vision)
- [Telegram Bot API - Stickers](https://core.telegram.org/bots/api#sticker)
- [aiogram Sticker Documentation](https://docs.aiogram.dev/en/latest/api/types/sticker.html)
