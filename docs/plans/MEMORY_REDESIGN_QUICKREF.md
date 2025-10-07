# Memory System Redesign - Quick Reference

**Status**: 📋 Planning  
**Full Plan**: `MEMORY_TOOL_CALLING_REDESIGN.md`

## The Big Idea

Give Gemini **control** over its own memory instead of automated heuristics.

```
Before (Phase 1-4):                After (Phase 5):
Bot: "Я з Києва"                   Bot: "Я з Києва"
System: [waits 10 messages]        Model: recall_facts(user_id=123)
System: [extracts facts]           Model: remember_fact(type="personal",
System: [stores to DB]                    key="location", value="Київ",
                                          confidence=0.95)
                                   Model: "Ага, кияни..."
```

## 9 Memory Tools

### Remember (3 tools)

| Tool | Purpose | Example |
|------|---------|---------|
| `remember_fact` | Store new fact about user | User says "Я програміст" → store skill=programming |
| `create_episode` | Mark conversation as memorable | After 15 messages about wedding → create episode |
| `mark_important` | Prevent message deletion | User makes promise → extend retention to 365 days |

### Update (3 tools)

| Tool | Purpose | Example |
|------|---------|---------|
| `update_fact` | Correct existing fact | "Тепер в Львові" → update location from Kyiv to Lviv |
| `update_episode` | Modify episode importance | New info about past event → raise importance |
| `merge_facts` | Consolidate duplicates | "Python" + "Python 3.11" → "Python 3.11" |

### Forget (2 tools)

| Tool | Purpose | Example |
|------|---------|---------|
| `forget_fact` | Archive outdated info | "Я більше не програміст" → archive skill |
| `archive_episode` | Remove irrelevant episode | Old discussion superseded → archive |

### Recall (1 tool)

| Tool | Purpose | Example |
|------|---------|---------|
| `recall_facts` | Search existing facts | Before storing → check for duplicates/conflicts |

## Implementation Timeline

```
Phase 5.1 (Week 1):          Phase 5.2 (Week 2):         Phase 5.3 (Week 3):
├─ remember_fact             ├─ create_episode           ├─ Async orchestrator
├─ recall_facts              ├─ update_episode           ├─ Batch operations  
├─ update_fact               ├─ forget_fact              ├─ Migration from Phase 1-4
├─ Tool definitions          ├─ archive_episode          ├─ Performance tuning
├─ System prompt update      ├─ merge_facts              └─ Load testing
└─ Basic telemetry           └─ mark_important
```

## Key Design Decisions

### 1. Async by Default

```python
# Tool returns immediately
result = await remember_fact_tool(...)
# → {"status": "queued", "task_id": "abc123"}

# Background worker processes
await memory_orchestrator.process_queue()
# → Stores to DB, generates embeddings, etc.
```

**Why**: Keep responses fast (< 200ms perceived latency)

### 2. Quality Checks Built-In

```python
# remember_fact automatically:
1. Checks for duplicates (semantic similarity)
2. Validates confidence threshold
3. Applies fact quality metrics
4. Logs for audit trail
```

**Why**: Prevent garbage in DB, maintain data quality

### 3. JSON String Returns

```python
# All tools return JSON strings (not objects)
return json.dumps({
    "status": "success",
    "fact_id": 12345,
    "message": "Remembered: location = Київ"
})
```

**Why**: Consistency with existing tools (calculator, weather, etc.)

### 4. Fallback to Automation

```python
if ENABLE_TOOL_BASED_MEMORY:
    try:
        # Use tools
    except Exception:
        # Fall back to Phase 1-4 automation
```

**Why**: Safety net during migration

## Configuration

```bash
# .env additions
ENABLE_TOOL_BASED_MEMORY=true
MEMORY_TOOL_ASYNC=true              # Run in background (recommended)
MEMORY_TOOL_TIMEOUT_MS=200          # Max sync operation time
MEMORY_TOOL_QUEUE_SIZE=1000         # Max pending tasks
ENABLE_AUTOMATED_MEMORY_FALLBACK=true  # Safety net
```

## Success Criteria

| Phase | Metric | Target |
|-------|--------|--------|
| 5.1 | Tool latency p95 | < 200ms |
| 5.1 | Success rate | > 90% |
| 5.1 | Model usage rate | > 70% of relevant cases |
| 5.2 | Episode creation accuracy | > 80% |
| 5.2 | Duplicate fact rate | < 5% |
| 5.3 | Test coverage | > 95% |
| 5.3 | Zero degradation vs baseline | ✅ |

## Example Conversation

```
User: Я з Києва, працюю програмістом
Bot (internal):
  1. recall_facts(user_id=123, fact_types=["personal", "skill"])
  2. remember_fact(type="personal", key="location", value="Київ", confidence=0.95)
  3. remember_fact(type="skill", key="profession", value="програміст", confidence=0.9)
Bot (response): "Ага, айтішник з Києва. Що ж, хтось має тримати інтернет живим"

User: Насправді я тепер в Львові
Bot (internal):
  1. recall_facts(user_id=123, fact_types=["personal"])
  2. update_fact(type="personal", key="location", new_value="Львів", 
                 confidence=0.95, change_reason="update")
Bot (response): "Переїхав? Львів теж непоганий, якщо любиш каву та хіпстерів"

[After 20 messages about job change]
Bot (internal):
  1. create_episode(topic="Зміна роботи", summary="Переїхав з Києва до Львова, 
                    знайшов нову роботу в стартапі", importance=0.8,
                    emotional_valence="positive", tags=["робота", "переїзд", "кар'єра"])
```

## Migration Path

```
Week 1: New chats only
  if chat_id not in legacy_chats:
      use_tools = True

Week 2: A/B test (50%)
  use_tools = (hash(chat_id) % 2 == 0)

Week 3: Full rollout
  use_tools = True
  fallback_enabled = True
```

## Monitoring

### Telemetry

```python
# Track usage
telemetry.increment_counter("memory_tool_calls", {"tool": "remember_fact"})

# Track latency
telemetry.record_histogram("memory_tool_latency_ms", value=45)

# Track patterns
telemetry.increment_counter("memory_tool_pattern", 
                           {"pattern": "recall_before_remember"})
```

### Dashboards

- **Usage**: Calls per tool (pie chart)
- **Performance**: Latency p50/p95/p99 (histogram)
- **Quality**: Duplicate rate, update/forget ratio
- **Behavior**: Facts stored per conversation, episodes created per day

## Files to Create

```
app/services/tools/
├── __init__.py
├── memory_tools.py           # Tool handler functions
├── memory_definitions.py     # Gemini tool schemas
└── memory_orchestrator.py    # Async queue + worker

tests/unit/
└── test_memory_tools.py      # Unit tests

tests/integration/
└── test_memory_tool_flow.py  # Integration tests

docs/guides/
└── MEMORY_TOOLS_GUIDE.md     # User-facing docs
```

## References

- Full plan: `docs/plans/MEMORY_TOOL_CALLING_REDESIGN.md` (1200 lines)
- Gemini function calling: https://ai.google.dev/docs/function_calling
- Phase 1-4 status: `docs/phases/`
- Current fact extraction: `docs/features/HYBRID_EXTRACTION_COMPLETE.md`

## Quick Start (After Implementation)

```bash
# Enable tool-based memory
echo "ENABLE_TOOL_BASED_MEMORY=true" >> .env

# Restart bot
docker compose restart bot

# Test in chat
# Bot: "Tell me about yourself"
# You: "I'm from Kyiv, I'm a programmer"
# (Bot should use remember_fact tool)

# Check telemetry
sqlite3 gryag.db "SELECT * FROM telemetry WHERE metric LIKE 'memory_tool%' ORDER BY ts DESC LIMIT 10"
```

---

**Next Steps**:
1. Review full plan with team
2. Create Phase 5.1 tasks
3. Set up test environment
4. Begin implementation (ETA: 3 weeks)
