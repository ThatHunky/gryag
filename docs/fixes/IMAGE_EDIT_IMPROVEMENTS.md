# Image Edit Tool Improvements

**Date**: October 19, 2025  
**Status**: Implemented  
**Related**: Image generation feature, chat tools

## Problem

User reported two issues with image editing:

1. **Not photorealistic by default**: Images were not generated with photorealistic style by default
2. **Required reply to image**: Bot couldn't edit images unless user explicitly replied to the image message, causing friction in conversation flow

Example conversation:
```
User: *[sends image]*
User: гряг прибери напис з картинки

Bot: Тю, ти ж не відповів на саме фото, яке треба редагувати...
```

## Solution

### 1. Photorealistic by default

Updated system prompt and tool descriptions to generate **photorealistic images (photos)** by default unless user specifies otherwise:

**Files changed:**
- `app/persona.py`: Updated tool descriptions to emphasize photorealistic generation and **English prompts**
- `app/services/image_generation.py`: Updated `GENERATE_IMAGE_TOOL_DEFINITION` prompt parameter description

Key changes:
- Added "photorealistic", "photo", "realistic photography" keywords to prompts
- Clear instruction: "ЗА ЗАМОВЧУВАННЯМ генеруй ФОТОРЕАЛІСТИЧНІ зображення"
- User can still request other styles (cartoon, illustration, painting)
- **CRITICAL: Bot now always translates prompts to ENGLISH** - significantly better results with image models

### 2. Smart image finding in conversation history

Enhanced `edit_image_tool` to search recent message history when no direct reply is present:

**Files changed:**
- `app/handlers/chat_tools.py`: Rewrote `edit_image_tool` function
- `app/handlers/chat.py`: Updated fallback logic to not require reply_context

**New behavior:**
1. First tries to get image from replied message (if present)
2. If no reply, searches `_RECENT_CONTEXT` cache (last 5 messages per chat/thread)
3. Extracts image from `media_parts` by decoding base64 `inline_data`
4. Returns helpful error if no image found in recent history

### 3. Automatic aspect ratio preservation

When editing images, the tool now **automatically detects and preserves** the original image's aspect ratio:

**Implementation:**
- Uses PIL to open image and get dimensions
- Calculates ratio (width/height)
- Maps to closest supported aspect ratio (1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 4:5, 5:4, 21:9)
- Passes detected ratio to `generate_image()` instead of default 1:1
- Removed `aspect_ratio` parameter from `EDIT_IMAGE_TOOL_DEFINITION` (now automatic)

**Example:**
- Original image: 1920x1080 (ratio 1.778) → detects as 16:9
- Original image: 1080x1920 (ratio 0.562) → detects as 9:16
- Edited image maintains the same aspect ratio

### 4. Updated tool descriptions

**`edit_image` tool:**
- "Інструмент сам знайде останнє фото в історії розмови"
- "Автоматично зберігає оригінальні пропорції зображення"
- Removed aspect_ratio parameter (now automatic)

## Technical Details

### Image search logic (`edit_image_tool`)

```python
# 1. Try reply message first
if reply:
    reply_media_raw = await collect_media_parts(bot, reply)
    image_bytes_list = [part.get("bytes") for part in reply_media_raw if part.get("kind") == "image"]
    if image_bytes_list:
        image_bytes = image_bytes_list[0]

# 2. Search recent context if no reply
if not image_bytes:
    from app.handlers.chat import _RECENT_CONTEXT
    key = (chat_id, thread_id)
    stored_queue = _RECENT_CONTEXT.get(key)
    if stored_queue:
        for item in reversed(stored_queue):  # Search backwards
            media_parts = item.get("media_parts")
            if media_parts:
                for part in media_parts:
                    if isinstance(part, dict) and "inline_data" in part:
                        mime = part.get("inline_data", {}).get("mime_type", "")
                        if mime.startswith("image/"):
                            data = part.get("inline_data", {}).get("data", "")
                            image_bytes = base64.b64decode(data)
                            break
```

### Aspect ratio detection

```python
from PIL import Image
from io import BytesIO

img = Image.open(BytesIO(image_bytes))
width, height = img.size
ratio = width / height

# Map to closest standard ratio
aspect_ratios = {
    "1:1": 1.0,
    "16:9": 16/9,
    "4:3": 4/3,
    # ... etc
}

closest_ratio = min(aspect_ratios.items(), key=lambda x: abs(x[1] - ratio))
detected_aspect_ratio = closest_ratio[0]
```

## Impact

### Before
- User had to remember to reply to the image message
- Aspect ratio not preserved (always 1:1 by default)
- Images weren't photorealistic unless explicitly requested

### After  
- Natural conversation flow: "гряг прибери напис з картинки" works without reply
- Original aspect ratio automatically preserved
- Photorealistic style by default
- Better UX: bot searches recent history (last 5 messages) for images

## Error Handling

New error messages:
- "Не знайшов жодного зображення в недавній історії. Пришли фото або відповідь на нього." - when no image in recent context
- Falls back to 1:1 aspect ratio if detection fails (with warning in logs)

## Testing

### Manual verification steps:

1. **Photorealistic generation:**
   ```
   User: гряг намалюй кота
   Expected: Generates photorealistic cat photo
   ```

2. **Edit without reply:**
   ```
   User: *[sends image of dog]*
   User: гряг зміни фон на осінній
   Expected: Bot finds image from history and edits it
   ```

3. **Aspect ratio preservation:**
   ```
   User: *[sends 16:9 landscape photo]*
   User: (reply) гряг прибери напис
   Expected: Edited image is also 16:9
   ```

4. **Fallback to photorealistic on edit:**
   ```
   User: (reply to cartoon image) гряг зроби реалістичним
   Expected: Converts to photorealistic style
   ```

### Run tests:
```bash
pytest tests/unit/test_chat_tools_image.py -v
```

## Notes

- The `_RECENT_CONTEXT` cache holds last 5 messages per chat/thread with 1-hour TTL
- Images are also persisted to database via `_remember_context_message()` for long-term context
- Aspect ratio detection is defensive (fallback to 1:1 on errors)
- Admin users bypass quotas (unchanged behavior)

## Future Improvements

- [ ] Search database history if image not in `_RECENT_CONTEXT` (currently only checks last 5 messages)
- [ ] Support "edit the 2nd last image" or "edit the image from 5 minutes ago"
- [ ] Allow user to explicitly specify aspect ratio in edit request ("зроби квадратним")
- [ ] Detect and preserve other image properties (color palette, style)
