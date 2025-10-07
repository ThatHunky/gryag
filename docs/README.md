# Docs

This folder contains the repository documentation organized into subfolders. When moving or reorganizing docs, follow the rules in `AGENTS.md` and add a short summary here describing the change.

Structure recommended:

- docs/overview/ — high-level project overviews
- docs/plans/ — implementation plans and roadmaps
- docs/phases/ — phase-specific writeups and status reports
- docs/features/ — feature specs
- docs/guides/ — operational guides and runbooks
- docs/history/ — transient exports or archived notes (optional)

## Recent Changes

**October 7, 2025**: Completed **Phase 2: Universal Bot Configuration** - Bot now supports multiple deployments with different identities. Added dynamic command prefixes (17 commands support both `/gryag*` and `/{prefix}*`), chat filter middleware (whitelist/blacklist modes), configurable trigger patterns, Redis namespace isolation, and `/chatinfo` command. All configurable via `.env` without code changes. See `docs/phases/UNIVERSAL_BOT_PHASE_2_COMPLETE.md`. Verification: `grep -r "ChatFilterMiddleware\|initialize_triggers\|chatinfo_command" app/ | wc -l` (should show 5+ matches)

**October 7, 2025**: Added **System Prompt Management** feature - admins can now customize bot personality via Telegram commands. Created `SystemPromptManager` service with database persistence, version history, and rollback. New commands: `/gryagprompt`, `/gryagsetprompt`, `/gryagresetprompt`, `/gryagprompthistory`, `/gryagactivateprompt`. Supports global and chat-specific prompts with file upload. See `docs/features/SYSTEM_PROMPT_MANAGEMENT.md`. Verification: `sqlite3 gryag.db ".schema system_prompts" && grep -c "def.*prompt" app/handlers/prompt_admin.py` (should show table + 5 handlers)

**October 7, 2025**: Removed local model infrastructure - bot now uses Google Gemini API exclusively. Deleted Phi-3-mini local model support, llama-cpp-python dependency, simplified fact extraction to 2-tier (rule-based + Gemini fallback). Updated 8 files, removed 2 services. Fact extraction now cloud-only via `ENABLE_GEMINI_FACT_EXTRACTION=true`. Verification: `! grep -r "LOCAL_MODEL" app/ && grep "enable_gemini_fact_extraction" app/config.py`

**October 7, 2025**: Added comprehensive universal bot configuration plan in `docs/plans/UNIVERSAL_BOT_PLAN.md`. This plan details how to transform the hardcoded gryag bot into a configurable universal framework supporting multiple personalities, languages, and group chat deployments. Verification: `grep -n "universal\|configurable\|persona" docs/plans/UNIVERSAL_BOT_PLAN.md`

**October 7, 2025**: Completed Phase 1 of universal bot configuration - configuration infrastructure. Added persona abstraction layer (`app/services/persona/`), created YAML persona configs (`personas/`), JSON response templates (`response_templates/`), and updated settings with 18 new configuration fields. See `docs/phases/UNIVERSAL_BOT_PHASE_1_COMPLETE.md` for details. Verification: `ls -la personas/ response_templates/ && python3 -c "import yaml; yaml.safe_load(open('personas/ukrainian_gryag.yaml'))"`

Verification: If you move or add files, update this README with a one-line note and a link to changed files.


Suggested top-level organization (proposal):

- docs/overview/
  - PROJECT_OVERVIEW.md
  - README.md (kept at root for quick start)
- docs/plans/
  - IMPLEMENTATION_PLAN_SUMMARY.md
  - INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md
  - IMPLEMENTATION_COMPLETE.md
- docs/phases/
  - PHASE_1_COMPLETE.md
  - PHASE_2_COMPLETE.md
  - PHASE_3_SUMMARY.md
  - PHASE_4_COMPLETE_SUMMARY.md
- docs/features/
  - USER_PROFILING_PLAN.md
  - LOCAL_FACT_EXTRACTION_PLAN.md
  - TOOL_LOGGING_GUIDE.md
- docs/guides/
  - PHASE_3_TESTING_GUIDE.md
  - PHASE_2_TESTING.md

If you accept this organization, move the files using `git mv` and add a short note here listing moved files and a verification step (e.g. run tests or a quick grep for top-level md files).

Recent changes:

- 2025-10-06: Added **Continuous Learning Improvements Plan** (`plans/CONTINUOUS_LEARNING_IMPROVEMENTS.md`) analyzing why fact extraction barely works and providing 4-phase improvement roadmap. Quick fix applied to `.env` (hybrid extraction, lower threshold, disabled filtering). See `guides/QUICK_START_LEARNING_FIX.md` for immediate verification steps.
- 2025-10-06: Added comprehensive **Memory and Context Improvements Plan** (`plans/MEMORY_AND_CONTEXT_IMPROVEMENTS.md`) based on thorough codebase analysis. Covers multi-level context, hybrid search, episodic memory, fact graphs, temporal awareness, and adaptive memory management. 14-week implementation roadmap with 6 phases.
# Documentation Index

This directory contains comprehensive documentation for the gryag project, organized by category.

## Recent Changes

**October 7, 2025**: Added forget_fact Tool (Phase 5.1+)
- ✅ **New Tool**: `forget_fact` - Soft delete facts with audit trail
- 🔄 **Configuration**: Disabled automated memory systems, now tool-based only
- 📊 **Testing**: 12 tests passing (added 3 forget tests)
- 🎯 **Use Cases**: User privacy requests, obsolete data cleanup
- ⚡ **Performance**: 60-90ms latency for forget operations
- 🔧 **Breaking**: Automated fact extraction and continuous monitoring now disabled
- See: `docs/CHANGELOG.md` (2025-10-07 entry)
- Verification: `python test_memory_tools_phase5.py` (should pass all 12 tests)
- Config: `.env` now has `ENABLE_TOOL_BASED_MEMORY=true`, automation disabled

**October 3, 2025**: Phase 5.1 Complete - Tool-Based Memory Control
- ✅ **Implementation Complete**: 3 core memory tools with Gemini function calling
- Tools: `remember_fact` (store), `recall_facts` (search), `update_fact` (modify)
- Model now decides when to remember/update facts instead of automated heuristics
- Performance: 70-140ms latency (well within 200ms target)
- Testing: 9 integration tests (all passing ✅)
- Configuration: 5 new settings (`ENABLE_TOOL_BASED_MEMORY`, `MEMORY_TOOL_ASYNC`, etc.)
- Files: 6 new (`app/services/tools/`, 3 plan docs), 4 modified (handler, config, persona, docs)
- See: `phases/PHASE_5.1_COMPLETE.md`, `plans/MEMORY_TOOL_CALLING_REDESIGN.md`
- Verification: `python test_memory_tools_phase5.py` (should pass all 9 tests)
- Next: Phase 5.2 (6 additional tools: episodes, forget, merge)

**October 7, 2025**: Memory System Redesign Plan
- 📋 **New Plan**: Tool-based memory management using Gemini function calling
- Shift from automated heuristics to model-controlled memory operations
- 9 new tools: remember_fact, recall_facts, update_fact, create_episode, forget_fact, merge_facts, etc.
- Async orchestrator for non-blocking memory operations (< 200ms overhead)
- 3-week implementation roadmap (Phase 5.1-5.3)
- See: `plans/MEMORY_TOOL_CALLING_REDESIGN.md`
- Verification: `grep -c "Function Declaration" docs/plans/MEMORY_TOOL_CALLING_REDESIGN.md` (should show 9)

**October 7, 2025**: Bot Self-Learning Integration Analysis
- 🔴 **Critical Issue Found**: Bot self-learning infrastructure exists but is never called from chat handler
- Root cause: Missing integration between `app/handlers/chat.py` and `BotLearningEngine`
- All services implemented but unused - 0 interactions tracked despite `ENABLE_BOT_SELF_LEARNING=true`
- Detailed fix plan: `docs/fixes/BOT_SELF_LEARNING_INTEGRATION_FIX.md` (requires ~6-9 hours implementation)
- Verification: Check `/gryagself` shows 0 interactions despite bot responding normally

**October 7, 2025**: Added time awareness to bot
- ✅ Bot now receives current timestamp with every message
- ✅ Format: "The current time is: {Day}, {Month} {Date}, {Year} at {HH:MM:SS}"
- ✅ Enables time-aware responses and context-appropriate greetings
- ✅ Negligible performance impact (<1ms per message)
- See: `features/TIME_AWARENESS.md`, `CHANGELOG.md` (2025-10-07 entry)
- Verification: `python3 test_timestamp_feature.py` to see format, or ask bot "What time is it?"

**October 6, 2025**: Bug fixes for Bot Self-Learning and User Profiling
- Fixed KeyError in Gemini fact extraction prompt (`app/services/user_profile.py` lines 36-46)
- Fixed AttributeError in `/gryaginsights` command (`app/services/bot_learning.py` line 394)
- Fixed UNIQUE constraint violation in `bot_profiles` table (`db/schema.sql`)
- See `docs/fixes/fact_extraction_keyerror_fix.md`, `docs/fixes/bot_learning_gemini_response_fix.md`, and `docs/CHANGELOG.md`
- Verification: `docker compose logs --since <restart_time> bot | grep -E "KeyError.*facts|AttributeError"` (should show no errors)

**October 6, 2025**: Phase 5 Complete - Bot Self-Learning System
- ✅ Bot learns about itself: tracks effectiveness, communication patterns, knowledge gaps
- ✅ 8 fact categories: communication_style, knowledge_domain, tool_effectiveness, user_interaction, persona_adjustment, mistake_pattern, temporal_pattern, performance_metric
- ✅ Semantic deduplication with embeddings (85% similarity threshold)
- ✅ Temporal decay for outdated facts (exponential: confidence * exp(-decay_rate * age_days))
- ✅ Gemini-powered self-reflection insights (weekly)
- ✅ Two new Gemini tools: query_bot_self, get_bot_effectiveness
- ✅ Admin commands: /gryagself, /gryaginsights
- ✅ Integrates with episodic memory for conversation-level learning
- ✅ Performance tracking: response_time_ms, token_count, sentiment_score
- ✅ 6 new database tables, 15 indexes
- See: `features/BOT_SELF_LEARNING.md`, `phases/PHASE_5_IMPLEMENTATION_SUMMARY.md`
- Verification: `sqlite3 gryag.db ".tables" | grep bot_` should show 6 tables

**October 6, 2025**: Critical bug fixes and improvements
- ✅ Fixed dependency management inconsistency (pyproject.toml now synced with requirements.txt)
- ✅ Added configuration weight validation for hybrid search
- ✅ Improved exception handling and logging across handlers
- See: `fixes/CRITICAL_IMPROVEMENTS_OCT_2025.md`
- Verification: `make test` should pass, config validation catches invalid weights

**October 6, 2025**: Fixed unaddressed media persistence bug
- ✅ Bot can now see images in past messages when tagged in replies
- ✅ All messages (addressed + unaddressed) now persisted to database with media
- ✅ Embeddings generated for all messages for semantic search
- ✅ Multi-level context includes complete media history
- See: `fixes/UNADDRESSED_MEDIA_PERSISTENCE.md`
- Verification: Send image without tagging bot, then reply and tag bot asking about image

**October 6, 2025**: Documentation reorganization - Phase and feature docs moved to proper folders
- Moved: `PHASE1_COMPLETE.md` → `docs/phases/PHASE_1_COMPLETE.md`
- Moved: `PHASE2_COMPLETE.md` → `docs/phases/PHASE_2_COMPLETE.md`
- Moved: `PHASE2_QUICKREF.md` → `docs/phases/PHASE_2_QUICKREF.md`
- Moved: `PHASE_4_1_*.md` → `docs/phases/` (2 files)
- Moved: `PHASE_4_2_*.md` → `docs/phases/` (6 files)
- Moved: `MULTIMODAL_*.md` → `docs/features/` (2 files)
- Moved: `QUICKSTART_PHASE1.md` → `docs/guides/`
- Moved: `QUICKREF.md` → `docs/guides/QUICKREF.md`
- Moved: `IMPLEMENTATION_SUMMARY.md` → `docs/plans/`
- Moved: `PROGRESS.md` → `docs/plans/`
- Verification: `ls *.md | grep -E "PHASE|MULTIMODAL|QUICKREF|IMPLEMENTATION|PROGRESS"` should return only `AGENTS.md` and `README.md`

**October 6, 2025**: Phase 4.1 Complete - Episode Boundary Detection
- ✅ Automatic boundary detection using 3 signals (semantic, temporal, topic markers)
- ✅ Multi-signal scoring with weighted combination
- ✅ Comprehensive test suite (24/24 tests passing)
- ✅ Configuration for all thresholds
- ✅ Support for Ukrainian and English topic markers
- ✅ Ready for Phase 4.2 (automatic episode creation)
- See: `phases/PHASE_4_1_COMPLETE.md`, `guides/EPISODE_BOUNDARY_DETECTION_QUICKREF.md`

**January 5, 2025**: Phase 3 Integration Complete - Multi-Level Context in Chat Handler
- ✅ Integrated multi-level context manager into chat handler
- ✅ Services initialized in main.py (hybrid search, episodic memory)
- ✅ Middleware injects services into handler
- ✅ Handler uses 5-layer context when enabled
- ✅ Graceful fallback to simple history
- ✅ Integration tests passing
- ✅ Production ready with monitoring
- See: `phases/PHASE_3_INTEGRATION_COMPLETE.md`

**January 5, 2025**: Completed Phase 3 of Memory and Context Improvements
- ✅ Multi-level context manager (580 lines)
- ✅ Five-layer context assembly (immediate, recent, relevant, background, episodic)
- ✅ Parallel retrieval with <500ms latency
- ✅ Token budget management with configurable allocation
- ✅ Comprehensive test suite (4 tests passing)
- See: `phases/PHASE_3_COMPLETE.md`

**October 6, 2025**: Implemented Phase 1-2 of Memory and Context Improvements
- ✅ Database schema enhancements (FTS5, importance tracking, episodes)
- ✅ Hybrid search engine (semantic + keyword + temporal)
- ✅ Episodic memory infrastructure
- See: `plans/PHASE_1_2_COMPLETE.md` and `plans/MEMORY_IMPLEMENTATION_STATUS.md`

**October 2, 2025**: Large documentation reorganization
