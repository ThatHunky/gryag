# Gryag V2 — Tools Reference

All tools are registered with strict JSON schemas and presented to Gemini as `FunctionDeclarations`. Feature toggles control which tools are available at runtime.

## Always Available

### `recall_memories`
Retrieve stored facts about a user. **Must be called before `remember_memory`** to avoid duplicates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | integer | ✅ | Telegram user ID |
| `chat_id` | integer | ✅ | Telegram chat ID |

### `remember_memory`
Store a new fact about a user. Duplicates are silently ignored (dedup via MD5 hash).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | integer | ✅ | Telegram user ID |
| `chat_id` | integer | ✅ | Telegram chat ID |
| `memory_text` | string | ✅ | Fact to remember |

### `forget_memory`
Delete a specific memory by its ID. **Must call `recall_memories` first** to get the `memory_id`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `memory_id` | integer | ✅ | ID from `recall_memories` |

### `calculator`
Evaluate a mathematical expression. Executed safely inside the Python sandbox.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `expression` | string | ✅ | Math expression (e.g., `2**10 + 3.14`) |

### `weather`
Get weather for a location. *(Integration pending)*

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `location` | string | ✅ | City or location name |

### `currency`
Convert between currencies. *(Integration pending)*

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from` | string | ✅ | Source currency code (e.g., `USD`) |
| `to` | string | ✅ | Target currency code (e.g., `UAH`) |
| `amount` | number | ✅ | Amount to convert |

---

## Feature-Toggled

### `generate_image` (`ENABLE_IMAGE_GENERATION=true`)
Generate a photorealistic image at 2K resolution via Gemini 3 Pro Image Preview (same GEMINI_API_KEY as chat). The backend caches the image and returns a `media_id` in the tool result so the model can pass it to `edit_image` later.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Image generation prompt **in ENGLISH only** (translate from the user's language) |
| `aspect_ratio` | string | | Optional. One of: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9 |
| `as_document` | boolean | | Optional. If true, send as file/document instead of inline photo |

### `edit_image` (`ENABLE_IMAGE_GENERATION=true`)
Edit an image: either by `media_id` (from a previous `generate_image` or `edit_image` response) or the image attached to the current message (`use_context_image: true`). Prompt must be in English only.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Edit instructions **in ENGLISH only** |
| `media_id` | string | | ID from a previous generation (for "edit that one") |
| `use_context_image` | boolean | | Set true when the user attached an image to the current message and asked to edit it |
| `aspect_ratio` | string | | Optional. Same values as `generate_image` |

**Supported input media (user sends to bot):** The bot receives and injects into context: photo, video, voice, sticker, animation (GIF), video_note, and document (image/video). So the model can see and hear attachments; use `use_context_image` when the user says "edit this" with an image attached.

### `run_python_code` (`ENABLE_SANDBOX=true`)
Execute Python code in the locked-down sandbox container. Zero network access, read-only filesystem, resource limits.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `code` | string | ✅ | Python code to execute |

**Sandbox limits:**
- Timeout: `SANDBOX_TIMEOUT_SECONDS` (default: 5s)
- Memory: `SANDBOX_MAX_MEMORY_MB` (default: 128MB)
- CPU: 0.5 cores
- Network: none
- Filesystem: read-only + 64MB tmpfs

---

### `search_web` (`ENABLE_WEB_SEARCH=true`)
Search the web using **Gemini Grounding** (a separate Gemini request with Google Search). No extra API key; uses `GEMINI_API_KEY`. Available in normal chat and in proactive messaging (e.g. 30% “conduct a news search” path).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | ✅ | Search query (e.g. “latest news Ukraine”, “weather London”) |

## Admin Endpoints

### `POST /api/v1/admin/stats`
Returns server statistics (uptime, memory, goroutines, GC). Requires `user_id` in ADMIN_IDS.

### `POST /api/v1/admin/reload_persona`
Hot-reloads the persona file. Requires `user_id` in ADMIN_IDS.
