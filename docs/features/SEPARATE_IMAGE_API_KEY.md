# Separate API Key for Image Generation

## Change Summary

Added support for using a separate Google Gemini API key for image generation, allowing you to use a different account/billing for images versus text generation.

## Motivation

- **Billing Separation**: Track image generation costs separately from text generation
- **API Quota Isolation**: Image generation won't affect text generation API limits
- **Account Flexibility**: Use different Google Cloud accounts for different features
- **Cost Control**: Monitor and limit image generation expenses independently

## Implementation

### Configuration Added

New optional environment variable:

```bash
IMAGE_GENERATION_API_KEY=your_separate_api_key_here
```

**Behavior:**
- If `IMAGE_GENERATION_API_KEY` is set → uses that key for image generation
- If `IMAGE_GENERATION_API_KEY` is empty/not set → falls back to `GEMINI_API_KEY`

### Files Modified

1. **`app/config.py`**
   - Added `image_generation_api_key` field (optional, defaults to None)
   - Type: `str | None`

2. **`app/main.py`**
   - Updated service initialization to use separate key with fallback
   - Added logging to show whether separate key is being used
   - Log field: `"separate_api_key": True/False`

3. **`.env.example`**
   - Documented new `IMAGE_GENERATION_API_KEY` setting
   - Added explanation of fallback behavior

4. **`docs/features/IMAGE_GENERATION.md`**
   - Updated features list to mention separate API key support
   - Added configuration example showing optional key
   - Documented use cases for separate keys

### Code Example

```python
# In app/main.py
image_api_key = settings.image_generation_api_key or settings.gemini_api_key

image_gen_service = ImageGenerationService(
    api_key=image_api_key,  # Uses separate key if available
    db_path=settings.db_path,
    daily_limit=settings.image_generation_daily_limit,
    admin_user_ids=settings.admin_user_ids_list,
)
```

## Usage

### Setup with Separate Key

1. Get a second Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

2. Add to `.env`:
   ```bash
   # Main bot functionality
   GEMINI_API_KEY=your_main_api_key
   
   # Image generation (separate account)
   IMAGE_GENERATION_API_KEY=your_image_api_key
   ENABLE_IMAGE_GENERATION=true
   ```

3. Restart the bot:
   ```bash
   docker compose restart bot
   ```

4. Check logs to verify:
   ```bash
   docker compose logs | grep "Image generation service initialized"
   # Should show: "separate_api_key": true
   ```

### Setup with Single Key (Default)

Just enable image generation without setting the separate key:

```bash
GEMINI_API_KEY=your_api_key
ENABLE_IMAGE_GENERATION=true
# IMAGE_GENERATION_API_KEY not set - will use GEMINI_API_KEY
```

## Verification

```bash
# 1. Check configuration is loaded
grep "image_generation_api_key" app/config.py

# 2. Check fallback logic in main.py
grep -A 5 "image_api_key = " app/main.py

# 3. Check logs for initialization
docker compose logs | grep "separate_api_key"

# 4. Test image generation
# Send to bot: "Намалюй кота"
# Check which API key was charged in Google Cloud Console
```

## Benefits

### Cost Management

With `GEMINI_API_KEY` (Free tier: 1500 requests/day):
- Text generation: Most of the quota
- Image generation: ~$0.04 per image

With separate keys:
- Text: 1500 requests/day on main account
- Images: 1500 requests/day on separate account (independent quota)

### API Quota Independence

If image generation hits rate limits, text generation continues normally (and vice versa).

### Billing Clarity

Google Cloud Console will show separate API usage:
- Account A: Text generation costs
- Account B: Image generation costs

## Backward Compatibility

✅ **Fully backward compatible**
- Existing deployments without `IMAGE_GENERATION_API_KEY` continue working
- Fallback to `GEMINI_API_KEY` is automatic
- No migration required

## Future Enhancements

Potential additions:
- Per-key rate limiting configuration
- Automatic failover between multiple keys
- Key rotation for load balancing
- Separate keys for embeddings, search, etc.

## References

- Google AI Studio (get API keys): https://aistudio.google.com/apikey
- Gemini API Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Image Generation Docs: `docs/features/IMAGE_GENERATION.md`
