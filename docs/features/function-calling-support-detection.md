# Function Calling Support Detection

**Date:** October 7, 2025  
**Issue:** `400 Function calling is not enabled for models/gemma-3-27b-it`

## Problem

The bot was trying to use tools (function calling) with Gemma models, which don't support this feature. This caused crashes when tools were provided in the API request.

### Error Message

```
google.api_core.exceptions.InvalidArgument: 400 Function calling is not enabled for models/gemma-3-27b-it
```

### Affected Tools

- `search_messages` - Semantic search in conversation history
- `calculator` - Math calculations
- `weather` - Weather information
- `currency` - Currency conversion
- `polls` - Poll creation
- `remember_fact`, `recall_facts`, etc. - Memory tools

## Root Cause

Gemma models (all variants: 1B, 4B, 12B, 27B) do not support function calling/tools. Only Gemini models (1.5+, 2.0+, Flash) support this feature.

The bot was always providing tools to the API regardless of model capabilities, causing errors for Gemma users.

## Solution

### 1. Tool Support Detection

Added automatic detection in `GeminiClient.__init__()`:

```python
self._tools_supported = self._detect_tools_support(model)
```

**Detection logic:**
```python
@staticmethod
def _detect_tools_support(model_name: str) -> bool:
    model_lower = model_name.lower()
    # Gemma models don't support function calling
    if "gemma" in model_lower:
        return False
    # Gemini models support function calling
    if "gemini" in model_lower:
        return True
    # Default to True (safer to try and fallback)
    return True
```

### 2. Tool Filtering

Enhanced `_filter_tools()` to disable all tools when not supported:

```python
def _filter_tools(self, tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    
    # If model doesn't support tools at all, return None
    if not self._tools_supported:
        if tools:
            logger.info(
                "Function calling not supported by model %s - disabling %d tool(s)",
                model_name, len(tools)
            )
        return None
    
    # Otherwise, filter search grounding if needed
    # ...
```

### 3. Runtime Fallback

Added `_maybe_disable_tools()` method for runtime detection:

```python
def _maybe_disable_tools(self, error_message: str) -> bool:
    if "Function calling is not enabled" in error_message:
        self._tools_supported = False
        logger.warning("Function calling not supported - disabling tools")
        return True
    return False
```

### 4. Automatic Retry

When function calling error is detected:
1. Disable tools (`filtered_tools = None`)
2. Retry API call without tools
3. Bot responds successfully (without tool functionality)

## Implementation Details

### Files Modified

1. **`app/services/gemini.py`** (+60 lines)
   - Added `_tools_supported` flag to `__init__()`
   - Added `_detect_tools_support()` static method
   - Enhanced `_filter_tools()` to check tool support
   - Added `_maybe_disable_tools()` for runtime detection
   - Updated exception handling to disable and retry

### Capability Detection Summary

| Capability | Detection Method | Gemma | Gemini |
|-----------|------------------|-------|--------|
| Audio | `_detect_audio_support()` | ❌ | ✅ |
| Video | `_detect_video_support()` | ❌ | ✅ |
| **Tools** | **`_detect_tools_support()`** | **❌** | **✅** |
| Images | (always supported) | ✅ | ✅ |

### Logging

**On Startup (Gemma model)**:
```
INFO - Function calling not supported by model models/gemma-3-27b-it - disabling 10 tool(s)
```

**On Runtime Detection**:
```
WARNING - Function calling not supported by model models/gemma-3-27b-it - disabling tools
```

**On Retry Success**:
```
INFO - Gemini request succeeded after disabling tools
```

## User Experience

### Before (With Tools Error)

```
User: @bot calculate 2+2
Bot: 💥 ERROR 400: Function calling is not enabled for models/gemma-3-27b-it
```

### After (Graceful Fallback)

```
User: @bot calculate 2+2
Bot: ✅ "Два плюс два дорівнює чотири" (responds without using calculator tool)
Logs: "Function calling not supported - disabling 10 tool(s)"
```

### Trade-offs

**With Gemma (no tools)**:
- ❌ No semantic search in history
- ❌ No calculator for complex math
- ❌ No weather/currency lookups
- ❌ No memory tools (remember/recall facts)
- ✅ Still responds to questions (uses training knowledge)
- ✅ Much cheaper API costs
- ✅ Faster response times

**With Gemini (full tools)**:
- ✅ All tool functionality available
- ✅ Can search conversation history
- ✅ Can perform calculations, lookups
- ✅ Can use memory system
- ❌ Higher API costs
- ❌ Slightly slower responses

## Configuration

### Switch to Gemini for Full Tools

```bash
# In .env
GEMINI_MODEL=gemini-2.5-flash  # Full tool support
# or
GEMINI_MODEL=gemini-1.5-pro    # Full tool support
```

### Keep Gemma for Cost Savings

```bash
# In .env
GEMINI_MODEL=models/gemma-3-27b-it  # No tools, cheaper
# or
GEMINI_MODEL=models/gemma-3-4b-it   # No tools, even cheaper
```

### No Configuration Needed

The system **automatically detects** and adapts based on the model name. No manual configuration required!

## Model Comparison

| Model | Tools | Audio | Video | Cost/1M tokens | Speed |
|-------|-------|-------|-------|----------------|-------|
| Gemma 3 1B | ❌ | ❌ | ❌ | Free | ⚡⚡⚡ |
| Gemma 3 4B | ❌ | ❌ | ❌ | Free | ⚡⚡ |
| Gemma 3 27B | ❌ | ❌ | ❌ | Free | ⚡ |
| Gemini Flash | ✅ | ✅ | ✅ | $0.075 | ⚡⚡ |
| Gemini 1.5 Pro | ✅ | ✅ | ✅ | $1.25 | ⚡ |
| Gemini 2.0 | ✅ | ✅ | ✅ | $2.00 | ⚡ |

## Verification

### Test Tool Support Detection

```bash
# Check logs during bot startup
docker compose logs bot | grep -E "Function calling|tool"

# Should see for Gemma:
# "Function calling not supported by model models/gemma-3-27b-it - disabling 10 tool(s)"

# Should see nothing for Gemini (tools silently enabled)
```

### Test Graceful Fallback

```bash
# 1. Send message that would trigger tool use
# 2. Check logs
docker compose logs bot | grep -A5 "Function calling"

# Should see:
# WARNING - Function calling not supported - disabling tools
# (Bot still responds, just without tool functionality)
```

### Test with Gemini Model

```bash
# Change .env to use Gemini
GEMINI_MODEL=gemini-2.5-flash

# Restart
docker compose restart bot

# Check logs - should NOT see tool disabling messages
docker compose logs bot | grep "Function calling"
```

## Benefits

### Before
- ❌ Bot crashes with function calling errors
- ❌ Gemma models unusable with default config
- ❌ Manual configuration required
- ❌ No graceful degradation

### After
- ✅ Works with all Gemini model families
- ✅ Automatic capability detection
- ✅ Graceful fallback (responds without tools)
- ✅ Clear logging for debugging
- ✅ No manual configuration needed
- ✅ Smart model selection (cost vs features)

## Related Capabilities

This completes the **model capability detection system**:

1. ✅ **Audio support** - Filters audio for Gemma
2. ✅ **Video support** - Filters inline video for Gemma  
3. ✅ **Media count limiting** - Limits to 28 items for Gemma
4. ✅ **Tool support** - Disables tools for Gemma
5. ✅ **Historical media filtering** - Cleans unsupported media from context
6. ✅ **Rate limit handling** - Clear warnings for quota issues

## Future Enhancements

1. **Tool-specific fallbacks** - Use LLM for simple calculations when calculator tool unavailable
2. **Hybrid approach** - Some models might support subset of tools
3. **Dynamic tool selection** - Choose tools based on model capabilities
4. **User notifications** - Inform users when tools are unavailable
5. **Telemetry** - Track tool usage patterns per model
6. **Cost optimization** - Suggest cheaper models when tools not needed

## Troubleshooting

### "Still getting function calling errors"

**Check**: Is detection working?
```bash
# Look for this log line
docker compose logs bot | grep "Function calling not supported"
```

**Check**: Is retry logic working?
```bash
# Should NOT see errors after warning
docker compose logs bot | grep -A10 "Function calling"
```

### "Bot not using tools"

**Check**: Which model are you using?
```bash
# In .env
echo $GEMINI_MODEL
# If contains "gemma" → No tool support
# If contains "gemini" → Full tool support
```

**Solution**: Switch to Gemini model for tool support

### "Want tools without high costs"

**Solution**: Use Gemini Flash (cheapest Gemini model with tools)
```bash
# In .env
GEMINI_MODEL=gemini-2.5-flash  # $0.075/1M tokens, all features
```

## Notes

- Tool disabling is **permanent for the session** (until bot restart)
- Detection happens at **startup** (checks model name)
- Runtime detection is **fallback only** (if startup detection missed)
- Works with **all current and future** Gemma/Gemini models
- **Backward compatible** - existing configs continue to work
- Tools are **all-or-nothing** for a model (no partial support yet)

## Testing Checklist

- [x] Bot starts without errors
- [x] Gemma models detected (tools disabled)
- [ ] Gemini models detected (tools enabled)
- [ ] Function calling error triggers fallback
- [ ] Bot responds successfully after fallback
- [ ] Tools work with Gemini models
- [ ] Tools properly disabled with Gemma
- [ ] Logs show capability detection

## Example Use Cases

### Use Case 1: Cost-Conscious Deployment

```bash
# .env
GEMINI_MODEL=models/gemma-3-4b-it  # Free, no tools
```

**Result**: Bot works, no API costs, basic functionality

### Use Case 2: Full-Featured Deployment

```bash
# .env
GEMINI_MODEL=gemini-2.5-flash  # Low cost, full tools
```

**Result**: Bot works, all tools available, reasonable costs

### Use Case 3: High-Performance Deployment

```bash
# .env
GEMINI_MODEL=gemini-2.0-flash-exp  # Latest, fastest
```

**Result**: Bot works, all tools, cutting-edge features

The system adapts automatically to each scenario! 🎉
