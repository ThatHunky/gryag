# RFC: Persona and Response Format Enforcement

Status: Proposed

Problem
- Persona rules require plain-text, Ukrainian tone, and no Markdown in user-facing replies. Enforcement points and test coverage should be explicit to prevent regressions when handlers evolve.

Evidence
- Persona guidance referenced in repo rules; responses flow through chat handlers (`app/handlers/chat.py`) and template loaders (`PersonaLoader`) when enabled.

Options
1. Add response post-processor that validates format and strips Markdown if necessary.
2. Enforce via LLM system prompt only (risk of drift).
3. Add both prompt constraints and a lightweight sanitizer in output path.

Recommendation
- Adopt (3). Keep system prompt strictness and add a sanitizer step before sending messages: forbid Markdown, enforce tone markers if missing, and add tests.

Impact
- Consistent UX; fewer moderation issues.

Effort
- S.

Risks
- Over-sanitization; mitigated with allowlist of safe symbols and unit tests.

Acceptance Criteria
- Tests that assert no Markdown escapes to Telegram output and that messages follow persona tone guidelines.


