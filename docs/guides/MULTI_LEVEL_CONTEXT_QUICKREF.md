# Multi-Level Context - Quick Reference

**Status**: ✅ Integrated and Production Ready  
**Date**: October 6, 2025

## Quick Start

### Enable/Disable

```bash
# Enable (default)
ENABLE_MULTI_LEVEL_CONTEXT=true

# Disable (fallback to simple history)
ENABLE_MULTI_LEVEL_CONTEXT=false
```

Restart bot after changing.

## How It Works

### 5 Context Layers

| Layer | Purpose | Token % | Source |
|-------|---------|---------|--------|
| **Immediate** | Current turn | 20% | Last N messages |
| **Recent** | Active conversation | 30% | Recent history |
| **Relevant** | Similar past discussions | 25% | Hybrid search |
| **Background** | User personality | 15% | Profile + facts |
| **Episodic** | Memorable events | 10% | Episode store |

### Performance

- **Assembly Time**: ~400-500ms (parallelized)
- **Token Budget**: 8000 tokens (configurable)
- **Fallback**: <50ms (simple history)

## Configuration

### Main Settings

```bash
# Multi-level context
ENABLE_MULTI_LEVEL_CONTEXT=true
CONTEXT_TOKEN_BUDGET=8000

# Hybrid search
ENABLE_HYBRID_SEARCH=true
SEMANTIC_WEIGHT=0.5
KEYWORD_WEIGHT=0.3
TEMPORAL_WEIGHT=0.2

# Episodic memory
ENABLE_EPISODIC_MEMORY=true
AUTO_CREATE_EPISODES=true
```

### Token Budget Allocation

Default ratios (must sum to ~1.0):

```bash
CONTEXT_IMMEDIATE_RATIO=0.20  # 20%
CONTEXT_RECENT_RATIO=0.30     # 30%
CONTEXT_RELEVANT_RATIO=0.25   # 25%
CONTEXT_BACKGROUND_RATIO=0.15 # 15%
CONTEXT_EPISODIC_RATIO=0.10   # 10%
```

## Monitoring

### Check Logs

```bash
# Service initialization
grep "Multi-level context services initialized" logs

# Context assembly
grep "Multi-level context assembled" logs

# Fallback triggers
grep "Multi-level context assembly failed" logs
```

### Log Fields

```json
{
  "chat_id": 123,
  "user_id": 456,
  "total_tokens": 5432,
  "immediate_count": 3,
  "recent_count": 15,
  "relevant_count": 8,
  "episodic_count": 2
}
```

## Testing

### Integration Test

```bash
python test_integration.py
```

Expected output:
```
✅ Context assembled successfully!
   Total tokens: 5/8000
```

### Unit Tests

```bash
# Multi-level context
python test_multi_level_context.py  # 4 tests

# Hybrid search
python test_hybrid_search.py        # All tests

# Phase 1 migration
python migrate_phase1.py            # Verify DB
```

## Troubleshooting

### Issue: Context not being used

**Check**:
```bash
# 1. Is feature enabled?
grep ENABLE_MULTI_LEVEL_CONTEXT .env

# 2. Are services initialized?
grep "HybridSearchEngine initialized" logs
grep "EpisodicMemoryStore initialized" logs

# 3. Any errors?
grep ERROR logs | grep -i context
```

### Issue: High latency

**Solutions**:
1. Reduce token budget:
   ```bash
   CONTEXT_TOKEN_BUDGET=4000  # Down from 8000
   ```

2. Disable heavy layers:
   ```bash
   ENABLE_EPISODIC_MEMORY=false
   ENABLE_HYBRID_SEARCH=false
   ```

3. Check database performance:
   ```bash
   sqlite3 gryag.db "ANALYZE;"
   sqlite3 gryag.db "PRAGMA optimize;"
   ```

### Issue: No relevant context found

**Reasons**:
- Empty database (no message history)
- No matching semantic results
- FTS index not populated

**Fix**:
```bash
# Re-run Phase 1 migration
python migrate_phase1.py
```

## Architecture

### Data Flow

```
Message arrives
    ↓
Addressed to bot?
    ↓ Yes
Multi-level enabled?
    ↓ Yes
Build context from 5 layers (parallel)
    ↓
Format for Gemini
    ↓
Generate response
```

### Services

```
main.py
  ├─ HybridSearchEngine
  │   └─ Semantic + keyword + temporal
  ├─ EpisodicMemoryStore
  │   └─ Episode storage + retrieval
  └─ MultiLevelContextManager
      ├─ Immediate (ContextStore)
      ├─ Recent (ContextStore)
      ├─ Relevant (HybridSearchEngine)
      ├─ Background (UserProfileStore)
      └─ Episodic (EpisodicMemoryStore)
```

## Common Patterns

### Check if multi-level is active

```python
if settings.enable_multi_level_context:
    # Multi-level code path
else:
    # Fallback to simple history
```

### Access context layers

```python
context = await context_manager.build_context(...)

# Check what's available
if context.immediate:
    print(f"Immediate: {len(context.immediate.messages)} messages")

if context.relevant:
    print(f"Relevant: {len(context.relevant.snippets)} snippets")
    print(f"Avg relevance: {context.relevant.average_relevance:.2f}")
```

### Format for Gemini

```python
formatted = context_manager.format_for_gemini(context)

history = formatted["history"]
system_context = formatted.get("system_context")

# Use in generation
response = await gemini_client.generate(
    system_prompt=PERSONA + "\n\n" + system_context,
    history=history,
    user_parts=user_parts,
)
```

## Performance Tips

### 1. Optimize Token Budget

Start conservative, increase if needed:

```bash
# Start
CONTEXT_TOKEN_BUDGET=4000

# If responses need more context
CONTEXT_TOKEN_BUDGET=8000

# Max (expensive)
CONTEXT_TOKEN_BUDGET=16000
```

### 2. Tune Search Weights

Adjust based on your use case:

```bash
# More semantic, less keyword (conversational)
SEMANTIC_WEIGHT=0.6
KEYWORD_WEIGHT=0.2
TEMPORAL_WEIGHT=0.2

# More keyword, less semantic (factual)
SEMANTIC_WEIGHT=0.3
KEYWORD_WEIGHT=0.5
TEMPORAL_WEIGHT=0.2

# Favor recent (real-time)
SEMANTIC_WEIGHT=0.4
KEYWORD_WEIGHT=0.2
TEMPORAL_WEIGHT=0.4
```

### 3. Database Maintenance

Weekly:
```bash
sqlite3 gryag.db "VACUUM;"
sqlite3 gryag.db "ANALYZE;"
sqlite3 gryag.db "PRAGMA optimize;"
```

### 4. Monitor Performance

Track these metrics:
- Context assembly time (target: <500ms)
- Token usage per layer
- Fallback frequency
- Response quality

## Rollback

### Emergency Disable

```bash
# .env
ENABLE_MULTI_LEVEL_CONTEXT=false

# Restart
docker-compose restart bot
```

Bot will immediately use simple history retrieval.

### Full Rollback

If you need to remove multi-level context:

1. Disable in config:
   ```bash
   ENABLE_MULTI_LEVEL_CONTEXT=false
   ```

2. Remove services from `main.py`:
   ```python
   # Comment out these lines:
   # hybrid_search = HybridSearchEngine(...)
   # episodic_memory = EpisodicMemoryStore(...)
   ```

3. Restart bot

Database schema remains (safe for future re-enable).

## FAQ

**Q: Does this work with Redis?**  
A: Yes, multi-level context is independent of Redis.

**Q: What if database is empty?**  
A: Context manager gracefully handles empty results from all layers.

**Q: Can I disable specific layers?**  
A: Yes, via settings:
```bash
ENABLE_HYBRID_SEARCH=false      # Disables relevant layer
ENABLE_EPISODIC_MEMORY=false    # Disables episodic layer
```

**Q: How much memory does this use?**  
A: ~40KB per request for 8000 token budget.

**Q: Is it worth the latency increase?**  
A: Yes - better context = better responses. But monitor and tune for your use case.

**Q: Can I use this in private chats?**  
A: Yes, works in both groups and private chats.

## Next Steps

After multi-level context is working well:

1. **Phase 4**: Automatic episode creation
2. **Phase 5**: Fact relationship graphs
3. **Phase 6**: Temporal awareness + adaptive memory
4. **Phase 7**: Optimization + relevance feedback

## Resources

- **Implementation**: `docs/phases/PHASE_3_COMPLETE.md`
- **Integration**: `docs/phases/PHASE_3_INTEGRATION_COMPLETE.md`
- **Testing**: `docs/guides/PHASE_3_TESTING_GUIDE.md`
- **Full Plan**: `docs/plans/MEMORY_AND_CONTEXT_IMPROVEMENTS.md`

---

**Last Updated**: October 6, 2025  
**Version**: Phase 3 Complete  
**Status**: Production Ready ✅
