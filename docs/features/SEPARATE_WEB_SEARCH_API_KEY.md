# Separate API Key for Web Search

**Added**: October 26, 2025

## Overview

You can now configure a separate Google Gemini API key specifically for web search grounding operations. This provides better cost control, quota isolation, and billing separation between search and other bot features.

## Configuration

Add to your `.env` file:

```bash
# Main Gemini API key (for text generation, embeddings, etc.)
GEMINI_API_KEY=your_main_api_key_here

# Optional: Separate API key for web search
WEB_SEARCH_API_KEY=your_search_api_key_here
```

**Behavior**:

- If `WEB_SEARCH_API_KEY` is set → uses that key for web search grounding
- If `WEB_SEARCH_API_KEY` is empty/not set → falls back to `GEMINI_API_KEY`

## Implementation Details

1. **Config** (`app/config.py`):
   - Added `web_search_api_key` field (optional, defaults to None)

2. **Search Tool** (`app/services/search_tool.py`):
   - Updated `search_web_tool()` to accept optional `api_key` parameter
   - Creates temporary client with separate key if provided
   - Falls back to main gemini_client's key otherwise

3. **Tool Callbacks** (`app/handlers/chat_tools.py`):
   - Retrieves `web_search_api_key` from settings
   - Falls back to main `gemini_api_key` if not set
   - Passes key to search tool callback

4. **Environment** (`.env.example`):
   - Documented new `WEB_SEARCH_API_KEY` setting

## Usage Example

```python
# In chat_tools.py (automatic)
search_api_key = settings.web_search_api_key or settings.gemini_api_key

callbacks["search_web"] = make_tracked_callback(
    "search_web",
    lambda params: search_web_tool(params, gemini_client, api_key=search_api_key),
)
```

## Benefits

1. **Cost Control**: Separate billing for search operations vs other features
2. **Quota Isolation**: Search quota doesn't affect text generation quota
3. **Independent Scaling**: Use different API tier/account for search
4. **Better Monitoring**: Track search costs separately in Google Cloud Console

## Example Use Cases

### Separate Free/Paid Accounts

```bash
# Free tier for search (15 RPM limit)
WEB_SEARCH_API_KEY=free_tier_key

# Paid tier for main bot (higher limits)
GEMINI_API_KEY=paid_tier_key
```

### Cost-Optimized Setup

```bash
# Low-cost key for search grounding
WEB_SEARCH_API_KEY=project_a_key

# High-cost key for text/image generation
GEMINI_API_KEY=project_b_key
IMAGE_GENERATION_API_KEY=project_c_key
```

## Verification

Check logs on startup:

```bash
# WEB_SEARCH_API_KEY set - will use separate key
INFO - Web search grounding enabled - separate_api_key: true

# WEB_SEARCH_API_KEY not set - will use GEMINI_API_KEY
INFO - Web search grounding enabled - separate_api_key: false
```

Test in your terminal:

```bash
grep "web_search_api_key" app/config.py
# Should show: web_search_api_key: str | None = Field(...)
```

## Backward Compatibility

- Existing deployments without `WEB_SEARCH_API_KEY` continue working
- Falls back to `GEMINI_API_KEY` automatically
- No breaking changes - fully optional feature

## Related Features

- **Image Generation API Key**: See `SEPARATE_IMAGE_API_KEY.md`
- **Free Tier Mode**: See main README for multi-key rotation

## Configuration Reference

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GEMINI_API_KEY` | Yes | - | Main API key for all features |
| `WEB_SEARCH_API_KEY` | No | `GEMINI_API_KEY` | Separate key for web search |
| `IMAGE_GENERATION_API_KEY` | No | `GEMINI_API_KEY` | Separate key for image generation |
| `ENABLE_SEARCH_GROUNDING` | No | `false` | Enable/disable web search feature |
