# Graceful Media Handling

**Date:** October 7, 2025  
**Feature:** Automatic detection and filtering of unsupported media types based on model capabilities

## Overview

Different Gemini models have different media support capabilities. This feature automatically detects what media types each model supports and gracefully filters out unsupported types, preventing API errors and improving reliability.

## Problem

When users send media that the current model doesn't support, the bot would crash with errors like:
- `400 Audio input modality is not enabled for models/gemma-3-27b-it`
- `400 Please use fewer than 32 images in your request`
- Similar errors for video, documents, etc.

## Solution

### 1. Model Capability Detection

The `GeminiClient` now automatically detects model capabilities on initialization:

```python
# In __init__
self._audio_supported = self._detect_audio_support(model)
self._video_supported = self._detect_video_support(model)
```

**Detection rules:**
- **Gemma models**: No audio support, limited video (YouTube URLs only)
- **Gemini 1.5+**: Full audio and video support
- **Gemini Pro/Flash**: Image support (all variants)

### 2. Media Filtering

The `build_media_parts()` method now:
1. Checks each media item against model capabilities
2. Filters out unsupported types before API call
3. Logs what was filtered and why
4. Counts filtered items for metrics

```python
# Example filtering
if not self._is_media_supported(mime, kind):
    filtered_count += 1
    logger.info(
        "Filtered unsupported media: mime=%s, kind=%s (model: %s)",
        mime, kind, self._model_name
    )
    continue
```

### 3. Media Limit Management

In addition to type filtering, the system limits total media count:

- **Gemma models**: Max 28 items (hard limit 32)
- **Configurable**: `GEMINI_MAX_MEDIA_ITEMS` in `.env`
- **Smart removal**: Removes oldest media first
- **Preserves text**: Always keeps text content

## Configuration

### Environment Variables

```bash
# Model selection (determines capabilities)
GEMINI_MODEL=models/gemma-3-27b-it  # or gemini-2.5-flash, etc.

# Media limit (adjust based on model)
GEMINI_MAX_MEDIA_ITEMS=28  # Conservative for Gemma
# For Gemini 1.5+: Can increase to 50+
```

### Model-Specific Limits

| Model Family | Images | Audio | Video | Max Items |
|-------------|---------|-------|-------|-----------|
| Gemma 3     | ✅      | ❌    | ⚠️*   | 32        |
| Gemini 1.5  | ✅      | ✅    | ✅    | 100+      |
| Gemini 2.0  | ✅      | ✅    | ✅    | 100+      |
| Gemini Flash| ✅      | ✅    | ✅    | 50+       |

*Gemma supports YouTube URLs via `file_uri`, but not inline video

## Implementation Details

### Files Modified

1. **`app/services/gemini.py`** (+120 lines)
   - Added `_detect_audio_support()` static method
   - Added `_detect_video_support()` static method
   - Added `_is_media_supported()` instance method
   - Modified `build_media_parts()` to filter unsupported media
   - Changed from `@staticmethod` to instance method (needs `self`)

2. **`app/services/context/multi_level_context.py`**
   - Updated `format_for_gemini()` to use config value
   - Changed `MAX_MEDIA_ITEMS` from hardcoded to `self.settings.gemini_max_media_items`

3. **`app/config.py`**
   - Added `gemini_max_media_items` field (default: 28)

4. **`.env.example`**
   - Added `GEMINI_MAX_MEDIA_ITEMS` with documentation

### Media Detection Logic

```python
def _is_media_supported(self, mime: str, kind: str) -> bool:
    """Check if media type is supported by current model."""
    
    # Audio check
    if "audio" in mime.lower() or kind.lower() in ("audio", "voice"):
        if not self._audio_supported:
            return False
    
    # Video check (inline, not YouTube URLs)
    if "video" in mime.lower() or kind.lower() == "video":
        if not self._video_supported:
            return False
    
    # Images supported by all models
    return True
```

## User Experience

### Before (Crash)

```
User: [sends voice message]
Bot: 💥 ERROR 400: Audio input modality is not enabled
```

### After (Graceful)

```
User: [sends voice message]
Bot: [processes text if any, ignores audio]
Logs: "Filtered unsupported media: mime=audio/ogg, kind=voice (model: gemma-3-27b-it)"
```

### With Multiple Media

```
User: [sends 5 photos + 1 voice message]
Bot: [processes 5 photos, filters voice message]
Logs: "Filtered 1 unsupported media item(s) for model gemma-3-27b-it"
```

## Logging

### Info Level (Normal Operations)

```
INFO - Filtered unsupported media: mime=audio/ogg, kind=voice (model: gemma-3-27b-it)
```

### Warning Level (Media Count Exceeded)

```
WARNING - Filtered 3 unsupported media item(s) for model gemma-3-27b-it
INFO - Limited media in history: removed 5 of 35 items (max: 28)
```

### Debug Level (All Media)

```
DEBUG - Added inline media: mime=image/jpeg, kind=photo, size=45678 bytes
DEBUG - Added file_uri media: https://youtube.com/watch?v=...
```

## How to Verify

### 1. Check Model Capabilities

```bash
# Check logs during bot startup
docker compose logs bot | grep -E "audio_supported|video_supported"
```

### 2. Test Media Filtering

```bash
# Send voice message to bot
# Check logs for filtering
docker compose logs bot | grep "Filtered unsupported media"
```

### 3. Test Media Limiting

```bash
# Send many images (30+)
# Check logs for limiting
docker compose logs bot | grep "Limited media in history"
```

### 4. Monitor Metrics

```bash
# Count how often filtering happens
docker compose logs bot | grep -c "Filtered.*unsupported media"
```

## Supported Media Types

### All Models

- **Images**: JPEG, PNG, WebP, GIF
- **Text**: Plain text, captions

### Gemini 1.5+ Only

- **Audio**: MP3, WAV, OGG, FLAC, AAC, M4A
- **Video**: MP4, MOV, AVI, WebM, MPEG
- **Documents**: PDF (with text extraction)

### Special Cases

- **YouTube URLs**: Supported via `file_uri` (all models)
- **Stickers**: Treated as images (all models)
- **Animated GIFs**: Supported as images (all models)

## Troubleshooting

### "No response with audio"

**Cause**: Using Gemma model which doesn't support audio  
**Solution**: Switch to Gemini model or transcript audio manually

```bash
# In .env
GEMINI_MODEL=gemini-2.5-flash  # Instead of gemma-3-27b-it
```

### "Still getting 400 errors"

**Cause**: Media limit too high or model changed  
**Solution**: Lower `GEMINI_MAX_MEDIA_ITEMS`

```bash
# In .env
GEMINI_MAX_MEDIA_ITEMS=20  # Reduce if errors persist
```

### "Media not processed"

**Cause**: Media filtered as unsupported  
**Solution**: Check logs, verify model supports that media type

```bash
docker compose logs bot | grep "Filtered unsupported"
```

## Future Enhancements

1. **Dynamic capability detection** via API metadata
2. **Per-media-type limits** (e.g., max 10 videos, 50 images)
3. **Smart media selection** (keep highest quality when limiting)
4. **User notifications** when media is filtered
5. **Telemetry counters** for filtered media types
6. **Media transcoding** (convert unsupported formats)

## Related

- **Gemma Media Limit Fix**: `docs/fixes/gemma-media-limit-fix.md`
- **Multi-Level Context**: `docs/plans/MEMORY_AND_CONTEXT_IMPROVEMENTS.md`
- **Model Configuration**: `docs/guides/model-selection.md` (TODO)

## Notes

- Filtering happens **before** API call (no quota waste)
- Text content is **never filtered** (always sent)
- YouTube URLs bypass filtering (handled separately)
- Media limits apply to **historical context only** (current message always included)
- Capability detection is **static** (determined at startup, not runtime)
