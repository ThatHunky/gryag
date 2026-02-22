# Gryag V2 Agent Instructions

You are an expert Go and Python developer, specializing in AI-driven bots, asynchronous pipelines, and secure sandboxing. Your task is to maintain and extend Gryag V2, a production-ready Telegram bot powered by Gemini.

This file provides the context, commands, boundaries, and style guidelines necessary for you to operate effectively in this repository.

## 1. Project Overview & Stack
- **Backend**: Go 1.22+ (Strictly standard library for HTTP/SQL where possible, `google.golang.org/genai` for LLM, `lib/pq` for Postgres)
- **Frontend / UI**: Python 3.11+ using `aiogram 3.x`
- **Data Stores**: PostgreSQL 16 (persistent memory/logs) and Redis (rate limiting)
- **Deployment**: Docker Compose
- **Design Pattern**: "Dumb Pipe" Frontend (pure router) + Stateless Go Backend (business logic & tools)

## 2. Core Commands
Use these commands to build, test, and run the project locally. 

**Backend (Go)**
```bash
cd backend
go mod tidy
go build ./...
go test ./... -v -count=1  # ALWAYS run tests before committing
```

**Frontend (Python)**
```bash
cd frontend
pip install -r requirements.txt
python3 -m pytest test_md_to_tg.py -v
```

**Infrastructure (Docker)**
```bash
# Start the full stack (DB, Redis, Backend, Frontend)
docker-compose up -d --build

# View backend logs specifically
docker-compose logs -f backend
```

## 3. Architecture & Style Guidelines

### Go Backend Rules
- **Dependency Map**: `main.go` -> `config` -> `i18n` -> `db` -> `cache` -> `llm` -> `tools` -> `handler` -> `middleware`.
- **Fault Tolerance**: Tool panics MUST be recovered within the `tools.Executor` defer statement. Never panic the main HTTP handler.
- **Dynamic System Prompting**: The persona and instructions must be built *per-request* based on the database state (`llm/instructions.go`). Do not use static prompts for the main chat loop.
- **SQL Best Practices**: Use parameterized queries (`$1, $2`). Close your `*sql.Rows` (`defer rows.Close()`).
- **No Hardcoded Strings**: All user-facing strings must pass through the `i18n.Bundle` (English and Ukrainian files in `config/locales/`).

### Python Frontend Rules
- **No Business Logic**: `main.py` is a router. It must not store state, parse command intents (except basic deep links), or query the database.
- **Markdown Translation**: Always pass backend text through `md_to_tg.md_to_telegram_html` and use `ParseMode.HTML` before sending. Telegram will crash if Markdown formatting isn't perfectly paired.
- **Async I/O**: Never block the main thread. Use `aiohttp` for backend communication and `asyncio.create_task` for long-running UI updates (like typing indicators).

## 4. Working with the Gemini SDK
We use the official `google.golang.org/genai` SDK.
- **Routing**: Use `Temperature: 0.0` and `ResponseMIMEType: "application/json"` when doing strict tool classification.
- **Thinking Models**: For complex tasks, ensure `ThinkingConfig{ThinkingBudget: ...}` is attached to the generation config if the user enables it via `GEMINI_THINKING_BUDGET`.
- **Schema Descriptions**: Tool descriptions are critical. Write them comprehensively so the model clearly understands when and how to trigger the function call.

## 5. Strict Boundaries (Do NOT do these)
- **DO NOT** commit secrets or API keys. Check `.env.example` to ensure new secrets are documented empty.
- **DO NOT** bypass the database migrations system. Every schema change requires a new pair of `.up.sql` and `.down.sql` files in the `migrations/` directory.
- **DO NOT** modify the Go standard library imports to use third-party web frameworks (no Gin, Echo, Fiber). Keep `net/http` pure.
- **DO NOT** push code that fails `go test`. Every feature requires unit tests.
