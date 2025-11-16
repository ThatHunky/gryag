# RFC: Security and Secrets Hygiene

Status: Proposed

Problem
- The bot integrates with external APIs and stores user/chat data. Input sanitization, prompt injection protections, and secrets handling need explicit policies and checks.

Evidence
- Persona and context assembly sanitize text and redact debug markers; external services are initialized and cleaned up in `app/main.py`.

Options
1. Document secrets handling (env-only, `.env.example`), input validation for commands, and prompt-injection mitigations (strip system-like instructions from user inputs when embedding/searching).
2. Add a central sanitizer for inbound messages before persistence.

Recommendation
- Adopt (1) and evaluate (2). Ensure no secrets in logs, validate ENV presence at startup, and document rotation guidance.

Impact
- Reduced risk of data leaks and prompt injection.

Effort
- S.

Risks
- Over-sanitization; keep allowlists for safe patterns.

Acceptance Criteria
- Docs list required env vars, rotation policy, and input validation rules for commands and message ingestion.


