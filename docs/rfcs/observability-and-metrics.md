# RFC: Observability and Metrics

Status: Proposed

Problem
- While logs are present, a clear metrics catalog (counters, histograms) for key operations is missing from docs, limiting visibility into latency and token usage.

Evidence
- `MultiLevelContextManager` increments telemetry counters when `enable_token_tracking` is true; timing data is logged.

Options
1. Define metrics for context assembly timings, token usage per level, hybrid search timings, cache hit ratios, and error rates.
2. Provide example exporters/integration (Prometheus, OTLP) and dashboards.

Recommendation
- Adopt (1); optionally (2) with a pluggable telemetry module and docs on enabling exporters.

Impact
- Faster performance diagnosis and capacity planning.

Effort
- S–M.

Risks
- Metric cardinality; limit labels to chat_id/thread_id scopes where necessary or sample.

Acceptance Criteria
- Docs list metrics and units with suggested alert thresholds and dashboard sketches.


