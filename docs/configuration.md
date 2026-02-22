# Gryag V2 — Configuration Reference

All values are configured via environment variables. Copy `.env.example` to `.env` and fill in secrets.

## Telegram

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `ADMIN_IDS` | — | Comma-separated admin Telegram user IDs |
| `TELEGRAM_MODE` | `polling` | `polling` (dev) or `webhook` (prod) |
| `WEBHOOK_URL` | — | Public URL for webhook mode |
| `WEBHOOK_SECRET` | — | Webhook verification secret |

## LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *required* | Google AI Studio API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name for generation |
| `GEMINI_TEMPERATURE` | `0.9` | Creative temperature for responses |
| `GEMINI_ROUTING_TEMPERATURE` | `0.0` | Deterministic temperature for tool routing |
| `GEMINI_THINKING_BUDGET` | `0` | Budget for Gemini 2.0 Thinking models (0 = disabled, e.g., 1024) |
| `OPENAI_API_KEY` | — | Optional OpenAI key for fallback routing |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |

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
| `ENABLE_IMAGE_GENERATION` | `true` | Enable Nano Banana Pro image gen |
| `ENABLE_PROACTIVE_MESSAGING` | `false` | Enable cron-based proactive messages |
| `ENABLE_WEB_SEARCH` | `true` | Enable Google Search Grounding |
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

## Image Generation

| Variable | Default | Description |
|----------|---------|-------------|
| `NANO_BANANA_API_KEY` | — | API key for Nano Banana Pro |
| `NANO_BANANA_API_URL` | — | Base URL for the image gen API |

## Context & Memory

| Variable | Default | Description |
|----------|---------|-------------|
| `IMMEDIATE_CONTEXT_SIZE` | `50` | Number of recent messages in context |
| `MEDIA_BUFFER_MAX` | `10` | Max media items in context |
| `PERSONA_FILE` | `config/persona.txt` | Path to hot-swappable persona file |
| `PROACTIVE_CRON_SCHEDULE` | `0 */4 * * *` | Cron schedule for proactive messages |
| `MESSAGE_RETENTION_DAYS` | `90` | Delete messages older than N days on startup (0 = keep forever) |

## Localization

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCALE_DIR` | `config/locales` | Directory containing JSON locale files |
| `DEFAULT_LANG` | `uk` | Default language code (must match a .json file) |
