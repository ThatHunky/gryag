# Improvement Index

This index lists proposed RFCs to improve the repository. Each RFC includes Problem, Evidence, Options, Recommendation, Impact, Effort, Risks, and Acceptance criteria. No code changes are included in this phase.

Legend:
- Priority: P0 (urgent), P1 (important), P2 (nice-to-have)
- Effort: S (≤0.5d), M (1–3d), L (>3d)
- Status: Proposed (default)

| Area | RFC | Priority | Effort | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Context | [Context architecture and token budgets](rfcs/context-architecture-and-token-budgets.md) | P0 | M | Maintainers | Proposed |
| Database | [DB schema and migrations alignment](rfcs/db-schema-and-migrations.md) | P0 | M | Maintainers | Proposed |
| Handlers | [Handlers and routing](rfcs/handlers-and-routing.md) | P1 | S | Maintainers | Proposed |
| Middleware | [Middleware and DI](rfcs/middleware-and-di.md) | P1 | S | Maintainers | Proposed |
| Persona | [Persona and response format enforcement](rfcs/persona-and-response-format.md) | P0 | S | Maintainers | Proposed |
| Errors/Logging | [Error handling and logging](rfcs/error-handling-and-logging.md) | P1 | M | Maintainers | Proposed |
| Config | [Feature flags and config parity](rfcs/feature-flags-and-config.md) | P1 | S | Maintainers | Proposed |
| Testing | [Tests and coverage](rfcs/tests-and-coverage.md) | P0 | M | Maintainers | Proposed |
| Performance | [Performance and caching](rfcs/performance-and-caching.md) | P1 | M | Maintainers | Proposed |
| Security | [Security and secrets hygiene](rfcs/security-and-secrets.md) | P0 | S | Maintainers | Proposed |
| CI/CD | [CI/CD and Makefile modernization](rfcs/ci-cd-and-makefile.md) | P1 | M | Maintainers | Proposed |
| Docker/Runtime | [Docker and runtime](rfcs/docker-and-runtime.md) | P2 | S | Maintainers | Proposed |
| Observability | [Observability and metrics](rfcs/observability-and-metrics.md) | P1 | S | Maintainers | Proposed |
| DevEx | [Tooling and developer experience](rfcs/tooling-and-developer-experience.md) | P1 | S | Maintainers | Proposed |
| Images | [Image generation and optional features](rfcs/image-generation-and-optional-features.md) | P2 | S | Maintainers | Proposed |
| Throttle | [Rate-limiting and throttle](rfcs/rate-limiting-and-throttle.md) | P1 | S | Maintainers | Proposed |

Notes:
- All examples in RFCs should use virtualenv commands: `.venv/bin/python3 -m app.main`, `.venv/bin/pytest tests/`.
- DB changes must update `db/schema.sql` and mirrored initialization/migration code.


