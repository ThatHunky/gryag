# RFC: Feature Flags and Configuration Parity

Status: Proposed

Problem
- Numerous feature toggles exist (multi-level context, image generation, web search, self-learning, donation scheduler, compact format). Parity between `Settings`, `.env.example`, and docs must be ensured to prevent misconfiguration.

Evidence
- Flags referenced in `app/main.py` branches and `ChatMetaMiddleware` conditionals (e.g., `enable_multi_level_context`, `enable_image_generation`, `enable_web_search`, `enable_bot_self_learning`, `enable_persona_templates`).

Options
1. Document all flags, defaults, and interactions; validate at startup with warnings.
2. Generate `.env.example` from `Settings` with descriptions.

Recommendation
- Adopt (1) and (2). Add a docs table, ensure `Settings.validate_startup()` warns on incoherent combinations (e.g., chat memory disabled but chat facts requested).

Impact
- Fewer runtime surprises; faster setup.

Effort
- S.

Risks
- None.

Acceptance Criteria
- Docs contain full flag matrix; startup validation rules are documented with example warnings.


