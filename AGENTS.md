# AGENTS

This repository accepts limited automated edits from trusted agents. The rules below are short and designed to minimize surprise for human maintainers.

Short contract for agents:

- Readability: Keep edits small and focused. If you must change >3 files, add a brief `docs/CHANGELOG.md` entry and create `docs/README.md` describing the changes.
- Docs: Put long-form documentation under `docs/` (see `docs/README.md`) and prefer `git mv` for renames. Preserve relative links inside moved files.
- Tests & Validation: If you change runnable code, run the project's tests or a quick smoke run where possible and include the result in your commit message.
- No secrets: Never add secrets, tokens, or credentials to the repository. If a secret is required, note the required env var in a `.env.example` update.
- Backwards compatible: Avoid breaking public APIs. If a change is large and may break things, create a draft PR and describe the migration steps in `docs/README.md`.
- Transparency: For any multi-file change add a one-paragraph summary to `docs/README.md` describing what moved/was added and how to verify.

If you are human: Follow these rules too; they make reviews faster and safer.

## Suggested moves

There are many top-level Markdown files in the repository. If you are an agent tasked with cleaning up docs, consider moving these to `docs/` using `git mv` and then update `docs/README.md` with a one-line note listing moved files. A suggested mapping:

- docs/overview/: PROJECT_OVERVIEW.md
- docs/plans/: IMPLEMENTATION_PLAN_SUMMARY.md, INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md, IMPLEMENTATION_COMPLETE.md
- docs/phases/: PHASE_1_COMPLETE.md, PHASE_2_COMPLETE.md, PHASE_3_SUMMARY.md, PHASE_4_COMPLETE_SUMMARY.md
- docs/features/: USER_PROFILING_PLAN.md, LOCAL_FACT_EXTRACTION_PLAN.md, TOOL_LOGGING_GUIDE.md
- docs/guides/: PHASE_3_TESTING_GUIDE.md, PHASE_2_TESTING.md

If you move files:

1. Use `git mv <src> <dest>` so git history is preserved.
2. Add a one-line entry in `docs/README.md` listing moved files and a short verification command (for example: `python -m pytest -q` or `grep -n "PROJECT_OVERVIEW" docs -R`).
3. Run the project's quick sanity checks (lint/tests) when possible and include results in the commit message.

Note: On 2025-10-02 a large reorganization was performed and many top-level Markdown docs were moved into `docs/`. See `docs/CHANGELOG.md` for the full list and verification steps. If you intend to move additional files, follow the same process and add a changelog entry.

If you cannot run tests (no runtime available), still add the `docs/README.md` entry and a short note explaining why tests were skipped.
