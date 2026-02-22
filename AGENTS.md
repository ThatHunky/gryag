# LLM-Driven Development: Best Practices & Guidelines

This guide outlines the core principles for building, extending, and maintaining Gryag V2 and similar LLM-driven applications. It covers architectural patterns, prompt engineering, context management, and SDK integration.

## 1. Context Engineering & Memory Management
The most critical aspect of an LLM application is managing the token window. An LLM's performance degrades as context length increases ("context bloat").

- **Strict Windowing**: Never pass the entire database history. Gryag uses `IMMEDIATE_CONTEXT_SIZE` to slice the end of the chat history.
- **Layered Memory Architecture**:
  - *Short-term*: The recent `N` messages.
  - *Long-term (Semantic)*: Facts explicitly extracted and stored via `remember_memory`.
  - *Searchable*: The `search_messages` tool allows the LLM to dynamically fetch old context only when needed, rather than bloating the system prompt.
- **Media Throttling**: Images consume massive token counts. Gryag enforces a `MEDIA_BUFFER_MAX` (e.g., 10 images) to prevent a few heavy messages from eclipsing text history.

## 2. Dynamic System Instructions (Persona)
System instructions are the foundation of the agent's behavior. They must be unambiguous, structured, and modular.

- **The "Dynamic Instructions" Pattern**: Instead of a static text block, construct the system prompt dynamically on every request.
  - *Base*: The core persona (e.g., loaded from `config/persona.txt`).
  - *Context*: Injected data (current time, username, stored facts).
  - *Capabilities*: A dynamically generated list of available tools.
- **Role Definition**: Clearly command the LLM's identity ("You are a terse, Gen-Z assistant").
- **Constraint Boundaries**: Explicitly state what the LLM *cannot* do.

## 3. Tool Building (Function Calling)
Tools turn an LLM from a text generator into an agentic system.

- **Deterministic Routing**: When possible, use a standard generation call for natural language, but if strict routing is needed, set the Temperature to `0.0` to force deterministic tool selection.
- **Fault Isolation (Sandboxing)**: Never let a tool panic crash the main agent loop. In Go, wrap tool execution in `defer func() { recover() }()` to catch internal errors and return graceful text summaries of the failure to the LLM.
- **Rich Schema Descriptions**: The LLM relies entirely on the `Description` fields in your tool schemas. Make them as descriptive as possible.
  - *Bad*: `description: "Executes code"`
  - *Good*: `description: "Executes Python code in a secure sandbox. Can generate charts, do math, or parse data. Runs in an isolated container with no network access."`

## 4. Backend Architecture (Go)
- **Dependency Inversion**: Pass interfaces (or tightly scoped structs like `*db.DB`) down into handlers. The `Handler` struct should hold all subsystem connections.
- **Graceful Degradation**: If an external API (like Nano Banana Pro for images) fails, the system must not collapse. The tool executor should trap the error and inform the LLM so it can apologize naturally.
- **Stateless Handlers**: The HTTP handler (`/api/v1/process`) must be entirely stateless. Context is pulled from PostgreSQL and passed to the LLM on every incoming request.

## 5. Frontend / UI (Python/aiogram)
- **The "Dumb Pipe" Pattern**: The Telegram frontend should possess *zero* business logic or LLM state. It is strictly a router that translates Telegram JSON into internal API payloads, and translates backend responses (with media URLs) back to Telegram methods.
- **Translation Layers**: LLMs output standard Markdown. Platforms like Telegram require specific HTML subsets or strict MarkdownV2. The frontend must handle this translation layer (e.g., `md_to_tg.py`) robustly, escaping entities to prevent parse errors.
- **Async Concurrency**: Use `aiohttp` and `asyncio` to prevent long-running LLM generation requests from blocking the webhook/polling thread. Use typing indicators to signal work.

## 6. Utilizing Gemini "Thinking" Models
With models like `gemini-2.0-pro-exp`, the model can produce a "Thinking" block to reason about code or complex logic before outputting the final response.

- **Configuration**: Use `ThinkingConfig` in the `GenerateContentConfig`.
- **Budgeting**: Set a `ThinkingBudget` (e.g., 1024 tokens). If disabled (0), the model behaves normally.
- **When to Use**: Enable for complex coding, system design, or multi-step logic. Keep it disabled for casual chat to reduce latency and cost.
