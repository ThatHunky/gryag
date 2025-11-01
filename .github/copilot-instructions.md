---

description: "Copilot instructions tailored for the gryag repository — concise, actionable, and code-aware."

## Purpose

A practical guide for AI coding agents to be productive in this repository. It covers the application's architecture, developer workflows, and project-specific conventions.

## Developer Workflow

- **Virtualenv**: A virtual environment at `.venv` is mandatory.
- **Run Locally**: `.venv/bin/python3 -m app.main`
- **Run Tests**: `make test` or `.venv/bin/pytest tests/`
- **Docker Dev**: `docker compose up bot`

## High-Level Architecture

- **Entry Point**: `app/main.py` initializes all services (e.g., `GeminiClient`, `ContextStore`), background tasks, and registers `aiogram` routers.
- **Dependency Injection**: `app/middlewares/chat_meta.py` contains `ChatMetaMiddleware`, which injects nearly all services into handler `data`. **Do not instantiate services directly in handlers.**
- **Request Handling**: `app/handlers/` contains `aiogram` `Router` modules. The core message processing logic is in `app/handlers/chat.py`.
- **Context Management**: `app/services/context/multi_level_context.py` defines the `MultiLevelContextManager`, which assembles a token-budgeted context from multiple sources (recent messages, hybrid search, episodic memory).
- **Database**: The canonical schema is defined in `db/schema.sql`. It uses SQLite with FTS5 for search.

## Project-Specific Conventions

- **Use Injected Services**: Always use the services injected by `ChatMetaMiddleware`. These are available as parameters in handler functions (e.g., `settings`, `store`, `gemini_client`, `telegram_service`).
- **Tool Implementation**: To add a new tool for the AI model:
  1. Implement the core logic in a new file under `app/services/`.
  2. Create `build_tool_definitions` and `build_tool_callbacks` functions (e.g., `app/services/tools/moderation_tools.py`).
  3. Integrate the new tool into `app/handlers/chat.py` by adding it to the tool registry.
- **Handler Registration**: To add a new feature with its own commands:
  1. Create a new `Router` in a file under `app/handlers/`.
  2. Register the router in `app/main.py` using `dispatcher.include_router(...)`.
- **Database Migrations**: When editing `db/schema.sql`, ensure corresponding changes are made to the initialization or migration logic, typically found in `app/services/` or `app/core/`.
- **Persona**: The bot's persona and system prompt are primarily loaded from template files in `personas/templates/`. The file `app/persona.py` contains a fallback. User-facing replies must conform to the persona (plain text, Ukrainian).

## Key Files to Examine

- `app/main.py`: Service initialization and application startup.
- `app/middlewares/chat_meta.py`: To see the full list of injected services.
- `app/handlers/chat.py`: The main message processing and tool-using logic.
- `app/services/context/multi_level_context.py`: To understand how context is built for the AI model.
- `db/schema.sql`: The authoritative database schema.
- `Makefile`: For a list of common development tasks like `test`, `lint`, and `format`.
