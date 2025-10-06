# Multimodal Capabilities

**Last Updated**: October 6, 2025  
**Status**: ✅ Fully Implemented

## Overview

The gryag bot now supports comprehensive multimodal input via Gemini 2.5 Flash API, enabling it to understand and respond to images, audio, video, and YouTube content in addition to text.

## Supported Input Types

### 1. **Images** 🖼️

**Telegram Types Supported:**
- Photos (compressed by Telegram)
- Image documents (PNG, JPEG, WebP, etc.)
- Stickers (WebP format)

**Formats:**
- PNG (`image/png`)
- JPEG (`image/jpeg`)
- WebP (`image/webp`)
- HEIC (`image/heic`)
- HEIF (`image/heif`)

**Capabilities:**
- Image understanding and description
- Visual question answering
- Object detection (Gemini 2.5+)
- Image segmentation (Gemini 2.5+)
- Multiple images per message

**Example Usage:**
```
User: [sends photo of a cat]
      Що це за порода?

Bot: Це виглядає як шотландська висловуха (Scottish Fold)...
```

### 2. **Audio** 🎵

**Telegram Types Supported:**
- Voice messages (OGG/Opus)
- Audio files (MP3, M4A, etc.)
- Audio documents

**Formats:**
- OGG Vorbis (`audio/ogg`)
- MP3 (`audio/mp3`, `audio/mpeg`)
- WAV (`audio/wav`)
- AAC (`audio/aac`)
- AIFF (`audio/aiff`)
- FLAC (`audio/flac`)

**Capabilities:**
- Audio transcription
- Content understanding (music, speech, ambient sounds)
- Question answering about audio
- Non-speech recognition (birdsong, sirens, etc.)
- Timestamp references

**Limitations:**
- Max 9.5 hours per message
- Downsampled to 16 Kbps mono
- 32 tokens per second of audio

**Example Usage:**
```
User: [sends voice message in Ukrainian]
      Переклади на англійську

Bot: Here's the translation: "..."
```

### 3. **Video** 🎬

**Telegram Types Supported:**
- Video files (MP4, MOV, etc.)
- Video notes (круглі відео)
- Animations/GIFs (treated as video)
- Video documents

**Formats:**
- MP4 (`video/mp4`)
- MPEG (`video/mpeg`)
- MOV (`video/mov`)
- AVI (`video/avi`)
- WebM (`video/webm`)
- WMV (`video/wmv`)
- FLV (`video/x-flv`)
- 3GPP (`video/3gpp`)

**Capabilities:**
- Video summarization
- Visual + audio transcription
- Scene understanding
- Timestamp references
- Question answering about content
- Frame sampling (default 1 FPS)

**Limitations:**
- 2M context models: up to 2 hours (default res) or 6 hours (low res)
- 1M context models: up to 1 hour (default res) or 3 hours (low res)
- ~300 tokens per second (default) or ~100 tokens/sec (low res)

**Example Usage:**
```
User: [sends video]
      Що відбувається на 0:45?

Bot: На 45-й секунді...
```

### 4. **YouTube Videos** 📺

**NEW Feature**: Direct YouTube URL support without downloading!

**How It Works:**
- Bot automatically detects YouTube URLs in messages
- Passes URLs directly to Gemini API as `file_uri`
- No need to download video files

**URL Patterns Detected:**
- `https://youtube.com/watch?v=VIDEO_ID`
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `http://` variants

**Limitations:**
- Free tier: max 8 hours of YouTube video per day
- Paid tier: no limit based on video length
- Only public videos (no private/unlisted)
- Max 10 videos per request (Gemini 2.5+)

**Example Usage:**
```
User: https://youtube.com/watch?v=dQw4w9WgXcQ
      Про що це відео?

Bot: Це класичний рікролл від Ріка Естлі...
```

## Implementation Details

### Architecture

**Media Collection** (`app/services/media.py`):
- `collect_media_parts()` - Downloads and structures media from Telegram
- `extract_youtube_urls()` - Detects YouTube links in text
- Handles all Telegram media types
- Logs media type and size for debugging

**Media Conversion** (`app/services/gemini.py`):
- `build_media_parts()` - Converts to Gemini API format
- Base64 encoding for inline data (<20MB)
- File URI format for YouTube URLs
- Supports mixed media types in one request

**Message Handling** (`app/handlers/chat.py`):
- Processes media in both addressed and unaddressed messages
- Caches media in context for continuity
- Creates Ukrainian summaries for user feedback
- Integrates with conversation history

### Size Limits

**Inline Data (Base64):**
- Total request size: <20MB (includes text + all media)
- Checked and logged if exceeded
- Recommendation: Use Files API for larger content (not yet implemented)

**YouTube URLs:**
- No download required, passed directly
- Only counts toward daily quota (free tier)

### Token Consumption

**Images:**
- Small (≤384px): 258 tokens
- Larger: tiled at 768×768, 258 tokens per tile

**Audio:**
- 32 tokens per second

**Video:**
- ~300 tokens/second (default resolution)
- ~100 tokens/second (low resolution)
- Includes frames (1 FPS) + audio + metadata

## Error Handling

**Download Failures:**
- Timeout: 60 seconds (increased for videos)
- Network errors logged, gracefully skipped
- Partial media processing continues

**Unsupported Types:**
- Documents with non-media MIME types are skipped
- Logged at DEBUG level for monitoring

**Size Warnings:**
- Total >20MB triggers warning log
- Gemini may reject oversized requests
- Future: Implement Files API for large content

## Telemetry

All media processing is logged:
```python
LOGGER.debug(
    "Collected video: %d bytes, %s, duration=%ds, %dx%d",
    len(data), mime, duration, width, height
)
```

Media summaries shown to users in Ukrainian:
- `"Прикріплення: 2 фото, відео"`
- `"Прикріплення: аудіо, YouTube відео"`

## Future Enhancements

### Planned
- [ ] Files API integration for >20MB content
- [ ] Custom video frame rate sampling
- [ ] Video clipping by timestamp
- [ ] Media resolution controls (high/low)
- [ ] Advanced image features (object detection, segmentation)
- [ ] Audio-only vs video transcription options

### Possible
- [ ] Image generation (Imagen integration)
- [ ] Video caching for repeated queries
- [ ] Multi-video analysis in single request
- [ ] Document OCR and PDF processing

## Testing

**Manual Testing Checklist:**
- [ ] Send photo → bot describes it
- [ ] Send voice message → bot transcribes
- [ ] Send video file → bot summarizes
- [ ] Send YouTube URL → bot analyzes without downloading
- [ ] Send GIF/animation → bot understands as video
- [ ] Send sticker → bot sees as image
- [ ] Send multiple media types together
- [ ] Send very large video (>20MB) → check warning
- [ ] Send non-media document → gracefully skipped

**Verification Commands:**
```bash
# Check logs for media processing
grep "Collected" logs/bot.log

# Monitor YouTube URL detection
grep "YouTube URL" logs/bot.log

# Watch for size warnings
grep "exceeds.*MB limit" logs/bot.log
```

## Migration Notes

**Breaking Changes:** None

**New Dependencies:** None (uses existing libraries)

**Configuration:** No new env vars required

**Database:** No schema changes

## Related Files

- `app/services/media.py` - Media collection and YouTube detection
- `app/services/gemini.py` - Media format conversion
- `app/handlers/chat.py` - Message processing integration
- `docs/features/MULTIMODAL_CAPABILITIES.md` - This document

## References

- [Gemini Image Understanding](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Gemini Audio Understanding](https://ai.google.dev/gemini-api/docs/audio)
- [Gemini Video Understanding](https://ai.google.dev/gemini-api/docs/video-understanding)
- [Telegram Bot API Media](https://core.telegram.org/bots/api#available-types)
