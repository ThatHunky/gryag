# gryag C++ Bot

This directory houses the C++ port of the gryag Telegram bot. It mirrors the Python architecture (context store, hybrid search, episodic memory, tool registry, Gemini client, middleware-driven handlers) while using modern C++20 primitives for performance.

## Features implemented (2025-10-30)

- Settings loader mirroring environment-driven configuration used by the Python service.
- Logging setup via `spdlog` with rotating log files.
- SQLite context store with schema bootstrap from `db/schema.sql`, including ban/rate-limit helpers.
- Hybrid search placeholder (SQL `LIKE`) plus episodic memory accessors and multi-level context assembly scaffolding.
- Gemini REST client (text/embeddings/image) with API key rotation and basic function-call handling.
- Persona loader consuming the existing persona configuration files.
- Tool registry with production integrations for weather (OpenWeather), currency (ExchangeRate API), polls, DuckDuckGo search/static chat search, calculator, Gemini image generation (with quota tracking), and memory management tools.
- Lightweight Telegram HTTP client (long polling over `cpr`) with HTML-safe replies and command registration.
- Admin and profile handlers: bans/unbans, rate-limit reset, chat info, donation prompt, profile lookup, user listing, and memory fact dumps.

## Building

Requirements:

- CMake ≥ 3.25
- A C++20-capable compiler (GCC 12+, Clang 15+, or MSVC 19.36+)
- System dependencies: `libcurl`, `openssl`, `sqlite3`, `hiredis`

```bash
.venv/bin/cmake -S cpp -B cpp/build
.venv/bin/cmake --build cpp/build -j
```

The resulting binary is placed in `cpp/build/bin/gryag-bot`.

## Running

```bash
export TELEGRAM_TOKEN=...
export GEMINI_API_KEY=...
export DB_PATH=gryag_cpp.db
# Optional/feature-specific overrides
export OPENWEATHER_API_KEY=...
export EXCHANGE_RATE_API_KEY=...
export ENABLE_WEB_SEARCH=1
export ENABLE_TOOL_BASED_MEMORY=1
export IMAGE_GENERATION_API_KEY=...      # or reuse GEMINI_API_KEY
export REDIS_URL=redis://localhost:6379  # enables distributed locks & rate limits

./cpp/build/bin/gryag-bot
```

The bot reuses the existing `db/schema.sql`, so it can operate on the same SQLite database (take a backup first). Logs are written to `logs/gryag_cpp.log`.

## Next steps

- Close the tool-call loop by feeding tool outputs back to Gemini for natural language responses.
- Port the remaining handlers (chat-admin, prompt-admin, chat_members) and donation scheduler tooling.
- Replace the hybrid search placeholder with FTS5 + embedding cosine similarity.
- Add parity-focused golden transcript tests and CI coverage for the C++ service.
