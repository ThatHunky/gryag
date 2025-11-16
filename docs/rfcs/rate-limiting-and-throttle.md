# RFC: Rate-Limiting and Throttle Edge Cases

Status: Proposed

Problem
- Multiple rate limiting layers exist (per-user, feature-level, cooldowns). Documentation for precedence, admin bypass, Redis vs DB paths, and abuse scenarios is needed.

Evidence
- `app/main.py` initializes `RateLimiter` and `FeatureRateLimiter` with Redis client; command throttle middleware is applied; DB tables for `rate_limits`, `feature_rate_limits`, `feature_cooldowns`, and user reputation metrics exist in `db/schema.sql`.

Options
1. Document precedence (cooldown > feature > global), bypass rules for admins, and Redis as performance optimization with DB fallback.
2. Add metrics for throttled counts and reputation adjustments.

Recommendation
- Adopt (1) and (2). Provide a flowchart and add tests covering burst traffic, cooldown enforcement, and admin bypass.

Impact
- Predictable throttling and easier abuse triage.

Effort
- S–M.

Risks
- Over-throttling; provide emergency override flags and clear admin messaging.

Acceptance Criteria
- Docs list rules and examples; tests assert expected behavior under bursts and edge cases.


