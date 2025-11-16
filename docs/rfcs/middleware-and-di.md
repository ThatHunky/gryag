# RFC: Middleware and Dependency Injection

Status: Proposed

Problem
- Many services are injected via `ChatMetaMiddleware`, but the set of keys, lifecycle, and thread-safety (locks, caching) should be documented to avoid direct instantiation in handlers and ensure consistent behavior across messages and callbacks.

Evidence
- `app/middlewares/chat_meta.py` injects: `settings`, `store`, `gemini_client`, `profile_store`, `chat_profile_store`, `hybrid_search`, `episodic_memory`, `episode_monitor`, `bot_profile`, `bot_learning`, `prompt_manager`, `redis_client`, `rate_limiter`, `persona_loader`, `image_gen_service`, `feature_limiter`, `donation_scheduler`, `memory_repo`, `telegram_service`, plus `bot_username` and `bot_id`, and optionally `multi_level_context_manager`.
- Identity retrieval uses an `asyncio.Lock` and is lazily cached.

Options
1. Document all injected keys and expected usage patterns; add typing hints in handlers via parameters.
2. Introduce a DI container abstraction with explicit scopes.

Recommendation
- Adopt (1). Keep middleware-centric DI, document injected keys and handler signatures, and add a checklist for adding new services (init in main, inject in middleware, avoid handler instantiation).

Impact
- Consistency, fewer regressions, easier onboarding.

Effort
- S.

Risks
- None—documentation only.

Acceptance Criteria
- Docs enumerate injected keys and how to access them in handlers, with examples of handler signatures and data usage.


