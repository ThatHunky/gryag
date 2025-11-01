# gryag C++ Migration Plan

Status: in progress (initial tooling + admin/profile handlers running in `cpp/`)

Executive summary: Yes, it’s feasible to convert gryag to C++. This plan outlines a staged, low‑risk migration that preserves the authoritative DB schema, DI/middleware patterns, and user-visible behavior (Ukrainian, plain text replies) while incrementally porting services and handlers. We recommend a strangler-fig approach: stand up a C++ service in parallel, validate parity via golden transcripts, then cut over behind feature flags.

## Progress Snapshot (2025-10-30)

- Bootstrapped the C++ service with settings/logging, SQLite context store, and tgbot-cpp loop.
- Implemented production tool integrations (weather, currency, polls, web/search, memory, Gemini image) with function definitions wired into the Gemini client.
- Ported admin/profile handlers, including ban/reset/user list workflows, and enabled Redis-backed locks/rate limiting with SQLite fallback.
- Added Gemini function-call parsing (single-hop) and storage of tool outputs in the context store.

## Goals and Non‑Goals

- Goals
  - Reach feature parity for core chat flow, tools, context/memory, and admin features.
  - Preserve DB schema and data in `db/schema.sql` (SQLite + FTS5) and reuse existing data.
  - Maintain persona constraints (Ukrainian tone, plain text) and message formatting rules.
  - Provide a robust C++ runtime (async IO, logging, config, retry, backoff, metrics).
  - Ship Dockerized builds and CI to replace Python service when parity is proven.
- Non‑Goals (initial phases)
  - Re‑architecting product behavior or changing schema semantics.
  - GPU acceleration or large IR redesign of retrieval; focus on correctness first.
  - Supporting every optional tool on day one; port core first, then expand.

## Guardrails and Constraints

- DB is authoritative: keep schema in sync with `db/schema.sql` and mirror init/migrations in C++.
- Preserve middleware‑style DI: do not instantiate services inside handlers; pass injected singletons.
- Persona/system prompt: enforce plain text, Ukrainian tone; avoid Markdown in replies.
- Keep edits small; run Python and C++ services side‑by‑side until parity.

## Target C++ Stack

- Language/runtime: C++20 (or C++23 if available) with coroutines; event loop via Boost.Asio.
- Build: CMake; package manager via Conan or vcpkg.
- Logging: spdlog (async, rotating file sinks).
- Config: environment variables (load `.env` via simple loader or inject via container env).
- HTTP: libcurl (via cpr or curlpp) for REST to Gemini and external tools.
- JSON: nlohmann/json.
- SQLite: sqlite3 with SQLiteCpp (or sqlite_modern_cpp). FTS5 retained for keyword retrieval.
- Redis: optional future integration; current implementation provides in-process locks/rate limits with a compatible API surface.
- Telegram bot: custom HTTP client over `cpr` (long polling via `getUpdates`, `sendMessage`), no `tgbot-cpp` dependency.
- Vector search: start with in‑DB vector storage + cosine over JSON blobs; optional FAISS later.
- Timezone: C++20 `<chrono>` time zones (uses system zoneinfo); fallback Howard Hinnant date lib.
- Tests: GoogleTest + GoogleMock; integration harness for golden transcript comparison.

## High‑Level Architecture Mapping

- Entry and bootstrap
  - Python: `app/main.py` → C++: `src/main.cpp`, `src/core/bootstrap.cpp` for init/wiring.
  - Background tasks (retention, resource monitoring, donation scheduler): Asio timers + coroutines.
- DI and middleware
  - Python: `app/middlewares/chat_meta.py` → C++: simple interceptor layer that enriches handler context structures and injects singletons (Settings, Store, GeminiClient, Redis, etc.).
- Handlers
  - Python router modules under `app/handlers/` → C++: `src/handlers/` namespaced handlers; a dispatcher that maps Telegram updates to handler functions.
  - Core chat flow: `app/handlers/chat.py` → `src/handlers/chat.cpp` with tool registry and callbacks.
- Services
  - Context/memory: `app/services/context/` → `src/services/context/` with `MultiLevelContextManager`, `HybridSearchEngine`, `EpisodicMemoryStore` ports.
  - Context store: `app/services/context_store.py` → `src/services/context_store/` (message persistence, FTS writes, pruning).
  - Gemini: `app/services/gemini.py` → `src/services/gemini/` with text/embedding/image REST clients, quota logic, thinking mode.
  - Persona/templates: `app/persona.py` and persona loader → `src/services/persona/` reading templates from existing paths.
  - Rate limiting/throttle: `app/services/rate_limiter.py`, `app/middlewares/command_throttle.py` → `src/services/rate_limit/` using Redis TTL + Lua where needed.
  - Prompt manager, profile stores, bot learning, episode monitor/summarizer: mirror under `src/services/` and `src/repositories/`.
- Repositories
  - `app/repositories/*` → `src/repositories/*` (SQL kept identical; use prepared statements and transactions).

## Directory Layout (proposed)

```
src/
  core/              # bootstrap, wiring, settings, logging
  handlers/          # chat, admin, profile, prompt, chat_members
  middlewares/       # DI/interceptors: chat_meta, filters, locks, throttle
  services/
    context/         # MultiLevelContextManager, EpisodicMemoryStore, HybridSearchEngine
    gemini/          # REST client: text, embeddings, image
    tools/           # calculator, weather, currency, search, polls, images
    rate_limit/      # Redis rate limiter, feature limiter
    scheduler/       # donation reminders, periodic tasks
    persona/         # system persona + templates loader
  repositories/      # sqlite accessors (profiles, memory, messages, bot profiles)
  infrastructure/    # sqlite utils, redis utils, http utils
include/             # public headers
cmake/
tests/               # gtest suites + integration harness
```

## Core Features to Reproduce

1) Telegram update handling: long polling; HTML parse mode; error handling parity (bad requests, throttles).  
2) Persona and formatting: plain text Ukrainian outputs; same fallbacks and templates.  
3) Context store: message persistence, thread awareness, role handling, FTS5 mirroring, pruning task.  
4) Multi‑level context: hybrid search, episodic memory, token budget assembly.  
5) Tools: calculator, weather, currency, web search, polls; image generation (Gemini).  
6) Rate limiting and locking: per‑user/hour limits, command throttle, processing lock.  
7) Admin/profile/prompt routers: command registration, menu set‑up.  
8) Observability: structured logs, metrics hooks, resource monitoring.

## Migration Strategy (Phased)

Phase 0 — Preparation (Day 0–1)
- Choose package manager (Conan or vcpkg), pin compiler (GCC 12+/Clang 15+), enable C++20.
- Create CMake skeleton, CI job to build in Docker; wire spdlog and nlohmann/json.

Phase 1 — Settings, Logging, DB, Redis (Day 1–3)
- Implement `Settings` struct reading env vars (mirror Python names); validate on startup.
- Add SQLite and Redis clients; write DB init to enforce WAL + pragmas; run `schema.sql` if needed.
- Port `ContextStore` minimal subset: insert message, recent history fetch, pruning (timer).

Phase 2 — Gemini minimal client (Day 3–5)
- Implement REST client with API key rotation, quota blocking, retry/backoff, thinking mode flag handling.
- Text generation only; add embedding endpoint for later hybrid search.

Phase 3 — CLI harness and parity tests (Day 4–6)
- Build a CLI that accepts a transcript and emits a reply using the persona and minimal context.
- Generate golden transcripts from Python for fixed prompts; compare outputs for regression.

Phase 4 — Telegram bootstrap (Day 6–8)
- Integrate tgbot-cpp; long‑poll loop; set command menu; echo handler + basic error mapping.
- Implement DI/interceptor to inject services into handler context.

Phase 5 — Chat flow (Day 8–12)
- Port core chat handler: triggers, addressed‑to‑bot detection, safety fallbacks, typing indicators.
- Output formatting aligned to Telegram HTML rules and length constraints.

Phase 6 — Context retrieval (Day 12–16)
- Port FTS5 keyword retrieval and recent history fallback.
- Add embeddings storage and naïve cosine similarity over vectors stored as JSON arrays.
- Implement `MultiLevelContextManager.build_context(...)` parity with token budgeting.

Phase 7 — Tools (Day 16–21)
- Port calculator, currency, weather, web search, polls; share tool registry and callbacks.
- Add image generation service (Gemini image model) with quotas and error types mirrored.

Phase 8 — Episodic memory (Day 21–26)
- Port episode boundary detector, monitor with timers, summarizer; record/access episodes.
- Add importance scoring and access tracking; keep SQL semantics identical.

Phase 9 — Admin/profile/prompt (Day 26–30)
- Port admin and profile routers, prompt manager; ensure command throttle bypass for admins.
- Donation scheduler with TZ‑aware timers.

Phase 10 — Observability and hardening (Day 30–34)
- Structured logs, metrics counters; resource monitoring hooks; graceful shutdown and cleanup.

Phase 11 — Parity verification and cutover (Day 34–38)
- Expand golden transcript set; stress test rate limits, locks, media paths, and error surfaces.
- Ship Docker `bot-cpp` service; run side‑by‑side in staging; switch traffic via feature flag.

## Data and Schema

- Keep `db/schema.sql` as the single source of truth. On startup:
  - Set `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`.
  - Ensure all indexes and FTS5 virtual tables exist.
  - Avoid auto‑migrating destructive changes; gate migrations behind explicit env flag.
- Embeddings: store as JSON arrays in `messages.embedding` for parity; consider FAISS later.

## Telegram Integration Details

- Long polling first; add webhook later if needed. Respect rate limits and map common `TelegramBadRequest` cases to user‑safe fallbacks.
- HTML parse mode; guard output length; escape unsafe content; truncate with ellipsis similar to Python helper.

## Gemini Integration Details

- REST over HTTPS; model selection via env; support multi‑key rotation, free‑tier mode, thinking budget.
- Implement: text generate, embed, and image generation endpoints; standardize error taxonomy (quota, content blocked, network, retryable).
- Media: forward compatible with file URIs; treat YouTube URLs as special inputs when enabled.

## Redis, Locks, and Throttling

- Processing locks: per‑user mutex with expiry; use Redis SET NX + PX; avoid deadlocks.
- Rate limits: per user per hour window; store counters in Redis with TTL; mirror bypass for admins.
- Feature throttle: one command per 5 minutes via Redis keys; admins exempt.

## Build, Packaging, and Deployment

- CMake targets: `gryag-bot` (main service), `gryag-lib` (shared library of services), `gryag-tools` (optional CLI for scripts).
- Dependencies managed via Conan/vcpkg lockfiles; reproducible builds in CI.
- Docker: multi‑stage (build then slim runtime with only binary + CA certs + tzdata).
- Env vars parity: `TELEGRAM_TOKEN`, `GEMINI_API_KEY`/`GEMINI_API_KEYS`, `DB_PATH`, `USE_REDIS`, `REDIS_URL`, `ADMIN_USER_IDS`, `ENABLE_MULTI_LEVEL_CONTEXT`, `ENABLE_IMAGE_GENERATION`, `ENABLE_COMPACT_CONVERSATION_FORMAT`, plus existing feature toggles.

## Testing and Verification

- Unit tests: GoogleTest for settings, SQL repositories, utilities.
- Integration: spawn ephemeral SQLite DB and Redis; run chat flows end‑to‑end.
- Golden transcripts: export canonical transcripts from Python across scenarios; compare C++ outputs for semantic and formatting parity.
- Property tests (where feasible) for token budgeting and retrieval ordering.
- Load tests: basic throughput for long polling and context assembly.

## Risks and Mitigations

- Telegram library coverage: choose tgbot‑cpp for Bot API; if gaps surface (e.g., inline queries), evaluate TDLib.
- Gemini API evolution: isolate REST client behind a stable interface; add feature flags per capability.
- Vector search performance: start with naïve cosine; switch to FAISS if latency is high.
- Concurrency safety: enforce single writer principle for SQLite; use WAL, transactions, and prepared statements.
- Time zones and locales: depend on system zoneinfo; vendor tzdata in Docker image.
- Behavior drift: mitigate via golden tests and transcript diffing before cutover.

## Milestones and Deliverables

1) Skeleton builds, CI, Docker image boots and loads config.  
2) DB/Redis wired; minimal `ContextStore` with WAL and pruning task.  
3) Gemini text client integrated; CLI harness returns responses with persona.  
4) Telegram bot online with echo + commands.  
5) Chat flow parity with recent context fallback.  
6) Hybrid search + embeddings stored; budgeted context assembly.  
7) Core tools (calc, weather, currency, web search, polls).  
8) Image generation tool with quotas and error handling.  
9) Episodic memory + monitor/summarizer.  
10) Admin/profile/prompt features.  
11) Observability, hardening, golden transcripts pass; staged cutover.

## Rollout Plan

- Add `bot-cpp` service to `docker-compose.yml`; point to same SQLite path (backup first) and Redis.
- Gate activation by env flag; mirror traffic for selected chats to compare outputs.
- When parity achieved, point production token to C++ bot and keep Python on standby.

## Appendix: Python → C++ Mapping Reference

- Entry/bootstrap: `app/main.py` → `src/main.cpp`, `src/core/bootstrap.cpp`  
- Middleware DI: `app/middlewares/chat_meta.py` → `src/middlewares/chat_meta.hpp/cpp`  
- Chat flow: `app/handlers/chat.py` → `src/handlers/chat.hpp/cpp`  
- Context store: `app/services/context_store.py` → `src/services/context_store/*`  
- Multi‑level context: `app/services/context/*` → `src/services/context/*`  
- Gemini client: `app/services/gemini.py` → `src/services/gemini/*`  
- Repositories: `app/repositories/*` → `src/repositories/*`  
- Persona: `app/persona.py` + loader → `src/services/persona/*`  
- Throttle/locks: `app/middlewares/command_throttle.py`, `app/middlewares/processing_lock.py` → `src/middlewares/*`, `src/services/rate_limit/*`  
- Admin/profile/prompt: `app/handlers/*_admin.py`, `app/services/system_prompt_manager.py` → `src/handlers/*`, `src/services/*`

---

Questions or preferences (Conan vs vcpkg, tgbot-cpp vs TDLib, FAISS) can be decided at Phase 0; the default choices above optimize for fast parity with minimal risk.
