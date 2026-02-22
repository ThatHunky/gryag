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

*   **Extraction Pipeline**:
    *   **Gemini API**: Primary engine for deeply nuanced dialogue and reasoning.
    *   **OpenAI API**: Utilized for fast structuring, fact classification, and routing.
*   **User Facts**: Stores user location, pronouns, likes/dislikes, relationships, and history. Loaded dynamically into the prompt for specific users.
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


## 6. Future Direction (V2): Python Frontend & Go Backend
For the new iteration, the architecture relies on a strong split between a **Python Telegram "Frontend"** and a **Go "Backend"**.

### Architecture Overview
1. **Python (Frontend)**: Handles the Telegram API connection via `aiogram`. Responsible for parsing incoming updates, downloading media, maintaining fast websocket connections, and sending formatted responses back to the user. It forwards sanitized requests to the Go backend.
2. **Go (Backend)**: Handles the heavyweight business logic: memory retrieval, SQLite database operations, Gemini API generation, OpenAI API routing, and tool execution.

### Wiring the Gemini API

#### Python (Frontend - Basic Generation Example)
While Python will primarily act as the Telegram router, if any direct LLM calls are needed on the frontend, the official Google GenAI SDK is used:

```python
# pip install google-genai
import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='Tell me a sarcastic joke about rewriting a codebase.'
)
print(response.text)
```

#### Go (Backend - Core Generation Engine)
The Go backend acts as the true brain. It requires the official Go GenAI SDK (`google.golang.org/genai`).

**Installation:**
```bash
go get google.golang.org/genai
```

**Implementation Example:**
```go
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"google.golang.org/genai"
)

func generateResponse(prompt string) (string, error) {
	ctx := context.Background()
	
	// Ensure GEMINI_API_KEY is set in environment
	client, err := genai.NewClient(ctx, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create client: %v", err)
	}

	model := "gemini-2.5-flash"
	resp, err := client.Models.GenerateContent(ctx, model, genai.Text(prompt), nil)
	if err != nil {
		return "", fmt.Errorf("failed to generate content: %v", err)
	}
	
	if len(resp.Candidates) > 0 && len(resp.Candidates[0].Content.Parts) > 0 {
		if text, ok := resp.Candidates[0].Content.Parts[0].(genai.Text); ok {
			return string(text), nil
		}
	}

	return "", fmt.Errorf("no output generated")
}

func main() {
	response, err := generateResponse("Тестовий запит для Гряга.")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(response)
}
```

By separating concerns, the highly concurrent Go backend can manage extensive memory and API orchestrations rapidly without blocking the Python-based Telegram polling loops.

## 7. Opportunities for Simplification & Recommended Stack

While the legacy bot was powerful, its 5-layer memory and hybrid local/cloud extraction pipeline were highly complex. For the V2 rewrite, we can **drastically simplify** the conceptual model by leaning into the raw capabilities of modern APIs and a streamlined stack.

### Simplification Strategies
1. **Flatten the Memory Architecture**: Instead of 5 distinct layers (Immediate, Recent, Semantically Relevant, Background, Episodic), reduce this to **3 layers**.
    - *Short-Term Context*: The last N messages (handled purely by array slicing).
    - *Long-Term Facts*: A simple key-value or document store of facts about users. 
    - *Consolidated Summaries*: Let Gemini 2.5 Flash native large context window (1M+ tokens) do the heavy lifting of summarizing past episodes *on the fly* rather than attempting complex manual grouping logic.
2. **Native Tool Calling (Function Calling)**: Remove custom extraction pipelines (like Regex matching or Phi-3-mini). Let the Gemini/OpenAI API natively decide when to trigger a tool (e.g., `save_user_fact(user_id, fact)` or `get_weather(city)`).
3. **Drop Redis (If Possible)**: Unless horizontal scaling is strictly required immediately, `SQLite` is more than fast enough for rate-limiting, caching, and state management in a single-instance Go backend.

### Recommended Simplified Tech Stack

#### The "Frontend" (Telegram Router)
- **Language**: Python 3.12+
- **Library**: `aiogram` (Async Telegram bot API framework).
- **Role**: Purely a dumb pipe. It receives webhooks/polls, downloads media to a temporary local buffer, and makes REST/gRPC calls to the Go backend. It does *no* thinking.

#### The "Backend" (The Brain)
- **Language**: Go 1.23+
- **Web Framework**: [`Fiber`](https://gofiber.io/) or the standard `net/http` for receiving requests from the Python frontend.
- **Primary Database**: `PostgreSQL v18+`. Given the high velocity of messages and complexity of vector/relational queries, PostgreSQL handles the heavy lifting for message logs, user facts, and episodic memory storage.
- **Caching & State**: `Redis`. Utilized for extreme-low-latency operations: rate-limiting (sliding windows), active session caching, and immediate context buffers.
- **AI Integration**:
    - **Google GenAI SDK (`google.golang.org/genai`)**: For the core conversational personality, utilizing Gemini 2.5 Flash's massive context window and native function calling. 
    - **OpenAI API (Optional)**: If you need extremely fast, cheap, predictable JSON formatting for minor classification tasks, though Gemini Flash is likely sufficient for both.

#### Simplified Toolset (What to Keep vs Change)
*   **Keep**: `search_web` (via Google Search Grounding natively inside Gemini).
*   **Change**: Replace manual `remember_memory`/`forget_memory` with native Gemini Tool Calling. 
*   **Change**: Drop manual image generation plugins if not vital; focus strictly on text/multimodal *understanding* first.
*   **Drop**: `SQLite`. Replaced by the robust combination of `PostgreSQL` and `Redis`.

## 8. Dynamic Instructions Template

To harness the capabilities of Gemini 2.5 without overflowing the context or causing hallucination, the prompt structure follows a strict "**Dynamic Instructions**" format inject per request:

1. **Immutable Block**: The core personality (sarcastic, Ukrainian, uncensored, zero-filter), format constraints (no markdown), and fixed identity rules.
2. **Current Time & Chat Info**: Injected as raw text to allow time-awareness without metadata echoing.
3. **Tools Block**: The explicit list of capabilities available to the bot (e.g., `generate_image`, `weather`, `remember_memory`, `mute_user`).
4. **Context (Multi-tiered Summary)**:
    - *30-Day Summary*: Overarching themes, memes, and significant past events.
    - *7-Day Summary*: Immediate past behaviors, running jokes, and active plotlines.
    - *Immediate Chat Context*: The raw log of the last `N` messages.
5. **Current User Context**: Spliced-in facts specifically about the user currently talking (the message author).
6. **Current Message**: The actual prompt/message triggering the bot.
