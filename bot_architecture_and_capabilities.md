# Gryag Bot Architecture & Capabilities

This document outlines the core capabilities and architectural concepts of the original Gryag bot (preserved in the `legacy` branch). These concepts should serve as a blueprint and inspiration for future development.

## 1. Core Persona & Behavior
- **Personality**: A sarcastic, sharp-tongued Ukrainian male bot (`@gryag`). He ignores standard bot niceties, uses colloquial/profane language where appropriate, and mocks users creatively.
- **Identities**: Recognizes specific "special" users (admin/creator) by their Telegram `user_id` and interacts with them differently.
- **Restrictions**: Ignores traditional bot commands, avoiding generic metadata echo. Time-aware but pretends to just "know" things rather than explicitly exposing system facts.

## 2. Advanced Memory & Context System (5-Layer Architecture)
The legacy bot utilized a sophisticated, multi-tiered memory system aimed at reducing LLM token consumption while maintaining high contextual accuracy.

*   **Immediate Context**: The most recent 30-50 messages in the current thread.
*   **Recent Context**: Summarized clusters of recent conversation.
*   **Relevant Context**: Semantically similar past messages retrieved via hybrid search (FTS5 + Embeddings).
*   **Background Context**: Global facts about the chat environment.
*   **Episodic Memory**: Conversations automatically grouped into "episodes" and summarized to provide overarching narrative context without passing raw text logs.

## 3. Fact Extraction & User Profiling
A defining feature is the bot's ability to invisibly build profiles of users over time.

*   **Hybrid Extraction Pipeline**:
    *   **Rule-based (Regex)**: Catches ~70% of common facts instantly (0 cost).
    *   **Local LLM (Phi-3-mini)**: Runs locally to analyze complex sentences and extract preferences/facts (~85% coverage).
    *   **Fallback (Gemini)**: Uses cloud API only when strictly necessary.
*   **User Facts**: Stores user location, pronouns, likes/dislikes, relationships, and history. 
*   **Self-Learning**: The bot analyzes its own performance and mistakes over time, automatically adjusting its persona behavior and strategies ("Semantic dedup", "temporal decay").

## 4. Multi-Modal Interactions
*   **Image/Video/Audio Analysis**: Processes media seamlessly by forwarding it to multimodal models.
*   **Sticker Context**: Understands and references Telegram stickers.
*   **Image Generation**: Uses external tools (like Pollinations) to generate images on demand.

## 5. Tool Calling & API Integrations
The LLM dynamically decides when to use external tools:
- `search_web` / `fetch_web_content` (Google Search Grounding)
- `calculator`, `currency`, `weather`
- Native memory management tools (`remember_memory`, `forget_memory`)

## 6. Architecture & Deployment
- **Database**: `SQLite` with extensive schema (`db/schema.sql`) for messages, users, and fact storage.
- **Caching**: Optional `Redis` for distributed rate-limiting and fast caching.
- **Containerization**: Deployed via `docker-compose` with optimized build contexts.

## Future Direction (V2)
For the new iteration, the architectural focus should likely remain on:
1. **Separation of Concerns**: Clean boundaries between Telegram Handlers, Memory Retrieval, Tool Execution, and LLM formatting.
2. **Efficiency**: Retaining the hybrid (local + cloud) approach to save API costs.
3. **Pluggability**: Easier addition of new "tools" for the LLM. 
