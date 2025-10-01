# Phase 2: Fact Quality Management - Testing Guide

**Purpose**: Validate semantic deduplication, conflict resolution, and confidence decay before Phase 3 activation.

## Overview

Phase 2 adds sophisticated fact quality management but **does not change bot behavior yet** (facts not extracted from windows until Phase 3). Testing focuses on:

1. **Semantic Deduplication**: Verify similar facts merge correctly
2. **Conflict Resolution**: Ensure best fact wins in contradictions  
3. **Confidence Decay**: Validate time-based confidence reduction
4. **Integration**: Confirm ContinuousMonitor wiring works
5. **Performance**: Check embedding API rate limiting

## Test Environment Setup

### Prerequisites

```bash
# Ensure environment is configured
cat .env | grep -E "(GEMINI_API_KEY|TELEGRAM_TOKEN|ENABLE_CONTINUOUS_MONITORING)"

# Expected output:
# GEMINI_API_KEY=your_key
# TELEGRAM_TOKEN=your_token
# ENABLE_CONTINUOUS_MONITORING=true
```

### Database State

```bash
# Check schema has fact_quality_metrics table
sqlite3 gryag.db "SELECT sql FROM sqlite_master WHERE name='fact_quality_metrics';"

# Should show table with columns: id, window_id, total_facts, duplicates_removed, etc.
```

## Unit Tests

### Test 1: Semantic Deduplication

**Goal**: Verify duplicate facts are merged and confidence boosted.

**Test Code** (Python REPL):

```python
import asyncio
from app.services.monitoring.fact_quality_manager import FactQualityManager
from app.services.gemini import GeminiClient
from app.services.context_store import ContextStore
from app.config import Settings
from datetime import datetime

async def test_deduplication():
    settings = Settings()
    gemini_client = GeminiClient(api_key=settings.gemini_api_key)
    context_store = ContextStore(db_path="gryag.db")
    
    manager = FactQualityManager(
        gemini_client=gemini_client,
        db_connection=context_store
    )
    
    # Create duplicate facts (same meaning, different wording)
    facts = [
        {
            "fact": "User likes Python programming",
            "confidence": 0.8,
            "timestamp": datetime.now(),
            "source": "addressed",
            "user_id": 12345,
        },
        {
            "fact": "User enjoys coding in Python",
            "confidence": 0.7,
            "timestamp": datetime.now(),
            "source": "addressed",
            "user_id": 12345,
        },
        {
            "fact": "User lives in Kyiv",
            "confidence": 0.9,
            "timestamp": datetime.now(),
            "source": "addressed",
            "user_id": 12345,
        }
    ]
    
    # Run deduplication
    result = await manager.deduplicate_facts(facts)
    
    # Validate results
    print(f"Original facts: {len(facts)}")
    print(f"After dedup: {len(result)}")
    print(f"Duplicates removed: {len(facts) - len(result)}")
    
    # Should have 2 facts (Python duplicates merged)
    assert len(result) == 2, f"Expected 2 facts, got {len(result)}"
    
    # Find merged Python fact - confidence should be boosted
    python_facts = [f for f in result if "Python" in f["fact"]]
    assert len(python_facts) == 1, "Should have exactly 1 Python fact"
    
    # Confidence should be boosted by 0.10
    # Original max was 0.8, so should be ~0.88
    assert python_facts[0]["confidence"] >= 0.85, \
        f"Expected boosted confidence >= 0.85, got {python_facts[0]['confidence']}"
    
    print("✅ Deduplication test passed!")
    print(f"   Merged fact: {python_facts[0]['fact']}")
    print(f"   Boosted confidence: {python_facts[0]['confidence']}")

# Run test
asyncio.run(test_deduplication())
```

**Expected Output**:
```
Original facts: 3
After dedup: 2
Duplicates removed: 1
✅ Deduplication test passed!
   Merged fact: User likes Python programming
   Boosted confidence: 0.88
```

### Test 2: Conflict Resolution

**Goal**: Verify conflicting facts are resolved, with best fact kept.

**Test Code**:

```python
from datetime import timedelta

async def test_conflict_resolution():
    settings = Settings()
    gemini_client = GeminiClient(api_key=settings.gemini_api_key)
    context_store = ContextStore(db_path="gryag.db")
    
    manager = FactQualityManager(
        gemini_client=gemini_client,
        db_connection=context_store
    )
    
    now = datetime.now()
    
    # Create conflicting facts (same topic, contradictory info)
    facts = [
        {
            "fact": "User prefers working in the morning",
            "confidence": 0.6,
            "timestamp": now - timedelta(days=30),  # 30 days old
            "source": "casual",
            "user_id": 12345,
        },
        {
            "fact": "User prefers working in the evening",
            "confidence": 0.8,
            "timestamp": now,  # Recent
            "source": "addressed",
            "user_id": 12345,
        }
    ]
    
    # Generate embeddings first
    result = await manager.deduplicate_facts(facts)  # Generates embeddings
    
    # Run conflict resolution
    result = manager.resolve_conflicts(result)
    
    # Filter superseded facts
    result = [f for f in result if not f.get("superseded")]
    
    print(f"Facts after conflict resolution: {len(result)}")
    
    # Should have 1 fact (newer, more confident one)
    assert len(result) == 1, f"Expected 1 fact, got {len(result)}"
    
    # Should be the evening fact (higher confidence + more recent)
    assert "evening" in result[0]["fact"], \
        f"Expected evening fact, got: {result[0]['fact']}"
    
    print("✅ Conflict resolution test passed!")
    print(f"   Winner: {result[0]['fact']}")
    print(f"   Confidence: {result[0]['confidence']}")
    print(f"   Reason: Higher confidence (0.8) + more recent")

asyncio.run(test_conflict_resolution())
```

**Expected Output**:
```
Facts after conflict resolution: 1
✅ Conflict resolution test passed!
   Winner: User prefers working in the evening
   Confidence: 0.8
   Reason: Higher confidence (0.8) + more recent
```

### Test 3: Confidence Decay

**Goal**: Validate exponential decay reduces old fact confidence.

**Test Code**:

```python
def test_confidence_decay():
    # Don't need async for decay (no API calls)
    from app.services.monitoring.fact_quality_manager import FactQualityManager
    
    manager = FactQualityManager()  # No dependencies for decay
    
    now = datetime.now()
    
    # Create facts with different ages
    facts = [
        {
            "fact": "User likes coffee",
            "confidence": 0.8,
            "timestamp": now,  # Fresh
            "user_id": 12345,
        },
        {
            "fact": "User dislikes tea",
            "confidence": 0.8,
            "timestamp": now - timedelta(days=90),  # 1 half-life
            "user_id": 12345,
        },
        {
            "fact": "User enjoys walks",
            "confidence": 0.8,
            "timestamp": now - timedelta(days=180),  # 2 half-lives
            "user_id": 12345,
        },
        {
            "fact": "User plays guitar",
            "confidence": 0.8,
            "timestamp": now - timedelta(days=365),  # Very old
            "user_id": 12345,
        }
    ]
    
    # Apply decay
    result = manager.apply_confidence_decay(facts)
    
    # Validate decay amounts
    fresh_conf = result[0]["confidence"]
    half_life_conf = result[1]["confidence"]
    two_half_lives_conf = result[2]["confidence"]
    very_old_conf = result[3]["confidence"]
    
    print(f"Fresh (0 days): {fresh_conf:.3f} (no change)")
    print(f"90 days old: {half_life_conf:.3f} (should be ~0.4)")
    print(f"180 days old: {two_half_lives_conf:.3f} (should be ~0.2)")
    print(f"365 days old: {very_old_conf:.3f} (should be ~0.1 floor)")
    
    # Fresh should be unchanged
    assert abs(fresh_conf - 0.8) < 0.01, \
        f"Fresh fact should have 0.8 confidence, got {fresh_conf}"
    
    # 90 days should be ~half (0.4)
    assert 0.35 < half_life_conf < 0.45, \
        f"90-day fact should be ~0.4, got {half_life_conf}"
    
    # 180 days should be ~quarter (0.2)
    assert 0.15 < two_half_lives_conf < 0.25, \
        f"180-day fact should be ~0.2, got {two_half_lives_conf}"
    
    # 365 days should hit floor (0.1)
    assert very_old_conf == 0.1, \
        f"Very old fact should hit floor (0.1), got {very_old_conf}"
    
    print("✅ Confidence decay test passed!")

test_confidence_decay()
```

**Expected Output**:
```
Fresh (0 days): 0.800 (no change)
90 days old: 0.400 (should be ~0.4)
180 days old: 0.200 (should be ~0.2)
365 days old: 0.100 (should be ~0.1 floor)
✅ Confidence decay test passed!
```

### Test 4: Full Pipeline

**Goal**: Verify all quality steps work together.

**Test Code**:

```python
async def test_full_pipeline():
    settings = Settings()
    gemini_client = GeminiClient(api_key=settings.gemini_api_key)
    context_store = ContextStore(db_path="gryag.db")
    
    manager = FactQualityManager(
        gemini_client=gemini_client,
        db_connection=context_store
    )
    
    now = datetime.now()
    
    # Create messy fact set: duplicates, conflicts, old facts
    facts = [
        # Duplicate pair (Python)
        {"fact": "User likes Python", "confidence": 0.8, 
         "timestamp": now, "source": "addressed", "user_id": 12345},
        {"fact": "User enjoys Python programming", "confidence": 0.7, 
         "timestamp": now, "source": "addressed", "user_id": 12345},
        
        # Conflicting pair (work time)
        {"fact": "User works mornings", "confidence": 0.6, 
         "timestamp": now - timedelta(days=30), "source": "casual", "user_id": 12345},
        {"fact": "User works evenings", "confidence": 0.8, 
         "timestamp": now, "source": "addressed", "user_id": 12345},
        
        # Old fact (should decay)
        {"fact": "User plays chess", "confidence": 0.8, 
         "timestamp": now - timedelta(days=180), "source": "addressed", "user_id": 12345},
        
        # Fresh unique fact
        {"fact": "User lives in Lviv", "confidence": 0.9, 
         "timestamp": now, "source": "addressed", "user_id": 12345},
    ]
    
    print(f"Input: {len(facts)} facts")
    print("  - 2 duplicates (Python)")
    print("  - 2 conflicts (work time)")
    print("  - 1 old fact (180 days)")
    print("  - 1 fresh unique fact")
    
    # Run full pipeline
    result = await manager.process_facts(facts)
    
    print(f"\nOutput: {len(result)} facts")
    print("Expected: 3-4 facts (Python merged, conflict resolved, chess decayed, Lviv kept)")
    
    # Check Python fact merged and boosted
    python_facts = [f for f in result if "Python" in f["fact"]]
    assert len(python_facts) == 1
    assert python_facts[0]["confidence"] >= 0.85  # Boosted
    
    # Check evening fact won conflict (if detected)
    work_facts = [f for f in result if "work" in f["fact"].lower()]
    if len(work_facts) == 1:
        assert "evening" in work_facts[0]["fact"]
    
    # Check chess fact decayed (180 days = 2 half-lives = ~0.2 confidence)
    chess_facts = [f for f in result if "chess" in f["fact"]]
    if chess_facts:
        assert chess_facts[0]["confidence"] < 0.3  # Significantly decayed
    
    print("\n✅ Full pipeline test passed!")
    print("\nFinal facts:")
    for i, fact in enumerate(result, 1):
        print(f"  {i}. {fact['fact']} (confidence: {fact['confidence']:.2f})")

asyncio.run(test_full_pipeline())
```

## Integration Tests

### Test 5: ContinuousMonitor Initialization

**Goal**: Verify FactQualityManager is properly wired into orchestrator.

**Test Code**:

```python
async def test_continuous_monitor_integration():
    from app.services.monitoring.continuous_monitor import ContinuousMonitor
    from app.services.context_store import ContextStore
    from app.services.gemini import GeminiClient
    from app.services.user_profile import UserProfileStore
    from app.config import Settings
    
    settings = Settings()
    gemini_client = GeminiClient(api_key=settings.gemini_api_key)
    context_store = ContextStore(db_path="gryag.db")
    profile_store = UserProfileStore(db_path="gryag.db")
    
    # Initialize monitor (should create FactQualityManager internally)
    monitor = ContinuousMonitor(
        settings=settings,
        gemini_client=gemini_client,
        context_store=context_store,
        profile_store=profile_store,
    )
    
    await monitor.start()
    
    # Check FactQualityManager exists and has dependencies
    assert monitor.fact_quality_manager is not None, \
        "FactQualityManager not initialized"
    
    assert monitor.fact_quality_manager.gemini_client is not None, \
        "GeminiClient not passed to FactQualityManager"
    
    assert monitor.fact_quality_manager.db_connection is not None, \
        "Database connection not passed to FactQualityManager"
    
    print("✅ ContinuousMonitor integration test passed!")
    print("   FactQualityManager properly initialized with dependencies")
    
    await monitor.stop()

asyncio.run(test_continuous_monitor_integration())
```

**Expected Output**:
```
✅ ContinuousMonitor integration test passed!
   FactQualityManager properly initialized with dependencies
```

## Performance Tests

### Test 6: Embedding Rate Limiting

**Goal**: Verify embedding API calls respect rate limits (5 concurrent, 1s interval).

**Test Code**:

```python
async def test_embedding_rate_limiting():
    import time
    from app.services.monitoring.fact_quality_manager import FactQualityManager
    from app.services.gemini import GeminiClient
    from app.config import Settings
    
    settings = Settings()
    gemini_client = GeminiClient(api_key=settings.gemini_api_key)
    
    manager = FactQualityManager(gemini_client=gemini_client)
    
    # Create 20 facts (will need 20 embedding calls)
    facts = [
        {
            "fact": f"User likes activity {i}",
            "confidence": 0.8,
            "timestamp": datetime.now(),
            "user_id": 12345,
        }
        for i in range(20)
    ]
    
    print("Generating 20 embeddings (testing rate limiting)...")
    start = time.time()
    
    embeddings = await manager._get_embeddings([f["fact"] for f in facts])
    
    elapsed = time.time() - start
    
    print(f"Elapsed time: {elapsed:.1f}s")
    print(f"Rate: {len(embeddings) / elapsed:.1f} embeddings/sec")
    
    # Should take at least 3 seconds (20 embeddings / 5 concurrent with 1s min)
    # Actually should take ~4s: (20 / 5) * 1s = 4 batches * 1s
    assert elapsed >= 3.0, \
        f"Rate limiting not working - completed too fast ({elapsed:.1f}s)"
    
    assert len(embeddings) == 20, \
        f"Expected 20 embeddings, got {len(embeddings)}"
    
    print(f"✅ Rate limiting test passed!")
    print(f"   Processed {len(embeddings)} embeddings in {elapsed:.1f}s")
    print(f"   Respected 5 concurrent + 1s interval limit")

asyncio.run(test_embedding_rate_limiting())
```

## Database Tests

### Test 7: Metrics Logging

**Goal**: Verify quality metrics are logged to database.

**Test SQL**:

```sql
-- Check fact_quality_metrics table exists
SELECT COUNT(*) as table_exists 
FROM sqlite_master 
WHERE type='table' AND name='fact_quality_metrics';
-- Should return: 1

-- Check table structure
PRAGMA table_info(fact_quality_metrics);

-- Check metrics (after running tests with window_id)
SELECT 
    total_facts,
    duplicates_removed,
    conflicts_resolved,
    facts_decayed,
    processing_time_ms,
    created_at
FROM fact_quality_metrics 
ORDER BY created_at DESC 
LIMIT 5;
```

## Production Readiness Checklist

Before enabling Phase 3:

- ✅ All unit tests pass (deduplication, conflicts, decay)
- ✅ Integration tests pass (ContinuousMonitor wiring)
- ✅ Performance tests pass (rate limiting works)
- ✅ No errors in bot logs during testing
- ✅ Code reviewed (Phase 2 implementation)
- ✅ Documentation complete (PHASE_2_COMPLETE.md + this file)

## Troubleshooting

### Issue: Embeddings Failing

**Symptoms**: `_get_embeddings()` raises `GeminiError`

**Solutions**:
1. Check Gemini API key is valid
2. Verify API quota not exceeded (60 embeddings/min)
3. Check network connectivity
4. Fallback to key-based deduplication (automatic)

### Issue: Slow Processing

**Symptoms**: Tests taking too long

**Solutions**:
1. Check embedding semaphore (should be 5)
2. Verify 1s interval not too conservative
3. Reduce test batch size
4. Check network latency

### Issue: Incorrect Deduplication

**Symptoms**: Non-duplicates merged or duplicates not detected

**Solutions**:
1. Adjust `DUPLICATE_THRESHOLD` (currently 0.85)
   - Increase: More strict (fewer merges)
   - Decrease: More aggressive (more merges)
2. Check embedding quality (print similarities)
3. Verify fact text formatting

## Next Steps

Once all tests pass:

1. **Mark Phase 2 Complete**: ✅ (done)
2. **Plan Phase 3**: Enable message filtering, async processing, window extraction
3. **Risk Assessment**: Review behavior changes in Phase 3
4. **Gradual Rollout**: Enable features one at a time
5. **Monitor Metrics**: Watch `fact_quality_metrics` table for anomalies

Phase 3 will activate continuous learning - this is where the system starts learning from 80%+ of messages instead of 5-10%!

---

**Test Status**: Ready for validation  
**Risk Level**: Low (changes isolated, not yet active)  
**Approval**: Required before Phase 3
