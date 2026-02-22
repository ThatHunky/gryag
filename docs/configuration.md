# Gryag V2 — Configuration Reference

All values are configured via environment variables. Copy `.env.example` to `.env` and fill in secrets.

## Telegram

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `ADMIN_IDS` | — | Comma-separated admin Telegram user IDs |
| `ALLOWED_CHAT_IDS` | — | Comma-separated chat IDs (DMs and groups) the bot responds to; empty = allow all |
| `TELEGRAM_MODE` | `polling` | `polling` (dev) or `webhook` (prod) |
| `WEBHOOK_URL` | — | Public URL for webhook mode |
| `WEBHOOK_SECRET` | — | Webhook verification secret |

## LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *required* | Google AI Studio API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name. **This app needs function calling (tools).** Per [Gemini models](https://ai.google.dev/gemini-api/docs/models), only some models support it (e.g. `gemini-3-flash-preview` lists "Function calling: Supported"). If you see "Tool use with function calling is unsupported by the model", set this to a model that supports tools. |
| `GEMINI_TEMPERATURE` | `0.9` | Creative temperature for responses |
| `GEMINI_ROUTING_TEMPERATURE` | `0.0` | Deterministic temperature for tool routing |
| `GEMINI_THINKING_BUDGET` | `0` | Budget for Gemini 2.0 Thinking models (0 = disabled, e.g., 1024) |
| `OPENAI_API_KEY` | — | Optional OpenAI key for fallback routing |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |

### Model and function calling (tools)

This app sends **tools** (function declarations) to the model for memory, search, image gen, etc. The Gemini API only accepts that for models that support function calling.

- **What we know from Google’s docs:** The [Gemini 3 Flash Preview](https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview) capability table lists **"Function calling: Supported"**. The [function calling guide](https://ai.google.dev/gemini-api/docs/function-calling) uses `gemini-3-flash-preview` in examples.
- **What we saw in practice:** With `gemini-2.5-flash`, the API can return `Tool use with function calling is unsupported by the model` (400 INVALID_ARGUMENT). So that model, on the Gemini API at least, does not support tool use in this setup.
- **What to do:** If you get that error, set `GEMINI_MODEL` to a model whose docs say it supports function calling (e.g. `gemini-3-flash-preview`). You can also call the [models API](https://ai.google.dev/api/models) (e.g. `models.get`) to see each model’s supported features. Support is per model and per API (Gemini API vs Vertex can differ).

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `gryag-postgres` | PostgreSQL hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL port (internal Docker network) |
| `POSTGRES_USER` | `gryag` | Database user |
| `POSTGRES_PASSWORD` | `changeme_in_production` | Database password |
| `POSTGRES_DB` | `gryag` | Database name |
| `REDIS_HOST` | `gryag-redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port (internal Docker network) |
| `REDIS_PASSWORD` | — | Redis password (empty = no auth) |

## Backend Server

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_HOST` | `0.0.0.0` | Listen address |
| `BACKEND_PORT` | `27710` | Listen port (non-standard) |

## Feature Toggles

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SANDBOX` | `true` | Enable Python code execution |
| `ENABLE_IMAGE_GENERATION` | `true` | Enable Gemini 3 Pro Image Preview image gen (uses GEMINI_API_KEY) |
| `ENABLE_PROACTIVE_MESSAGING` | `false` | Enable proactive messages (random timing within active hours, Kyiv time) |
| `ENABLE_WEB_SEARCH` | `true` | Enable the `search_web` tool (Gemini Grounding). When enabled, the model can search the web for news/facts; used in chat and by proactive messaging (30% news path). |
| `ENABLE_VOICE_STT` | `false` | Enable voice-to-text processing |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_GLOBAL_PER_MINUTE` | `10` | Max requests per chat per minute |
| `RATE_LIMIT_USER_PER_MINUTE` | `3` | Max requests per user per minute |
| `RATE_LIMIT_IMAGE_PER_DAY` | `5` | Max image generations per day |
| `RATE_LIMIT_SANDBOX_PER_DAY` | `20` | Max sandbox executions per day |

## Sandbox

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_TIMEOUT_SECONDS` | `5` | Max execution time |
| `SANDBOX_MAX_MEMORY_MB` | `128` | RAM limit for sandbox container |

Image generation uses the same `GEMINI_API_KEY` and model `gemini-3-pro-image-preview`; no separate key or URL is required.

## Context & Memory

| Variable | Default | Description |
|----------|---------|-------------|
| `IMMEDIATE_CONTEXT_SIZE` | `50` | Number of recent messages in context |
| `MEDIA_BUFFER_MAX` | `10` | Max media items in context |
| `PERSONA_FILE` | `config/persona.txt` | Path to hot-swappable persona file |
| `PROACTIVE_ACTIVE_HOURS_KYIV` | `9-22` | Active hours for proactive messages in Kyiv time (e.g. 9-22 = 09:00–22:00); triggers are random within this window |
| `MESSAGE_RETENTION_DAYS` | `90` | Delete messages older than N days on startup (0 = keep forever) |

## Localization

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCALE_DIR` | `config/locales` | Directory containing JSON locale files |
| `DEFAULT_LANG` | `uk` | Default language code (must match a .json file) |
