# Google Search Grounding - SDK Compatibility Investigation

**Date**: 2025-10-08  
**Status**: ⚠️ Reverted - SDK Incompatibility Discovered  
**Type**: Investigation & Rollback

## Summary

Attempted to update Google Search Grounding from `google_search_retrieval` to modern `google_search` format, but discovered that the bot uses the **legacy `google.generativeai` SDK (0.8.x)** which doesn't support the modern format. Reverted to working configuration.

## Investigation

### Initial Assumption (Incorrect)
- Assumed we could use `google_search` format with Gemini 2.5 models
- Based on latest Google AI documentation showing modern API

### Reality Discovered
The bot uses **`google.generativeai` SDK (0.8.x)** which:
- Only supports `google_search_retrieval` format
- Does not recognize `google_search` as a valid tool type
- Would require upgrading to new `google-genai` SDK for modern format

### Error Encountered

```
ValueError: Unknown field for FunctionDeclaration: google_search
```

**Root Cause**: The SDK tried to parse `{"google_search": {}}` as a FunctionDeclaration, which failed because `google_search` is not a valid field in the legacy SDK.

## Current Working Configuration

**Format**: `google_search_retrieval` (legacy, but compatible with our SDK)

```python
if settings.enable_search_grounding:
    retrieval_tool: dict[str, Any] = {
        "google_search_retrieval": {
            "dynamic_retrieval_config": {
                "mode": "MODE_DYNAMIC",
                "dynamic_threshold": 0.5,
            }
        }
    }
    tool_definitions.append(retrieval_tool)
```

**Why This Works**:
- Compatible with `google.generativeai` SDK 0.8.x
- Properly recognized by the SDK's tool parser
- Works with Gemini 2.5 models despite being "legacy" format
- Same 500 req/day Free tier limit

## SDK Versions

**Current**: `google-generativeai` (legacy SDK)
- Package: `google-generativeai` 
- Format: `google_search_retrieval` with `dynamic_retrieval_config`
- Status: ✅ Working

**Modern**: `google-genai` (new SDK)  
- Package: `google-genai`
- Format: `google_search` with simplified config
- Status: ❌ Not installed

## Future Path Forward

To use the modern `google_search` format, we would need to:

1. **Upgrade SDK**: Replace `google-generativeai` with `google-genai`
2. **Update requirements.txt**: Change package dependency
3. **Refactor GeminiClient**: Update to use new SDK API
4. **Test thoroughly**: New SDK has different APIs and behavior

**Recommendation**: Keep current setup. The legacy format works fine with Gemini 2.5 models.

## Rollback Performed
