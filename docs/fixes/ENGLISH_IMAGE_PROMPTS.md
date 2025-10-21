# English Image Prompts Enhancement

**Date**: October 19, 2025  
**Status**: Implemented  
**Related**: Image generation/editing improvements

## Problem

Image generation models (including Gemini 2.5 Flash Image) work significantly better with English prompts compared to Ukrainian or other languages. Users were requesting images in Ukrainian, and the bot was passing those prompts directly to the image model, resulting in suboptimal results.

## Solution

Updated all image tool definitions to instruct the bot to **always translate user requests to English** when generating or editing images.

### Changes Made

1. **Updated `GENERATE_IMAGE_TOOL_DEFINITION`** in `app/services/image_generation.py`:
   - Changed prompt parameter description from Ukrainian to English
   - Added explicit instruction: "ALWAYS write this prompt in ENGLISH, even if user's request was in Ukrainian - translate their request to English"
   - Tool description (for bot): "ВАЖЛИВО: Завжди пиши prompt АНГЛІЙСЬКОЮ мовою для кращого результату"

2. **Updated `EDIT_IMAGE_TOOL_DEFINITION`** in `app/services/image_generation.py`:
   - Changed prompt parameter description to English
   - Added explicit instruction: "ALWAYS write this prompt in ENGLISH, even if user's request was in Ukrainian - translate their request to English"
   - Tool description (for bot): "ВАЖЛИВО: Завжди пиши prompt АНГЛІЙСЬКОЮ мовою для кращого результату"

3. **Updated system prompt** in `app/persona.py`:
   - Added clear rule: "**CRITICAL: Always write the prompt in ENGLISH** for best results, even if user asks in Ukrainian - translate their request"
   - Added to tool usage rules: "For both image tools: **ALWAYS translate user's request to ENGLISH** when writing the prompt parameter - English works significantly better with image models"

## Examples

User request in Ukrainian → Bot translates to English for image model:

- "намалюй кота" → "photorealistic photo of a cat"
- "прибери напис з картинки" → "remove text from image"
- "зміни фон на осінній" → "change background to autumn scenery"
- "зроби в стилі ван гога" → "in the style of Van Gogh"
- "намалюй пейзаж з горами" → "photorealistic landscape photo with mountains"

## Benefits

1. **Better image quality**: English prompts produce significantly more accurate results
2. **More detailed generations**: English descriptions are better understood by the model
3. **Consistent style**: Photorealistic keywords like "photo", "realistic photography" work better in English
4. **No user friction**: Users can still request in Ukrainian - bot handles translation automatically

## Technical Details

The bot (Gemini 2.5 Flash text model) now:
1. Receives user request in Ukrainian
2. Understands the intent
3. Translates to English when calling `generate_image` or `edit_image` tools
4. Passes English prompt to Gemini 2.5 Flash Image model
5. Responds to user in Ukrainian after image is generated

This is handled entirely by the function calling mechanism - no additional translation service needed.

## Files Changed

- `app/services/image_generation.py` - Updated both tool definitions
- `app/persona.py` - Updated system prompt and tool usage rules
- `docs/fixes/IMAGE_EDIT_IMPROVEMENTS.md` - Updated documentation
- `docs/CHANGELOG.md` - Added entry
- `docs/README.md` - Updated recent changes

## Verification

1. **Manual test**: Ask bot in Ukrainian: "гряг намалюй красиву квітку"
2. **Check logs**: Look for the function call to `generate_image` with English prompt
3. **Expected**: Prompt should be translated to something like "beautiful photorealistic flower photo"

Example log output:
```
Function call: generate_image
Args: {"prompt": "photorealistic photo of a beautiful flower, detailed petals, natural lighting, bokeh background", "aspect_ratio": "1:1"}
```

## Notes

- This change doesn't affect user interaction - they can still request in Ukrainian
- The translation quality depends on Gemini 2.5 Flash's translation capabilities
- For complex artistic requests, users can still specify in Ukrainian and bot will translate appropriately
- If user requests in English already, bot passes it through unchanged

## Future Improvements

- [ ] Monitor translation quality and adjust system prompt if needed
- [ ] Consider adding examples of good English prompts in system prompt
- [ ] Track if certain Ukrainian phrases are consistently mistranslated
