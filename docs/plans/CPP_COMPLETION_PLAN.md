# gryag C++ Feature Parity Plan

Status: draft — outlines the staged work required to reach functional parity between the Python and C++ implementations of the gryag bot.

## 1. Feature Inventory & Gap Analysis

### 1.1 Core Runtime (Complete)
- ✅ Message persistence & context store (messages, bans, rate limits, WAL, retention)
- ✅ Gemini client (text, embeddings, image generation, function calling loop)
- ✅ Tool suite: weather, currency, polls, web search, chat search, memory, image generation
- ✅ Admin/profile commands (ban/unban/reset/chatinfo/donate/profile/users/facts)
- ✅ Persona loader & HTML-safe messaging
- ✅ Custom Telegram long-poll client over HTTP (cpr)

### 1.2 Remaining Python Features
- Chat admin handlers (`chat_admin`, throttles, chat-specific settings)
- Prompt admin handlers (`prompt_admin`, prompt manager, persona overrides)
- Background jobs
  - Donation scheduler (group cadence, per-chat toggles)
  - Episode monitoring (boundary detection, summarisation, episodic store updates)
  - Retention pruning loop (scheduled deletion)
  - Resource monitoring / optimisation (optional)
- Advanced context & search
  - Hybrid search with embeddings + FTS5
  - Episodic memory summarisation pipeline
  - Multi-level context token budgeting identical to Python behaviour
- Self-learning & analytics
  - Bot profile store, interaction outcomes, learning engine hooks
  - Telemetry / metrics parity (for future observability)
- Feature limiting & throttles
  - Command throttle logic port (per-feature limits, admin bypass)
  - Adaptive throttle / redis primitives (map to in-process equivalent or optional Redis backend)
- Media handling
  - Comprehensive media ingestion (documents, audio, images, video) with storage rules
  - Media tool helpers (collect_media_parts etc.)
- Integration & tooling
  - Golden transcript test suite (Python vs C++ outputs)
  - CI workflow for C++ build/tests
  - Developer tooling: lint, formatting, container images, scripted setup

## 2. Roadmap Overview

Phase | Scope | Outcomes
----- | ----- | --------
P1 | Infrastructure alignment | Decide on Redis vs in-process abstraction, confirm SQLite schema usage, outline telemetry hooks
P2 | Admin & prompt features | Port chat_admin and prompt_admin handlers, including prompt manager (SQLite-based) and command registration
P3 | Background services | Donation scheduler, retention pruning loop, episode monitoring (boundary detection, summariser, episodic store updates)
P4 | Advanced context | Implement embedding pipeline (Gemini embeddings stored in SQLite), FTS5 search integration, multi-level token budgeting parity
P5 | Memory & self-learning | Port bot self-learning engine, profile updates, memory repo extras, adaptive throttling
P6 | Media & tooling | Extend media handling, add golden transcript tests, integrate CI build, document operational runbooks

## 3. Detailed Phase Breakdown

### Phase 1 – Infrastructure Alignment
- **Redis abstraction**: finalize strategy (pure in-process with optional Redis support). Define interface used across throttles/locks.
- **Schema audit**: Confirm all required tables from `db/schema.sql` are covered (bot_profiles, bot_interaction_outcomes, episodic tables, etc.). Create SQLite migrations if needed.
- **Configuration parity**: Ensure `Settings` exposes toggles used by remaining features.
- **Deliverables**: Updated settings/infra modules, documented decisions, backlog refined per feature.

### Phase 2 – Admin & Prompt Features
- Port `chat_admin` functionality (fact limits, toggles, public memory management).
- Implement prompt manager (`SystemPromptManager`) with C++ SQLite bindings and prompt admin commands (list/set/reset prompts, persona overrides).
- Add feature flag command registration and per-chat command menus where applicable.
- Ensure command throttling/injection matches Python behaviour.
- **Deliverables**: C++ handlers mirroring Python responses, updated tool registry/command list, tests for admin flows.

### Phase 3 – Background Services
- Donation scheduler: intervals, per-chat rules, last-notified tracking.
- Retention pruning loop: scheduled task removing aged messages/memories.
- Episode monitoring: boundary detector, summariser, episodic store writes, optional background task.
- Resource monitoring/optimiser (if required in current deployment).
- **Deliverables**: Async task manager (likely `std::jthread`/`asio`), scheduler modules, config toggles validated.

### Phase 4 – Advanced Context
- Embedding storage: call Gemini embed API, store vectors (SQLite BLOB/JSON), migrations.
- FTS5 integration: mirror Python `messages_fts` usage, implement search rank logic.
- Multi-level context budgeting: port `MultiLevelContextManager` logic from Python, aligning token accounting, fallback strategies, persona enforcement.
- Hybrid search combining embeddings, FTS, episodic summaries.
- **Deliverables**: Full `MultiLevelContextManager` parity, tested context assembly across scenarios.

### Phase 5 – Memory & Self-Learning
- Bot self-learning engine: profiles, facts, interaction outcomes, summariser loops.
- Adaptive throttles, feature limiter, rate limit store parity.
- Memory repository extras: timeline exports, fact scoring, autopruning semantics.
- Telemetry hooks for learning events.
- **Deliverables**: Self-learning background tasks, admin integration (insights/self commands), validated storage updates.

### Phase 6 – Media & Tooling
- Media ingestion parity (documents, audio, video) with safe storage references.
- Golden transcript suite: selected real-world conversations exported from Python, replayed against C++ bot with assertion diffing.
- CI pipeline: Docker build, unit/integration tests, transcript run, artifact upload.
- Operational documentation: deployment checklist, monitoring expectations.
- **Deliverables**: CI config, test harness, extended docs, ready-for-prod signal.

## 4. Cross-Cutting Concerns
- **Error handling & logging**: standardize structured logging (spdlog) across modules.
- **Configuration management**: maintain `.env` parity, document new variables.
- **Testing**: unit tests for repositories/services, integration tests for handlers, transcript-based regression tests.
- **Docs**: update `docs/README.md` and feature guides per phase, note C++ service usage.

## 5. Next Steps
1. Review this plan with stakeholders and adjust scope/priorities.
2. Approve Phase 1 tasks (infra audit) and create tickets per bullet point.
3. Establish cadence (e.g., weekly progress checkpoints) and define success metrics (parity checklist, test coverage targets, operational sign-off).
4. Kick off Phase 1 implementation once priorities are confirmed.
