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
Generate a photorealistic image at 2K resolution via Nano Banana Pro.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | ✅ | Image generation prompt **in ENGLISH** |

### `edit_image` (`ENABLE_IMAGE_GENERATION=true`)
Edit an existing generated image by its `media_id`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `media_id` | string | ✅ | ID from a previous `generate_image` response |
| `prompt` | string | ✅ | Edit instructions **in ENGLISH** |

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

## Google Search Grounding (`ENABLE_WEB_SEARCH=true`)
Automatically injected alongside custom tools. Not a function call — Gemini uses it natively to ground responses in real-time web data.

## Admin Endpoints

### `POST /api/v1/admin/stats`
Returns server statistics (uptime, memory, goroutines, GC). Requires `user_id` in ADMIN_IDS.

### `POST /api/v1/admin/reload_persona`
Hot-reloads the persona file. Requires `user_id` in ADMIN_IDS.
