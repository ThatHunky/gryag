---
description: AI rules derived by SpecStory from the project AI interaction history
globs: *
---

## Quick map

- Entry point: `python -m app.main` (or script `gryag`) wires aiogram v3 dispatcher, applies middlewares, and starts long polling after purging pending updates.
- Core layout: `app/handlers` for user and admin routers, `app/middlewares` for context+throttle wiring, `app/services` for persistence, Gemini, triggers, telemetry, and media support, with settings in `app/config.py`.
- Root `main.py` exists only as a shim—always import/run through `app.main` to avoid stale code.

## Message lifecycle

- `ChatMetaMiddleware` fetches bot identity once and injects `settings`, `ContextStore`, `GeminiClient`, and optional `redis_client` so handlers never instantiate dependencies themselves.
- `ThrottleMiddleware` guards addressed traffic: it answers with `SNARKY_REPLY` when limits hit, sets `throttle_blocked`/`throttle_reason` in handler data, and records passes vs. blocks in telemetry.
- `handlers.chat.handle_group_message` ignores small talk but caches it via `_remember_context_message`; addressed turns get fallback context, metadata, and media parts assembled before Gemini is called.
- User turns are logged with embeddings (`ContextStore.add_turn`) before generation so throttle decisions are auditable even if Gemini fails.
- Admin IDs from `settings.admin_user_ids` bypass bans and quotas; reuse `_is_admin` in `handlers.admin` for consistency.

## Data & quotas

- Persistence is SQLite (`gryag.db`) managed by `ContextStore`; `init()` applies `db/schema.sql` and adds the `embedding` column if missing (keep docker volume mounted at `/app`).
- Messages store `[meta]` payloads (see `format_metadata`) plus optional media JSON; `ContextStore.recent()` rebuilds Gemini-ready `parts`—use it instead of crafting history manually.
- Semantic search uses cosine similarity over stored embeddings; always persist embeddings as JSON arrays of floats and expect `semantic_search` to cap candidates per chat/thread.
- Rate limits log to `quotas` table and, if Redis is on, share the `gryag:quota:{chat_id}:{user_id}` namespace so `/gryagreset` can purge both stores.

## Gemini integration

- `GeminiClient.generate` wraps `google-generativeai` async API, handles safety settings, tool arbitration, system-instruction fallbacks, and a simple circuit breaker—propagate `GeminiError` so callers can send friendly fallbacks.
- Media ingestion flows through `services.media.collect_media_parts`, then `GeminiClient.build_media_parts` base64-encodes content before embedding in the request.
- Tooling: `search_messages_tool` returns JSON strings; additional tools should follow that pattern so `_handle_tools` can merge follow-up calls. Toggle Google Search Grounding via `ENABLE_SEARCH_GROUNDING`.
- Embeddings are rate-limited with an async semaphore; prefer `gemini_client.embed_text` for all similarity work to reuse backoff logic.

## Persona & replies

- System persona in `app/persona.py` enforces a terse, sarcastic Ukrainian voice—inject it as `system_prompt` and never echo its raw text to users.
- Reply wrappers in `handlers.chat` reuse constants like `ERROR_FALLBACK`, `EMPTY_REPLY`, `BANNED_REPLY`; extend this module when adding new canned responses.
- Metadata-first user parts (`format_metadata`) must remain the first chunk for each turn so Gemini can reference chat/user IDs reliably.

## Admin & moderation

- `/gryagban` and `/gryagunban` operate on message replies or numeric IDs; they refuse `@username` strings because Telegram lacks ID lookup without an extra call.
- `/gryagreset` clears quotas in SQLite and, when Redis is active, scans `gryag:quota:{chat_id}:*` keys—reuse that prefix for any new quota-like data.
- `ContextStore.should_send_notice` throttles how often throttle warnings fire; check it before emitting new rate-limit messages.

## Dev workflows

- Local setup: create a venv, `pip install -r requirements.txt`, copy `.env.example`, fill in `TELEGRAM_TOKEN` + `GEMINI_API_KEY`, then `python -m app.main`. Docker path: `docker-compose up bot` (installs deps each boot).
- Set `LOGLEVEL=DEBUG` to see telemetry counters emitted via `app.services.telemetry`; use `telemetry.snapshot()` in REPLs for quick sanity checks.
- SQLite file is created automatically; delete `gryag.db` to reset chat history. Redis is optional—set `USE_REDIS=true` and ensure the URL resolves before boot.
- No formal tests exist; exercise flows against a staging chat and inspect counters/logs when validating behaviour.

## Extending patterns

- Add new routers under `app/handlers` and register them in `app/main.py`; rely on middleware-injected deps instead of creating new clients in handlers.
- When introducing new stored fields, update `db/schema.sql` and extend `ContextStore.init()` to backfill or `ALTER TABLE`, keeping migrations idempotent for Docker volume reuse.
- Expand media support via `services.media.collect_media_parts`; return dicts with `bytes`, `mime`, and a descriptive `kind` so `build_media_parts` just works.
- For new telemetry, call `telemetry.increment_counter` with clear labels; DEBUG logs render counters as structured extras for scraping.

## Docs, repo organization, and agent behavior

This repository adopts a small, consistent docs layout under `docs/` and keeps a concise top-level `README.md` for quick setup. Automated agents and humans should follow these conventions when creating, moving, or editing documentation:

- Recommended docs tree under `docs/`:

  - `docs/overview/` — high-level project and architecture overviews (e.g. `PROJECT_OVERVIEW.md`).
  - `docs/plans/` — technical plans and roadmaps (`IMPLEMENTATION_PLAN_SUMMARY.md`, `INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md`).
  - `docs/phases/` — phase-level status and test guides (`PHASE_*_COMPLETE.md`).
  - `docs/features/` — feature specs and design notes (`USER_PROFILING_PLAN.md`, `LOCAL_FACT_EXTRACTION_PLAN.md`).
  - `docs/guides/` — operational guides and runbooks (`TOOL_LOGGING_GUIDE.md`).
  - `docs/history/` — optional archived notes or exports (keep small).

- When reorganizing docs:

  - Create or update `docs/README.md` describing the change and listing moved/added files.
  - Prefer `git mv` for renames to preserve history. If moving without `git mv`, add a brief redirect note in the original file pointing to the new path.
  - Preserve relative links inside moved files and update cross-links where necessary.
  - If many files are touched in one commit, add a `docs/CHANGELOG.md` entry summarizing the edits.

- Guidance for automated agents editing docs/code:
  - Read `AGENTS.md` at the repo root first — it contains the short contract for doc edits and migration rules.
  - Make minimal, targeted edits. Avoid bulk rewrites unless explicitly requested by a maintainer.
  - Preserve the original author's voice and technical intent when possible.
  - When adding new documentation, include a short "How to verify" section with simple commands or expected outcomes.

These guidelines keep the repository organized and make human review easier.

Note: On 2025-10-02 many top-level documentation files were reorganized into the `docs/` tree. See `docs/CHANGELOG.md` for the full list and verification steps.
