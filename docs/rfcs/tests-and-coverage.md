# RFC: Tests and Coverage Strategy

Status: Proposed

Problem
- Complex flows (context assembly, hybrid search fallbacks, middleware DI, throttling) need robust tests. Coverage thresholds and fixtures should be documented to preserve behavior under refactors.

Evidence
- Async flows across `MultiLevelContextManager`, `HybridSearchEngine`, middleware injection, and background tasks.

Options
1. Establish coverage gate (e.g., 80%) and define fixtures for DB (Postgres), Redis, and Telegram client stubs.
2. Add contract tests for handler middleware ordering and DI keys.

Recommendation
- Adopt (1) and (2). Provide pytest fixtures using `.venv/bin/pytest tests/` in CI, and document how to run locally.

Impact
- Safer iteration; quicker validation of changes.

Effort
- M.

Risks
- Test flakiness; mitigate with deterministic time helpers and seeded data.

Acceptance Criteria
- Docs include coverage target, fixtures outline, and example tests to validate context assembly under constrained budgets and timeouts.


