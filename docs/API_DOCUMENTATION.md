# Comprehensive API Documentation

This document provides comprehensive documentation for all public APIs, functions, and components in the gryag bot codebase.

## Table of Contents

1. [Entry Point](#entry-point)
2. [Handlers](#handlers)
3. [Services](#services)
4. [Repositories](#repositories)
5. [Middlewares](#middlewares)
6. [Tools](#tools)
7. [Configuration](#configuration)
8. [Usage Examples](#usage-examples)

---

## Entry Point

### `app.main`

Main application entry point that initializes all services and starts the bot.

#### Functions

##### `main() -> None`
Async main function that sets up and runs the Telegram bot.

**Initialization Flow:**
1. Loads settings from environment variables
2. Validates configuration
3. Sets up logging
4. Initializes database (PostgreSQL)
5. Initializes Redis (if enabled)
6. Creates all service instances
7. Registers middleware and handlers
8. Starts polling

**Example:**
```python
import asyncio
from app.main import main

asyncio.run(main())
```

##### `run() -> None`
Synchronous entry point for console scripts and `python -m app.main`.

**Example:**
```bash
python -m app.main
```

##### `setup_bot_commands(bot: Bot) -> None`
Registers bot commands with Telegram for the command menu.

**Example:**
```python
from aiogram import Bot
from app.main import setup_bot_commands

bot = Bot(token="...")
await setup_bot_commands(bot)
```

---

## Handlers

Handlers process Telegram messages and commands. All handlers use dependency injection via middleware.

### `app.handlers.chat`

Main chat handler that processes group messages and generates bot responses.

#### Key Functions

##### `handle_group_message(...)`
Processes group messages and generates bot responses.

**Parameters (injected via middleware):**
- `message: Message` - Telegram message object
- `bot: Bot` - Bot instance
- `settings: Settings` - Application settings
- `store: ContextStore` - Conversation context store
- `gemini_client: GeminiClient` - Gemini API client
- `profile_store: UserProfileStore` - User profile store
- `bot_username: str` - Bot's username
- `bot_id: int | None` - Bot's Telegram ID
- `multi_level_context_manager: MultiLevelContextManager` - Context manager
- `hybrid_search: HybridSearchEngine` - Search engine
- `episodic_memory: EpisodicMemoryStore` - Episodic memory store
- And many more services...

**Behavior:**
- Checks if message is addressed to bot (mentions, replies, triggers)
- Validates rate limits and bans
- Builds multi-level context
- Generates response using Gemini
- Handles tool calls (memory, search, moderation, etc.)
- Sends response back to chat

**Example:**
```python
# Handler is automatically registered via router
# Messages are processed automatically when bot receives them
```

### `app.handlers.admin`

Admin commands for managing the bot.

#### Commands

##### `/gryagban` or `/ban`
Bans a user from using the bot.

**Usage:**
```
/gryagban @username
/gryagban 123456789
/gryagban (in reply to a message)
```

**Handler:** `ban_user_command`

##### `/gryagunban` or `/unban`
Unbans a user.

**Usage:**
```
/gryagunban @username
/gryagunban 123456789
```

**Handler:** `unban_user_command`

##### `/gryagreset`
Resets message quotas for a chat.

**Handler:** `reset_quota_command`

##### `/gryagchatinfo`
Shows chat ID for configuration.

**Handler:** `chat_info_command`

### `app.handlers.profile_admin`

Commands for managing user profiles.

#### Commands

##### `/gryagprofile`
View user profile (your own or in reply).

**Handler:** `profile_command`

##### `/gryagfacts`
List facts about a user.

**Handler:** `facts_command`

### `app.handlers.chat_admin`

Commands for managing chat profiles and facts.

#### Commands

##### `/gryagchatprofile`
View chat profile and facts.

**Handler:** `chat_profile_command`

##### `/gryagchatfacts`
List facts about the chat.

**Handler:** `chat_facts_command`

### `app.handlers.prompt_admin`

Commands for managing system prompts.

#### Commands

##### `/gryagprompt`
View or set system prompt.

**Handler:** `prompt_command`

### `app.handlers.checkers`

Checkers game handler.

#### Commands

##### `/checkers`
Start or interact with a checkers game.

**Handler:** `checkers_command`

---

## Services

### `app.services.gemini`

Gemini API client for text generation and embeddings.

#### `GeminiClient`

Async wrapper around Google Gemini models.

**Constructor:**
```python
GeminiClient(
    api_key: str,
    model: str,
    embed_model: str,
    embedding_cache: EmbeddingCache | None = None,
    *,
    api_keys: list[str] | None = None,
    free_tier_mode: bool = False,
    key_cooldown_seconds: float = 120.0,
    quota_block_seconds: float = 86400.0,
    enable_thinking: bool = False,
    thinking_budget_tokens: int = 1024,
)
```

**Methods:**

##### `async generate(...) -> str`
Generates text response from messages.

**Parameters:**
- `messages: list[dict]` - Conversation history
- `system_instruction: str | None` - System prompt
- `tools: list[dict] | None` - Tool definitions
- `tool_callbacks: dict[str, Callable] | None` - Tool handlers
- `temperature: float = 1.0` - Sampling temperature
- `max_tokens: int | None = None` - Max output tokens

**Returns:** Generated text response

**Example:**
```python
client = GeminiClient(api_key="...", model="gemini-2.5-flash", embed_model="...")
response = await client.generate(
    messages=[{"role": "user", "parts": [{"text": "Hello!"}]}],
    system_instruction="You are a helpful assistant."
)
```

##### `async embed(text: str) -> list[float]`
Generates embedding vector for text.

**Parameters:**
- `text: str` - Text to embed

**Returns:** Embedding vector (list of floats)

**Example:**
```python
embedding = await client.embed("Hello world")
```

#### Exceptions

##### `GeminiError`
Base exception for Gemini API errors.

##### `GeminiContentBlockedError(GeminiError)`
Raised when content is blocked by safety filters.

**Attributes:**
- `block_reason: str | None` - Reason for blocking
- `safety_ratings: Any` - Safety rating details

### `app.services.context_store`

Manages conversation context and message history.

#### `ContextStore`

Stores and retrieves conversation messages.

**Constructor:**
```python
ContextStore(database_url: str)
```

**Methods:**

##### `async init() -> None`
Initializes the store (creates tables if needed).

##### `async add_message(...) -> None`
Adds a message to the conversation.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID (for topics)
- `message_id: int` - Telegram message ID
- `user_id: int` - User ID
- `text: str | None` - Message text
- `role: str` - Role ("user" or "assistant")
- `metadata: dict[str, Any]` - Additional metadata
- `sender: MessageSender | None` - Sender information

**Example:**
```python
store = ContextStore("postgresql://...")
await store.init()
await store.add_message(
    chat_id=123,
    thread_id=None,
    message_id=456,
    user_id=789,
    text="Hello!",
    role="user",
    metadata={},
    sender=MessageSender(role="user", name="John")
)
```

##### `async recent(...) -> list[dict]`
Retrieves recent messages for context.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID
- `limit: int = 50` - Max messages to retrieve
- `before_message_id: int | None` - Get messages before this ID

**Returns:** List of message dictionaries

**Example:**
```python
messages = await store.recent(chat_id=123, thread_id=None, limit=20)
```

##### `async search(...) -> list[dict]`
Searches messages using full-text search.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID
- `query: str` - Search query
- `limit: int = 10` - Max results

**Returns:** List of matching messages

**Example:**
```python
results = await store.search(chat_id=123, query="weather", limit=5)
```

### `app.services.context.multi_level_context`

Multi-level context manager for layered context retrieval.

#### `MultiLevelContextManager`

Manages 5 levels of context:
1. **Immediate** - Current turn (0-5 messages, <1 min)
2. **Recent** - Active thread (5-30 messages, <30 min)
3. **Relevant** - Hybrid search results
4. **Background** - User profile and facts
5. **Episodic** - Memorable events

**Constructor:**
```python
MultiLevelContextManager(
    db_path: Path | str,
    settings: Settings,
    context_store: Any,
    profile_store: Any | None = None,
    chat_profile_store: Any | None = None,
    hybrid_search: Any | None = None,
    episode_store: Any | None = None,
    gemini_client: Any | None = None,
)
```

**Methods:**

##### `async build_context(...) -> LayeredContext`
Builds complete multi-level context.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID
- `user_id: int` - User ID
- `query_text: str` - User's query
- `max_tokens: int | None = None` - Token budget
- `include_recent: bool = True` - Include recent context
- `include_relevant: bool = True` - Include relevant search results
- `include_background: bool = True` - Include user profile
- `include_episodes: bool = True` - Include episodic memory

**Returns:** `LayeredContext` with all context levels

**Example:**
```python
manager = MultiLevelContextManager(...)
context = await manager.build_context(
    chat_id=123,
    thread_id=None,
    user_id=789,
    query_text="What did we discuss yesterday?",
    max_tokens=4000
)
```

### `app.services.context.hybrid_search`

Hybrid search engine combining FTS, semantic search, and temporal relevance.

#### `HybridSearchEngine`

**Constructor:**
```python
HybridSearchEngine(
    db_path: str,
    gemini_client: GeminiClient,
    settings: Settings,
    redis_client: RedisLike | None = None,
)
```

**Methods:**

##### `async search(...) -> list[SearchResult]`
Performs hybrid search.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID
- `query: str` - Search query
- `limit: int = 10` - Max results
- `min_relevance: float = 0.0` - Minimum relevance score

**Returns:** List of `SearchResult` objects

**Example:**
```python
engine = HybridSearchEngine(...)
results = await engine.search(
    chat_id=123,
    query="weather forecast",
    limit=5
)
```

### `app.services.context.episodic_memory`

Episodic memory store for conversation episodes.

#### `EpisodicMemoryStore`

**Constructor:**
```python
EpisodicMemoryStore(
    db_path: str,
    gemini_client: GeminiClient,
    settings: Settings,
)
```

**Methods:**

##### `async init() -> None`
Initializes the store.

##### `async get_relevant_episodes(...) -> list[Episode]`
Retrieves relevant episodes for context.

**Parameters:**
- `chat_id: int` - Chat ID
- `thread_id: int | None` - Thread ID
- `query: str | None` - Optional query for relevance
- `limit: int = 5` - Max episodes

**Returns:** List of `Episode` objects

**Example:**
```python
store = EpisodicMemoryStore(...)
await store.init()
episodes = await store.get_relevant_episodes(
    chat_id=123,
    query="discussion about project",
    limit=3
)
```

### `app.services.user_profile_adapter`

User profile management with fact extraction.

#### `UserProfileStoreAdapter`

**Constructor:**
```python
UserProfileStoreAdapter(
    database_url: str,
    redis_client: RedisLike | None = None,
)
```

**Methods:**

##### `async init() -> None`
Initializes the adapter.

##### `async get_profile(user_id: int, chat_id: int) -> dict`
Gets user profile with facts.

**Returns:** Profile dictionary with facts, relationships, etc.

##### `async update_pronouns(user_id: int, chat_id: int, pronouns: str | None) -> None`
Updates user pronouns.

**Example:**
```python
adapter = UserProfileStoreAdapter("postgresql://...")
await adapter.init()
profile = await adapter.get_profile(user_id=789, chat_id=123)
await adapter.update_pronouns(user_id=789, chat_id=123, pronouns="she/her")
```

### `app.services.rate_limiter`

Rate limiting for user requests.

#### `RateLimiter`

**Constructor:**
```python
RateLimiter(
    database_url: str,
    per_user_per_hour: int,
    redis_client: RedisLike | None = None,
)
```

**Methods:**

##### `async init() -> None`
Initializes rate limiter.

##### `async check_limit(user_id: int) -> tuple[bool, int | None]`
Checks if user has exceeded rate limit.

**Returns:** `(allowed, seconds_until_reset)`

**Example:**
```python
limiter = RateLimiter("postgresql://...", per_user_per_hour=5)
await limiter.init()
allowed, reset_in = await limiter.check_limit(user_id=789)
if not allowed:
    print(f"Rate limited. Reset in {reset_in} seconds")
```

### `app.services.feature_rate_limiter`

Feature-specific rate limiting.

#### `FeatureRateLimiter`

**Constructor:**
```python
FeatureRateLimiter(
    database_url: str,
    admin_user_ids: list[int],
    redis_client: RedisLike | None = None,
)
```

**Methods:**

##### `async init() -> None`
Initializes feature limiter.

##### `async check_feature_limit(...) -> tuple[bool, int | None]`
Checks feature-specific limit.

**Parameters:**
- `user_id: int` - User ID
- `feature: str` - Feature name (e.g., "weather", "currency")
- `limit_per_hour: int` - Limit for this feature

**Returns:** `(allowed, seconds_until_reset)`

**Example:**
```python
limiter = FeatureRateLimiter("postgresql://...", admin_user_ids=[123])
await limiter.init()
allowed, _ = await limiter.check_feature_limit(
    user_id=789,
    feature="weather",
    limit_per_hour=10
)
```

### `app.services.bot_profile`

Bot self-learning profile store.

#### `BotProfileStore`

Stores what the bot learns about itself.

**Constructor:**
```python
BotProfileStore(
    db_path: str,
    bot_id: int,
    gemini_client: GeminiClient,
    enable_temporal_decay: bool = True,
    enable_semantic_dedup: bool = True,
)
```

**Methods:**

##### `async init() -> None`
Initializes the store.

##### `async record_interaction(...) -> None`
Records a bot interaction for learning.

**Parameters:**
- `chat_id: int` - Chat ID
- `user_id: int` - User ID
- `user_message: str` - User's message
- `bot_response: str` - Bot's response
- `reaction: str | None` - User reaction (positive/negative)
- `tokens_used: int` - Tokens consumed

**Example:**
```python
store = BotProfileStore(..., bot_id=123456)
await store.init()
await store.record_interaction(
    chat_id=123,
    user_id=789,
    user_message="Hello",
    bot_response="Hi there!",
    reaction="positive",
    tokens_used=50
)
```

### `app.services.bot_learning`

Bot self-learning engine.

#### `BotLearningEngine`

**Constructor:**
```python
BotLearningEngine(
    bot_profile: BotProfileStore,
    gemini_client: GeminiClient,
    enable_gemini_insights: bool = True,
)
```

**Methods:**

##### `async generate_insights() -> str`
Generates insights about bot performance.

**Returns:** Insights text

**Example:**
```python
engine = BotLearningEngine(bot_profile, gemini_client)
insights = await engine.generate_insights()
```

### `app.services.image_generation`

Image generation service using Gemini.

#### `ImageGenerationService`

**Constructor:**
```python
ImageGenerationService(
    api_key: str,
    database_url: str,
    daily_limit: int = 50,
    admin_user_ids: list[int] | None = None,
)
```

**Methods:**

##### `async generate_image(...) -> bytes`
Generates an image from a prompt.

**Parameters:**
- `prompt: str` - Image generation prompt (in English)
- `aspect_ratio: str = "1:1"` - Aspect ratio
- `user_id: int | None` - User ID for quota tracking

**Returns:** Image bytes (PNG)

**Example:**
```python
service = ImageGenerationService(api_key="...", database_url="...")
image_bytes = await service.generate_image(
    prompt="A beautiful sunset over mountains",
    aspect_ratio="16:9",
    user_id=789
)
```

##### `async edit_image(...) -> bytes`
Edits an existing image.

**Parameters:**
- `image_bytes: bytes` - Original image
- `prompt: str` - Edit prompt (in English)
- `user_id: int | None` - User ID for quota tracking

**Returns:** Edited image bytes

### `app.services.search_tool`

Web search tool using DuckDuckGo.

#### Functions

##### `async search_web_tool(params: dict) -> str`
Searches the web.

**Parameters:**
- `query: str` - Search query
- `search_type: str` - "text", "images", "videos", or "news"
- `max_results: int = 5` - Max results

**Returns:** JSON string with results

**Example:**
```python
result = await search_web_tool({
    "query": "Ukraine news",
    "search_type": "news",
    "max_results": 5
})
```

##### `async fetch_web_content_tool(params: dict) -> str`
Fetches content from a URL.

**Parameters:**
- `url: str` - URL to fetch
- `index: int | None` - Optional index from search results

**Returns:** JSON string with content

### `app.services.calculator`

Mathematical calculator tool.

#### Functions

##### `async calculator_tool(params: dict) -> str`
Evaluates a mathematical expression.

**Parameters:**
- `expression: str` - Math expression (e.g., "2 + 2")

**Returns:** JSON string with result

**Example:**
```python
result = await calculator_tool({"expression": "sqrt(16) + 5 * 2"})
```

### `app.services.weather`

Weather forecast service.

#### Functions

##### `async weather_tool(params: dict) -> str`
Gets weather forecast.

**Parameters:**
- `location: str` - Location name
- `days: int = 3` - Number of days

**Returns:** JSON string with forecast

**Example:**
```python
result = await weather_tool({"location": "Kyiv, Ukraine", "days": 3})
```

### `app.services.currency`

Currency exchange rate service.

#### Functions

##### `async currency_tool(params: dict) -> str`
Gets exchange rates or converts currency.

**Parameters:**
- `from_currency: str` - Source currency code
- `to_currency: str | None` - Target currency code (optional)
- `amount: float | None` - Amount to convert (optional)

**Returns:** JSON string with rates or conversion

**Example:**
```python
result = await currency_tool({
    "from_currency": "USD",
    "to_currency": "UAH",
    "amount": 100
})
```

### `app.services.polls`

Poll creation and management.

#### Functions

##### `async polls_tool(params: dict) -> str`
Creates, votes on, or gets poll results.

**Parameters:**
- `action: str` - "create", "vote", or "results"
- `question: str` - Poll question (for create)
- `options: list[str]` - Poll options (for create)
- `poll_id: str` - Poll ID (for vote/results)
- `choice: int` - Choice index (for vote)

**Returns:** JSON string with result

**Example:**
```python
# Create poll
result = await polls_tool({
    "action": "create",
    "question": "Favorite color?",
    "options": ["Red", "Blue", "Green"]
})

# Vote
result = await polls_tool({
    "action": "vote",
    "poll_id": "123_456",
    "choice": 0
})
```

---

## Repositories

Repositories provide data access layer abstraction.

### `app.repositories.base`

Base repository interface.

#### `Repository[T]`

Generic base class for all repositories.

**Methods:**

##### `async find_by_id(id: Any) -> T | None`
Finds entity by ID.

##### `async save(entity: T) -> T`
Saves entity.

##### `async delete(id: Any) -> bool`
Deletes entity by ID.

**Protected Methods:**

##### `_get_connection()`
Gets database connection manager.

##### `async _execute(query: str, params: tuple | dict | None) -> str`
Executes a query.

##### `async _fetch_one(query: str, params: tuple | dict | None) -> asyncpg.Record | None`
Fetches a single row.

##### `async _fetch_all(query: str, params: tuple | dict | None) -> list[asyncpg.Record]`
Fetches all rows.

### `app.repositories.memory_repository`

User memory repository.

#### `MemoryRepository`

**Methods:**

##### `async init() -> None`
Initializes repository.

##### `async add_memory(user_id: int, chat_id: int, memory_text: str) -> UserMemory`
Adds a memory. Auto-deletes oldest if user has 15 memories.

**Example:**
```python
repo = MemoryRepository("postgresql://...")
await repo.init()
memory = await repo.add_memory(
    user_id=789,
    chat_id=123,
    memory_text="User lives in Kyiv"
)
```

##### `async get_memories_for_user(user_id: int, chat_id: int) -> list[UserMemory]`
Gets all memories for a user.

##### `async get_memory_by_id(memory_id: int) -> UserMemory | None`
Gets a memory by ID.

##### `async delete_memory(memory_id: int) -> bool`
Deletes a memory.

##### `async delete_all_memories(user_id: int, chat_id: int) -> int`
Deletes all memories for a user. Returns count deleted.

### `app.repositories.user_profile`

User profile repository.

#### `UserProfileRepository`

**Methods:**

##### `async get_profile(user_id: int, chat_id: int) -> dict`
Gets user profile.

##### `async add_fact(user_id: int, chat_id: int, fact: dict) -> None`
Adds a fact to profile.

##### `async update_pronouns(user_id: int, chat_id: int, pronouns: str | None) -> None`
Updates pronouns.

### `app.repositories.chat_profile`

Chat profile repository.

#### `ChatProfileRepository`

**Methods:**

##### `async get_chat_profile(chat_id: int) -> dict`
Gets chat profile.

##### `async add_chat_fact(chat_id: int, fact: dict) -> None`
Adds a fact about the chat.

---

## Middlewares

### `app.middlewares.chat_meta`

Dependency injection middleware.

#### `ChatMetaMiddleware`

Injects services into handler context.

**Injected Services:**
- `settings: Settings`
- `store: ContextStore`
- `gemini_client: GeminiClient`
- `profile_store: UserProfileStore`
- `chat_profile_store: ChatProfileRepository | None`
- `hybrid_search: HybridSearchEngine | None`
- `episodic_memory: EpisodicMemoryStore | None`
- `episode_monitor: EpisodeMonitor | None`
- `bot_profile: BotProfileStore | None`
- `bot_learning: BotLearningEngine | None`
- `prompt_manager: SystemPromptManager | None`
- `redis_client: RedisLike | None`
- `rate_limiter: RateLimiter`
- `image_gen_service: ImageGenerationService | None`
- `feature_limiter: FeatureRateLimiter`
- `donation_scheduler: DonationScheduler`
- `memory_repo: MemoryRepository`
- `telegram_service: TelegramService`
- `bot_username: str`
- `bot_id: int | None`
- `multi_level_context_manager: MultiLevelContextManager`
- `persona_loader: PersonaLoader | None`

**Usage:**
Services are automatically injected into handler function parameters.

**Example:**
```python
@router.message()
async def handler(
    message: Message,
    settings: Settings,  # Injected automatically
    store: ContextStore,  # Injected automatically
    gemini_client: GeminiClient,  # Injected automatically
    # ... other services
):
    # Use injected services
    pass
```

### `app.middlewares.chat_filter`

Chat filtering middleware.

#### `ChatFilterMiddleware`

Filters messages based on chat allowlist/blocklist.

**Behavior:**
- If `bot_behavior_mode == "whitelist"`, only processes messages from allowed chats
- If `bot_behavior_mode == "blacklist"`, blocks messages from blocked chats
- Admins always bypass filters

### `app.middlewares.processing_lock`

Processing lock middleware.

#### `ProcessingLockMiddleware`

Prevents multiple simultaneous messages per user.

**Configuration:**
- `ENABLE_PROCESSING_LOCK` - Enable/disable
- `PROCESSING_LOCK_USE_REDIS` - Use Redis for locks
- `PROCESSING_LOCK_TTL_SECONDS` - Lock timeout (default 300s)

### `app.middlewares.command_throttle`

Command throttling middleware.

#### `CommandThrottleMiddleware`

Limits commands to 1 per 5 minutes (admins bypass).

---

## Tools

Tools are functions that the bot can call via Gemini function calling.

### Memory Tools

#### `remember_memory_tool`
Stores a memory about a user.

**Parameters:**
- `user_id: int` - User ID
- `memory_text: str` - Memory text
- `chat_id: int` (injected) - Chat ID
- `memory_repo: MemoryRepository` (injected) - Memory repository

**Returns:** JSON string with status and memory ID

#### `recall_memories_tool`
Retrieves all memories for a user.

**Parameters:**
- `user_id: int` - User ID
- `chat_id: int` (injected) - Chat ID
- `memory_repo: MemoryRepository` (injected) - Memory repository

**Returns:** JSON string with list of memories

#### `forget_memory_tool`
Deletes a specific memory.

**Parameters:**
- `user_id: int` - User ID
- `memory_id: int` - Memory ID
- `chat_id: int` (injected) - Chat ID
- `memory_repo: MemoryRepository` (injected) - Memory repository

**Returns:** JSON string with status

#### `forget_all_memories_tool`
Deletes all memories for a user.

**Parameters:**
- `user_id: int` - User ID
- `chat_id: int` (injected) - Chat ID
- `memory_repo: MemoryRepository` (injected) - Memory repository

**Returns:** JSON string with count deleted

#### `set_pronouns_tool`
Updates user pronouns.

**Parameters:**
- `user_id: int` - User ID
- `pronouns: str` - Pronouns (e.g., "she/her")
- `chat_id: int` (injected) - Chat ID
- `profile_store: UserProfileStore` (injected) - Profile store

**Returns:** JSON string with status

### Moderation Tools

#### `find_user`
Finds a user by username or name.

**Parameters:**
- `query: str` - Username, display name, or first name
- `chat_id: int` - Chat ID

**Returns:** JSON with user_id, username, display_name

#### `kick_user`
Kicks a user from chat.

**Parameters:**
- `user_id: int` - User ID (from find_user)
- `chat_id: int` - Chat ID

**Returns:** JSON with success status

#### `mute_user`
Temporarily mutes a user.

**Parameters:**
- `user_id: int` - User ID (from find_user)
- `chat_id: int` - Chat ID
- `duration_minutes: int | None` - Mute duration (default ~10 min)

**Returns:** JSON with success status

#### `unmute_user`
Unmutes a user.

**Parameters:**
- `user_id: int` - User ID (from find_user)
- `chat_id: int` - Chat ID

**Returns:** JSON with success status

### Search Tools

#### `search_messages`
Searches past conversation messages.

**Parameters:**
- `query: str` - Search query
- `chat_id: int` - Chat ID
- `limit: int = 10` - Max results

**Returns:** JSON with matching messages

---

## Configuration

### `app.config.Settings`

Pydantic settings loaded from environment variables.

#### Key Settings

**Telegram:**
- `TELEGRAM_TOKEN` - Bot token (required)

**Gemini:**
- `GEMINI_API_KEY` - Primary API key
- `GEMINI_API_KEYS` - Comma-separated additional keys
- `GEMINI_MODEL` - Model name (default: "gemini-2.5-flash")
- `GEMINI_EMBED_MODEL` - Embedding model (default: "models/text-embedding-004")
- `FREE_TIER_MODE` - Enable free tier mode
- `GEMINI_ENABLE_THINKING` - Enable thinking mode
- `THINKING_BUDGET_TOKENS` - Thinking token budget

**Database:**
- `DATABASE_URL` - PostgreSQL connection string

**Rate Limiting:**
- `PER_USER_PER_HOUR` - Messages per user per hour (default: 5)
- `WEATHER_LIMIT_PER_HOUR` - Weather requests per hour
- `CURRENCY_LIMIT_PER_HOUR` - Currency requests per hour
- `WEB_SEARCH_LIMIT_PER_HOUR` - Web searches per hour
- `MEMORY_LIMIT_PER_HOUR` - Memory operations per hour

**Features:**
- `ENABLE_WEB_SEARCH` - Enable web search
- `ENABLE_IMAGE_GENERATION` - Enable image generation
- `ENABLE_MULTI_LEVEL_CONTEXT` - Enable multi-level context
- `ENABLE_BOT_SELF_LEARNING` - Enable bot self-learning
- `ENABLE_CHAT_MEMORY` - Enable chat memory

**Admin:**
- `ADMIN_USER_IDS` - Comma-separated admin user IDs

**Example:**
```python
from app.config import get_settings

settings = get_settings()
print(settings.telegram_token)
print(settings.gemini_model)
```

---

## Usage Examples

### Creating a Custom Handler

```python
from aiogram import Bot, Router
from aiogram.types import Message
from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient

router = Router()

@router.message()
async def my_handler(
    message: Message,
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
):
    # Your handler logic
    await message.reply("Hello!")
```

### Using Context Store

```python
from app.services.context_store import ContextStore, MessageSender

store = ContextStore("postgresql://...")
await store.init()

# Add a message
await store.add_message(
    chat_id=123,
    thread_id=None,
    message_id=456,
    user_id=789,
    text="Hello!",
    role="user",
    metadata={},
    sender=MessageSender(role="user", name="John")
)

# Get recent messages
messages = await store.recent(chat_id=123, limit=20)

# Search messages
results = await store.search(chat_id=123, query="weather")
```

### Using Multi-Level Context

```python
from app.services.context.multi_level_context import MultiLevelContextManager

manager = MultiLevelContextManager(
    db_path="postgresql://...",
    settings=settings,
    context_store=store,
    profile_store=profile_store,
    hybrid_search=hybrid_search,
    episode_store=episodic_memory,
    gemini_client=gemini_client,
)

context = await manager.build_context(
    chat_id=123,
    thread_id=None,
    user_id=789,
    query_text="What did we discuss?",
    max_tokens=4000
)

print(f"Total tokens: {context.total_tokens}")
print(f"Immediate messages: {len(context.immediate.messages)}")
print(f"Recent messages: {len(context.recent.messages) if context.recent else 0}")
```

### Using Gemini Client

```python
from app.services.gemini import GeminiClient

client = GeminiClient(
    api_key="...",
    model="gemini-2.5-flash",
    embed_model="models/text-embedding-004"
)

# Generate text
response = await client.generate(
    messages=[
        {"role": "user", "parts": [{"text": "Hello!"}]}
    ],
    system_instruction="You are a helpful assistant."
)

# Generate embedding
embedding = await client.embed("Hello world")
```

### Using Memory Repository

```python
from app.repositories.memory_repository import MemoryRepository

repo = MemoryRepository("postgresql://...")
await repo.init()

# Add memory
memory = await repo.add_memory(
    user_id=789,
    chat_id=123,
    memory_text="User lives in Kyiv"
)

# Get all memories
memories = await repo.get_memories_for_user(user_id=789, chat_id=123)

# Delete memory
deleted = await repo.delete_memory(memory_id=memory.id)
```

### Using Rate Limiter

```python
from app.services.rate_limiter import RateLimiter

limiter = RateLimiter(
    database_url="postgresql://...",
    per_user_per_hour=5
)
await limiter.init()

allowed, reset_in = await limiter.check_limit(user_id=789)
if not allowed:
    print(f"Rate limited. Reset in {reset_in} seconds")
```

### Creating a Custom Tool

```python
from app.services.tools.base import format_tool_error

async def my_custom_tool(params: dict) -> str:
    """Custom tool that does something."""
    try:
        # Your tool logic
        result = {"status": "success", "data": "..."}
        return json.dumps(result)
    except Exception as e:
        return format_tool_error(str(e))

# Tool definition for Gemini
MY_TOOL_DEFINITION = {
    "function_declarations": [{
        "name": "my_custom_tool",
        "description": "Does something custom",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."}
            },
            "required": ["param1"]
        }
    }]
}

# Register in handler
tool_callbacks = {
    "my_custom_tool": my_custom_tool
}
```

---

## Error Handling

### Common Exceptions

#### `GeminiError`
Raised when Gemini API fails.

#### `GeminiContentBlockedError`
Raised when content is blocked by safety filters.

#### `DatabaseError`
Raised when database operations fail.

#### `QuotaExceededError`
Raised when rate limits are exceeded.

**Example:**
```python
from app.services.gemini import GeminiClient, GeminiError, GeminiContentBlockedError

try:
    response = await client.generate(...)
except GeminiContentBlockedError as e:
    print(f"Content blocked: {e.block_reason}")
except GeminiError as e:
    print(f"Gemini error: {e}")
```

---

## Best Practices

1. **Always use dependency injection** - Don't instantiate services in handlers
2. **Use middleware-injected services** - Services are automatically available
3. **Handle errors gracefully** - Use try/except blocks
4. **Respect rate limits** - Check limits before expensive operations
5. **Use async/await** - All operations are async
6. **Initialize services** - Call `init()` before using repositories/services
7. **Close connections** - Let context managers handle cleanup
8. **Use type hints** - Helps with IDE support and documentation

---

## Additional Resources

- [Architecture Documentation](architecture/)
- [Feature Documentation](features/)
- [Implementation Guides](guides/)
- [README](../README.md)
