## CHANGELOG for docs/ reorganization

2025-10-02 — Top-level docs moved into `docs/` folders to improve repo organization.

Files moved (git history preserved via `git mv`):

docs/overview/

- PROJECT_OVERVIEW.md
- CONTINUOUS_LEARNING_INDEX.md
- CHAT_ANALYSIS_INSIGHTS.md

docs/plans/

- IMPLEMENTATION_PLAN_SUMMARY.md
- INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md
- LOCAL_FACT_EXTRACTION_PLAN.md
- USER_PROFILING_PLAN.md
- TOOLS_IMPLEMENTATION_PLAN.md
- NEXT_STEPS_PLAN_I5_6500.md
- IMPROVEMENTS_SUMMARY.md

docs/phases/

- PHASE_1_COMPLETE.md
- PHASE_1_TESTING.md
- PHASE_2_COMPLETE.md
- PHASE_2_SUMMARY.md
- PHASE_2_TESTING.md
- PHASE_2_FACT_QUALITY_TESTING.md
- PHASE_3_SUMMARY.md
- PHASE_3_TESTING_GUIDE.md
- PHASE_3_TESTING_STATUS.md
- PHASE_3_IMPLEMENTATION_COMPLETE.md
- PHASE_3_VALIDATION_SUMMARY.md
- PHASE_4_PLANNING_COMPLETE.md
- PHASE_4_IMPLEMENTATION_PLAN.md
- PHASE_4_IMPLEMENTATION_COMPLETE.md
- PHASE_4_COMPLETE_SUMMARY.md

docs/features/

- HYBRID_EXTRACTION_COMPLETE.md
- HYBRID_EXTRACTION_IMPLEMENTATION.md

docs/guides/

- TOOL_LOGGING_GUIDE.md
- PHASE_3_TESTING_GUIDE.md

docs/history/

- (moved .specstory history files)

docs/other/

- IMPLEMENTATION_COMPLETE.md
- USER_PROFILING_STATUS.md

Verification steps (manual):

1. Confirm files exist under `docs/`:

   grep -n "#" docs -R | head -n 10

2. Quick git sanity check (should show renames):

   git log --name-status --pretty="%h %ad %s" --date=short | head -n 40

3. Optional tests (if you can run the environment):

   python -m pytest -q

Notes:

- Relative links inside moved files may need updating; run a link-checker or `grep -R "(.md)" docs` to find internal references.
- If you prefer `git mv` for some files that were moved outside of git, follow up with `git mv <src> <dest>` to preserve history; most files were moved with `git mv` in this change.
