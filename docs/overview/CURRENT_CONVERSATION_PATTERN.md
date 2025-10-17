# CURRENT_CONVERSATION_PATTERN

This document describes the canonical message flow and formatting for conversations processed by the gryag bot as sent to Google Gemini API.

---

## Actual Gemini API Format

Messages are sent to Gemini using the official Google Generative AI SDK format with **roles** and **parts**:

```json
[
  {
    "role": "user",
    "parts": [
      {"text": "[meta] chat_id=-123456789 thread_id=12 message_id=456 user_id=987654321 name=\"Alice\" username=\"alice_ua\""},
      {"text": "Як справи, гряг?"}
    ]
  },
  {
    "role": "model",
    "parts": [
      {"text": "[meta] chat_id=-123456789 message_id=457 name=\"gryag\" username=\"gryag_bot\" reply_to_message_id=456"},
      {"text": "Не набридай."}
    ]
  },
  {
    "role": "user",
    "parts": [
      {"text": "[meta] chat_id=-123456789 message_id=458 user_id=111222333 name=\"Bob\" username=\"bob_kyiv\" reply_to_message_id=457"},
      {"text": "А що тут відбувається?"}
    ]
  }
]
```

---

## Pattern Structure

### Message Object
Each message is a dictionary with:
- **`role`**: Either `"user"` (human or bot addressing gryag) or `"model"` (gryag's responses)
- **`parts`**: Array of content parts (text, media, function calls/responses)

### Parts Array
The `parts` array contains ordered content:

1. **Metadata part** (always first):
   ```json
   {"text": "[meta] chat_id=-123 user_id=456 name=\"Alice\" ..."}
   ```
   - Compact key=value format (see `format_metadata()` in `context_store.py`)
   - Contains: `chat_id`, `thread_id`, `message_id`, `user_id`, `name`, `username`
   - For replies: adds `reply_to_message_id`, `reply_to_user_id`, `reply_to_name`, `reply_excerpt`
   - For bot messages: `user_id` is `None`, `name` is `"gryag"`

2. **Text content** (if present):
   ```json
   {"text": "User's actual message text"}
   ```

3. **Media parts** (if present):
   ```json
   {"inline_data": {"mime_type": "image/jpeg", "data": "base64..."}}
   ```
   or
   ```json
   {"file_uri": "https://generativelanguage.googleapis.com/v1beta/files/..."}
   ```

### Role Assignment
- **`"user"`**: All human messages, including when they address gryag
- **`"model"`**: All gryag bot responses
- **`"tool"`**: Function call responses (search, calculator, weather, etc.)

### System Instruction
The system prompt (persona) is sent separately via the `system_instruction` parameter (if supported by model) or prepended as a `"user"` role message in the conversation.

---

## Code References

### Message Assembly
- **`app/services/context_store.py`**: `format_metadata()` - Formats metadata blocks
- **`app/services/context_store.py`**: `recent()` - Retrieves conversation history in Gemini format
- **`app/handlers/chat.py`**: Message handling and user parts construction
- **`app/services/gemini.py`**: `generate()` - Assembles final payload for Gemini API

### Context Layers (Multi-Level Context)
When `ENABLE_MULTI_LEVEL_CONTEXT=true`:
- **`app/services/context/multi_level_context.py`**: `format_for_gemini()` assembles 5 context layers
  - **Immediate** (last 5 messages) + **Recent** (last 30 messages) → `history` array
  - **Relevant** (hybrid search) + **Background** (user profile) + **Episodic** (past episodes) → `system_context` string

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

## Alternative: Compact Plain Text Format (Phase 6)

**Status**: Implemented (October 2025), disabled by default

An alternative compact format is available that reduces token usage by 70-80%:

```text
Alice#987654: Як справи, гряг?
gryag: Не набридай.
Bob#111222 → Alice#987654: А що тут відбувається?
[RESPOND]
```

### Compact Format Features

- **Username#UserID**: Compact identifier (last 6 digits of Telegram user_id)
- **Reply chains**: `Bob#111222 → Alice#987654:` shows reply-to relationships
- **Media**: `[Image]`, `[Video]`, `[Audio]` inline descriptions
- **Bot messages**: `gryag:` (no user ID needed)
- **End marker**: `[RESPOND]` indicates where bot should generate response

### Token Savings

Based on integration tests:
- **JSON format**: ~57 tokens for 3-message conversation
- **Compact format**: ~15 tokens for same conversation
- **Savings**: 73.7% token reduction
- **Tokens per message**: ~6 tokens (vs ~19 in JSON)

### Enabling Compact Format

```bash
# In .env
ENABLE_COMPACT_CONVERSATION_FORMAT=true
COMPACT_FORMAT_MAX_HISTORY=50  # Can be higher due to efficiency
```

### Code References

- **Formatter**: `app/services/conversation_formatter.py`
- **Integration**: `app/services/context/multi_level_context.py::format_for_gemini_compact()`
- **Handler**: `app/handlers/chat.py` (feature flag branching)
- **Tests**: `tests/integration/test_compact_format.py`

### Trade-offs

**Advantages**:
- 70-80% token reduction
- 3-4x more conversation history in same budget
- Human-readable (easier debugging)
- Faster processing (no JSON overhead)

**Disadvantages**:
- Loss of structured metadata (chat_id, message_id, timestamps)
- Media requires text descriptions (actual media still sent for analysis)
- Less precise context (no exact timestamps)

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
