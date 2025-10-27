---
description: concise AI agent guide for gryag (tailored)
globs: *
---

## Quick start (what to run)

- Run locally (preferred): `.venv/bin/python3 -m app.main` (or activate venv: `source .venv/bin/activate` then `python -m app.main`).
- Tests: `.venv/bin/pytest tests/` or `make test` when venv activated.
- Docker (dev): `docker-compose up bot` (service name `bot` in `docker-compose.yml`).

## Critical conventions (do not break)

- Never instantiate services inside handlers — use middleware-injected instances from `app/middlewares/chat_meta.py` (ChatMetaMiddleware).
- DB schema is authoritative in `db/schema.sql`. Mirror schema edits in `app/services/context/context_store.py` (migrations/initialization there).
- Persona/system prompt lives in `app/persona.py` — bot replies must follow that constraint (no markdown in user-facing replies).

## Key places to look (fast path)

- Handlers and routing: `app/handlers/` — see `app/handlers/chat.py` for message flow and tool wiring.
- Middlewares (DI & throttling): `app/middlewares/` — `chat_meta.py`, `throttle.py`.
- Business services: `app/services/` — `context/`, `fact_extractors/`, `monitoring/`, `gemini` client.
- Context & memory: `app/services/context/` — `multi_level_context.py`, `episodic_memory.py`, `hybrid_search.py`.

## Patterns & examples

- Register a handler: create `app/handlers/<feature>.py` and add `dispatcher.include_router(...)` in `app/main.py`.
- Add a Gemini tool: implement `app/services/<tool>.py`, export a definition and add it to `tool_definitions` in `app/handlers/chat.py`.
- Use MultiLevelContext: call `MultiLevelContextManager.build_context()`; fallback is `ContextStore.recent()`.

## Dev workflow specifics

- Virtualenv is mandatory: `.venv/` exists in project root. Use `.venv/bin/python3` for scripts in automation.
- Tests: `tests/unit/` for fast checks, integration tests rely on SQLite fixtures (`tests/conftest.py`).
- CI: follow the existing `Makefile` targets (`make test`) and ensure you do not add secrets to commits.

## PR and agent rules

- Keep edits small and reversible. If changing >3 files, add a one-line `docs/CHANGELOG.md` entry and update `docs/README.md` with verification steps.
- Never add secrets — update `.env.example` for new env vars and document them.

## Useful file references

- `app/main.py` — app startup and middleware registration
- `app/persona.py` — system prompt and persona rules
- `db/schema.sql` — DB schema (FTS5, embeddings columns)
- `app/services/context/multi_level_context.py` — token-aware context composition

If you want this trimmed further or to include specific example snippets from a file, tell me which parts to expand.

## Examples (concrete)

- Middleware-injected keys (available in handler `data` / parameters):

  - `settings`, `store` (ContextStore), `gemini_client`, `profile_store`, `chat_profile_store`,
    `hybrid_search`, `episodic_memory`, `episode_monitor`, `bot_profile`, `bot_learning`,
    `prompt_manager`, `feature_limiter`, `multi_level_context_manager`, `redis_client`,
    `rate_limiter`, `persona_loader`, `image_gen_service`, `donation_scheduler`, `memory_repo`,
    plus `bot_username` and `bot_id`.

- Typical handler signature (real example from `app/handlers/chat.py`):

  async def handle_group_message(message: Message, bot: Bot, settings: Settings, store: ContextStore, gemini_client: GeminiClient, profile_store: UserProfileStore, bot_username: str, bot_id: int | None, ...)

- Callback-query middleware: register `ChatMetaMiddleware` for callbacks too — see `app/main.py` where the code calls:

  dispatcher.callback_query.middleware(chat_meta_middleware)

- Key env vars (most immediately useful):
  - `TELEGRAM_TOKEN`, `GEMINI_API_KEY` / `GEMINI_API_KEYS`, `DB_PATH`, `USE_REDIS`, `REDIS_URL`, `ADMIN_USER_IDS`.
  - Feature toggles: `ENABLE_MULTI_LEVEL_CONTEXT`, `ENABLE_IMAGE_GENERATION`, `ENABLE_COMPACT_CONVERSATION_FORMAT`.
