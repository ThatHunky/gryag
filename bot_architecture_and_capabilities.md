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
