# RFC: Image Generation and Optional Features

Status: Proposed

Problem
- Image generation, web search, and other optional features should degrade gracefully when disabled and enforce quotas/rate-limits when enabled.

Evidence
- Image generation initialization in `app/main.py` gated by `enable_image_generation`, with daily limits and optional separate API key. Web search logging toggled via `enable_web_search`.

Options
1. Document feature gates, quotas, cooldowns, and admin bypass; add tests for disabled-state behavior.
2. Centralize feature policy in one module for consistency.

Recommendation
- Adopt (1) and evaluate (2). Provide clear user/admin messaging when features are disabled and document configuration knobs.

Impact
- Predictable UX and safer resource usage.

Effort
- S.

Risks
- None.

Acceptance Criteria
- Docs list gates and quota logic; tests cover disabled/enabled paths and admin bypass behavior.


