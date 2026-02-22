# Gryag Bot Architecture & Capabilities

This document outlines the core capabilities and architectural concepts of the original Gryag bot (preserved in the `legacy` branch). These concepts should serve as a blueprint and inspiration for future development.

## 1. Core Persona & Behavior (Configurable)
- **Personality**: By default/initially, the bot assumes the "Gryag" persona (`@gryag`): a sarcastic, sharp-tongued Ukrainian male bot who ignores standard bot niceties, uses colloquial/profane language where appropriate, and mocks users creatively. 
- **Customizability**: This default persona is injected via the *Dynamic Instructions* template. The repository is designed so that whoever deploys the bot can easily hot-swap the immutable instruction block to configure **any custom persona** desired.
- **Identities**: Recognizes specific "special" users (admin/creator) by their Telegram `user_id` and interacts with them differently based on the active persona rules.
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
6. **Multi-Media Buffer**: Gemini natively supports massive multimodal payloads. The Dynamic Instructions builder must collect and inject up to **10 recent media files** (images, compressed video frames, audio) referenced in the *Immediate Chat Context* directly into the `genai.Part` array, ensuring the bot sees the full visual/audio scope of the conversation.
7. **Current Message**: The actual prompt/message triggering the bot.

## 9. Versatility & Security (OpenClaw-style Integration)

To elevate Gryag beyond a simple conversational agent to an **extremely versatile** orchestration layer (similar to the concept behind *OpenClaw* / *Moltbot*), the bot must be able to execute code, format data, and generate high-fidelity media, all while maintaining strict security boundaries.

### 1. The Code Interpreter (Secure Sandbox)
Gryag needs the ability to write and execute code on the fly to solve math, generate charts, parse files, or scrape unique data.
*   **The Mechanism**: The LLM uses a `run_python_code` (or similar) tool. The backend receives the raw code.
*   **Security (CRITICAL)**: Code **must never** execute directly on the host machine or the primary Go backend process. 
    *   **Dockerized Sandboxing**: Code must be passed to a strictly isolated, ephemeral Docker container (e.g., using a microVM like Firecracker, or a highly restricted Docker network with no internet access and read-only mounts). 
    *   **Timeouts & Resource Limits**: The execution environment must have hard CPU/RAM limits and a strict execution timeout (e.g., 5 seconds) to prevent infinite loops or denial-of-service.
    *   **Artifact Return**: If the code generates a chart (e.g., `matplotlib`), the sandbox returns the raw bytes or base64 image back to the Go backend, which forwards it to the Python Telegram frontend to send to the user.

### 2. Advanced Image Generation (Nano Banana Pro)
The bot will support premium image generation, specifically targeting **Nano Banana Pro at 2K resolution**.
*   **Execution**: The LLM translates user requests into English (if necessary) and triggers a `generate_image` tool mapped to the Nano Banana Pro API.
*   **Media Lifecycle & Editing**:
    *   *High-Quality Persistence*: 2K images are large. When generated, the original high-quality file must be temporarily cached on the backend (e.g., in a Redis-backed blob store or local temporary disk with a TTL of 24-48 hours).
    *   *Reference ID*: The bot replies with the image and a hidden or internal `media_id`. 
    *   *Editing*: If the user replies to the generated image asking to "make it darker" or "add a hat", the LLM retrieves the *original 2K quality image* from the temporary cache using the `media_id`, edits it via the appropriate API tool, and returns the result without cumulative compression artifacting.
*   **File Delivery (Document vs. Photo)**: 
    *   Previously, Telegram aggressively capped photos at 1280px. However, the Bot API now natively supports `sendPhoto` for resolutions up to **2560px** (which perfectly maps to 2K/1440p) without server-side dimensional downscaling.
    *   By default, the bot sends the Nano Banana Pro image using `sendPhoto`. Users who have the "Experimental > Send large photos" setting enabled in their Desktop clients (or HD modes on mobile) will receive and view the stunning 2K image seamlessly in the feed.
    *   A document (`sendDocument`) fallback is only necessary if the user explicitly demands the absolute raw uncompressed byte stream to bypass any residual JPEG compression Telegram applies during transit.

## 10. Access Control, Admin Setup & Rate Limiting

Because the bot relies on powerful LLMs and advanced media generation (which incur high API costs and compute time), robust access control is required.

### 1. Admin/Creator Setup
- **Configuration Level**: Admin Telegram `user_id`s (and potentially high-privilege VIPs) must be configured directly via Environment Variables (e.g., `ADMIN_IDS=12345678,87654321`) or a secure backend configuration file, completely separate from the LLM context.
- **Privilege Separation**:
    - *Operational Privileges*: Only Admins can invoke backend-level override commands (e.g., forcing a bot restart, flushing Redis caches, or modifying the system prompt).
    - *Persona Privileges*: The backend injects the Admin IDs into the *Dynamic Instructions* context so the LLM recognizes its "creator", triggering the respectful/subservient conversational behavior outlined in the persona.

### 2. Rate Limiting & Throttling (Redis)
All incoming Telegram updates are intercepted by a highly performant Redis middleware layer *before* they hit the database or LLM generation logic.
- **Tiered Sliding Window Algorithm**:
    - **Global Chat Limit**: Prevent an entire group chat from overwhelming the bot (e.g., max 10 requests per minute per chat group).
    - **Per-User Throttle**: Restrict individual users from spamming (e.g., max 3 messages per rolling 60-second window).
    - **Expensive Tool Quotas**: Specific constraints placed on slow or costly tools. For instance, Nano Banana Pro image generation might be hard-capped at 5 images per user, per day.
- **Cost Protection (Circuit Breakers)**: If an API anomaly is detected (e.g., Gemini spinning in an infinite loop or Telegram sending duplicated webhook events), Redis tracks consecutive failures/rapid spikes and temporarily short-circuits execution for that chat/user, notifying Admins directly. 
- **Strict Silence on Throttle (Background Logging)**: If a user hits a throttle, the backend **instantly drops the request**. The bot must **not** respond with any error messages, avoiding chat spam. However, the dropped message **must still be written to the PostgreSQL message log**. This ensures that when the bot finally *does* respond to a future valid trigger, it has full context of what was said during its silence.
- **Message Queue Locking (Exclusive Processing)**: By default, the bot processes **one message at a time per chat context**. It must lock the ability to queue multiple triggers. If a user sends 5 consecutive messages while the bot is already thinking/generating a response to the 1st, the subsequent 4 are ignored for active processing (but are still logged to the DB for context unless explicitly configured otherwise by an Admin).
- **Action/Typing Indicators**: During the (sometimes lengthy) execution of the Go backend logic, the Python frontend must continuously emit appropriate Telegram Chat Actions (e.g., `typing`, `upload_photo`, `upload_document`) so users know the bot is actively working on the request.
