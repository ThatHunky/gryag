# Model Context Pipeline (End‑to‑End)

This document shows exactly how gryag assembles context and calls the model (Google Gemini), including system instructions, metadata blocks, speaker headers, history, attachments, tools, and response cleanup.

---

## High‑Level Flow

```
[SYSTEM INSTRUCTIONS]
        + optional multi‑level system context
        + current timestamp (Kyiv)
                     ↓
[HISTORY]
  Immediate + Recent turns (with [speaker] + [meta] + text)
                     ↓
[CURRENT USER PARTS]
  [speaker] + [meta] + text + attachments (+ inline reply excerpt)
        + Tool declarations (function_declarations)
                     ↓
GeminiClient.generate → google.genai Client.models.generate_content
  (optionally: tool → function_call/response loop)
                     ↓
Response text extracted → metadata stripped → sent to Telegram
                     ↓
[OUTPUT]
```

Key toggles: `ENABLE_MULTI_LEVEL_CONTEXT`, `ENABLE_COMPACT_CONVERSATION_FORMAT`, media caps (`GEMINI_MAX_MEDIA_ITEMS*`), tools (`ENABLE_SEARCH_GROUNDING`, `ENABLE_IMAGE_GENERATION`, `ENABLE_TOOL_BASED_MEMORY`). See `app/config.py` for full list.

---

## Sources and Assembly

- System prompt
  - Default persona: `app/persona.py:1` (`SYSTEM_PERSONA`)
  - Optional DB override: `app/services/system_prompt_manager.py` (active chat/global prompt)
  - Current time injection: `app/handlers/chat.py:1492` (Kyiv timestamp)
- Multi‑level context (if enabled)
  - Builder: `app/services/context/multi_level_context.py:64` (`MultiLevelContextManager`)
  - Levels: Immediate, Recent, Relevant (hybrid search), Background (profile), Episodic
  - Formatting to Gemini:
    - JSON mode: `format_for_gemini()` `app/services/context/multi_level_context.py:1120`
    - Compact text mode: `format_for_gemini_compact()` `app/services/context/multi_level_context.py:1173`
- History retrieval (fallback/simple mode)
  - `ContextStore.recent(...)` returns Gemini‑ready messages with `[speaker]` + `[meta]`: `app/services/context_store.py:332`
  - Metadata block builder: `format_metadata()` `app/services/context_store.py:132`
  - Speaker header builder: `format_speaker_header()` `app/services/context_store.py:48`
- Current message assembly
  - Media collection: `app/services/media.py` (`collect_media_parts()`)
  - Gemini media parts: `GeminiClient.build_media_parts()` `app/services/gemini.py:401`
  - User metadata: `_build_user_metadata()` `app/handlers/chat.py:406`
  - User parts (text + media): `_build_clean_user_parts()` `app/handlers/chat.py:432`
  - Inline reply excerpt and reply media handling: `app/handlers/chat.py:1420` and `app/handlers/chat.py:1920`
- Tools (function calling)
  - Definitions registry: `app/handlers/chat_tools.py:186` (`build_tool_definitions`)
  - Callbacks registry: `app/handlers/chat_tools.py:120` (`build_tool_callbacks`)
  - Example built‑in tools: `search_messages`, `calculator`, `weather`, `currency`, polls, memory, media helpers

---

## Exact Payloads Sent to Gemini

The client uses the official Google SDK. The final call is built in `GeminiClient.generate()` and `_invoke_model()`:

- Entry: `app/services/gemini.py:600` (`generate()`)
- Low‑level invoke: `app/services/gemini.py:336` (`_invoke_model()`), which calls:
  - `client.aio.models.generate_content(model=..., contents=..., config=...)`
  - `system_instruction` used when supported; otherwise persona is prepended as a `user` message

### JSON Mode (default)

When `ENABLE_COMPACT_CONVERSATION_FORMAT=false`.

1) System instruction (separate parameter if supported): persona + timestamp (+ multi‑level `system_context`)
2) History: array of messages with `role` + `parts`
3) Current user parts: metadata/speaker + text + attachments

Example (reply with image; shortened for clarity):

```json
{
  "system_instruction": "... gryag persona ...\n\n# Current Time\nThe current time is: ...\n\nRelevant Past Context:\n[Relevance: 0.82] ...",
  "contents": [
    {
      "role": "user",
      "parts": [
        {"text": "[speaker role=user id=392817811 name=\"Всеволод Добровольський\" username=\"vsevolod_dobrovolskyi\" is_bot=0]"},
        {"text": "[meta] chat_id=-100123 thread_id=12 message_id=450 user_id=392817811 username=\"vsevolod_dobrovolskyi\" name=\"Всеволод Добровольський\""},
        {"text": "гряг, подивись на це"}
      ]
    },
    {
      "role": "model",
      "parts": [
        {"text": "[speaker role=assistant name=\"gryag\" username=\"gryag_bot\" is_bot=1]"},
        {"text": "[meta] chat_id=-100123 message_id=451 username=\"gryag_bot\" reply_to_message_id=450 reply_to_user_id=392817811 reply_to_name=\"Всеволод Добровольський\""},
        {"text": "Га?"}
      ]
    },
    {
      "role": "user",
      "parts": [
        {"text": "[speaker role=user id=392817811 name=\"Всеволод Добровольський\" username=\"vsevolod_dobrovolskyi\" is_bot=0]"},
        {"text": "[meta] chat_id=-100123 thread_id=12 message_id=452 user_id=392817811 reply_to_message_id=451 reply_excerpt=\"Га?\""},
        {"text": "ось фото"}
      ]
    },
    {
      "role": "user",
      "parts": [
        {"text": "[speaker role=user id=392817811 name=\"Всеволод Добровольський\" username=\"vsevolod_dobrovolskyi\" is_bot=0]"},
        {"text": "[meta] chat_id=-100123 thread_id=12 message_id=453 user_id=392817811 reply_to_message_id=452 reply_excerpt=\"ось фото\""},
        {"text": "[↩︎ Відповідь на Всеволод Добровольський: ось фото]"},
        {"text": "Подивись"},
        {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
      ]
    }
  ],
  "tools": [{"function_declarations": [{"name": "search_messages", "parameters": {"type": "object"}}]}]
}
```

Notes:
- History messages already include `[speaker …]` and `[meta]` at the top of `parts`
- In JSON mode, historical media is dropped from history to save tokens; reply media is attached to `user_parts` (`app/handlers/chat.py:1760` onward)
- Reply context may be injected into history if the replied message is outside the window (`app/handlers/chat.py:1920`)

### Compact Mode (optional)

When `ENABLE_COMPACT_CONVERSATION_FORMAT=true`.

1) System instruction as above
2) History is collapsed into a single `user` part with plain text lines and a `[RESPOND]` marker
3) Attachments: media parts for current and reply messages, optionally limited historical media

Example:

```
Alice#392817811: Привіт
gryag: Га?
Alice#392817811 → gryag: Подивись [Media] [Image]
[RESPOND]
```

The actual `contents` sent:

```json
[
  {"role": "user", "parts": [{"text": "Alice#392817811: Привіт\ngryag: Га?\nAlice#392817811 → gryag: Подивись [Media] [Image]\n[RESPOND]"}, {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}]}
]
```

Formatter: `app/services/conversation_formatter.py`.

---

## Tools (Function Calling) Round‑Trip

- Tools are declared via `tools=[types.Tool(...)]` (built from JSON dictionaries)
- Gemini may return `function_call` parts; callbacks run in Python and respond with `function_response`
- The client then re‑invokes the model with the new messages until a text answer is produced

Shape during tool use:

```json
{
  "role": "model",
  "parts": [{"function_call": {"name": "calculator", "args": {"expression": "15*23"}}}]
}
{
  "role": "tool",
  "parts": [{"function_response": {"name": "calculator", "response": {"result": 345}}}]
}
```

Implementation: `_handle_tools()` inside `GeminiClient.generate()` `app/services/gemini.py:600+`.

---

## Attachments

- Media descriptors from Telegram: `collect_media_parts()` `app/services/media.py`
- Conversion to Gemini parts: `build_media_parts()` `app/services/gemini.py:401`
  - Inline images/audio/video become `{ "inline_data": { "mime_type", "data" } }`
  - YouTube links become `{ "file_data": { "file_uri" } }`
- Limits and filtering:
  - Per‑message and total caps: `GEMINI_MAX_MEDIA_ITEMS*` in `app/config.py`
  - Unsupported modalities filtered per model capability
  - Multi‑level history media limited/dropped: `app/services/context/multi_level_context.py:1080`

---

## Response Extraction and Cleaning

- Text extracted from SDK response: `_extract_text()` `app/services/gemini.py:600+`
- Before sending to Telegram, metadata and markers are stripped: `_clean_response_text()` `app/handlers/chat.py:520`
  - Removes `[meta] ...`, technical IDs, and bracketed system markers like `[ATTACHMENT]`
  - Telegram formatting fixer ensures underscores in usernames remain literal

---

## Where The Call Happens

- Chat handler invokes the model here: `app/handlers/chat.py:2184` (`gemini_client.generate(...)`)
- The SDK call path:
  - `GeminiClient.generate()` → `_invoke_model()` → `client.aio.models.generate_content(...)`

---

## Minimal End‑to‑End Example

```
[SYSTEM INSTRUCTIONS]
  gryag persona + Current Time (+ optional system_context)
      ↓
User: [speaker …]\n[meta …]\n"Як справи, гряг?"
Bot:  [speaker …]\n[meta …]\n"Нормально."
User: [speaker …]\n[meta …]\n"Подивись" + [inline_data image/jpeg]
      ↓
Gemini → (optionally tools) → text reply
      ↓
[OUTPUT] Telegram message (cleaned from meta)
```

---

## Verification

- Enable logs and look for send/formatting lines in handler:
  - `"Sending to Gemini: history_length=..., user_parts_count=..., tools_count=..., system_prompt_length=..."`
  - Files: `app/handlers/chat.py:2184`, `app/services/gemini.py:336`
- Inspect last stored messages in SQLite to see persisted `media` and `meta` JSON:
  - `sqlite3 gryag.db` then `SELECT role, text, media FROM messages ORDER BY id DESC LIMIT 10;`

---

## System Context Block Inside System Instructions

Objective
- Embed the last N chat messages (default 60) inside the system instructions as a fenced monospace block.
- Keep media awareness focused: only the trigger message and its reply target show placeholders, while other lines stay text-only.
- Clearly mark the current message with `[REPLY TO THIS]` and finish with `[RESPOND]` so Gemini answers the right turn.

How It Works
- Placement: appended after persona, timestamp, and optional multi-level `system_context` in the `system_instruction` payload.
- Source: pulls recent messages directly from `ContextStore.recent()` in chronological order (no turn pairing).
- Media scope: uses `[Image]`, `[Video]`, `[Audio]`, `[YouTube]`, or `[Document]` markers only for trigger/reply lines; actual attachments for those lines still ride in `user_parts`.
- Deduplication: when enabled, the regular `history` array is cleared—context lives solely in the block plus the live `user_parts`.

Example (system instruction excerpt)

```
Here’s the current conversation context (last up to 60 messages):

```
user [meta chat_id=-100123 user_id=392817811 name="Всеволод Добровольський" username="vsevolod_dobrovolskyi" message_id=440]: …
bot  [meta name="gryag" username="gryag_bot" message_id=441 reply_to_message_id=440]: …
user [meta chat_id=-100123 user_id=392817811 message_id=452 reply_to_message_id=451]: Ось фото [Image]
user [meta chat_id=-100123 user_id=392817811 message_id=453 reply_to_message_id=452]: Подивись [REPLY TO THIS]
```

[RESPOND]
```
```

Key Details
- Triple backticks enforce monospace so the model treats the block as literal context.
- Metadata uses the same compact format as `format_metadata()`; toggle it with `SYSTEM_CONTEXT_BLOCK_INCLUDE_META`.
- Thread scoping obeys `SYSTEM_CONTEXT_BLOCK_THREAD_ONLY`—set to `false` to span the entire chat.
- Attachments beyond trigger/reply are removed from both the block and outgoing payload; only those two messages include media parts.

Configuration Knobs
- `ENABLE_SYSTEM_CONTEXT_BLOCK` (default `false`) — master toggle.
- `SYSTEM_CONTEXT_BLOCK_MAX_MESSAGES` (default `60`) — max lines listed; oldest messages drop first.
- `SYSTEM_CONTEXT_BLOCK_INCLUDE_META` (default `true`) — include or suppress `[meta …]` blocks.
- `SYSTEM_CONTEXT_BLOCK_THREAD_ONLY` (default `true`) — restrict to the current thread in supergroups.
- `SYSTEM_CONTEXT_BLOCK_MEDIA_SCOPE` (default `trigger_and_reply`) — currently only supported mode.

Operational Notes
- Token budget shifts toward the system prompt; size `CONTEXT_TOKEN_BUDGET` accordingly.
- DEBUG logs show the enlarged `system_prompt_length`; use them to confirm the block content.
- Feature flag `false` restores legacy behavior (history or compact format) without the block.
