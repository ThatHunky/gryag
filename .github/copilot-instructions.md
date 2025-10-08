---
description: AI coding guide for gryag - Ukrainian Telegram bot with smart memory
globs: *
---

## ⚠️ CRITICAL: File Organization Rules

**NEVER create files at the repository root!** Follow these strict rules:

**Allowed at root ONLY:**

- `README.md`, `AGENTS.md` (documentation)
- Configuration: `.env.example`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, `requirements*.txt`
- Package metadata: `LICENSE`, `setup.py` (if needed)

**All other files MUST go in proper directories:**

- **Documentation** → `docs/` (features/, plans/, phases/, guides/, fixes/, history/, overview/)
- **Scripts** → `scripts/` (migrations/, diagnostics/, tests/, verification/, deprecated/)
- **Application code** → `app/`
- **Tests** → `tests/` (unit/, integration/)

**Before creating ANY file, check:** Is this a root-level config? If NO → use proper subdirectory!

See `AGENTS.md` and `scripts/README.md` for complete organization structure.

## Architecture Overview

**gryag** is a Telegram group bot with a sarcastic Ukrainian personality, powered by Google Gemini 2.5 Flash. It features multi-level context management, user profiling, episodic memory, and hybrid fact extraction (local LLM + regex patterns).

**Tech stack**: aiogram v3, SQLite (with FTS5), optional Redis, Google Generative AI SDK, llama-cpp-python (optional local model)

**Entry point**: `python -m app.main` or script `gryag`

- Root `main.py` is a **deprecated shim** (now in `scripts/deprecated/`) - always use `app.main`
- Main initializes all services and wires aiogram dispatcher with middlewares

**Core directories**:

- `app/handlers/` - Message routers (chat, admin, profile_admin)
- `app/middlewares/` - ChatMetaMiddleware (DI), ThrottleMiddleware (rate limiting)
- `app/services/` - Business logic (context, gemini, user_profile, fact_extractors, media, tools)
- `app/services/context/` - Multi-level context, hybrid search, episodic memory
- `app/services/monitoring/` - Continuous monitoring, event system, message classification
- `db/schema.sql` - **Single source of truth** for SQLite schema (FTS5, user profiles, episodes, fact graphs)
- `scripts/` - Utilities organized by purpose (see `scripts/README.md`)
- `docs/` - All documentation organized by category (see `docs/README.md`)

## Message Flow (Critical Path)

1. **Middleware injection** (`ChatMetaMiddleware`):

   - Fetches bot identity once, injects into handler data: `settings`, `store` (ContextStore), `gemini_client`, `profile_store`, `fact_extractor`, `hybrid_search`, `episodic_memory`, `episode_monitor`, `continuous_monitor`, optional `redis_client`
   - **Never instantiate these services in handlers** - always use injected instances

2. **Throttle check** (`ThrottleMiddleware`):

   - Adaptive rate limiting (base + dynamic adjustment based on user behavior)
   - Uses Redis if available, falls back to SQLite `quotas` table
   - Admins (from `ADMIN_USER_IDS`) bypass all limits
   - Sets `throttle_blocked`/`throttle_reason` in handler data
   - Replies with `SNARKY_REPLY` when limit hit (once per hour via `should_send_notice`)

3. **Message classification** (`handlers.chat.handle_group_message`):

   - **All messages** processed by `continuous_monitor.process_message()` for learning
   - **Unaddressed messages**: cached via `_remember_context_message()` for fallback context (5 messages per chat/thread in-memory TTL cache)
   - **Addressed messages** (mentions, replies, `/gryag`): proceed to generation

4. **Context assembly** (when `ENABLE_MULTI_LEVEL_CONTEXT=true`):

   - Uses `MultiLevelContextManager.build_context()` to assemble 5 layers:
     - **Immediate** (last 5 messages) - always included
     - **Recent** (last 30 messages) - recent conversation flow
     - **Relevant** (10 hybrid-search results) - semantic + keyword + temporal
     - **Background** (user profile summary) - facts about the user
     - **Episodic** (3 similar past episodes) - significant past conversations
   - Token budget: 8000 tokens default (`CONTEXT_TOKEN_BUDGET`)
   - Formats into Gemini-ready history + system context string
   - **Fallback**: Simple history via `store.recent()` if multi-level fails

5. **User turn persistence**:

   - `store.add_turn()` **before** Gemini call (for audit trail even on API failures)
   - Stores: text, media JSON, metadata (`format_metadata`), embedding (768-dim vector as JSON array)
   - Embedding via `gemini_client.embed_text()` (rate-limited semaphore)

6. **Gemini generation**:

   - `gemini_client.generate()` with system prompt, history, user parts, tools
   - Tools: `search_messages`, `calculator`, `weather`, `currency`, `polls` (all return JSON strings)
   - Google Search Grounding (if `ENABLE_SEARCH_GROUNDING=true`) - uses `google_search_retrieval` (legacy SDK format), 500 req/day limit on Free tier
   - Circuit breaker: 3 failures → 60s cooldown
   - Safety settings: `BLOCK_NONE` for all categories

7. **Response cleaning**:

   - `_clean_response_text()` strips `[meta]` blocks, technical IDs, extra whitespace
   - `_escape_markdown()` removes formatting chars (bot persona forbids markdown)
   - Truncate to 4096 chars (Telegram limit)

8. **Background tasks**:
   - User profiling (`_update_user_profile_background()`) - fire-and-forget asyncio task
   - Episode tracking (`episode_monitor.track_message()`) - for automatic episode creation
   - Model turn persistence (`store.add_turn()` for bot's response)

## Data Layer Conventions

**SQLite (`gryag.db`)** via `ContextStore`:

- Schema applied via `db/schema.sql` in `init()` - **always edit schema.sql**, not raw queries
- `messages` table: chat_id, thread_id, user_id, role, text, media (JSON), embedding (JSON array), ts
- `messages_fts` virtual table (FTS5) for keyword search - **auto-synced via triggers**
- `user_facts` table: fact_type, fact_key, fact_value, confidence, evidence_text
- `episodes` table: topic, summary, summary_embedding, importance, message_ids (JSON), participant_ids (JSON)
- Retention: 30 days default (`RETENTION_DAYS`), adaptive for important messages

**Metadata format** (`format_metadata`):

- Compact string: `[meta] chat_id=123 user_id=456 name="Alice" reply_to_message_id=789`
- **Always first part** in user message for Gemini context
- Sanitized (no newlines, quotes escaped, truncated to 50 chars per value)
- **Never echo metadata in responses** - cleaned via `_clean_response_text()`

**Embeddings**:

- Model: `text-embedding-004` (768 dimensions)
- Stored as JSON arrays: `"[0.123, -0.456, ...]"`
- Cosine similarity for semantic search (dot product of normalized vectors)
- Rate-limited via `gemini_client._embed_semaphore` (8 concurrent)

**Redis (optional)**:

- Namespace: `gryag:quota:{chat_id}:{user_id}` (sorted sets with timestamps)
- Only for throttling - SQLite remains source of truth for history
- Admin commands like `/gryagreset` clear both Redis and SQLite

## User Profiling & Fact Extraction

**Hybrid extraction** (`FACT_EXTRACTION_METHOD=hybrid`, recommended):

1. **Rule-based** (instant, 70% coverage): Regex patterns in `services/fact_extractors/patterns/`
   - Location: "я з Києва", "я живу в..."
   - Language: "я вивчаю англійську", multilingual detection
   - Skills: "я програміст", "я вмію малювати"
2. **Local model** (100-500ms, 85% coverage): Phi-3-mini-4k-instruct (llama.cpp)
   - Path: `LOCAL_MODEL_PATH=models/phi-3-mini-q4.gguf`
   - Threads: `LOCAL_MODEL_THREADS=4` (tune for CPU)
   - Download: `bash download_model.sh` (~2.2GB)
3. **Gemini fallback** (if `ENABLE_GEMINI_FALLBACK=true`): For complex cases

**Fact storage**:

- Deduplication via `fact_quality_metrics` table (semantic similarity)
- Confidence threshold: 0.7 default (`FACT_CONFIDENCE_THRESHOLD`)
- Max facts per user: 100 (`MAX_FACTS_PER_USER`)
- Versioning via `fact_versions` table (tracks changes: creation, reinforcement, evolution, correction, contradiction)

**Profile summarization** (optional, `ENABLE_PROFILE_SUMMARIZATION=true`):

- Runs at 3 AM daily (`PROFILE_SUMMARIZATION_HOUR=3`)
- Batch size: 30 profiles/run (`PROFILE_SUMMARIZATION_BATCH_SIZE=30`)
- Generates natural language summaries via Gemini

## Persona & Voice

**System prompt** (`app/persona.py`):

- Terse, sarcastic, Ukrainian by default
- Black humor, no political correctness
- **Never use markdown** (bold/italic forbidden)
- **Never echo metadata** or technical details to users

**Canned responses** (in `handlers/chat.py`):

- `ERROR_FALLBACK` - "Ґеміні знову тупить..."
- `EMPTY_REPLY` - "Скажи конкретніше..."
- `BANNED_REPLY` - "Ти для гряга в бані..."
- `SNARKY_REPLY` (throttle) - "Пригальмуй, балакучий..."

## Testing & Development

**Run tests**: `make test` or `pytest tests/`

- Unit tests: `tests/unit/` (fast, mocked)
- Integration tests: `tests/integration/` (require SQLite, slower)
- Test fixtures in `tests/conftest.py` (async DB fixture, settings)
- Async tests via `pytest-asyncio` (auto mode in `pyproject.toml`)

**Run locally**:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill TELEGRAM_TOKEN, GEMINI_API_KEY
python -m app.main
```

**Docker**: `docker-compose up bot`

- Volume mount: `/app` (for `gryag.db` persistence)
- Redis: Optional service in `docker-compose.yml`

**Logging**:

- `LOGLEVEL=DEBUG` for verbose output
- Telemetry counters via `app.services.telemetry.increment_counter()`
- Resource monitoring (if psutil installed): CPU/memory pressure warnings

**Database inspection**:

```bash
sqlite3 gryag.db
.tables  # List all tables
SELECT * FROM user_facts ORDER BY created_at DESC LIMIT 10;
SELECT * FROM episodes ORDER BY importance DESC LIMIT 5;
```

## Extending Patterns

**Add a new handler**:

1. Create router in `app/handlers/new_feature.py`
2. Register in `app/main.py`: `dispatcher.include_router(new_feature_router)`
3. Use middleware-injected services (never instantiate clients)

**Add a new tool for Gemini**:

1. Define in `app/services/new_tool.py`: function + `NEW_TOOL_DEFINITION` dict (JSON schema)
2. Add to `tool_definitions` list in `handlers/chat.handle_group_message`
3. Add callback to `tool_callbacks` dict
4. **Always return JSON strings** (for consistency with existing tools)

**Schema changes**:

1. Edit `db/schema.sql` (single source of truth)
2. Add migration logic in `ContextStore.init()` (idempotent `ALTER TABLE` with try/except)
3. Test with fresh DB: `rm gryag.db && python -m app.main`
4. Document in `docs/CHANGELOG.md`

**Add a new fact pattern** (rule-based extraction):

1. Add regex in `app/services/fact_extractors/patterns/ukrainian.py` or `english.py`
2. Test in `tests/unit/test_fact_extractors.py`
3. Pattern format: `(pattern, fact_type, fact_key_template, confidence)`

## Documentation Rules (see AGENTS.md)

- **Read `AGENTS.md` first** - short contract for automated edits
- Docs live in `docs/` (overview, plans, phases, features, guides, history)
- Use `git mv` for renames to preserve history
- Update `docs/README.md` with one-line summary + verification step
- Multi-file changes: add `docs/CHANGELOG.md` entry
- Preserve original author's voice and technical intent
- Include "How to verify" section in new docs

**Top-level markdown files** (only these allowed at root):

- `README.md` - Quick start, features, setup
- `AGENTS.md` - Rules for automated code/doc edits
- `.github/copilot-instructions.md` (this file)

## Common Pitfalls

1. **Don't use `main.py`** at repo root - it's deprecated, use `app.main`
2. **Don't instantiate services in handlers** - use middleware-injected instances
3. **Don't craft Gemini history manually** - use `ContextStore.recent()` or `MultiLevelContextManager`
4. **Don't forget to clean metadata** from Gemini responses via `_clean_response_text()`
5. **Don't skip embedding persistence** - needed for semantic search and episodic memory
6. **Don't add schema changes outside `db/schema.sql`** - migrations go in `ContextStore.init()`
7. **Don't bypass throttle checks** - admins use `admin_user_ids_list`, not manual bypasses
8. **Don't echo persona/metadata to users** - system prompts are internal only

## Phase Status (as of Oct 2025)

✅ **Phase 1-2**: FTS5, hybrid search, episodic memory, fact graphs
✅ **Phase 3**: Multi-level context manager (5 layers, <500ms)
✅ **Phase 4.1**: Episode boundary detection (semantic, temporal, topic signals)
🚧 **Phase 4.2**: Automatic episode creation (in progress)
📋 **Phase 5-6**: Adaptive memory consolidation, fact graph expansion

See `docs/phases/` for detailed completion reports and `docs/plans/MEMORY_AND_CONTEXT_IMPROVEMENTS.md` for roadmap.
