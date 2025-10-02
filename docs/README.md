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

- 2025-10-02: Moved a large set of top-level documentation into this `docs/` tree (overview, plans, phases, features, guides, history). See `docs/CHANGELOG.md` for the full list and verification commands.
