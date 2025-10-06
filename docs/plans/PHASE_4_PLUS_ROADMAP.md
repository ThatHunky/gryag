# Phase 4+ Roadmap: Completing Memory & Context Improvements

**Date**: October 6, 2025  
**Current Status**: Phase 3 Complete ✅  
**Overall Progress**: 43% (3/7 phases)

## Current State

### ✅ Completed (Phases 1-3)

**Phase 1: Database Foundation**
- FTS5 full-text search index
- Message importance tracking
- Episode storage tables
- Fact relationship schema
- Fact versioning infrastructure

**Phase 2: Hybrid Search Engine**
- 4-signal scoring (semantic + keyword + temporal + importance)
- Parallel query execution
- Result caching and optimization
- Configurable weights

**Phase 3: Multi-Level Context Manager**
- 5-layer context assembly
- Parallel retrieval (<500ms)
- Token budget management
- Gemini API formatting
- **Fully integrated into chat handler** ✅

### 🔄 Partial (Phase 4)

**Phase 4: Episodic Memory** - 75% Complete
- ✅ Database schema (episodes, episode_accesses)
- ✅ EpisodicMemoryStore service
- ✅ Episode storage and retrieval
- ✅ Semantic search over episodes
- ❌ Automatic episode creation during conversations
- ❌ Boundary detection for topic shifts
- ❌ Real-time importance scoring

## Phase 4: Complete Episodic Memory

**Goal**: Automatically create and manage episodes during conversations

**Remaining Work**: 25%

### 4.1 Episode Boundary Detection

**What**: Detect when conversation topics shift

**Implementation**:
```python
# app/services/context/episode_boundary_detector.py

class EpisodeBoundaryDetector:
    """Detect conversation topic boundaries."""
    
    async def detect_boundary(
        self,
        recent_messages: list[dict],
        new_message: dict,
        threshold: float = 0.6,
    ) -> bool:
        """
        Detect if new message starts a new topic.
        
        Uses:
        1. Semantic similarity to recent context
        2. Time gap between messages
        3. User shift (different speaker)
        4. Explicit markers ("changing topic", "new question")
        """
        # Semantic shift detection
        recent_embedding = await self._get_average_embedding(recent_messages)
        new_embedding = new_message.get("embedding")
        
        similarity = cosine_similarity(recent_embedding, new_embedding)
        
        # Time gap detection
        time_gap = new_message["ts"] - recent_messages[-1]["ts"]
        
        # Boundary if:
        # - Low semantic similarity (<0.6)
        # - Long time gap (>300s)
        # - Explicit topic markers
        return (
            similarity < threshold
            or time_gap > 300
            or self._has_topic_markers(new_message)
        )
```

**Testing**:
```python
# test_episode_boundaries.py
# Test cases:
# 1. Topic shift detection
# 2. Time gap handling
# 3. Explicit markers
# 4. Continuity preservation
```

**Estimated Time**: 2-3 days

### 4.2 Automatic Episode Creation

**What**: Create episodes from conversation windows automatically

**Implementation**:
```python
# In app/handlers/chat.py or background task

async def create_episode_if_needed(
    context_store: ContextStore,
    episode_store: EpisodicMemoryStore,
    chat_id: int,
    thread_id: int | None,
) -> None:
    """
    Check if recent conversation should be saved as episode.
    
    Criteria:
    - Minimum 5 messages
    - Minimum 60 seconds duration
    - Importance score > 0.6
    - Topic boundary detected
    """
    # Get recent conversation window
    window = await context_store.recent(
        chat_id=chat_id,
        thread_id=thread_id,
        max_turns=20,
    )
    
    if len(window) < 5:
        return  # Too short
    
    # Calculate importance
    importance = await _calculate_window_importance(window)
    
    if importance < 0.6:
        return  # Not important enough
    
    # Detect boundary
    boundary_detected = await boundary_detector.detect_boundary(
        recent_messages=window[:-1],
        new_message=window[-1],
    )
    
    if not boundary_detected:
        return  # Still in same topic
    
    # Create episode
    await episode_store.create_episode(
        chat_id=chat_id,
        thread_id=thread_id,
        messages=window,
        importance=importance,
    )
```

**Integration Point**: Add to `handle_group_message` as background task

**Testing**:
```python
# test_episode_creation.py
# Test cases:
# 1. Episode created on boundary
# 2. Short conversations ignored
# 3. Low importance ignored
# 4. Metadata preserved
```

**Estimated Time**: 2-3 days

### 4.3 Importance Scoring

**What**: Calculate importance of conversations in real-time

**Implementation**:
```python
# app/services/context/importance_scorer.py

class ImportanceScorer:
    """Calculate conversation importance."""
    
    async def score_window(
        self,
        messages: list[dict],
    ) -> float:
        """
        Score conversation window (0.0-1.0).
        
        Factors:
        1. Length (more messages = more important)
        2. User engagement (multiple participants)
        3. Emotional intensity (sentiment analysis)
        4. Question density (questions indicate importance)
        5. Bot engagement (was bot actively involved)
        """
        length_score = min(len(messages) / 20, 1.0)
        
        unique_users = len(set(m["user_id"] for m in messages))
        engagement_score = min(unique_users / 5, 1.0)
        
        bot_messages = sum(1 for m in messages if m["role"] == "model")
        bot_score = min(bot_messages / 5, 1.0)
        
        question_count = sum(
            1 for m in messages if "?" in m.get("text", "")
        )
        question_score = min(question_count / 3, 1.0)
        
        # Weighted average
        importance = (
            length_score * 0.2
            + engagement_score * 0.3
            + bot_score * 0.3
            + question_score * 0.2
        )
        
        return importance
```

**Testing**:
```python
# test_importance_scoring.py
# Test cases:
# 1. Long conversations score high
# 2. Multi-user conversations score high
# 3. Bot-engaged conversations score high
# 4. Short chit-chat scores low
```

**Estimated Time**: 1-2 days

### 4.4 Integration & Testing

**What**: Wire automatic episode creation into production flow

**Steps**:
1. Add background task in chat handler
2. Configure episode creation settings
3. Add monitoring and logging
4. Test with real conversations
5. Tune thresholds based on results

**Estimated Time**: 2 days

**Total Phase 4 Remaining**: 7-10 days

## Phase 5: Fact Graphs (Week 7)

**Goal**: Build interconnected knowledge networks

### 5.1 Entity Extraction

Extract entities from conversations:
- People (names, roles)
- Places (cities, locations)
- Objects (things mentioned)
- Events (what happened)
- Concepts (abstract ideas)

### 5.2 Relationship Inference

Infer relationships between facts:
- "X is Y" (identity)
- "X likes Y" (preference)
- "X works at Y" (association)
- "X happened in Y" (temporal)

### 5.3 Graph-Based Retrieval

Navigate fact graphs for multi-hop queries:
```
Query: "What does Alice's friend like?"
  → Find Alice's friends (1-hop)
  → Find their preferences (2-hop)
  → Return results
```

### 5.4 Semantic Clustering

Group related facts automatically:
- Topic clusters
- Entity clusters
- Time-based clusters

**Estimated Time**: 1 week

## Phase 6: Temporal & Adaptive Memory (Weeks 8-10)

**Goal**: Time-aware memory management

### 6.1 Fact Versioning

Track changes over time:
```python
# Before: "Alice works at Company A"
# After: "Alice works at Company B"
# System tracks: transition, reasons, timing
```

### 6.2 Importance Decay

Fade old, low-value memories:
```python
importance(t) = base_importance * exp(-age_days / half_life)
```

### 6.3 Memory Consolidation

Merge related facts:
```python
# "Alice likes pizza" (confidence: 0.7)
# "Alice ordered pizza" (confidence: 0.6)
# → "Alice likes pizza" (confidence: 0.85)
```

### 6.4 Adaptive Retrieval

Adjust retrieval based on conversation type:
- Private chat: More personal context
- Group chat: More shared context
- Technical discussion: More factual context

**Estimated Time**: 3 weeks

## Phase 7: Optimization (Weeks 13-14)

**Goal**: Performance and quality improvements

### 7.1 Smart Deduplication

Remove duplicates across context levels:
```python
# Same message in immediate AND recent
# → Keep in immediate, remove from recent
```

### 7.2 Streaming Assembly

Yield context incrementally:
```python
# Instead of waiting for all levels
# Stream as each completes
for level in context_manager.stream_context(...):
    yield level
```

### 7.3 Adaptive Budget Allocation

Learn optimal token allocation:
```python
# Track which levels contribute most
# Automatically adjust ratios
# Example: More relevant, less background
```

### 7.4 Relevance Feedback

Learn from Gemini's usage:
```python
# Track which context gets cited in responses
# Improve retrieval weights based on usage
# Boost sources that lead to better responses
```

**Estimated Time**: 2 weeks

## Implementation Timeline

| Week | Phase | Tasks | Status |
|------|-------|-------|--------|
| 1-2 | Phase 1 | Database foundation | ✅ Done |
| 2-3 | Phase 2 | Hybrid search | ✅ Done |
| 3-4 | Phase 3 | Multi-level context | ✅ Done |
| 5-6 | Phase 4 | Complete episodic memory | 🔄 In Progress |
| 7 | Phase 5 | Fact graphs | 📋 Planned |
| 8-10 | Phase 6 | Temporal & adaptive | 📋 Planned |
| 13-14 | Phase 7 | Optimization | 📋 Planned |

**Total Timeline**: 14 weeks  
**Completed**: 4 weeks (29%)  
**Remaining**: 10 weeks (71%)

## Quick Wins (Short Term)

While working on Phase 4, these can be done in parallel:

### 1. Improve Hybrid Search Weights

Test different weight configurations:
```bash
# Experiment 1: More semantic
SEMANTIC_WEIGHT=0.6
KEYWORD_WEIGHT=0.2
TEMPORAL_WEIGHT=0.2

# Experiment 2: More temporal
SEMANTIC_WEIGHT=0.4
KEYWORD_WEIGHT=0.2
TEMPORAL_WEIGHT=0.4
```

**Time**: 1 day testing  
**Impact**: Better relevance scoring

### 2. Add Context Quality Metrics

Track context quality:
```python
# metrics.py
- context_assembly_time
- context_tokens_used
- context_levels_populated
- gemini_response_quality
```

**Time**: 1 day  
**Impact**: Better observability

### 3. Optimize FTS Index

Improve keyword search performance:
```sql
-- Rebuild FTS index with better tokenization
DROP TABLE messages_fts;
CREATE VIRTUAL TABLE messages_fts USING fts5(
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);
```

**Time**: 1 hour  
**Impact**: Faster keyword search

### 4. Add Context Caching

Cache assembled contexts:
```python
# Cache key: (chat_id, thread_id, query_hash)
# Cache TTL: 60 seconds
# Benefit: Skip assembly for repeated queries
```

**Time**: 2 hours  
**Impact**: Faster repeated queries

## Priority Recommendations

### High Priority (Do Next)

1. **Complete Phase 4** - Automatic episode creation
   - Most impactful for long-term memory
   - Enables better context over time
   - Foundation for Phase 5-6

2. **Monitor Production Performance**
   - Track context assembly times
   - Identify bottlenecks
   - Tune configurations

3. **Collect Usage Metrics**
   - Which levels get populated most
   - Which contribute to responses
   - User feedback on quality

### Medium Priority (Next 2 Weeks)

1. **Phase 5: Fact Graphs** - After Phase 4
2. **Context Quality Metrics** - Parallel to Phase 5
3. **Hybrid Search Tuning** - Based on metrics

### Low Priority (Future)

1. **Phase 6: Temporal Awareness** - Weeks 8-10
2. **Phase 7: Optimization** - Weeks 13-14
3. **Advanced Features** - After core complete

## Success Metrics

Track these to measure improvement:

### Context Quality
- Average relevance score
- Context tokens used vs budget
- Levels populated per query
- Duplicate reduction %

### Performance
- Context assembly time (p50, p95, p99)
- Fallback frequency
- Error rate
- Cache hit rate

### User Experience
- Response quality (subjective)
- Conversation continuity
- Long-term memory recall
- User satisfaction

## Risks & Mitigation

### Risk 1: Performance Degradation

**Mitigation**:
- Aggressive monitoring
- Conservative token budgets
- Easy rollback via config
- Gradual rollout

### Risk 2: Memory Bloat

**Mitigation**:
- Episode limits per chat
- Automatic cleanup (Phase 6)
- Database vacuum
- Storage monitoring

### Risk 3: Poor Quality Episodes

**Mitigation**:
- Importance thresholds
- Boundary detection tuning
- Manual review tools
- Easy deletion

## Next Steps (Immediate)

1. **Start Phase 4.1**: Episode boundary detection
2. **Set up monitoring**: Context quality metrics
3. **Test in production**: Monitor multi-level context
4. **Document findings**: What works, what doesn't
5. **Iterate**: Tune based on real usage

---

**Last Updated**: October 6, 2025  
**Next Review**: After Phase 4 completion  
**Overall Progress**: 43% → Target: 100% in 10 weeks
