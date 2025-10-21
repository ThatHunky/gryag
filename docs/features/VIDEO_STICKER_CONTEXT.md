# Video & Sticker Context in Compact Format

**Status**: Implemented (Oct 2025)
**Related**: VIDEO_STICKER_CONTEXT_FIX_PLAN.md

## Problem

When using compact conversation format (70-80% token savings), videos and stickers from conversation history were not visible to the bot. The bot could only "see" media from the current message, making conversations about historical videos/stickers impossible.

### Root Causes

1. **Compact format dropped historical media**: `format_for_gemini_compact()` rendered text-only history, didn't include `inline_data`/`file_data` parts
2. **Generic media descriptions**: Format showed "[Media]" instead of "[Video]", "[Sticker]", "[Image]"
3. **Kind matching mismatch**: `describe_media()` checked `kind=="photo"` but code uses `kind="image"`

## Solution

### Phase 1: Historical Media Inclusion (HIGH PRIORITY)

**Modified**: `app/services/context/multi_level_context.py`, `app/handlers/chat.py`

- `format_for_gemini_compact()` now collects media parts from immediate and recent context
- Returns `historical_media` array alongside `conversation_text`
- Chat handler includes historical media in `user_parts` with priority ordering:
  1. **Current message media** (highest priority)
  2. **Historical media** (chronological order, oldest first)
- Enforces `GEMINI_MAX_MEDIA_ITEMS` limit (default 28)
- Token counting includes historical media (258 per inline_data, 100 per file_uri)

### Phase 2: Media Type Descriptions (MEDIUM PRIORITY)

**Modified**: `app/services/conversation_formatter.py`

- Fixed `describe_media()` kind matching: `kind=="image"` (not "photo")
- Added sticker detection: WebP (`image/webp`) and WebM (`video/webm`)
- `format_history_compact()` now uses `describe_media()` instead of generic "[Media]"
- Descriptions: "[Image]", "[Video]", "[Sticker]", "[Audio]", "[Document: filename]"

### Phase 4: Debug Logging

**Modified**: `app/handlers/chat.py` (lines 1035-1047)

- Logs media type distribution after `build_media_parts()`: `{"video/mp4": 2, "image/webp": 1}`
- Tracks historical media truncation: "Historical media truncated: X items kept, Y dropped"
- Warns when media limit exceeded

### Phase 7: Telemetry Counters

**Modified**: `app/handlers/chat.py`

- `context.historical_media_included`: Count of historical media items included
- `context.historical_media_dropped`: Count of historical media items dropped due to limit
- `context.media_limit_exceeded`: Incremented when total media exceeds `GEMINI_MAX_MEDIA_ITEMS`

## Implementation Details

### Media Priority Algorithm

**3-Tier Priority System** with video limiting:

```python
max_media_total = settings.gemini_max_media_items  # Default 28 (Gemini API limit)
max_historical = settings.gemini_max_media_items_historical  # Default 5
max_videos = settings.gemini_max_video_items  # Default 1
all_media = []
video_count = 0
video_descriptions = []

# Priority 1: Current message media
for media_item in media_parts:
    if is_video and video_count >= max_videos:
        continue  # Skip, no description available for current message
    all_media.append(media_item)
    if is_video:
        video_count += 1

# Priority 2: Reply message media (ALWAYS included if available)
for media_item in reply_media_parts:
    if is_video and video_count >= max_videos:
        # Skip video but retrieve description from history
        description = await _get_video_description_from_history(...)
        if description:
            video_descriptions.append(f"[Previously about video]: {description}")
        continue
    all_media.append(media_item)
    if is_video:
        video_count += 1

# Priority 3: Historical media (limited to max_historical)
for media_item in historical_media[:remaining_slots]:
    if is_video and video_count >= max_videos:
        continue  # Skip, no description available
    all_media.append(media_item)
    if is_video:
        video_count += 1

# Add video descriptions to conversation text
if video_descriptions:
    user_parts[0]["text"] += "\n\n" + "\n".join(video_descriptions)

# Final user_parts
user_parts = [{"text": full_conversation}]
user_parts.extend(all_media[:max_media_total])
```

**Key improvements**:
- **Video limit**: Maximum 1 video included (configurable via `GEMINI_MAX_VIDEO_ITEMS`)
- **Description fallback**: Videos over limit replaced with text descriptions from bot's previous responses
- **Reply media always included**: Unless it's a video over the limit (then description is added)
- **Historical media**: Limited to 5 items by default, videos count toward video limit

### Media Type Inference

For historical media (where `kind` is not available in Gemini API format):

```python
if "inline_data" in part:
    mime = part["inline_data"]["mime_type"]
    if "image" in mime:
        kind = "image"
    elif "video" in mime:
        kind = "video"
    elif "audio" in mime:
        kind = "audio"
elif "file_data" in part:
    kind = "video"  # File URIs are typically YouTube/uploaded videos
```

### Sticker Detection

Telegram stickers come in 3 formats:
- **Static**: `image/webp` (kind="image")
- **Animated**: `application/x-tgsticker` (.TGS, Lottie JSON)
- **Video**: `video/webm` (kind="image" but mime is video)

Detection logic:

```python
if kind == "image" or "image" in mime.lower():
    if "webp" in mime.lower() or ("webm" in mime.lower() and "video" in mime.lower()):
        descriptions.append("[Sticker]")
    else:
        descriptions.append("[Image]")
```

## Configuration

- `GEMINI_MAX_MEDIA_ITEMS`: Max media items per request (default 28, Gemini API limit)
  - Gemini Flash 2.0 limit: 32 media per request
  - We use 28 to leave headroom for safety
- `GEMINI_MAX_MEDIA_ITEMS_HISTORICAL`: Max historical media from context (default 5)
  - Set to 0 to disable historical media entirely
  - **Reply message media is ALWAYS included** regardless of this setting
  - Lower limit saves tokens while still providing visual context
- `GEMINI_MAX_VIDEO_ITEMS`: Max videos/animations to include total (default 1) **NEW**
  - Videos over this limit are **replaced with text descriptions** from bot's previous responses
  - Set to 0 to exclude all videos (descriptions only)
  - **Recommended: 1** - reduces Gemini API errors (PROHIBITED_CONTENT, empty responses)
  - Images/stickers don't count toward this limit
- `ENABLE_COMPACT_FORMAT`: Enable compact conversation format (default true)

### Why Limit Videos?

Gemini Flash sometimes has issues processing multiple videos:
- **Empty responses**: Model returns `FinishReason.STOP` but with no text (even for cat GIFs)
- **PROHIBITED_CONTENT blocks**: Multiple videos trigger content policy even with `BLOCK_NONE` safety settings
- **Better descriptions**: Using text descriptions from previous bot responses provides context without media processing overhead

**Solution**: Include only 1 video, replace others with the bot's description of what it saw.

## Testing

**Test file**: `tests/unit/test_video_sticker_context.py` (25 tests)

### Coverage

- ✅ Media descriptions: image, video, sticker (WebP, WebM), audio, document
- ✅ Historical media collection and structure
- ✅ Media limit enforcement with priority ordering
- ✅ Chronological order preservation (oldest first)
- ✅ Telemetry counter logic

### Test Results

```bash
$ pytest tests/unit/test_video_sticker_context.py -v
25 passed in 0.05s
```

## Example Usage

### Before (Missing Video Context)

**User history**:
```
Alice#123: [Video] Check out this tutorial
Bob#456: That's helpful
Alice#123: Can you explain the part at 2:30?
```

**Bot sees**: "Alice#123: Can you explain the part at 2:30?" (no video context)

### After (Video Included)

**User history**:
```
Alice#123: Check out this tutorial [Video]
Bob#456: That's helpful
Alice#123: Can you explain the part at 2:30?
```

**Bot receives**:
- Text: "Alice#123: Check out this tutorial [Video]\nBob#456: That's helpful\nAlice#123: Can you explain the part at 2:30?"
- Media: `[{"inline_data": {"mime_type": "video/mp4", "data": "..."}}]`

Bot can now analyze the video and answer questions about it.

## Token Budget Impact

- **Historical media costs**: 258 tokens per inline_data (image/video/audio), 100 tokens per file_uri
- **Max historical impact**: 5 media × 258 = 1,290 tokens (default, reduced from 28)
- **Reply media**: Always included when replying to older messages (ensures context continuity)
- **Total budget**: Up to 28 media items total (current + reply + historical)
- **Mitigation**: Compact format saves 70-80% on text, leaving more room for media

## Debugging

### Check DEBUG logs

```bash
# Media type distribution for current message
grep "Current message media types:" logs/gryag.log

# Historical media truncation
grep "Historical media truncated:" logs/gryag.log

# Media limit exceeded warnings
grep "Media limit exceeded:" logs/gryag.log
```

### Telemetry queries

```python
# Historical media inclusion rate
telemetry.get_counter("context.historical_media_included") / 
    (telemetry.get_counter("context.historical_media_included") + 
     telemetry.get_counter("context.historical_media_dropped"))

# Media limit hit rate
telemetry.get_counter("context.media_limit_exceeded") / 
    telemetry.get_counter("context.compact_format_used")
```

## Limitations

1. **Token budget**: Historical media is expensive (258 tokens each)
2. **Limit enforcement**: Only 28 media items per request (Gemini API limit)
3. **Priority ordering**: Current message media always prioritized over historical
4. **No duration info**: Video descriptions don't include duration (could be added)
5. **TGS stickers**: Animated TGS stickers are filtered out (not supported by Gemini)

## Future Improvements

1. **Adaptive media limits**: Reduce historical media when token budget is tight
2. **Media relevance scoring**: Prioritize media mentioned in recent conversation
3. **Duration extraction**: Show "[Video 1:23]" instead of "[Video]"
4. **Thumbnail caching**: Cache video thumbnails to reduce token costs
5. **Media type filtering**: Allow users to configure which media types to include

## Verification Steps

1. **Unit tests**: `pytest tests/unit/test_video_sticker_context.py` (25 tests)
2. **Integration test**: Send video in Telegram, ask bot about it 5 messages later
3. **Sticker test**: Send sticker, verify bot sees it as "[Sticker]" in next messages
4. **Limit test**: Send 30 images, verify only 28 are included (current + historical)
5. **Telemetry**: Check counters after deployment for media inclusion rates

## Related Documentation

- `docs/plans/VIDEO_STICKER_CONTEXT_FIX_PLAN.md` - Original implementation plan
- `docs/features/COMPACT_CONVERSATION_FORMAT.md` - Compact format overview
- `docs/features/MULTI_LEVEL_CONTEXT.md` - Context assembly system
- `docs/overview/CURRENT_CONVERSATION_PATTERN.md` - Conversation format specification
