# Docs

This folder contains the repository documentation organized into subfolders. When moving or reorganizing docs, follow the rules in `AGENTS.md` and add a short summary here describing the change.

Structure recommended:

- docs/overview/ — high-level project overviews
- docs/plans/ — implementation plans and roadmaps
- docs/phases/ — phase-specific writeups and status reports
- docs/features/ — feature specs
- docs/guides/ — operational guides and runbooks
- docs/history/ — transient exports or archived notes (optional)

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
