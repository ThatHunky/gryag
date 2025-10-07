# Memory Tools Architecture Diagram

## High-Level Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    User sends message                          │
│              "Я з Києва, працюю програмістом"                 │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                  Chat Handler (chat.py)                        │
│  • Builds context (multi-level or fallback)                   │
│  • Assembles system prompt + history                          │
│  • Defines 13 tools (4 existing + 9 new memory tools)         │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Gemini 2.5 Flash (with tools)                     │
│  Decides: Should I remember this?                             │
│           Already know this user?                             │
│           Need to update existing facts?                      │
└──────────────────────────────────────────────────────────────┘
                              │
                  ┌───────────┼───────────┐
                  │           │           │
                  ▼           ▼           ▼
         ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
         │recall_facts │ │remember_fact│ │remember_fact│
         │user_id=123  │ │type=personal│ │type=skill   │
         │             │ │key=location │ │key=job      │
         └─────────────┘ │value=Київ   │ │value=prog   │
                │        │confidence=.9│ │confidence=.9│
                │        └─────────────┘ └─────────────┘
                │                │               │
                ▼                ▼               ▼
    ┌─────────────────────────────────────────────────────┐
    │         Memory Orchestrator (async queue)            │
    │  • Deduplication check (semantic similarity)         │
    │  • Quality validation (confidence threshold)         │
    │  • Batches operations for performance                │
    └─────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────┐
    │           Background Worker (async)                  │
    │  • Generates embeddings                              │
    │  • Writes to database                                │
    │  • Updates telemetry                                 │
    │  • Returns immediately (non-blocking)                │
    └─────────────────────────────────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │    SQLite Database     │
                 │  • user_facts          │
                 │  • episodes            │
                 │  • fact_versions       │
                 │  • fact_quality_metrics│
                 └────────────────────────┘
```

## Tool Categories Breakdown

### 1. Remember Tools (Proactive Memory)

```
remember_fact
├─ Use case: "Я з Києва"
├─ Checks: Duplicate detection via recall_facts
├─ Stores: user_facts table
├─ Returns: {"status": "success", "fact_id": 123}
└─ Latency: <50ms (queued) + ~200ms (background)

create_episode
├─ Use case: After 15 messages about wedding plans
├─ Stores: episodes table with summary embedding
├─ Returns: {"status": "success", "episode_id": 45}
└─ Latency: ~500ms (Gemini summarization in background)

mark_important
├─ Use case: "I promise to help you tomorrow"
├─ Updates: message_importance table
├─ Returns: {"status": "success", "marked": 5}
└─ Latency: <20ms (DB write only)
```

### 2. Update Tools (Adaptive Memory)

```
update_fact
├─ Use case: "Тепер я в Львові" (was Київ)
├─ Updates: user_facts.fact_value + fact_versions
├─ Tracks: change_reason ("update", "correction", "refinement")
├─ Returns: {"status": "success", "old": "Київ", "new": "Львів"}
└─ Latency: <30ms

update_episode
├─ Use case: New info about past event
├─ Updates: episodes.summary, importance, tags
├─ Returns: {"status": "success", "episode_id": 45}
└─ Latency: ~300ms (re-embed summary)

merge_facts
├─ Use case: "Python" + "Python 3.11" → "Python 3.11"
├─ Archives: Duplicate facts with superseded=true
├─ Creates: New merged fact with higher confidence
├─ Returns: {"status": "success", "merged_id": 99}
└─ Latency: <50ms
```

### 3. Forget Tools (Memory Pruning)

```
forget_fact
├─ Use case: "Я більше не програміст"
├─ Soft delete: is_active=false, archived_at=now()
├─ Audit trail: Preserved in fact_versions
├─ Returns: {"status": "success", "archived": true}
└─ Latency: <20ms

archive_episode
├─ Use case: Old discussion no longer relevant
├─ Updates: episodes.archived=true
├─ Preserves: Data for analytics
├─ Returns: {"status": "success", "archived": true}
└─ Latency: <20ms
```

### 4. Recall Tools (Memory Retrieval)

```
recall_facts
├─ Use case: Check before storing new fact
├─ Searches: user_facts with optional semantic search
├─ Filters: By type, confidence, active status
├─ Returns: {"status": "success", "facts": [...]}
└─ Latency: <100ms (hybrid search)
```

## Data Flow Example: Full Conversation

```
Message 1: "Я з Києва"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot thinks:
  1. recall_facts(user_id=123, types=["personal"])
     → Result: No location found
  2. remember_fact(type="personal", key="location", value="Київ")
     → Queued (50ms)
Bot responds: "Ага, кияни теж бувають розумними"

Background (200ms later):
  • Check semantic similarity: No duplicate
  • Generate embedding for "Київ"
  • Store to user_facts table
  • Update telemetry counter

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Message 2 (20 messages later): "Насправді я тепер в Львові"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot thinks:
  1. recall_facts(user_id=123, types=["personal"])
     → Result: location="Київ" (fact_id=456)
  2. update_fact(fact_id=456, new_value="Львів", reason="update")
     → Updated (30ms)
Bot responds: "Переїхав? Львів теж непоганий"

Background:
  • Store version in fact_versions (old=Київ, new=Львів)
  • Re-generate embedding
  • Log change reason

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[After 20 messages about job change]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot thinks:
  1. create_episode(
       topic="Зміна роботи та переїзд",
       summary="Користувач переїхав з Києва до Львова...",
       importance=0.85,
       emotional_valence="positive",
       tags=["робота", "переїзд", "кар'єра"]
     )
     → Queued (50ms)
Bot responds: (normal conversation)

Background (500ms later):
  • Generate episode summary embedding
  • Store episode with message_ids
  • Link to user profile
```

## Performance Characteristics

### Latency Targets

| Operation | Sync (perceived) | Async (background) | Total |
|-----------|------------------|-------------------|-------|
| remember_fact | <50ms (queue) | ~200ms (embed+store) | ~250ms |
| recall_facts | <100ms (search) | - | <100ms |
| update_fact | <30ms (DB write) | ~100ms (re-embed) | ~130ms |
| create_episode | <50ms (queue) | ~500ms (summarize) | ~550ms |
| forget_fact | <20ms (soft delete) | - | <20ms |

### Database Impact

```
Before (Phase 1-4):
  • user_facts: Manual extraction, batch writes
  • episodes: Heuristic creation, no control
  • Total writes: ~5-10 per conversation

After (Phase 5 - Tool-based):
  • user_facts: On-demand via tools, selective
  • episodes: Model-controlled, quality over quantity
  • Total writes: ~3-7 per conversation (30% reduction expected)
```

### API Quota Impact

```
Before:
  • Embeddings: 1 per message (user turn only)
  • Generation: 1 per addressed message
  • Total: ~50-100 API calls/day (100 messages)

After:
  • Embeddings: 1 per message + 1-2 per fact stored
  • Generation: 1 per addressed message (unchanged)
  • Tool calls: Embedded in same generation request
  • Total: ~60-120 API calls/day (20% increase)
```

## Configuration Matrix

| Setting | Default | Impact |
|---------|---------|--------|
| `ENABLE_TOOL_BASED_MEMORY` | true | Master switch |
| `MEMORY_TOOL_ASYNC` | true | Background processing |
| `MEMORY_TOOL_TIMEOUT_MS` | 200 | Max sync latency |
| `MEMORY_TOOL_QUEUE_SIZE` | 1000 | Max pending ops |
| `ENABLE_AUTOMATED_MEMORY_FALLBACK` | true | Safety net |
| `FACT_CONFIDENCE_THRESHOLD` | 0.7 | Min confidence |
| `SEMANTIC_SIMILARITY_THRESHOLD` | 0.85 | Dedup threshold |

## Migration Strategy

```
Week 1: Tool-based for new chats only
┌─────────────────────────────────────┐
│ if chat_id in legacy_chats:         │
│     use_automation()  # Phase 1-4   │
│ else:                               │
│     use_tools()       # Phase 5     │
└─────────────────────────────────────┘

Week 2: A/B test (50% rollout)
┌─────────────────────────────────────┐
│ if hash(chat_id) % 2 == 0:          │
│     use_tools()                     │
│ else:                               │
│     use_automation()                │
└─────────────────────────────────────┘

Week 3: Full rollout (with fallback)
┌─────────────────────────────────────┐
│ try:                                │
│     use_tools()                     │
│ except Exception as e:              │
│     log_error(e)                    │
│     use_automation()  # Fallback    │
└─────────────────────────────────────┘
```

## Error Handling

```
Tool Call Failures:
├─ Network error → Retry 3x with exponential backoff
├─ Gemini error → Fall back to automation
├─ DB error → Log and skip (non-critical)
└─ Timeout → Queue for later processing

Quality Checks:
├─ Duplicate detected → Return skipped status
├─ Confidence too low → Reject with error
├─ Invalid parameters → Validation error
└─ Rate limit hit → Queue or throttle

Fallback Chain:
1. Tool-based memory (preferred)
2. Phase 1-4 automation (fallback)
3. No memory operations (degraded mode)
```

## Monitoring & Alerts

```
Metrics to Track:
├─ memory_tool_calls_total (by tool)
├─ memory_tool_success_rate (by tool)
├─ memory_tool_latency_ms (p50, p95, p99)
├─ memory_tool_queue_depth (gauge)
├─ memory_tool_errors_total (by error_type)
└─ memory_duplicate_rate (dedup effectiveness)

Alerts:
├─ Success rate < 90% → Page on-call
├─ Latency p95 > 500ms → Warning
├─ Queue depth > 500 → Warning
├─ Error rate > 5% → Warning
└─ Duplicate rate > 10% → Investigation
```

## File Structure

```
app/services/tools/
├── __init__.py
├── memory_tools.py           # Tool handler functions
│   ├── remember_fact_tool()
│   ├── recall_facts_tool()
│   ├── update_fact_tool()
│   ├── create_episode_tool()
│   ├── forget_fact_tool()
│   ├── merge_facts_tool()
│   ├── update_episode_tool()
│   ├── archive_episode_tool()
│   └── mark_important_tool()
├── memory_definitions.py     # Gemini function schemas
│   └── All 9 TOOL_DEFINITION dicts
└── memory_orchestrator.py    # Async queue & worker
    ├── MemoryOrchestrator
    ├── enqueue_memory_op()
    ├── _worker() [background]
    └── get_result()
```

---

**See also:**
- Full plan: `MEMORY_TOOL_CALLING_REDESIGN.md`
- Quick reference: `MEMORY_REDESIGN_QUICKREF.md`
- Implementation guide: (TBD - Phase 5.1)
