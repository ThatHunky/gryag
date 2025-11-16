# RFC: Handlers and Routing

Status: Proposed

Problem
- Many routers are registered in `app/main.py`, but ordering and middleware application constraints should be documented to prevent expensive work on filtered chats and to ensure callbacks receive DI context.

Evidence
- Router registration in `app/main.py` via `dispatcher.include_router(...)`.
- Middleware ordering: `ChatFilterMiddleware` before other processing; `CommandThrottleMiddleware` and `ProcessingLockMiddleware` applied to messages; callback query middleware also registered.

Options
1. Document current order and invariants; add tests to protect ordering.
2. Introduce a central registry where handlers declare requirements and auto-ordering occurs.

Recommendation
- Adopt (1). Document required ordering (filters first, locks, throttles, then functional handlers). Add a test to assert middleware registration order and router inclusion.

Impact
- Prevents performance regressions and missing DI for callbacks.

Effort
- S.

Risks
- None; documentation and tests only.

Acceptance Criteria
- Docs enumerate handler/middleware order and why it matters, with a code snippet showing correct registration sequence.


