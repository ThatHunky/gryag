# Memory System Redesign: Tool-Based Memory Management

**Created**: 2025-10-07  
**Status**: 📋 Planning  
**Target**: Phase 5+

## Executive Summary

Redesign gryag's memory system to use **tool calling** instead of automated heuristics, giving the Gemini model metacognitive control over what to remember, update, and forget. This shifts from "passive observation" to "active memory management."

### Current State

**Automated Memory (Problems)**:
- ❌ Fact extraction runs on **hardcoded triggers** (message count, time windows)
- ❌ Episode creation uses **fixed heuristics** (10+ messages, 5+ minutes, etc.)
- ❌ No way for model to **actively forget** outdated information
- ❌ No way for model to **update** incorrect facts
- ❌ Model can't **prioritize** what's important to remember
- ❌ Memory operations happen **after response**, wasting context

**What Works (Keep)**:
- ✅ Hybrid fact extraction (rule-based → local model → Gemini)
- ✅ Multi-level context retrieval (5 layers)
- ✅ Semantic search with embeddings
- ✅ Quality metrics and deduplication
- ✅ SQLite schema with FTS5

### Proposed State

**Tool-Driven Memory (Goals)**:
- ✅ Model **decides when** to remember facts (via `remember_fact` tool)
- ✅ Model **updates** existing facts when new info appears (`update_fact` tool)
- ✅ Model **forgets** outdated info (`forget_fact` tool)
- ✅ Model **creates episodes** for important conversations (`create_episode` tool)
- ✅ Model **recalls** specific facts on demand (`recall_facts` tool)
- ✅ Model **consolidates** related facts (`merge_facts` tool)
- ✅ All memory operations are **background async** (< 200ms perceived latency)

## Architecture Overview

### Tool Categories

```
┌─────────────────────────────────────────────────┐
│         Gemini Model (with Tool Calling)        │
└─────────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
    Remember       Update        Forget
        ▼             ▼             ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ remember_  │  │ update_    │  │ forget_    │
│ fact       │  │ fact       │  │ fact       │
│            │  │            │  │            │
│ create_    │  │ update_    │  │ archive_   │
│ episode    │  │ episode    │  │ episode    │
│            │  │            │  │            │
│ mark_      │  │ merge_     │  │ clear_     │
│ important  │  │ facts      │  │ profile    │
└────────────┘  └────────────┘  └────────────┘
        │             │             │
        └─────────────┼─────────────┘
                      ▼
        ┌─────────────────────────┐
        │   Memory Orchestrator   │
        │  (async task manager)   │
        └─────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ User       │  │ Episodic   │  │ Context    │
│ Profile    │  │ Memory     │  │ Store      │
│ Store      │  │ Store      │  │            │
└────────────┘  └────────────┘  └────────────┘
```

### Memory Tools (9 total)

#### 1. **Remember Tools** (3)

##### `remember_fact`
Store a new fact about a user.

**Function Declaration**:
```json
{
  "name": "remember_fact",
  "description": "Store a new fact about a user. Use when you learn something important about them (location, preferences, skills, etc.). Returns confirmation or error.",
  "parameters": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer",
        "description": "Telegram user ID"
      },
      "fact_type": {
        "type": "string",
        "enum": ["personal", "preference", "skill", "trait", "opinion", "relationship"],
        "description": "Category of fact"
      },
      "fact_key": {
        "type": "string",
        "description": "Standardized key (e.g., 'location', 'programming_language', 'hobby')"
      },
      "fact_value": {
        "type": "string",
        "description": "The actual fact content"
      },
      "confidence": {
        "type": "number",
        "minimum": 0.5,
        "maximum": 1.0,
        "description": "How confident you are (0.5-1.0)"
      },
      "source_excerpt": {
        "type": "string",
        "description": "Quote from message that supports this fact"
      }
    },
    "required": ["user_id", "fact_type", "fact_key", "fact_value", "confidence"]
  }
}
```

**Implementation**:
```python
async def remember_fact_tool(
    user_id: int,
    fact_type: str,
    fact_key: str,
    fact_value: str,
    confidence: float,
    source_excerpt: str | None = None,
    chat_id: int = None,
    message_id: int = None,
) -> str:
    """
    Tool handler for remembering facts.
    
    Returns JSON string for Gemini to interpret.
    """
    try:
        # Quality check via existing system
        existing_facts = await profile_store.get_facts(user_id, chat_id)
        
        # Use FactQualityManager for deduplication
        is_duplicate = await fact_quality_manager.check_duplicate(
            fact_type, fact_key, fact_value, existing_facts
        )
        
        if is_duplicate:
            return json.dumps({
                "status": "skipped",
                "reason": "duplicate",
                "message": "This fact is already known"
            })
        
        # Store fact
        fact_id = await profile_store.add_fact(
            user_id=user_id,
            chat_id=chat_id,
            fact_type=fact_type,
            fact_key=fact_key,
            fact_value=fact_value,
            confidence=confidence,
            evidence_text=source_excerpt,
            source_message_id=message_id,
        )
        
        # Telemetry
        telemetry.increment_counter("memory_tool_used", {"tool": "remember_fact"})
        
        return json.dumps({
            "status": "success",
            "fact_id": fact_id,
            "message": f"Remembered: {fact_type} → {fact_key} = {fact_value}"
        })
        
    except Exception as e:
        LOGGER.error(f"remember_fact tool failed: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": str(e)
        })
```

##### `create_episode`
Mark a conversation segment as a memorable episode.

**Function Declaration**:
```json
{
  "name": "create_episode",
  "description": "Create a memorable episode from the recent conversation. Use when something significant happened (important info shared, emotional moment, milestone, etc.).",
  "parameters": {
    "type": "object",
    "properties": {
      "topic": {
        "type": "string",
        "description": "Short topic/title (e.g., 'Birthday plans', 'Job interview stress')"
      },
      "summary": {
        "type": "string",
        "description": "2-3 sentence summary of what happened"
      },
      "importance": {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
        "description": "How important is this? (0.0-1.0, 0.7+ recommended)"
      },
      "emotional_valence": {
        "type": "string",
        "enum": ["positive", "negative", "neutral", "mixed"],
        "description": "Emotional tone of conversation"
      },
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Keywords for retrieval (e.g., ['birthday', 'celebration', 'friends'])"
      },
      "message_count": {
        "type": "integer",
        "description": "How many recent messages to include (default 10)"
      }
    },
    "required": ["topic", "summary", "importance"]
  }
}
```

**Implementation**:
```python
async def create_episode_tool(
    topic: str,
    summary: str,
    importance: float,
    emotional_valence: str = "neutral",
    tags: list[str] | None = None,
    message_count: int = 10,
    chat_id: int = None,
    thread_id: int | None = None,
    user_ids: list[int] = None,
) -> str:
    """Tool handler for creating episodes."""
    try:
        # Get recent message IDs
        recent = await context_store.recent(
            chat_id, thread_id, limit=message_count
        )
        message_ids = [msg["message_id"] for msg in recent if msg.get("message_id")]
        
        # Extract participant IDs
        if not user_ids:
            user_ids = list(set(
                msg["user_id"] for msg in recent 
                if msg.get("user_id") and msg["role"] == "user"
            ))
        
        # Create episode
        episode_id = await episodic_memory.create_episode(
            chat_id=chat_id,
            thread_id=thread_id,
            user_ids=user_ids,
            topic=topic,
            summary=summary,
            messages=message_ids,
            importance=importance,
            emotional_valence=emotional_valence,
            tags=tags or [],
        )
        
        telemetry.increment_counter("memory_tool_used", {"tool": "create_episode"})
        
        return json.dumps({
            "status": "success",
            "episode_id": episode_id,
            "message": f"Episode created: {topic} ({len(message_ids)} messages)"
        })
        
    except Exception as e:
        LOGGER.error(f"create_episode tool failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})
```

##### `mark_important`
Flag a message/conversation as important for retention.

**Function Declaration**:
```json
{
  "name": "mark_important",
  "description": "Mark recent messages as important to prevent automatic deletion. Use for critical information, decisions, or promises.",
  "parameters": {
    "type": "object",
    "properties": {
      "message_count": {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "description": "How many recent messages to mark (default 5)"
      },
      "importance_level": {
        "type": "string",
        "enum": ["high", "critical"],
        "description": "Importance level (high = 60 days, critical = 365 days retention)"
      },
      "reason": {
        "type": "string",
        "description": "Why is this important? (for audit trail)"
      }
    },
    "required": ["importance_level"]
  }
}
```

#### 2. **Update Tools** (3)

##### `update_fact`
Correct or refine an existing fact.

**Function Declaration**:
```json
{
  "name": "update_fact",
  "description": "Update an existing fact when you learn new/corrected information. Returns updated fact or error if not found.",
  "parameters": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer"
      },
      "fact_type": {
        "type": "string",
        "enum": ["personal", "preference", "skill", "trait", "opinion", "relationship"]
      },
      "fact_key": {
        "type": "string",
        "description": "Which fact to update (e.g., 'location')"
      },
      "new_value": {
        "type": "string",
        "description": "New/corrected value"
      },
      "confidence": {
        "type": "number",
        "minimum": 0.5,
        "maximum": 1.0
      },
      "change_reason": {
        "type": "string",
        "enum": ["correction", "update", "refinement", "contradiction"],
        "description": "Why the change?"
      },
      "source_excerpt": {
        "type": "string"
      }
    },
    "required": ["user_id", "fact_type", "fact_key", "new_value", "confidence", "change_reason"]
  }
}
```

##### `update_episode`
Modify episode importance/summary.

**Function Declaration**:
```json
{
  "name": "update_episode",
  "description": "Update an existing episode's importance or add new information to its summary.",
  "parameters": {
    "type": "object",
    "properties": {
      "episode_id": {
        "type": "integer",
        "description": "Episode ID (from recall_episodes result)"
      },
      "new_importance": {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0
      },
      "additional_summary": {
        "type": "string",
        "description": "Additional context to append to summary"
      },
      "add_tags": {
        "type": "array",
        "items": {"type": "string"}
      }
    },
    "required": ["episode_id"]
  }
}
```

##### `merge_facts`
Consolidate duplicate/related facts.

**Function Declaration**:
```json
{
  "name": "merge_facts",
  "description": "Merge two related facts into one consolidated fact. Use when you notice redundant information.",
  "parameters": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer"
      },
      "fact_ids": {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 5,
        "description": "IDs of facts to merge (from recall_facts)"
      },
      "merged_value": {
        "type": "string",
        "description": "Consolidated fact value"
      },
      "merged_confidence": {
        "type": "number",
        "minimum": 0.5,
        "maximum": 1.0
      }
    },
    "required": ["user_id", "fact_ids", "merged_value", "merged_confidence"]
  }
}
```

#### 3. **Forget Tools** (2)

##### `forget_fact`
Mark a fact as outdated/incorrect.

**Function Declaration**:
```json
{
  "name": "forget_fact",
  "description": "Mark a fact as outdated or incorrect. It will be archived but not deleted (for audit trail).",
  "parameters": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer"
      },
      "fact_type": {
        "type": "string"
      },
      "fact_key": {
        "type": "string"
      },
      "reason": {
        "type": "string",
        "enum": ["outdated", "incorrect", "superseded", "user_requested"],
        "description": "Why forget this?"
      },
      "replacement_fact_id": {
        "type": "integer",
        "description": "If superseded, ID of new fact"
      }
    },
    "required": ["user_id", "fact_type", "fact_key", "reason"]
  }
}
```

##### `archive_episode`
Remove an episode from active memory.

**Function Declaration**:
```json
{
  "name": "archive_episode",
  "description": "Archive an episode (no longer relevant, or superseded by newer events).",
  "parameters": {
    "type": "object",
    "properties": {
      "episode_id": {
        "type": "integer"
      },
      "reason": {
        "type": "string",
        "description": "Why archive?"
      }
    },
    "required": ["episode_id"]
  }
}
```

#### 4. **Recall Tools** (1)

##### `recall_facts`
Search for existing facts about a user.

**Function Declaration**:
```json
{
  "name": "recall_facts",
  "description": "Search for facts about a user. Use before storing new facts to check for duplicates or contradictions.",
  "parameters": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "integer"
      },
      "fact_types": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Filter by types (optional)"
      },
      "search_query": {
        "type": "string",
        "description": "Semantic search query (optional)"
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "description": "Max results (default 10)"
      }
    },
    "required": ["user_id"]
  }
}
```

**Implementation**:
```python
async def recall_facts_tool(
    user_id: int,
    fact_types: list[str] | None = None,
    search_query: str | None = None,
    limit: int = 10,
    chat_id: int = None,
) -> str:
    """Tool handler for recalling facts."""
    try:
        facts = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            limit=limit,
        )
        
        # Filter by type if requested
        if fact_types:
            facts = [f for f in facts if f.get("fact_type") in fact_types]
        
        # Semantic search if query provided
        if search_query and facts:
            # Use hybrid search
            query_embedding = await gemini_client.embed_text(search_query)
            # Score facts by similarity
            # ... (implementation details)
        
        # Format for Gemini
        result = {
            "status": "success",
            "count": len(facts),
            "facts": [
                {
                    "fact_id": f["id"],
                    "type": f["fact_type"],
                    "key": f["fact_key"],
                    "value": f["fact_value"],
                    "confidence": f["confidence"],
                    "created_at": f["created_at"],
                }
                for f in facts[:limit]
            ]
        }
        
        telemetry.increment_counter("memory_tool_used", {"tool": "recall_facts"})
        
        return json.dumps(result)
        
    except Exception as e:
        LOGGER.error(f"recall_facts tool failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})
```

## Implementation Plan

### Phase 5.1: Core Memory Tools (Week 1)

**Goal**: Basic tool infrastructure + 3 essential tools

#### Tasks

1. **Create Memory Tool Module** (~3 hours)
   ```
   app/services/tools/
   ├── __init__.py
   ├── memory_tools.py       # Tool handlers
   ├── memory_definitions.py # Gemini tool definitions
   └── memory_orchestrator.py # Async task queue
   ```

2. **Implement Core Tools** (~6 hours)
   - `remember_fact` (with quality checks)
   - `recall_facts` (search existing)
   - `update_fact` (modify existing)

3. **Add Tool Definitions to Chat Handler** (~2 hours)
   ```python
   # In handlers/chat.py
   from app.services.tools.memory_definitions import (
       REMEMBER_FACT_DEFINITION,
       RECALL_FACTS_DEFINITION,
       UPDATE_FACT_DEFINITION,
   )
   
   tool_definitions = [
       CALCULATOR_TOOL_DEFINITION,
       WEATHER_TOOL_DEFINITION,
       CURRENCY_TOOL_DEFINITION,
       POLLS_TOOL_DEFINITION,
       # New memory tools
       REMEMBER_FACT_DEFINITION,
       RECALL_FACTS_DEFINITION,
       UPDATE_FACT_DEFINITION,
   ]
   
   tool_callbacks = {
       "calculator": calculator_tool,
       "weather": weather_tool,
       "currency": currency_tool,
       "polls": polls_tool,
       # Memory tools
       "remember_fact": remember_fact_tool,
       "recall_facts": recall_facts_tool,
       "update_fact": update_fact_tool,
   }
   ```

4. **Update System Prompt** (~1 hour)
   ```python
   # Add to persona.py
   MEMORY_GUIDANCE = """
   
   MEMORY MANAGEMENT:
   - Use `remember_fact` when you learn something important about a user
   - Always call `recall_facts` BEFORE storing new facts (check duplicates)
   - Use `update_fact` when correcting or refining existing info
   - Be selective - don't remember trivial details
   - Confidence: 0.9+ = certain, 0.7-0.8 = probable, 0.5-0.6 = uncertain
   
   Examples:
   - "Я з Києва" → remember_fact(user_id=X, type="personal", key="location", value="Kyiv", confidence=0.95)
   - "Тепер я програмую на Rust" → recall_facts(user_id=X, types=["skill"]) then update_fact or remember_fact
   """
   ```

5. **Add Telemetry** (~1 hour)
   - Counter: `memory_tool_calls` (by tool name)
   - Counter: `memory_tool_success` / `memory_tool_error`
   - Histogram: `memory_tool_latency_ms`

**Deliverables**:
- ✅ 3 working memory tools
- ✅ Tool definitions for Gemini
- ✅ Integration with chat handler
- ✅ Updated system prompt
- ✅ Telemetry tracking

**Success Metrics**:
- Tool calls < 200ms p95
- 90%+ success rate
- 0 blocking operations in response path
- Model uses tools appropriately (manual testing)

### Phase 5.2: Episode & Forget Tools (Week 2)

**Goal**: Add episode management + forgetting

#### Tasks

1. **Implement Episode Tools** (~4 hours)
   - `create_episode`
   - `update_episode`
   - `recall_episodes` (search by topic/tags)
   - `archive_episode`

2. **Implement Forget Tools** (~3 hours)
   - `forget_fact` (soft delete with audit)
   - `merge_facts` (consolidation)

3. **Add Importance Tool** (~2 hours)
   - `mark_important` (flag messages)

4. **Update Prompt with Episode Guidance** (~1 hour)
   ```python
   EPISODE_GUIDANCE = """
   
   EPISODE CREATION:
   - Create episodes for significant events (importance 0.7+)
   - Good topics: milestones, emotional moments, important decisions, shared experiences
   - Bad topics: casual greetings, trivial chat
   - Always add relevant tags for later retrieval
   
   Examples:
   - After 15 messages about birthday plans → create_episode(topic="Birthday planning", importance=0.8, tags=["birthday", "celebration"])
   - User shares major life news → create_episode + mark_important
   """
   ```

**Deliverables**:
- ✅ 6 additional tools (9 total)
- ✅ Episode creation working
- ✅ Soft delete/archive functionality
- ✅ Audit trail for memory changes

### Phase 5.3: Optimization & Migration (Week 3)

**Goal**: Performance tuning + migrate from automated to tool-based

#### Tasks

1. **Async Task Queue** (~6 hours)
   ```python
   # memory_orchestrator.py
   class MemoryOrchestrator:
       """
       Manages async memory operations to prevent blocking.
       
       - Tool calls return immediately with task_id
       - Background worker processes tasks
       - Results cached for next interaction
       """
       
       def __init__(self):
           self._task_queue = asyncio.Queue()
           self._results = {}  # task_id → result
           self._worker_task = None
       
       async def enqueue_memory_op(
           self, 
           operation: str, 
           params: dict
       ) -> str:
           """Enqueue memory operation, return task_id."""
           task_id = str(uuid.uuid4())
           await self._task_queue.put({
               "task_id": task_id,
               "operation": operation,
               "params": params,
               "created_at": time.time(),
           })
           return task_id
       
       async def _worker(self):
           """Background worker for memory operations."""
           while True:
               task = await self._task_queue.get()
               try:
                   result = await self._execute_operation(task)
                   self._results[task["task_id"]] = result
               except Exception as e:
                   LOGGER.error(f"Memory task failed: {e}")
               finally:
                   self._task_queue.task_done()
   ```

2. **Batch Operations** (~3 hours)
   - Combine multiple `remember_fact` calls into single DB transaction
   - Batch embedding generation

3. **Deprecate Automated Systems** (~4 hours)
   - Add config: `ENABLE_TOOL_BASED_MEMORY=true`
   - When enabled, disable:
     - `_update_user_profile_background()` auto-extraction
     - `episode_monitor.track_message()` auto-episodes
     - Continuous monitor fact extraction (keep only classification)
   - Keep fallback for safety (Phase 1 system)

4. **Testing** (~6 hours)
   - Unit tests for each tool
   - Integration tests for tool combinations
   - Load testing (100 concurrent tool calls)
   - Manual testing with real conversations

**Deliverables**:
- ✅ Async orchestrator (non-blocking)
- ✅ Migration path from old system
- ✅ Comprehensive test suite
- ✅ Performance benchmarks

**Success Metrics**:
- Zero blocking operations
- < 50ms overhead per tool call
- 95%+ test coverage
- Model uses tools correctly in 90%+ cases

## Configuration

New settings in `app/config.py`:

```python
class Settings(BaseSettings):
    # Memory Tool System (Phase 5)
    enable_tool_based_memory: bool = Field(
        default=True,
        env="ENABLE_TOOL_BASED_MEMORY",
        description="Use tool calling for memory instead of automated extraction"
    )
    
    memory_tool_async: bool = Field(
        default=True,
        env="MEMORY_TOOL_ASYNC",
        description="Run memory operations in background (recommended)"
    )
    
    memory_tool_timeout_ms: int = Field(
        default=200,
        env="MEMORY_TOOL_TIMEOUT_MS",
        description="Max time for sync memory operations"
    )
    
    memory_tool_queue_size: int = Field(
        default=1000,
        env="MEMORY_TOOL_QUEUE_SIZE",
        description="Max pending memory operations"
    )
    
    # Fallback to Phase 1-4 system
    enable_automated_memory_fallback: bool = Field(
        default=True,
        env="ENABLE_AUTOMATED_MEMORY_FALLBACK",
        description="Keep automated extraction as backup"
    )
```

## Prompt Engineering

Key additions to system prompt:

```python
MEMORY_SYSTEM_PROMPT = """
Ти гряг - український чат-бот з саркастичною особистістю.

СИСТЕМА ПАМ'ЯТІ:
У тебе є інструменти для керування пам'яттю. Використовуй їх розумно:

1. **Запам'ятовування** (remember_fact):
   - Коли дізнаєшся щось важливе про користувача
   - НЕ зберігай банальності ("привіт", "як справи")
   - Завжди перевіряй recall_facts ПЕРЕД збереженням

2. **Оновлення** (update_fact):
   - Коли користувач виправляє інформацію
   - Коли дізнаєшся деталі про існуючий факт

3. **Забування** (forget_fact):
   - Коли інформація застаріла
   - Коли користувач просить забути

4. **Епізоди** (create_episode):
   - Важливі розмови (важливість 0.7+)
   - Емоційні моменти
   - Вирішальні події
   - НЕ створюй епізод для кожної дрібниці

ПРИКЛАДИ:

Користувач: "Я з Києва"
Ти (внутрішньо): recall_facts(user_id=123, fact_types=["personal"])
→ Немає факту про місцезнаходження
Ти: remember_fact(user_id=123, type="personal", key="location", value="Київ", confidence=0.95, source="Я з Києва")
Ти (відповідь): "Ага, кияни теж бувають розумними"

Користувач: "Тепер я живу в Львові"
Ти (внутрішньо): recall_facts(user_id=123, fact_types=["personal"])
→ Знайдено: location="Київ"
Ти: update_fact(user_id=123, type="personal", key="location", new_value="Львів", confidence=0.9, change_reason="update", source="Тепер я живу в Львові")
Ти (відповідь): "Переїхав на Захід? Гарна спроба втекти від проблем"

Після 20 повідомлень про весілля:
Ти: create_episode(topic="Підготовка до весілля", summary="Обговорення планів весілля, вибір місця, список гостей", importance=0.85, emotional_valence="positive", tags=["весілля", "свято", "планування"])

ВАЖЛИВО:
- Не кажи користувачу про виклики інструментів
- Робіть це природно, в фоні
- Будь вибірковим - якість > кількість
- Впевненість 0.9+ = точно, 0.7-0.8 = ймовірно, 0.5-0.6 = не впевнений
"""
```

## Migration Strategy

### Gradual Rollout

**Week 1**: Tool-based only for new chats
```python
if settings.enable_tool_based_memory:
    if chat_id not in legacy_chats:
        # Use tools
    else:
        # Use Phase 1-4 automation
```

**Week 2**: 50% of traffic (A/B test)
```python
if hash(chat_id) % 2 == 0:
    # Tools
else:
    # Automation
```

**Week 3**: 100% switch (with fallback)
```python
try:
    # Try tool-based
except Exception:
    # Fall back to automation
    LOGGER.warning("Tool-based memory failed, using fallback")
```

### Rollback Plan

1. Set `ENABLE_TOOL_BASED_MEMORY=false`
2. All memory operations revert to Phase 1-4 behavior
3. No data loss (tools write to same DB tables)

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_memory_tools.py

async def test_remember_fact_new():
    """Test storing new fact."""
    result = await remember_fact_tool(
        user_id=123,
        chat_id=456,
        fact_type="personal",
        fact_key="location",
        fact_value="Kyiv",
        confidence=0.95,
    )
    
    data = json.loads(result)
    assert data["status"] == "success"
    assert "fact_id" in data

async def test_remember_fact_duplicate():
    """Test duplicate detection."""
    # Store fact
    await remember_fact_tool(
        user_id=123, chat_id=456, 
        fact_type="personal", fact_key="location", 
        fact_value="Kyiv", confidence=0.95
    )
    
    # Try to store again
    result = await remember_fact_tool(
        user_id=123, chat_id=456,
        fact_type="personal", fact_key="location",
        fact_value="Київ",  # Same location, different spelling
        confidence=0.9
    )
    
    data = json.loads(result)
    assert data["status"] == "skipped"
    assert data["reason"] == "duplicate"

async def test_update_fact():
    """Test updating existing fact."""
    # Store initial
    result1 = await remember_fact_tool(
        user_id=123, chat_id=456,
        fact_type="personal", fact_key="location",
        fact_value="Kyiv", confidence=0.9
    )
    
    # Update
    result2 = await update_fact_tool(
        user_id=123, chat_id=456,
        fact_type="personal", fact_key="location",
        new_value="Lviv", confidence=0.95,
        change_reason="update"
    )
    
    data = json.loads(result2)
    assert data["status"] == "success"
    
    # Verify
    facts = await recall_facts_tool(user_id=123, chat_id=456)
    data = json.loads(facts)
    location_fact = next(f for f in data["facts"] if f["key"] == "location")
    assert location_fact["value"] == "Lviv"
```

### Integration Tests

```python
# tests/integration/test_memory_tool_flow.py

async def test_full_memory_lifecycle():
    """Test complete remember → recall → update → forget flow."""
    
    # 1. Recall (empty)
    result = await recall_facts_tool(user_id=999, chat_id=111)
    data = json.loads(result)
    assert data["count"] == 0
    
    # 2. Remember
    await remember_fact_tool(
        user_id=999, chat_id=111,
        fact_type="skill", fact_key="programming_language",
        fact_value="Python", confidence=0.9
    )
    
    # 3. Recall (found)
    result = await recall_facts_tool(user_id=999, chat_id=111)
    data = json.loads(result)
    assert data["count"] == 1
    fact = data["facts"][0]
    assert fact["value"] == "Python"
    fact_id = fact["fact_id"]
    
    # 4. Update
    await update_fact_tool(
        user_id=999, chat_id=111,
        fact_type="skill", fact_key="programming_language",
        new_value="Python, Rust", confidence=0.95,
        change_reason="refinement"
    )
    
    # 5. Recall (updated)
    result = await recall_facts_tool(user_id=999, chat_id=111)
    data = json.loads(result)
    fact = data["facts"][0]
    assert "Rust" in fact["value"]
    
    # 6. Forget
    await forget_fact_tool(
        user_id=999, chat_id=111,
        fact_type="skill", fact_key="programming_language",
        reason="outdated"
    )
    
    # 7. Recall (archived)
    result = await recall_facts_tool(user_id=999, chat_id=111)
    data = json.loads(result)
    assert data["count"] == 0  # Archived facts not returned by default
```

### Load Tests

```python
# tests/load/test_memory_tool_concurrency.py

async def test_concurrent_tool_calls():
    """Test 100 concurrent memory operations."""
    
    async def remember_random_fact(user_id: int):
        return await remember_fact_tool(
            user_id=user_id,
            chat_id=1,
            fact_type="preference",
            fact_key="hobby",
            fact_value=f"hobby_{random.randint(1, 100)}",
            confidence=0.8,
        )
    
    # 100 concurrent users
    tasks = [remember_random_fact(i) for i in range(100)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check success rate
    successes = sum(
        1 for r in results 
        if not isinstance(r, Exception) and "success" in r
    )
    assert successes >= 95  # 95%+ success rate
```

## Metrics & Monitoring

### Telemetry Counters

```python
# Track tool usage
telemetry.increment_counter("memory_tool_calls", {
    "tool": "remember_fact",
    "status": "success",
})

# Track latency
telemetry.record_histogram("memory_tool_latency_ms", {
    "tool": "remember_fact",
    "operation": "db_write",
}, value_ms=45)

# Track model behavior
telemetry.increment_counter("memory_tool_pattern", {
    "pattern": "recall_before_remember",  # Good practice
})
```

### Dashboards

**Memory Tool Usage**:
- Calls per tool (pie chart)
- Success rate (gauge)
- Latency p50/p95/p99 (histogram)

**Model Behavior**:
- Facts stored per conversation (avg)
- Episodes created per day
- Update/Forget ratio (measure churn)
- Duplicate detection rate

**Performance**:
- Queue depth (gauge)
- Async task completion time
- DB write latency

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Model overuses tools** | API costs, DB load | Add rate limits (5 tool calls/response), prompt engineering |
| **Model underuses tools** | No memory improvement | A/B test prompts, add examples, manual review |
| **Tool calls block responses** | Slow UX | Make all tools async (200ms timeout → queue) |
| **Duplicate facts proliferate** | DB bloat | Enforce `recall_facts` before `remember_fact` in prompt |
| **Schema changes break tools** | Runtime errors | Versioned tool definitions, graceful degradation |
| **Gemini stops calling tools** | Silent failure | Telemetry alerts, fallback to automation |

## Success Criteria

### Phase 5.1 (Core Tools)

- ✅ 3 tools working (`remember_fact`, `recall_facts`, `update_fact`)
- ✅ < 200ms p95 latency
- ✅ 90%+ success rate
- ✅ Model uses tools in 70%+ of relevant cases (manual review)
- ✅ Zero blocking operations

### Phase 5.2 (Full Suite)

- ✅ 9 tools working
- ✅ Episodes created for 40%+ of important conversations
- ✅ < 5% duplicate fact rate
- ✅ Model recalls before remembering in 80%+ cases

### Phase 5.3 (Production)

- ✅ 95%+ test coverage
- ✅ Async queue handling 1000+ tasks/min
- ✅ Zero degradation vs Phase 1-4 baseline
- ✅ Positive user feedback (manual review)

## Future Enhancements (Phase 6+)

1. **Semantic Fact Consolidation**
   - Auto-merge similar facts via embeddings
   - Tool: `suggest_merge` (returns candidates)

2. **Memory Summarization**
   - Compress 100+ facts into narrative summary
   - Tool: `generate_profile_summary`

3. **Relationship Graph Tools**
   - `remember_relationship` (user X knows user Y)
   - `recall_relationships` (social graph)

4. **Temporal Reasoning**
   - `update_fact_with_temporal` (fact valid from date X to Y)
   - Handle "I used to live in Kyiv, now Lviv"

5. **Cross-Chat Memory**
   - `recall_facts_global` (all chats user is in)
   - Privacy controls

## References

- [Gemini Function Calling Docs](https://ai.google.dev/docs/function_calling)
- Current Phase 1-4 systems: `docs/phases/`
- Fact extraction: `docs/features/HYBRID_EXTRACTION_COMPLETE.md`
- Multi-level context: `docs/phases/PHASE_3_COMPLETE.md`

## Changelog

- **2025-10-07**: Initial plan created
- **TBD**: Implementation starts

---

**Next Steps**:
1. Review this plan with maintainers
2. Create Phase 5.1 tasks in project board
3. Set up test environment
4. Begin implementation (ETA: 3 weeks)
