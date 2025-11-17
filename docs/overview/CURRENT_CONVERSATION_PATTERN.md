# CURRENT_CONVERSATION_PATTERN

This document describes the canonical message flow and formatting for conversations processed by the gryag bot as sent to Google Gemini API.

---

## Native Gemini Format (Current)

**Status**: Active (January 2025)

The bot now uses the native Gemini API format with all metadata moved to structured markdown system instructions. This provides the cleanest, most native format for Gemini while maintaining all necessary context.

### Format Structure

**History**: Clean native format - only `role` and `parts` with text/media, no metadata blocks:
```json
[
  {
    "role": "user",
    "parts": [
      {"text": "Як справи, гряг?"}
    ]
  },
  {
    "role": "model",
    "parts": [
      {"text": "Не набридай."}
    ]
  },
  {
    "role": "user",
    "parts": [
      {"text": "А що тут відбувається?"}
    ]
  }
]
```

**System Instruction**: Comprehensive markdown with all context:
```markdown
# Persona
[Persona content from ukrainian_gryag.txt]

# Current Time
The current time is: Monday, January 15, 2025 at 14:30:00

## Current User
**Name**: Alice
**User ID**: 987654321
**Username**: @alice_ua

## Reply Context
**Replying to**: Bob (ID: 111222333)
**Original message**: Привіт, як справи?

# Memories about Alice (ID: 987654321)
- User is from Kyiv
- Works as a software developer
- Likes coffee

## User Profile
[User profile summary]

## Key Facts
- Location: Kyiv
- Occupation: Software Developer

## Relevant Past Context
- [Relevance: 0.82] Previous conversation about...
- [Relevance: 0.75] Mentioned that...

## Memorable Events
- **Topic**: First meeting
- **Summary**: User introduced themselves...
```

### Key Design Decisions

1. **No Metadata Blocks**: History messages contain only `role` and `parts` (text/media) - no `[meta]` blocks
2. **System Instruction Contains All Context**: User metadata, reply context, memories, and multi-level context are all in the system instruction as markdown
3. **Native Media**: Media is sent as native `inline_data`/`file_data` parts in history and current message
4. **Reply Context**: Included in system instruction, not in message text or history

### Message Object
Each message in history is a dictionary with:
- **`role`**: Either `"user"` (human messages) or `"model"` (gryag's responses)
- **`parts`**: Array of content parts (text, media) - **no metadata blocks**

### Parts Array
The `parts` array contains only:
1. **Text content** (if present):
   ```json
   {"text": "User's actual message text"}
   ```

2. **Media parts** (if present):
   ```json
   {"inline_data": {"mime_type": "image/jpeg", "data": "base64..."}}
   ```
   or
   ```json
   {"file_data": {"file_uri": "https://generativelanguage.googleapis.com/v1beta/files/..."}}
   ```

### Role Assignment
- **`"user"`**: All human messages
- **`"model"`**: All gryag bot responses
- **`"tool"`**: Function call responses (search, calculator, weather, etc.)

### System Instruction Structure
The system instruction is sent via the `system_instruction` parameter and contains:
1. **Persona**: Base system prompt from `ukrainian_gryag.txt`
2. **Current Time**: Timestamp in Kyiv timezone
3. **Current User**: Name, ID, username of message sender
4. **Reply Context**: If replying, includes replied-to user and excerpt
5. **User Memories**: Automatically loaded memories about the current user
6. **Multi-Level Context**: 
   - User Profile and Key Facts
   - Relevant Past Context (hybrid search results)
   - Memorable Events (episodic memory)

#### System Context Block (optional)
- Enabled with `ENABLE_SYSTEM_CONTEXT_BLOCK=true`.
- Adds a fenced monospace block to the system instruction containing the last `SYSTEM_CONTEXT_BLOCK_MAX_MESSAGES` messages (chronological order).
- Only the trigger message (current user turn) and its reply target display media markers such as `[Image]`, `[Video]`, `[Audio]`, `[YouTube]`, `[Document]`; all other lines remain text-only.
- The trigger line ends with `[REPLY TO THIS]`, and the block concludes with `[RESPOND]` to cue Gemini.
- When active, the payload’s `history` array is cleared—context is provided by the block plus the current `user_parts` (which still carry trigger/reply attachments).
- Metadata within the block mirrors `format_metadata()` output unless `SYSTEM_CONTEXT_BLOCK_INCLUDE_META=false`.

---

## Code References

### Message Assembly
- **`app/services/context/multi_level_context.py`**: `format_for_gemini_native()` - Formats context in native Gemini format
- **`app/handlers/chat.py`**: `_build_native_system_instruction()` - Builds comprehensive system instruction with all context
- **`app/handlers/chat.py`**: `_build_message_context()` - Main context building logic using native format
- **`app/services/gemini.py`**: `generate()` - Assembles final payload for Gemini API

### Context Layers (Multi-Level Context)
When `ENABLE_MULTI_LEVEL_CONTEXT=true`:
- **`app/services/context/multi_level_context.py`**: `format_for_gemini_native()` assembles 5 context layers
  - **Immediate** (last 5 messages) + **Recent** (last 30 messages) → `history` array (clean native format, no metadata blocks)
  - **Relevant** (hybrid search) + **Background** (user profile) + **Episodic** (past episodes) → `system_context` markdown string

### Media Handling
- Images, videos, audio sent as `inline_data` (base64) or `file_uri` (uploaded files)
- Media parts interleaved with text in `parts` array
- See `app/services/gemini.py`: `build_media_parts()`

---

## Example with Media

```json
{
  "role": "user",
  "parts": [
    {"text": "[meta] chat_id=-123 user_id=456 name=\"Alice\""},
    {"text": "Подивись на це фото"},
    {"inline_data": {"mime_type": "image/jpeg", "data": "/9j/4AAQ..."}}
  ]
}
```

---

## Tools/Function Calling

When tools are used (search, calculator, weather, etc.):

```json
[
  {
    "role": "user",
    "parts": [{"text": "Скільки буде 15 * 23?"}]
  },
  {
    "role": "model",
    "parts": [
      {"function_call": {"name": "calculator", "args": {"expression": "15 * 23"}}}
    ]
  },
  {
    "role": "tool",
    "parts": [
      {"function_response": {"name": "calculator", "response": {"result": 345}}}
    ]
  },
  {
    "role": "model",
    "parts": [{"text": "345."}]
  }
]
```

---

## Metadata Cleaning

**Critical**: The `[meta]` blocks are **stripped from bot responses** before sending to users:
- `_clean_response_text()` in `app/handlers/chat.py` removes all metadata
- Users never see technical IDs or internal formatting
- Metadata is only for Gemini's context understanding

---

## Verification

To see the actual format sent to Gemini:
```bash
# Enable debug logging
export LOGLEVEL=DEBUG
python -m app.main

# Look for logs like:
# "Using multi-level context for Gemini" with history_length, system_context_length
```

Or inspect the database:
```bash
sqlite3 gryag.db
SELECT role, text, media FROM messages ORDER BY id DESC LIMIT 10;
```

---

## Legacy Formats (Deprecated)

### Compact Plain Text Format (Deprecated)

**Status**: Deprecated (January 2025)

The compact format used custom syntax like `Alice#987654: message` but has been replaced by native format for better model understanding.

### Legacy JSON Format with Metadata Blocks (Deprecated)

**Status**: Deprecated (January 2025)

The legacy format included `[meta]` blocks in every message part. This has been replaced by native format with metadata in system instructions.

### Implementation Plan

See `docs/plans/TODO_CONVO_PATTERN.md` for full 6-phase implementation plan.

---

## Update Instructions

If the conversation pattern changes:
1. Update this file with new format examples
2. Update `.github/copilot-instructions.md` to reference changes
3. Update `AGENTS.md` to reference changes
4. Update relevant code in `app/services/gemini.py` or `app/handlers/chat.py`
5. Add entry to `docs/CHANGELOG.md`
