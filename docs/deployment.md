# Gryag V2 — Deployment Guide

## Prerequisites

- Docker Engine 24+ with Docker Compose v2
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Gemini API Key (from [Google AI Studio](https://aistudio.google.com/))

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/ThatHunky/gryag.git
cd gryag

# 2. Copy and configure environment
cp .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, POSTGRES_PASSWORD

# 3. Boot the entire stack
docker compose up --build -d

# 4. Check health
curl http://localhost:27710/health
# → {"status":"ok"}

# 5. View logs
docker compose logs -f gryag-backend
docker compose logs -f gryag-frontend
```

## Service Topology

| Service | Image | Port | Health |
|---------|-------|------|--------|
| `gryag-frontend` | Python 3.12 | 27711 | `GET /health` |
| `gryag-backend` | Go 1.23 Alpine | 27710 | `GET /health` |
| `gryag-postgres` | postgres:18-alpine | 5432 (internal) | `pg_isready` |
| `gryag-redis` | redis:7-alpine | 6379 (internal) | `redis-cli ping` |
| `gryag-sandbox` | Python 3.12 slim | none | on-demand |

## Startup Order

Docker Compose enforces this via `depends_on` + health checks:

```
PostgreSQL → Redis → Backend → Frontend
```

The backend automatically runs database migrations on startup.

## Database Migrations

Migrations are stored in `migrations/` as versioned `.up.sql`/`.down.sql` pairs:

```
migrations/
├── 001_initial_schema.up.sql
└── 001_initial_schema.down.sql
```

The backend tracks applied migrations in a `schema_migrations` table — migrations only run once.

## Persona Hot-Swap

Edit `config/persona.txt` and call the admin endpoint:

```bash
curl -X POST http://localhost:27710/api/v1/admin/reload_persona \
  -H "Content-Type: application/json" \
  -d '{"user_id": 392817811}'
```

## Adding a New Locale

1. Create `config/locales/{lang}.json` (copy from `en.json`)
2. Translate all keys
3. Set `DEFAULT_LANG={lang}` in `.env`
4. Restart the backend

## Running Tests

```bash
cd backend
go test ./... -v
```

## Production Checklist

- [ ] Set a strong `POSTGRES_PASSWORD`
- [ ] Set `TELEGRAM_MODE=webhook` + `WEBHOOK_URL` + `WEBHOOK_SECRET`
- [ ] Set `NANO_BANANA_API_KEY` and `NANO_BANANA_API_URL` for image generation
- [ ] Configure `ADMIN_IDS` with trusted Telegram user IDs
- [ ] Review rate limits for your expected traffic
