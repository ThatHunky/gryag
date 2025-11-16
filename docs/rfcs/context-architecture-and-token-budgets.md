# RFC: Context Architecture and Token Budgets

Status: Proposed

Problem
- Multi-level context is powerful but complex; token budgeting, media limits, and dynamic budget allocation must be explicitly documented and validated against real usage to avoid overruns and slow responses.

Evidence
- Core assembly and budgeting in `app/services/context/multi_level_context.py` (`MultiLevelContextManager.build_context`, `_truncate_to_budget`, `_truncate_snippets_to_budget`).
- Dynamic budgeting uses `token_optimizer.calculate_dynamic_budget` and accurate estimators.
- Media limiting in `format_for_gemini` with `gemini_max_media_items`.
- Hybrid search relevance pruning and dedup in `_get_relevant_context`.

Options
1. Keep current design; add documentation, invariants, and tests.
2. Introduce per-level hard ceilings and telemetry alerts when exceeded.
3. Add configurable profiles (compact vs verbose) and auto-switch on latency.

Recommendation
- Adopt (1) and (2). Document per-level budgets; enforce hard ceilings and log budget breaches with counters. Provide two output formatters (JSON and compact) with selection via settings.

Impact
- Predictable token usage, fewer model errors, improved performance insight.

Effort
- M (docs + tests + minor guardrails).

Risks
- Over-truncation on edge cases; mitigated with tests and telemetry thresholds.

Acceptance Criteria
- Docs outline levels, budgets, and media limits with examples.
- Tests validate truncation under constrained budgets and media-heavy histories.
- Telemetry counters for budget usage per level are referenced and thresholds documented.


