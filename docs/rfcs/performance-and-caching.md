# RFC: Performance and Caching

Status: Proposed

Problem
- Context assembly and hybrid search can be latency-sensitive; caches exist (immediate/recent caches in context manager, user weight cache in search), but cache policies and telemetry are not centrally documented.

Evidence
- `MultiLevelContextManager` caches immediate and recent contexts with TTL.
- `HybridSearchEngine` caches user interaction weights and uses timeouts + retries.
- Background tasks: resource monitoring and pruning tasks in `app/main.py`.

Options
1. Document current caches, TTLs, and invalidation triggers; add metrics around hits/misses.
2. Introduce a shared caching interface (Redis-backed) for multi-process environments.

Recommendation
- Adopt (1) and evaluate (2) if multi-process scaling is needed. Add timing histograms for context assembly phases and hybrid search sub-queries.

Impact
- Better SLO adherence and fewer timeouts.

Effort
- M.

Risks
- Over-caching stale data; mitigated with TTLs and invalidation on writes.

Acceptance Criteria
- Docs include cache tables (keys, TTL), and prescribed metrics with example dashboards.


