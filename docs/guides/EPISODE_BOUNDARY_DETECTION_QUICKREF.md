# Episode Boundary Detection - Quick Reference

**Phase 4.1**: Automatic episode boundary detection  
**Status**: ✅ Complete

## TL;DR

The bot now automatically detects when conversations shift topics using:

1. **Time gaps** between messages
2. **Topic change markers** ("by the way", "давайте поговорим про...")
3. **Semantic similarity** (embedding comparison)

Combined score ≥ 0.6 → Episode boundary detected.

## How It Works

### Three Detection Methods

#### 1. Temporal (35% weight)

| Gap Duration | Strength | Example |
|--------------|----------|---------|
| < 2 min | No signal | Normal chat flow |
| 2-15 min | 0.4 (weak) | Coffee break |
| 15-60 min | 0.7 (moderate) | Lunch break |
| > 1 hour | 1.0 (strong) | Different time of day |

#### 2. Topic Markers (25% weight)

**Detects explicit topic changes**:

- Ukrainian: "Давайте поговорим про", "Змінімо тему", "Кстаті", "А зараз"
- English: "Let's talk about", "By the way", "Changing subject", "What about"

Strength: 0.8 (high confidence)

#### 3. Semantic (40% weight)

**Compares message embeddings**:

- Similarity > 0.7: No signal (same topic)
- Similarity 0.5-0.7: No signal (related topic)
- Similarity < 0.5: Signal strength = 1.0 - similarity

## Configuration

### Environment Variables

```bash
# Temporal thresholds (seconds)
EPISODE_SHORT_GAP_SECONDS=120       # 2 minutes
EPISODE_MEDIUM_GAP_SECONDS=900      # 15 minutes
EPISODE_LONG_GAP_SECONDS=3600       # 1 hour

# Semantic thresholds
EPISODE_LOW_SIMILARITY_THRESHOLD=0.3
EPISODE_MEDIUM_SIMILARITY_THRESHOLD=0.5
EPISODE_HIGH_SIMILARITY_THRESHOLD=0.7

# Combined score threshold
EPISODE_BOUNDARY_THRESHOLD=0.6      # 60%
```

### Tuning Guide

**Want more episodes?** Lower `EPISODE_BOUNDARY_THRESHOLD` to 0.4-0.5

**Want fewer episodes?** Raise `EPISODE_BOUNDARY_THRESHOLD` to 0.7-0.8

**Adjust temporal sensitivity**: Change gap thresholds

**Adjust semantic sensitivity**: Change similarity thresholds

## Examples

### Example 1: No Boundary (Coherent Chat)

```
User A [10:00]: "I love pizza" 
User B [10:01]: "Me too, pepperoni is the best"
User A [10:02]: "Yeah totally agree"
```

**Signals**: None (short gaps, same topic, no markers)  
**Score**: ~0.1  
**Decision**: ❌ No boundary

### Example 2: Strong Boundary (Clear Topic Shift)

```
User A [10:00]: "Python is great for data science"
User B [10:01]: "Yeah pandas is so useful"
--- 1 hour gap ---
User A [11:05]: "By the way, how's the weather?"
User B [11:06]: "It's raining"
```

**Signals**:
- Temporal: 1.0 (long gap)
- Topic Marker: 0.8 ("by the way")
- Semantic: ~0.85 (low similarity: programming → weather)

**Score**: (1.0×0.35) + (0.8×0.25) + (0.85×0.4) = 0.89 → ×1.3 (3 signal types) = **1.0**  
**Decision**: ✅ Create boundary

### Example 3: Medium Boundary

```
User A [10:00]: "I went to the store"
--- 10 minute gap ---
User B [10:10]: "What about work tomorrow?"
```

**Signals**:
- Temporal: 0.7 (medium gap)
- Semantic: ~0.6 (moderate shift)

**Score**: (0.7×0.35) + (0.6×0.4) = 0.485 → ×1.2 (2 signal types) = **0.58**  
**Decision**: ❌ No boundary (below 0.6 threshold)

## API Usage

```python
from app.services.context.episode_boundary_detector import (
    EpisodeBoundaryDetector,
    MessageSequence,
)

# Initialize
detector = EpisodeBoundaryDetector(db_path, settings, gemini_client)
await detector.init()

# Create sequence
sequence = MessageSequence(
    messages=messages,
    chat_id=chat_id,
    thread_id=thread_id,
    start_timestamp=messages[0]["timestamp"],
    end_timestamp=messages[-1]["timestamp"],
)

# Detect boundaries
signals = await detector.detect_boundaries(sequence)

# Check if boundary should be created
should_create, score, contributing = await detector.should_create_boundary(
    sequence, signals
)

if should_create:
    print(f"Boundary detected! Score: {score:.2f}")
    print(f"Contributing signals: {len(contributing)}")
```

## Signal Details

### BoundarySignal Object

```python
@dataclass
class BoundarySignal:
    message_id: int          # Where boundary occurs
    timestamp: int           # When boundary occurs
    signal_type: str         # "temporal", "topic_marker", or "semantic"
    strength: float          # 0.0 to 1.0
    reason: str              # Human-readable explanation
    metadata: dict | None    # Additional data
```

### MessageSequence Object

```python
@dataclass
class MessageSequence:
    messages: list[dict]     # Messages to analyze
    chat_id: int            # Chat identifier
    thread_id: int | None   # Thread identifier (optional)
    start_timestamp: int    # First message time
    end_timestamp: int      # Last message time
```

## Performance

| Scenario | Time |
|----------|------|
| 10 messages, all cached embeddings | <50ms |
| 10 messages, 50% cached | 200-400ms |
| 10 messages, no cache | 800-1200ms |
| 50 messages, all cached | <200ms |
| 50 messages, 50% cached | 1-2s |
| 50 messages, no cache | 4-6s |

**Optimization**: Embeddings are cached in the database, so repeated analysis is fast.

## Testing

Run tests:

```bash
python -m pytest tests/unit/test_episode_boundary_detector.py -v
```

Expected: **24/24 tests passing**

## Monitoring

### Debug Logging

Enable debug logging to see boundary decisions:

```bash
export LOGLEVEL=DEBUG
```

Look for:

```
DEBUG: Boundary detection: score=0.85, threshold=0.6, decision=True
```

### Key Metrics to Track

- Boundaries detected per day
- Average boundary score
- Signal type distribution (temporal vs marker vs semantic)
- False positives (boundaries created incorrectly)
- False negatives (missed boundaries)

## Common Issues

### Issue: Too Many Boundaries

**Symptom**: Episodes created for every few messages

**Solutions**:
1. Raise `EPISODE_BOUNDARY_THRESHOLD` to 0.7-0.8
2. Raise `EPISODE_SHORT_GAP_SECONDS` to 300 (5 min)
3. Raise `EPISODE_MEDIUM_SIMILARITY_THRESHOLD` to 0.6

### Issue: Too Few Boundaries

**Symptom**: Clear topic shifts not detected

**Solutions**:
1. Lower `EPISODE_BOUNDARY_THRESHOLD` to 0.4-0.5
2. Lower `EPISODE_MEDIUM_GAP_SECONDS` to 600 (10 min)
3. Add more topic marker patterns in code

### Issue: Slow Performance

**Symptom**: Detection takes >5 seconds

**Solutions**:
1. Ensure embeddings are being cached (check `message.embedding` field)
2. Reduce sequence length (analyze fewer messages at once)
3. Skip semantic detection for some scenarios (use only temporal + markers)

## Next Steps

**Phase 4.2**: Automatic episode creation using detected boundaries

**Phase 4.3**: Episode refinement (importance scoring, emotional valence, tags)

---

**Quick Links**:
- [Full Documentation](PHASE_4_1_COMPLETE.md)
- [Test Suite](../../tests/unit/test_episode_boundary_detector.py)
- [Source Code](../../app/services/context/episode_boundary_detector.py)
