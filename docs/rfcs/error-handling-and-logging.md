# RFC: Error Handling and Logging

Status: Proposed

Problem
- Errors across async tasks, background jobs, and I/O boundaries must be consistently logged and surfaced. Structured logs and correlation IDs aid diagnosis; current logging is present but policies and mandatory fields are not documented.

Evidence
- `app/main.py` initializes logging via `app.core.logging_config.setup_logging`, and logs configuration issues, task cleanup, and service init. Background tasks (monitoring, pruning) log exceptions.

Options
1. Document logging levels, fields, and correlation strategy (chat_id, user_id, message_id).
2. Add a logging helper to standardize extra fields and error wrapping.

Recommendation
- Adopt (1) and (2). Define required log fields and a small utility that enriches logs. Add tests to ensure error paths emit expected logs.

Impact
- Faster incident resolution and better observability.

Effort
- M.

Risks
- Log volume; mitigate with sampling for debug and guardrails.

Acceptance Criteria
- Docs define required fields, sampling policy, and example log lines; tests assert presence of correlation fields on error logs.


