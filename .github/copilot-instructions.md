---
description: "Copilot instructions tailored for the gryag repository — concise, actionable, and code-aware."

## Purpose (one-liner)
Practical guidance for automated coding agents to be immediately productive in this repo: how the app boots, where to look for service boundaries, and project-specific rules to follow.

- Run locally: `.venv/bin/python3 -m app.main` (or `source .venv/bin/activate` then `python3 -m app.main`).
- Tests: `.venv/bin/pytest tests/` (or `make test`).
- Docker dev: `docker compose up bot` (service `bot`).

## High-level architecture (what matters)
- Entry: `app/main.py` — initializes services, background tasks, and registers routers (see `dispatcher.include_router(...)`).
- Handlers: `app/handlers/` (core chat flow in `app/handlers/chat.py`).
- Dependency injection: `app/middlewares/chat_meta.py` — middleware injects almost all services into handler `data` (do NOT instantiate services in handlers).
- Context & memory: `app/services/context/` — `MultiLevelContextManager`, `HybridSearchEngine`, `EpisodicMemoryStore`; DB schema in `db/schema.sql` is authoritative.

## Project-specific conventions (do not break)
- Always use middleware-injected services (see `ChatMetaMiddleware`). Example injected keys: `settings`, `store`, `gemini_client`, `profile_store`, `multi_level_context_manager`, `redis_client`, `bot_username`, `bot_id`.
- Persona/system prompt: `app/persona.py` — user-facing replies must conform (plain text, Ukrainian tone). Do not add Markdown in replies.
- Virtualenv mandatory: use `.venv/bin/python3` for scripts and tests.
- DB edits: update `db/schema.sql` and mirror migration/initialization code under `app/core/` or `app/services/context/`.
- DB schema is authoritative in `db/schema.sql`. Mirror schema edits in `app/services/context/context_store.py` (migrations/initialization there).
## Concrete examples & patterns
- Handler registration: add a `Router` in `app/handlers/<feature>.py` and include it in `app/main.py`.
- Tools: implement tool code under `app/services/` and register tool definitions via `build_tool_definitions` / `build_tool_callbacks` used in `app/handlers/chat.py`.
- Context: call `MultiLevelContextManager.build_context(...)` for token-budgeted context assembly; fallback is `ContextStore.recent(...)`.

## Safety, PRs and agent rules
- Never create arbitrary files at repo root (see `AGENTS.md` file-organization rules). Put new code under `app/`, docs under `docs/`, scripts under `scripts/`.
- Keep edits small. If changing >3 files, add a one-line `docs/CHANGELOG.md` entry and update `docs/README.md` with verification steps.
- Do NOT add secrets. If a new env var is required, document it in `.env.example` (do not commit real secrets).

## Useful files to open first
- `app/main.py` — start/registration and background tasks.
- `app/handlers/chat.py` — central message flow, tool wiring, formatting rules.
- `app/middlewares/chat_meta.py` — which services are injected and how.
- `app/services/context/multi_level_context.py` — how multi-level context is assembled and token budgets.
- `app/persona.py` — system persona and strict behavior rules.
- `db/schema.sql` — canonical schema (FTS, memories, bot learning).
- Middlewares (DI & throttling): `app/middlewares/` — `chat_meta.py`, `throttle.py`.
If you want this shortened further or want concrete code snippets for any of the above files, tell me which area to expand and I will iterate.
- Context & memory: `app/services/context/` — `multi_level_context.py`, `episodic_memory.py`, `hybrid_search.py`.
## Examples (concrete)
## Patterns & examples
- Middleware-injected keys (available in handler `data` / parameters):
- Register a handler: create `app/handlers/<feature>.py` and add `dispatcher.include_router(...)` in `app/main.py`.
  - `settings`, `store` (ContextStore), `gemini_client`, `profile_store`, `chat_profile_store`,
    `hybrid_search`, `episodic_memory`, `episode_monitor`, `bot_profile`, `bot_learning`,
    `prompt_manager`, `feature_limiter`, `multi_level_context_manager`, `redis_client`,
    `rate_limiter`, `persona_loader`, `image_gen_service`, `donation_scheduler`, `memory_repo`,
    plus `bot_username` and `bot_id`.
- Virtualenv is mandatory: `.venv/` exists in project root. Use `.venv/bin/python3` for scripts in automation.
- Typical handler signature (real example from `app/handlers/chat.py`):
- CI: follow the existing `Makefile` targets (`make test`) and ensure you do not add secrets to commits.
  async def handle_group_message(message: Message, bot: Bot, settings: Settings, store: ContextStore, gemini_client: GeminiClient, profile_store: UserProfileStore, bot_username: str, bot_id: int | None, ...)
## PR and agent rules
- Callback-query middleware: register `ChatMetaMiddleware` for callbacks too — see `app/main.py` where the code calls:
- Keep edits small and reversible. If changing >3 files, add a one-line `docs/CHANGELOG.md` entry and update `docs/README.md` with verification steps.
  dispatcher.callback_query.middleware(chat_meta_middleware)

- Key env vars (most immediately useful):
  - `TELEGRAM_TOKEN`, `GEMINI_API_KEY` / `GEMINI_API_KEYS`, `DB_PATH`, `USE_REDIS`, `REDIS_URL`, `ADMIN_USER_IDS`.
  - Feature toggles: `ENABLE_MULTI_LEVEL_CONTEXT`, `ENABLE_IMAGE_GENERATION`, `ENABLE_COMPACT_CONVERSATION_FORMAT`.
- `app/persona.py` — system prompt and persona rules
---

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
