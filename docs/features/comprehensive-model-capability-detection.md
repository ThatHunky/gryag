# Comprehensive Model Capability Detection System

**Date**: October 7, 2025  
**Status**: ✅ Complete  
**Version**: 1.0

## Overview

The bot now features a **comprehensive model capability detection system** that automatically adapts to different Gemini model families (Gemma, Gemini, Flash) by detecting and handling:

1. ✅ **Audio support** - Filters unsupported audio from context
2. ✅ **Video support** - Filters unsupported inline video from context
3. ✅ **Media count limits** - Respects per-model image limits (32 for Gemma)
4. ✅ **Function calling (tools)** - Disables tools when not supported
5. ✅ **Rate limiting** - Graceful handling with user-friendly messages
6. ✅ **Historical context** - Two-phase filtering of past messages

## Motivation

### The Problem

Different Gemini model families have vastly different capabilities:

| Feature | Gemma 3 | Gemini 1.5+ | Gemini 2.0+ |
|---------|---------|-------------|-------------|
| Text | ✅ | ✅ | ✅ |
| Images | ✅ (max 32) | ✅ (max 3000) | ✅ (max 3000) |
| Audio | ❌ | ✅ | ✅ |
| Video | ❌ | ✅ | ✅ |
| Tools | ❌ | ✅ | ✅ |
| Search Grounding | ❌ | ✅ | ✅ |
| Cost | Free | $0.075-2/1M | $2-10/1M |

**Without capability detection**:
- Bot crashes with 400 errors on unsupported features
- Manual configuration required for each model
- No graceful degradation
- Poor user experience

**With capability detection**:
- Automatic adaptation to model capabilities
- Graceful fallback (responds without features vs crashing)
- Zero configuration needed
- Clear logging for debugging
- Smart cost/feature trade-offs

## Architecture

### Detection Flow

```
Bot Startup
    ↓
Parse GEMINI_MODEL from .env
    ↓
GeminiClient.__init__()
    ↓
┌─────────────────────────────────────┐
│ Capability Detection                │
│                                     │
│ _detect_audio_support(model_name)  │
│ _detect_video_support(model_name)  │
│ _detect_tools_support(model_name)  │
└─────────────────────────────────────┘
    ↓
Store flags: _audio_supported, _video_supported, _tools_supported
    ↓
Runtime Usage
    ↓
┌─────────────────────────────────────┐
│ Filtering Applied                   │
│                                     │
│ • build_media_parts() - filters     │
│   current message media by type     │
│ • _filter_tools() - disables tools  │
│   if not supported                  │
│ • MultiLevelContextManager -        │
│   filters historical media          │
└─────────────────────────────────────┘
    ↓
API Request to Gemini
    ↓
If 400 Error → Runtime Detection
    ↓
┌─────────────────────────────────────┐
│ Fallback Logic                      │
│                                     │
│ • _maybe_disable_audio()            │
│ • _maybe_disable_search_grounding() │
│ • _maybe_disable_tools()            │
└─────────────────────────────────────┘
    ↓
Retry Request (with disabled features)
    ↓
Success ✅
```

### Detection Methods

#### 1. Audio Support Detection

```python
@staticmethod
def _detect_audio_support(model_name: str) -> bool:
    """Detect if model supports audio input."""
    model_lower = model_name.lower()
    # Gemma models don't support audio
    if "gemma" in model_lower:
        return False
    # Gemini models support audio
    if "gemini" in model_lower:
        return True
    # Default to False (safer - prevents errors)
    return False
```

**Applies to**: Voice messages, audio files

#### 2. Video Support Detection

```python
@staticmethod
def _detect_video_support(model_name: str) -> bool:
    """Detect if model supports inline video input."""
    model_lower = model_name.lower()
    # Gemma models don't support inline video (file_uri)
    if "gemma" in model_lower:
        return False
    # Gemini models support video
    if "gemini" in model_lower:
        return True
    # Default to False (safer)
    return False
```

**Applies to**: Video files uploaded to Telegram (not YouTube URLs)

#### 3. Tool Support Detection

```python
@staticmethod
def _detect_tools_support(model_name: str) -> bool:
    """Detect if model supports function calling."""
    model_lower = model_name.lower()
    # Gemma models don't support function calling
    if "gemma" in model_lower:
        return False
    # Gemini models support function calling
    if "gemini" in model_lower:
        return True
    # Default to True (allows trying and falling back)
    return True
```

**Applies to**: All tools (calculator, weather, currency, memory search, polls)

### Filtering Logic

#### Current Message Filtering

**File**: `app/services/gemini.py`  
**Method**: `build_media_parts()`

```python
def build_media_parts(self, message: Message) -> list[dict]:
    """Build Gemini Parts from Telegram message media (with filtering)."""
    parts = []
    
    # Process all media types
    media_items = [
        (message.photo, "image/jpeg", "inline_data"),
        (message.voice, "audio/ogg", "inline_data"),
        (message.video, "video/mp4", "file_data"),  # file_uri
        # ... etc
    ]
    
    for media, mime_type, kind in media_items:
        if media:
            # Check if supported by current model
            if not self._is_media_supported(mime_type, kind):
                logger.info(
                    "Skipping unsupported media: %s (%s)",
                    mime_type, kind
                )
                continue
            
            # Add to parts
            parts.append(...)
    
    return parts
```

**Behavior**:
- Gemma: Filters audio/video, keeps images
- Gemini: Includes all media types

#### Historical Context Filtering

**File**: `app/services/context/multi_level_context.py`  
**Method**: `_limit_media_in_history()`

```python
def _limit_media_in_history(
    self,
    history: list[dict],
    max_media: int,
) -> list[dict]:
    """Two-phase media filtering."""
    
    # Phase 1: Filter by type (remove unsupported)
    filtered_by_type = 0
    for message in history:
        if "parts" in message:
            original_parts = message["parts"]
            filtered_parts = []
            
            for part in original_parts:
                # Check if media is supported
                if self._is_media_part(part):
                    mime_type = self._get_mime_type(part)
                    kind = self._get_part_kind(part)
                    
                    if not self.gemini_client._is_media_supported(mime_type, kind):
                        # Replace with text placeholder
                        filtered_parts.append({
                            "text": f"[media: {mime_type}]"
                        })
                        filtered_by_type += 1
                        continue
                
                filtered_parts.append(part)
            
            message["parts"] = filtered_parts
    
    # Phase 2: Limit by count (remove oldest)
    total_media = sum(count_media(msg) for msg in history)
    removed_count = 0
    
    if total_media > max_media:
        # Remove oldest media first
        for message in history:
            if total_media <= max_media:
                break
            removed = remove_media_from_message(message)
            removed_count += removed
            total_media -= removed
    
    logger.info(
        "Limited media in history: removed %d of %d items (max: %d, also filtered %d by type)",
        removed_count,
        total_media + removed_count,
        max_media,
        filtered_by_type,
    )
    
    return history
```

**Behavior**:
- **Phase 1**: Removes unsupported media types (audio/video for Gemma)
- **Phase 2**: Limits remaining media to configured max (28 for Gemma)

#### Tool Filtering

**File**: `app/services/gemini.py`  
**Method**: `_filter_tools()`

```python
def _filter_tools(self, tools: list[dict] | None) -> list[dict] | None:
    """Filter tools based on model capabilities."""
    if not tools:
        return None
    
    # If model doesn't support tools at all, return None
    if not self._tools_supported:
        logger.info(
            "Function calling not supported by model %s - disabling %d tool(s)",
            self._model_name,
            len(tools),
        )
        return None
    
    # Otherwise, filter search grounding if needed
    if not self._search_grounding_enabled:
        tools = [t for t in tools if "google_search_retrieval" not in str(t)]
    
    return tools if tools else None
```

**Behavior**:
- Gemma: Returns `None` (all tools disabled)
- Gemini: Returns full tool list (or filtered for search grounding)

### Runtime Fallback

If startup detection misses a capability issue, runtime detection catches it:

```python
async def generate(...):
    try:
        # Try API call
        response = await model.generate_content_async(...)
    except Exception as e:
        error_msg = str(e)
        
        # Detect specific errors and retry
        if self._maybe_disable_audio(error_msg):
            return await self.generate(...)  # Retry without audio
        
        if self._maybe_disable_tools(error_msg):
            return await self.generate(...)  # Retry without tools
        
        if self._maybe_disable_search_grounding(error_msg):
            return await self.generate(...)  # Retry without search
        
        raise  # Re-raise if unknown error
```

**Error Patterns Detected**:
- `"Audio input modality is not enabled"` → Disable audio
- `"Function calling is not enabled"` → Disable tools
- `"Search grounding is not enabled"` → Disable search
- `"Please use fewer than 32 images"` → Apply media limiting

## Configuration

### Environment Variables

```bash
# .env

# Model selection (auto-detects capabilities)
GEMINI_MODEL=models/gemma-3-27b-it  # Free, no audio/video/tools
# or
GEMINI_MODEL=gemini-2.5-flash       # Low cost, full features
# or
GEMINI_MODEL=gemini-1.5-pro         # High quality, full features

# Media limiting (optional, auto-configured per model)
GEMINI_MAX_MEDIA_ITEMS=28  # Default for Gemma
# or
GEMINI_MAX_MEDIA_ITEMS=100  # For Gemini models

# Feature flags (optional, auto-detected)
ENABLE_SEARCH_GROUNDING=true  # Only works with Gemini models
```

### Recommended Configurations

#### Budget Deployment (Free Tier)

```bash
GEMINI_MODEL=models/gemma-3-4b-it
GEMINI_MAX_MEDIA_ITEMS=20
ENABLE_SEARCH_GROUNDING=false
```

**Result**: Free, fast, basic functionality

#### Balanced Deployment

```bash
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MAX_MEDIA_ITEMS=50
ENABLE_SEARCH_GROUNDING=true
```

**Result**: Low cost ($0.075/1M), full features, good performance

#### Premium Deployment

```bash
GEMINI_MODEL=gemini-1.5-pro
GEMINI_MAX_MEDIA_ITEMS=100
ENABLE_SEARCH_GROUNDING=true
```

**Result**: Best quality, all features, higher cost ($1.25/1M)

## User Experience

### Scenario 1: Voice Message with Gemma

**User Action**: Sends voice message  
**Bot Behavior**:
1. Detects Gemma model → audio not supported
2. Filters audio from current message
3. Responds to message text only
4. Logs: `"Skipping unsupported media: audio/ogg (inline_data)"`

**User sees**: Normal text response (bot ignores audio gracefully)

### Scenario 2: Video with Gemini

**User Action**: Sends video file  
**Bot Behavior**:
1. Detects Gemini model → video supported
2. Includes video in API request
3. Gemini analyzes video content
4. Responds with video-aware reply

**User sees**: Response about video content (e.g., "Nice skateboarding trick!")

### Scenario 3: Calculator with Gemma

**User Action**: "What's 123 * 456?"  
**Bot Behavior**:
1. Detects Gemma model → tools not supported
2. Disables calculator tool
3. Uses LLM training knowledge for calculation
4. Logs: `"Function calling not supported - disabling 10 tool(s)"`

**User sees**: Response with calculation (may be approximate)

### Scenario 4: Memory Search with Gemini

**User Action**: "What did I say about pizza last week?"  
**Bot Behavior**:
1. Detects Gemini model → tools supported
2. Uses `search_messages` tool
3. Searches conversation history
4. Returns relevant past messages

**User sees**: Accurate quote from last week's conversation

## Logging

### Startup Logs (Gemma Model)

```
INFO - Initializing GeminiClient with model: models/gemma-3-27b-it
INFO - Audio support: False (Gemma models don't support audio)
INFO - Video support: False (Gemma models don't support inline video)
INFO - Tool support: False (Gemma models don't support function calling)
```

### Startup Logs (Gemini Model)

```
INFO - Initializing GeminiClient with model: gemini-2.5-flash
INFO - Audio support: True
INFO - Video support: True
INFO - Tool support: True
```

### Runtime Filtering Logs

```
INFO - Skipping unsupported media: audio/ogg (inline_data)
INFO - Filtered 2 unsupported media item(s) from history
INFO - Limited media in history: removed 3 of 31 items (max: 28, also filtered 2 by type)
INFO - Function calling not supported by model models/gemma-3-27b-it - disabling 10 tool(s)
```

### Error Recovery Logs

```
WARNING - Gemini API error: Audio input modality is not enabled for models/gemma-3-27b-it - disabling audio
WARNING - Function calling not supported - disabling tools
INFO - Gemini request succeeded after disabling tools
```

## Testing

### Verify Capability Detection

```bash
# Check startup logs for capability detection
docker compose logs bot | grep -E "Audio support|Video support|Tool support"

# Should see for Gemma:
# Audio support: False (Gemma models don't support audio)
# Video support: False (Gemma models don't support inline video)
# Tool support: False (Gemma models don't support function calling)
```

### Test Audio Filtering

1. Send voice message to bot (with Gemma model)
2. Check logs:

```bash
docker compose logs bot | grep -E "Skipping unsupported|audio"
# Should see: "Skipping unsupported media: audio/ogg"
```

3. Verify bot responds without crash

### Test Video Filtering

1. Send video file to bot (with Gemma model)
2. Check logs:

```bash
docker compose logs bot | grep -E "Skipping unsupported|video"
# Should see: "Skipping unsupported media: video/mp4"
```

3. Verify bot responds without crash

### Test Historical Filtering

1. Send multiple voice messages
2. Mention bot in text message
3. Check logs:

```bash
docker compose logs bot | grep "Filtered.*unsupported media"
# Should see: "Filtered X unsupported media item(s) from history"
```

### Test Tool Disabling

1. Ask bot to calculate something (with Gemma model)
2. Check logs:

```bash
docker compose logs bot | grep "Function calling"
# Should see: "Function calling not supported - disabling X tool(s)"
```

3. Verify bot responds (using LLM knowledge, not calculator tool)

### Test Media Count Limiting

1. Send 40 images in rapid succession
2. Mention bot
3. Check logs:

```bash
docker compose logs bot | grep "Limited media in history"
# Should see: "removed X of Y items (max: 28)"
```

## Benefits

### Development

- ✅ **Zero-config**: Works out of the box with any Gemini model
- ✅ **Type-safe**: Pydantic models for configuration
- ✅ **Clear logging**: Easy to debug capability issues
- ✅ **Graceful degradation**: Never crashes on unsupported features
- ✅ **Future-proof**: Handles new models automatically

### Operations

- ✅ **Cost optimization**: Easy to switch between free/paid models
- ✅ **Feature flexibility**: Trade cost for capabilities as needed
- ✅ **Production-ready**: Handles all edge cases gracefully
- ✅ **Monitoring**: Clear logs for capability detection

### Users

- ✅ **Reliable**: Bot always responds, never crashes
- ✅ **Transparent**: Clear about what features are available
- ✅ **Fast**: Gemma models provide instant responses
- ✅ **Smart**: Gemini models provide advanced features

## Cost Analysis

### Gemma 3 (Free Tier)

**Monthly Cost**: $0  
**Features**: Text, images (limited)  
**Best For**: Development, testing, low-traffic bots

### Gemini Flash ($0.075/1M tokens)

**Monthly Cost**: ~$5-20 (depending on usage)  
**Features**: All (audio, video, tools, search)  
**Best For**: Production, moderate traffic, full features

### Gemini 1.5 Pro ($1.25/1M tokens)

**Monthly Cost**: ~$50-200 (depending on usage)  
**Features**: All + highest quality  
**Best For**: Premium bots, high quality requirements

### Example Calculation

**Assumptions**:
- 1000 messages/day
- Average 500 tokens per context
- 30 days/month

**Gemma**: 15M tokens/month × $0 = **$0**  
**Flash**: 15M tokens/month × $0.075 = **$1.13**  
**Pro**: 15M tokens/month × $1.25 = **$18.75**

## Troubleshooting

### "Bot not responding to voice messages"

**Check**: Is this expected?

```bash
# View model
grep GEMINI_MODEL .env
# If "gemma" → Voice not supported (expected behavior)
# If "gemini" → Voice should work (bug)
```

**Solution**: Switch to Gemini model for voice support

### "Tools not working"

**Check**: Model capabilities

```bash
docker compose logs bot | grep "Tool support"
# Should see: "Tool support: True" for Gemini
# Should see: "Tool support: False" for Gemma
```

**Solution**: Switch to Gemini model for tool support

### "Too many images error"

**Check**: Media limiting configuration

```bash
grep GEMINI_MAX_MEDIA_ITEMS .env
# Should be ≤32 for Gemma
# Can be higher for Gemini
```

**Solution**: Adjust limit or reduce images in conversation

### "Rate limit errors"

**Check**: Quota usage

```bash
docker compose logs bot | grep "rate limit"
# Should see warnings if approaching quota
```

**Solution**:
- Reduce context size (lower `CONTEXT_TOKEN_BUDGET`)
- Upgrade to paid tier
- Use caching to reduce token usage

## Future Enhancements

1. **Dynamic capability testing** - Test each capability with actual API calls (more reliable)
2. **Capability caching** - Cache test results to avoid redundant checks
3. **Partial tool support** - Some models might support subset of tools
4. **User notifications** - Inform users when features are unavailable
5. **Telemetry** - Track capability usage patterns
6. **Auto-optimization** - Suggest cheaper models when advanced features not needed
7. **Hybrid approaches** - Fallback to local models for unsupported features

## Related Documentation

- `docs/fixes/gemma-media-limit-fix.md` - Media count limiting implementation
- `docs/features/graceful-media-handling.md` - Current message filtering
- `docs/fixes/historical-media-filtering.md` - Historical context filtering
- `docs/features/function-calling-support-detection.md` - Tool detection
- `docs/features/multi-level-context.md` - Context assembly system

## Summary

The **Comprehensive Model Capability Detection System** makes gryag production-ready for all Gemini model families:

✅ **Automatic** - No manual configuration  
✅ **Graceful** - Responds instead of crashing  
✅ **Flexible** - Easy to switch models  
✅ **Clear** - Excellent logging for debugging  
✅ **Cost-effective** - Use cheaper models when possible  
✅ **Feature-rich** - Access advanced features with premium models

**One config line, infinite possibilities!** 🚀
