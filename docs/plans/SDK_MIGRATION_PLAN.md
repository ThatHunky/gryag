# SDK Migration Plan: google-generativeai → google-genai

**Date**: 2025-10-08  
**Status**: 🚧 In Progress  
**Type**: Major SDK Upgrade

## Goal

Migrate from legacy `google-generativeai` (0.8.x) to modern `google-genai` (0.2+) to enable modern `google_search` tool format and future SDK features.

## Why Migrate

1. **Modern API**: `google_search` tool is simpler and recommended for all new development
2. **Better Support**: New SDK is the future direction from Google
3. **Cleaner Code**: More Pythonic API design
4. **Future-Proof**: Legacy SDK will eventually be deprecated

## API Differences

### Old SDK (`google-generativeai` 0.8.x)

```python
import google.generativeai as genai

genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.5-flash")

response = await model.generate_content_async(
    contents=history,
    tools=tools,
    system_instruction=system_prompt,
    safety_settings=safety_settings
)

text = response.text
```

### New SDK (`google-genai` 0.2+)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

config = types.GenerateContentConfig(
    tools=[types.Tool(google_search=types.GoogleSearch())],
    system_instruction=system_prompt,
    safety_settings=safety_settings
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=contents,
    config=config
)

text = response.text
```

## Migration Steps

### 1. Update Dependencies ✅

- [x] Changed `requirements.txt`: `google-generativeai>=0.8` → `google-genai>=0.2.0`

### 2. Refactor GeminiClient

**Files to Update**:
- `app/services/gemini.py` - Main client class

**Changes Needed**:
1. Change import: `import google.generativeai as genai` → `from google import genai`
2. Add types import: `from google.genai import types`
3. Replace `genai.configure()` + `GenerativeModel()` with `genai.Client()`
4. Update `_invoke_model()` to use new API
5. Update tool format handling
6. Update safety settings format
7. Update embedding API calls

### 3. Update Tool Definitions ✅

- [x] Changed `app/handlers/chat.py`: Modern `{"google_search": {}}` format

### 4. Update Type Handling

**Safety Settings**:
- Old: `HarmCategory`, `HarmBlockThreshold` from `google.generativeai.types`
- New: `types.HarmCategory`, `types.HarmBlockThreshold` from `google.genai.types`

**Content Format**:
- Old: Dict-based content with `{"role": ..., "parts": [...]}`
- New: May need `types.Content()` objects

### 5. Update Embedding Calls

**Old**:
```python
result = genai.embed_content(
    model=embed_model,
    content=text
)
return result['embedding']
```

**New**:
```python
result = client.models.embed_content(
    model=embed_model,
    content=text
)
return result.embedding
```

### 6. Testing Strategy

1. **Unit Tests**: Update mocks for new SDK
2. **Integration Tests**: Test with real API
3. **Backwards Compatibility**: Ensure no breaking changes for users

### 7. Rollback Plan

If migration fails:
1. Revert `requirements.txt` to `google-generativeai>=0.8`
2. Revert `app/services/gemini.py` changes
3. Revert `app/handlers/chat.py` to use `google_search_retrieval`
4. Document issues for future attempt

## Implementation Timeline

- **Phase 1** (30 min): Refactor core GeminiClient methods
- **Phase 2** (15 min): Update tool handling and safety settings
- **Phase 3** (15 min): Test and fix issues
- **Phase 4** (10 min): Update documentation

**Total Estimate**: ~70 minutes

## Breaking Changes for Users

**None** - This is an internal SDK change. All external APIs remain the same.

## Benefits After Migration

1. ✅ Modern `google_search` tool (simpler config)
2. ✅ Better error messages from new SDK
3. ✅ Future-proof codebase
4. ✅ Alignment with Google's recommended approach
5. ✅ Potential performance improvements

## Risks

1. **API Incompatibility**: New SDK might have subtle behavior differences
2. **Test Coverage**: Need to ensure all features still work
3. **Production Impact**: Requires thorough testing before deployment

## Next Steps

1. Create `app/services/gemini_v2.py` with new SDK implementation
2. Test new implementation in parallel
3. Switch over when validated
4. Remove old implementation
5. Update all documentation

---

**Status**: Ready to implement. Waiting for confirmation to proceed.
