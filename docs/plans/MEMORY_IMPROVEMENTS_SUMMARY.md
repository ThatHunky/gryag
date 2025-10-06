# Memory & Context Improvements - Executive Summary

**Status**: Planning Complete  
**Date**: October 6, 2025  
**Full Plan**: [MEMORY_AND_CONTEXT_IMPROVEMENTS.md](./MEMORY_AND_CONTEXT_IMPROVEMENTS.md)

---

## Quick Overview

This plan addresses major gaps in the bot's memory and context management through 6 strategic improvements delivered over 14 weeks.

### Current Problems

1. **Poor context retrieval** - Misses relevant past conversations (semantic-only search)
2. **Weak long-term memory** - Doesn't effectively use accumulated knowledge
3. **Flat fact organization** - No hierarchy, topic clustering, or relationships
4. **No temporal awareness** - Recent and old information weighted equally
5. **Performance issues** - Slow queries with large histories

### Expected Impact

- **30-50% better context relevance** through hybrid search
- **3-5x improved long-term recall** via episodic memory
- **60% reduction in redundant facts** through better deduplication
- **2x faster retrieval** via optimized indexing and caching

---

## Six Key Improvements

### 1. Multi-Level Context System ⭐⭐⭐

**Problem**: Flat context doesn't distinguish immediate, recent, and background information

**Solution**: Layered context with 5 levels:

```
1. IMMEDIATE (0-5 messages, <1 min) - Current turn
2. RECENT (5-30 messages, <30 min) - Active thread
3. RELEVANT (semantic/keyword, any time) - Hybrid search results
4. BACKGROUND (user profile, facts) - User-specific knowledge
5. EPISODIC (memorable events) - Long-term event memory
```

**Benefit**: Bot can distinguish "what just happened" from "what's relevant from past"

**Implementation**: Weeks 5-6 (Phase 3)

---

### 2. Hybrid Search & Ranking ⭐⭐⭐

**Problem**: Semantic search alone misses keyword matches and ignores recency

**Solution**: Multi-signal search combining:

- **Semantic similarity** (embedding cosine)
- **Keyword matching** (SQLite FTS5)
- **Temporal recency** (exponential decay)
- **User importance** (interaction weighting)
- **Message type** (addressed vs unaddressed)

**Benefit**: More relevant results, especially for specific queries like "that restaurant we discussed"

**Implementation**: Weeks 3-4 (Phase 2)

---

### 3. Episodic Memory ⭐⭐

**Problem**: Bot doesn't remember significant conversation events long-term

**Solution**: Store memorable conversation episodes as summaries with:

- Topic and summary
- Participants and timeline
- Importance score
- Emotional context
- Searchable tags

**Triggers**: High emotional content, important facts shared, long coherent discussions

**Benefit**: Long-term event recall like "remember when we planned that trip?"

**Implementation**: Weeks 7-8 (Phase 4)

---

### 4. Fact Graphs ⭐⭐

**Problem**: Facts are isolated, can't reason over relationships

**Solution**: Build knowledge graph with:

- Facts as nodes
- Inferred relationships as edges (semantic similarity, category clustering, domain rules)
- Multi-hop queries (e.g., "What do we know about user's work?")
- Topic clustering

**Benefit**: Richer reasoning, connect related information, answer complex queries

**Implementation**: Weeks 9-10 (Phase 5)

---

### 5. Temporal Awareness ⭐⭐⭐

**Problem**: Recent and old information weighted equally

**Solution**: 

- **Fact versioning** - Track changes over time (preferences evolve)
- **Recency boosting** - Exponential decay (7-day half-life)
- **Change tracking** - Reinforcement, evolution, contradiction detection

**Benefit**: Recent info appropriately prioritized, preference changes tracked

**Implementation**: Weeks 11-12 (Phase 6)

---

### 6. Adaptive Memory ⭐

**Problem**: All messages retained equally regardless of importance

**Solution**:

- **Importance scoring** - Based on facts, emotions, engagement
- **Adaptive retention** - Important messages kept longer
- **Memory consolidation** - Merge old messages into episode summaries
- **Smart pruning** - Low-value content removed faster

**Benefit**: Automatic memory management, focus on important information

**Implementation**: Weeks 11-12 (Phase 6)

---

## Implementation Timeline

```
Phase 1 (Weeks 1-2): Database schema updates
    ├─ FTS5 virtual table
    ├─ Episodes schema
    ├─ Fact relationships/versions
    └─ Importance tracking

Phase 2 (Weeks 3-4): Hybrid Search
    ├─ Multi-signal search engine
    ├─ Keyword search (FTS5)
    ├─ Temporal boosting
    └─ Result ranking

Phase 3 (Weeks 5-6): Multi-Level Context
    ├─ Context manager
    ├─ Layered retrieval
    ├─ Token budgeting
    └─ Integration with chat handler

Phase 4 (Weeks 7-8): Episodic Memory
    ├─ Episode store
    ├─ Boundary detection
    ├─ Summarization
    └─ Retrieval system

Phase 5 (Weeks 9-10): Fact Graphs
    ├─ Graph construction
    ├─ Relationship inference
    ├─ Multi-hop queries
    └─ Clustering

Phase 6 (Weeks 11-12): Temporal & Adaptive
    ├─ Fact versioning
    ├─ Importance scoring
    ├─ Adaptive retention
    └─ Consolidation

Phase 7 (Weeks 13-14): Optimization
    ├─ Caching layer
    ├─ Query optimization
    ├─ Load testing
    └─ Production readiness
```

---

## Technical Highlights

### New Components

**Files to create**:

- `app/services/context/multi_level_context.py` - Layered context manager
- `app/services/context/hybrid_search.py` - Multi-signal search
- `app/services/context/episodic_memory.py` - Episode storage and retrieval
- `app/services/context/fact_graph.py` - Knowledge graph
- `app/services/context/temporal_facts.py` - Temporal versioning
- `app/services/context/adaptive_memory.py` - Memory management

**Database changes**:

- FTS5 virtual table for full-text search
- `episodes` table for event memory
- `fact_relationships` and `fact_versions` tables
- `message_importance` table
- New indexes for performance

**Configuration** (`app/config.py`):

```python
enable_multi_level_context: bool = True
enable_hybrid_search: bool = True
enable_episodic_memory: bool = True
enable_fact_graphs: bool = True
enable_fact_versioning: bool = True
enable_adaptive_retention: bool = True
temporal_half_life_days: int = 7
```

---

## Performance Impact

| Component | Latency | Memory | Notes |
|-----------|---------|--------|-------|
| Multi-level context | 200-300ms | +10MB | Includes all levels |
| Hybrid search | 100-200ms | +5MB | Parallel semantic + keyword |
| Episodic retrieval | 50-100ms | +2MB | Infrequent, high value |
| Fact graph query | 150-250ms | +15MB | Cached results |
| **Total overhead** | **400-600ms** | **+30MB** | One-time per query |

**Optimizations**:

- Query result caching (Redis) - 60%+ hit rate
- Embedding reuse - avoid re-computing
- Lazy loading - fetch only needed levels
- Strategic indexes - faster SQLite queries

---

## Success Criteria

**Context Quality**:

- ✅ Relevant context retrieved >80% of time
- ✅ Context coherence score >0.7
- ✅ User satisfaction >75%

**Performance**:

- ✅ Context assembly <500ms p95
- ✅ Search latency <200ms p95
- ✅ Database size growth <20%

**Memory Quality**:

- ✅ Fact deduplication >70%
- ✅ Episode detection >85% accurate
- ✅ Long-term recall >90% for important events

---

## Quick Start (After Implementation)

### Enable New Features

```bash
# Enable all improvements
export ENABLE_MULTI_LEVEL_CONTEXT=true
export ENABLE_HYBRID_SEARCH=true
export ENABLE_EPISODIC_MEMORY=true
export ENABLE_FACT_GRAPHS=true
```

### Test Hybrid Search

```python
from app.services.context import HybridSearchEngine

search = HybridSearchEngine(...)
results = await search.search(
    query="that restaurant in downtown",
    chat_id=123,
    limit=5
)
# Returns top 5 results with semantic + keyword + temporal scoring
```

### Query Fact Graph

```python
from app.services.context import FactGraphManager

graph_mgr = FactGraphManager(...)
graph = await graph_mgr.build_fact_graph(user_id=456, chat_id=123)
paths = await graph_mgr.query_graph(graph, "What about user's work?")
# Returns multi-hop paths through knowledge graph
```

### Retrieve Episodes

```python
from app.services.context import EpisodicMemoryStore

episodes = EpisodicMemoryStore(...)
relevant = await episodes.retrieve_relevant_episodes(
    chat_id=123,
    user_id=456,
    query="trip planning",
    limit=5
)
# Returns memorable conversation episodes about trips
```

---

## Rollout Strategy

### Stage 1: Internal Testing (Week 15)

- Admin-only chat
- Monitor metrics closely
- Fix bugs, tune parameters
- Performance validation

### Stage 2: Limited Beta (Weeks 16-17)

- 2-3 active chats
- Conservative settings
- Daily monitoring
- User feedback

### Stage 3: Gradual Rollout (Weeks 18-20)

- 25% of chats
- Production settings
- Automated monitoring
- Issue tracking

### Stage 4: General Availability (Week 21+)

- All chats
- Optimized configuration
- Continuous improvement

---

## Key Decisions

### Why Hybrid Search?

Semantic search alone misses exact keyword matches. Users often reference specific terms ("that **pizza** place" requires keyword match, not just semantic similarity).

### Why Episodic Memory?

Long conversation histories lose narrative structure. Episodes preserve memorable events with context, enabling natural long-term recall.

### Why Fact Graphs?

Related facts should be connected (city=Kyiv → country=Ukraine → language=Ukrainian). Graphs enable multi-hop reasoning and richer understanding.

### Why Temporal Awareness?

User preferences change. "Was vegetarian" → "Now pescatarian" requires temporal versioning. Recent info should be prioritized.

### Why Adaptive Memory?

All messages aren't equally important. Smart retention focuses storage on valuable information, prunes noise.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Slow queries** | Indexes, caching, optimization |
| **Memory bloat** | Adaptive retention, consolidation |
| **Complexity** | Phased rollout, comprehensive tests |
| **API costs** | Embedding caching, batch processing |

---

## Next Steps

1. **Review this plan** with team/stakeholders
2. **Prioritize phases** based on impact vs effort
3. **Allocate resources** for 14-week implementation
4. **Begin Phase 1** (database schema changes)

---

## Resources

- **Full Plan**: [MEMORY_AND_CONTEXT_IMPROVEMENTS.md](./MEMORY_AND_CONTEXT_IMPROVEMENTS.md)
- **Current Architecture**: `app/services/context_store.py`, `app/services/user_profile.py`
- **Phase Documentation**: `docs/phases/`
- **Related**: [INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md](./INTELLIGENT_CONTINUOUS_LEARNING_PLAN.md)

---

**Estimated Effort**: 14 weeks (3.5 months)  
**Expected Impact**: 2-3x improvement in context relevance and conversation quality  
**Status**: Ready for implementation

