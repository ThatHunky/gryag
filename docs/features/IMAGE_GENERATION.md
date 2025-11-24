# Image Generation Feature

## Overview

Gryag can generate images using either Google's Gemini 2.5 Flash Image model or Pollinations.ai. The bot can create images from text descriptions conversationally, with daily quota limits to control usage.

## Implementation Details

### Providers

#### Gemini (Default)
- **Model**: `gemini-2.5-flash-image`
- **Method**: Native Gemini API (same SDK as text generation)
- **Output**: PNG images with SynthID watermark (Google's AI watermark)
- **Cost**: ~$0.04 per image ($30 per 1M tokens, 1290 tokens per image)
- **Features**: Supports aspect ratios, context images for editing

#### Pollinations.ai
- **Service**: Free, open-source AI image generation
- **Method**: HTTP GET request to Pollinations.ai API
- **Output**: JPEG/PNG images
- **Cost**: Free (no API key required)
- **Limitations**: No aspect ratio support, no context image support

### Features

- ✅ Text-to-image generation from natural language prompts
- ✅ Daily quota system (3 images/day for regular users by default, unlimited for admins)
- ✅ **Multiple provider support** (Gemini or Pollinations.ai)
- ✅ **Separate API key support** for Gemini (use different Gemini account for images)
- ✅ Support for aspect ratios: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9 (Gemini only)
- ✅ Context image support (for image editing, Gemini only)
- ✅ Ukrainian language support in responses
- ✅ Automatic quota tracking per user per chat
- ✅ Admin bypass for quota limits

### Configuration

Add to `.env`:

```bash
# Image Generation
ENABLE_IMAGE_GENERATION=true  # Enable/disable the feature
IMAGE_GENERATION_PROVIDER=gemini  # Provider: "gemini" (default) or "pollinations"
IMAGE_GENERATION_API_KEY=your_separate_key_here  # Optional: Use separate account for images (Gemini only)
IMAGE_GENERATION_DAILY_LIMIT=3  # Images per user per day (1-10, default: 3)
```

**Provider Selection**:
- `gemini` (default): Uses Google Gemini 2.5 Flash Image model. Requires `GEMINI_API_KEY` or `IMAGE_GENERATION_API_KEY`. Supports aspect ratios and context images.
- `pollinations`: Uses free Pollinations.ai service. No API key required. Simpler but no aspect ratio or context image support.

**Note for Gemini**: If `IMAGE_GENERATION_API_KEY` is not set, the service will fall back to using `GEMINI_API_KEY`. This allows you to:
- Use a separate Google Cloud account for image generation billing
- Isolate image generation API limits from text generation
- Control costs more granularly

**Note for Pollinations**: No API key is required. The service is free but has limitations:
- No aspect ratio control (always generates square images)
- No context image support (edit_image tool will generate a new image instead of editing)
- Simpler API with fewer features

**Quota behavior**:
- Quota is **only consumed on successful image generation**
- Failed generations (errors, safety blocks, API issues) do **not** count against the limit
- Admins (set via `ADMIN_USER_IDS`) have unlimited image generation

### Database Schema

New table `image_quotas`:

```sql
CREATE TABLE IF NOT EXISTS image_quotas (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    generation_date TEXT NOT NULL,  -- YYYY-MM-DD format
    images_generated INTEGER DEFAULT 0,
    last_generation_ts INTEGER,
    PRIMARY KEY (user_id, chat_id, generation_date)
);
```

### Usage

Users can request images naturally in conversation:

- "Намалюй кота з бананом"
- "Створи фото робота в стилі ретро"
- "Згенеруй логотип для кав'ярні"

The bot will:
1. Check if user has remaining quota
2. Generate the image using Gemini
3. Send the image to chat
4. Reply with quota status

### Tool Definition

Function name: `generate_image`

Parameters:
- `prompt` (required): Detailed description of the image to generate
- `aspect_ratio` (optional): Image aspect ratio (default: "1:1")

### Error Handling

- **Quota exceeded**: "Перевищено денний ліміт (X/Y зображень). Спробуй завтра!"
- **Safety rejection**: "Запит відхилено через політику безпеки"
- **API limit**: "Перевищено ліміт API. Спробуй пізніше"
- **Timeout**: "Тайм-аут генерації. Спробуй ще раз"
- **Generic error**: "Не вдалося згенерувати зображення"

## Architecture

### Components

1. **ImageGenerationService** (`app/services/image_generation.py`)
   - Manages quota checking and tracking
   - Routes to appropriate provider (Gemini or Pollinations.ai)
   - Handles error scenarios
   - **PollinationsImageGenerator**: Client for Pollinations.ai API

2. **Tool Integration** (`app/handlers/chat.py`)
   - Adds `generate_image` to tool definitions
   - Creates async callback that sends photos to Telegram
   - Tracks tool usage for telemetry

3. **Middleware Injection** (`app/middlewares/chat_meta.py`)
   - Injects `image_gen_service` into handler data
   - Initialized only if `ENABLE_IMAGE_GENERATION=true`

4. **Database** (`db/schema.sql`)
   - `image_quotas` table for daily usage tracking
   - Automatic date-based quota reset

### Files Modified

- ✅ `db/schema.sql` - Added `image_quotas` table
- ✅ `app/config.py` - Added configuration settings
- ✅ `app/services/image_generation.py` - New service (created)
- ✅ `app/handlers/chat.py` - Added tool definition and callback
- ✅ `app/middlewares/chat_meta.py` - Added service injection
- ✅ `app/main.py` - Service initialization
- ✅ `.env.example` - Documented new settings

## Future Enhancements

1. **Image Editing**: Support for context images (edit existing images)
2. **Style Transfer**: Apply artistic styles to images
3. **Multi-image Composition**: Combine multiple images
4. **Iterative Refinement**: Multi-turn conversation to refine images
5. **Admin Commands**: Manual quota management (`/gryagimagequota`)

## Verification

To verify the implementation:

```bash
# 1. Check database schema
sqlite3 gryag.db ".schema image_quotas"

# 2. Check service exists
grep -r "class ImageGenerationService" app/services/

# 3. Check tool definition
grep -r "GENERATE_IMAGE_TOOL_DEFINITION" app/

# 4. Check configuration
grep "enable_image_generation" app/config.py

# 5. Test generation (requires .env setup)
# Enable in .env: ENABLE_IMAGE_GENERATION=true
# Run bot and send message: "Намалюй синього кота"
```

## Limits and Constraints

- **Model Limits**: Best performance with English/Spanish/Japanese/Chinese/Hindi prompts
- **Input**: Does not support audio or video inputs
- **Output Count**: Model may not always follow exact image count requests
- **Context Images**: Best with up to 3 context images
- **EEA Restrictions**: Cannot upload images of children in EEA, Switzerland, UK
- **Watermark**: All generated images include SynthID watermark

## Cost Estimate

With default settings (1 image/day/user):
- 100 users = 100 images/day = $4/day = $120/month
- 1000 users = 1000 images/day = $40/day = $1,200/month

Adjust `IMAGE_GENERATION_DAILY_LIMIT` to control costs.

## References

- [Gemini Image Generation Docs](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini 2.5 Flash Image Model](https://ai.google.dev/gemini-api/docs/models/gemini)
- [SynthID Watermark](https://ai.google.dev/responsible/docs/safeguards/synthid)
- [Pollinations.ai GitHub](https://github.com/pollinations/pollinations)
