# RFC: CI/CD and Makefile Modernization

Status: Proposed

Problem
- Ensure CI uses `.venv` invocations, enforces tests/coverage, lints/formatting, and uses `docker compose` (not deprecated `docker-compose`). Makefile should provide consistent developer entrypoints.

Evidence
- `Makefile` exists; CI config not shown here—document expected targets and behaviors for future alignment.

Options
1. Define standard Make targets: `setup`, `lint`, `format`, `test`, `typecheck`, `run`, `docker-build`, `docker-up`.
2. Enforce CI pipeline stages with cache and artifacts.

Recommendation
- Adopt (1) and (2). Ensure CI uses `.venv/bin/pytest tests/` and `docker compose up bot` for smoke tests.

Impact
- Reliable automation and developer consistency.

Effort
- M.

Risks
- None.

Acceptance Criteria
- Docs list targets and CI stages; pipeline includes test+coverage gates and smoke test job.


