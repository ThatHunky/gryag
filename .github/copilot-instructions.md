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

## Conversation Pattern Reference

**Canonical conversation format:** See `docs/overview/CURRENT_CONVERSATION_PATTERN.md` for the up-to-date message flow and formatting used by gryag and Gemini.

- If the conversation pattern changes, update `CURRENT_CONVERSATION_PATTERN.md` and update this file and `AGENTS.md` to reference the new pattern.

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

## .github/copilot-instructions.md — quick agent guide (compact)

Purpose: give an AI coding agent only the essential, actionable facts to be productive in this repo.

- Root rule: do NOT create new files at repository root except allowed configs (`README.md`, `AGENTS.md`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, `requirements*.txt`, `LICENSE`, `setup.py`). Put code under `app/`, docs under `docs/`, scripts under `scripts/`, tests under `tests/`.

- Entrypoint & run:

  - Run locally: `python -m app.main` (root `main.py` is deprecated; see `scripts/deprecated/`).
  - Docker: `docker-compose up bot` (service name `bot` in `docker-compose.yml`).

- Key architecture facts (where to look):

  - Handlers / routing: `app/handlers/` (chat/admin/profile_admin). See `app/handlers/chat.py` for message flow.
  - Dependency injection & throttling: `app/middlewares/` (ChatMetaMiddleware, ThrottleMiddleware).
  - Business logic: `app/services/` (context, gemini client, profile, fact_extractors, monitoring).
  - Multi-level context: `app/services/context/` (use `MultiLevelContextManager.build_context()`; fallback `ContextStore.recent()`).

- Non-negotiable conventions:

  - Never instantiate services in handlers — use middleware-injected instances from `ChatMetaMiddleware`.
  - Edit DB schema only in `db/schema.sql`. Changes must be mirrored in `ContextStore.init()` migration logic.
  - Persona constraints: system prompt in `app/persona.py` — no markdown in bot replies and never echo metadata to users.
  - **aiogram callback handlers**: When adding callback query handlers (inline buttons), ALWAYS register middleware for `dispatcher.callback_query.middleware()` in `app/main.py`, not just `dispatcher.message.middleware()`. Callback handlers need dependency injection too.

- Tests & validation:

  - Run full test suite: `make test` or `pytest tests/`.
  - Fast unit tests: `tests/unit/`. Integration tests use SQLite and fixtures in `tests/conftest.py`.

- Common edit patterns (examples):

  - Add a handler: create `app/handlers/<feature>.py` and register it in `app/main.py` with `dispatcher.include_router(...)`.
  - Add a Gemini tool: implement `app/services/<tool>.py`, export `NEW_TOOL_DEFINITION`, add to `tool_definitions` in `app/handlers/chat.py`, add callback to `tool_callbacks`.
  - Add fact pattern: edit `app/services/fact_extractors/patterns/ukrainian.py` or `english.py`; tests in `tests/unit/test_fact_extractors.py`.

- Runtime/config tips:

  - Env vars live in `.env.example`. Common toggles: `ENABLE_MULTI_LEVEL_CONTEXT`, `FACT_EXTRACTION_METHOD`, `USE_REDIS`, `ENABLE_SEARCH_GROUNDING`.
  - Embeddings: model `text-embedding-004`, stored as JSON arrays on `messages` table (see `db/schema.sql`).

- PR / automation rules for agents:
  - Keep edits small. If changing >3 files, add a one-line `docs/CHANGELOG.md` entry and update `docs/README.md` with verification steps.
  - Never add secrets — if needed, update `.env.example` and document required env vars.
  - Use `git mv` for renames to preserve history.

Read more: `AGENTS.md`, `docs/README.md`, and `docs/overview/CURRENT_CONVERSATION_PATTERN.md` for conversation specifics.

If you'd like, I can further trim or expand any section or add a short checklist for PR reviewers.

## Data Layer Conventions
