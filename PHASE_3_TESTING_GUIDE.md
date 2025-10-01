# Phase 3: Continuous Learning - Testing & Activation Guide

**Purpose**: Test Phase 3 implementation before enabling filtering and async processing, then guide gradual activation.

## Overview

Phase 3 enables continuous learning from conversation windows. The implementation is complete but **disabled by default** for safety. This guide covers:

1. **Testing**: Validate window fact extraction works correctly
2. **Activation Step 1**: Enable message filtering (40-60% reduction)
3. **Activation Step 2**: Enable async processing (non-blocking)
4. **Monitoring**: Track system health and performance

## Current State

**What's Working**:
- ✅ Windows tracked and closed (Phase 1)
- ✅ Facts extracted from windows (Phase 3)
- ✅ Quality processing applied (Phase 2)
- ✅ Facts stored in database (Phase 3)

**What's Disabled**:
- ❌ Message filtering (all messages processed)
- ❌ Async processing (synchronous, blocking)

**Current Behavior**:
```
Message → Classify → Window → [Close]
  → Extract Facts (1-3s) 
  → Quality Processing (0.5-1s)
  → Store Facts (0.1-0.3s)
  → TOTAL: 1.5-4s (BLOCKING message handler)
```

## Testing Phase

### Prerequisites

```bash
# Verify environment
cat .env | grep -E "ENABLE_CONTINUOUS_MONITORING|ENABLE_MESSAGE_FILTERING|ENABLE_ASYNC_PROCESSING"

# Expected:
ENABLE_CONTINUOUS_MONITORING=true  ✅
ENABLE_MESSAGE_FILTERING=false     ❌ (testing phase)
ENABLE_ASYNC_PROCESSING=false      ❌ (testing phase)
```

### Test 1: Basic Window Processing

**Goal**: Verify windows are created and facts extracted

**Steps**:
1. Start bot: `python -m app.main`
2. Look for initialization log:
   ```
   INFO - ContinuousMonitor initialized
   INFO - Continuous monitoring initialized (async processing disabled)
   ```
3. In a test chat, send 8-10 messages over 2 minutes
4. Wait 3 minutes for window to close (timeout)
5. Check logs for:
   ```
   INFO - Conversation window closed: Timeout 180s exceeded
   INFO - Extracted N facts from window
   INFO - Quality processing: N → M facts
   INFO - Stored M facts for user 12345
   ```

**Success Criteria**:
- ✅ Window closes after timeout
- ✅ Facts extracted (N > 0 for meaningful conversation)
- ✅ Quality processing reduces facts (N → M, typically 20-50% reduction)
- ✅ Facts stored without errors
- ✅ No bot crashes

### Test 2: Quality Processing Integration

**Goal**: Verify Phase 2 deduplication works with Phase 3

**Steps**:
1. In test chat, have conversation about user's hobby (e.g., "I like Python")
2. Wait for window to close
3. Check logs for: `Extracted N facts from window`
4. In same chat, repeat similar information: "I enjoy coding in Python"
5. Wait for second window to close
6. Check logs for: `Quality processing: N → M facts` (M should be < N due to dedup)
7. Query database:
   ```sql
   SELECT * FROM fact_quality_metrics 
   WHERE duplicates_removed > 0 
   ORDER BY created_at DESC LIMIT 5;
   ```

**Success Criteria**:
- ✅ Second window has fewer stored facts (duplicates removed)
- ✅ `fact_quality_metrics` table shows `duplicates_removed > 0`
- ✅ User profile doesn't have duplicate facts

### Test 3: Multi-User Windows

**Goal**: Verify facts extracted for all participants

**Steps**:
1. In group chat with 2-3 users, have conversation
2. Each user mentions something (e.g., User A: "I live in Kyiv", User B: "I prefer tea")
3. Wait for window to close
4. Check logs for:
   ```
   INFO - Extracted N facts from window for user 111
   INFO - Extracted M facts from window for user 222
   ```
5. Query database:
   ```sql
   SELECT user_id, COUNT(*) as fact_count 
   FROM user_facts 
   WHERE json_extract(evidence_text, '$.extracted_from_window') = 1
   GROUP BY user_id;
   ```

**Success Criteria**:
- ✅ Facts extracted for each participant
- ✅ Bot's own messages skipped
- ✅ Facts tagged with `extracted_from_window = true`

### Test 4: Performance Check

**Goal**: Measure processing time and resource usage

**Steps**:
1. Monitor CPU/memory before test:
   ```bash
   # If psutil installed
   python -c "from app.services.resource_monitor import get_resource_monitor; get_resource_monitor().log_resource_summary()"
   ```
2. Create window with 8 messages
3. Note timestamp when window closes
4. Note timestamp when "Stored N facts" appears in logs
5. Calculate: `processing_time = stored_time - closed_time`
6. Check resource usage after

**Success Criteria**:
- ✅ Processing time: 1-4 seconds (acceptable for synchronous)
- ✅ Memory increase: <100MB per window
- ✅ CPU spike: <50% (brief, then returns to idle)
- ✅ No memory leaks (memory returns after processing)

### Test 5: Error Handling

**Goal**: Verify graceful error handling

**Steps**:
1. Create window with only emoji/stickers (no extractable text)
2. Check logs for: `No text content in window, skipping fact extraction`
3. Verify no errors, bot continues normally
4. Create window where Gemini API might fail (invalid tokens, etc.)
5. Verify error logged but bot doesn't crash

**Success Criteria**:
- ✅ Empty windows handled gracefully
- ✅ Extraction failures logged, not crash
- ✅ One user's failure doesn't block others
- ✅ Bot remains responsive

## Database Validation

### Check Facts Extracted from Windows

```sql
-- Count window-extracted facts
SELECT COUNT(*) as window_facts
FROM user_facts
WHERE json_extract(evidence_text, '$.extracted_from_window') = 1;

-- Compare with total facts
SELECT 
    SUM(CASE WHEN json_extract(evidence_text, '$.extracted_from_window') = 1 THEN 1 ELSE 0 END) as window_facts,
    COUNT(*) as total_facts,
    ROUND(100.0 * SUM(CASE WHEN json_extract(evidence_text, '$.extracted_from_window') = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as window_percentage
FROM user_facts
WHERE is_active = 1;
```

### Check Quality Metrics

```sql
-- Recent quality processing
SELECT 
    window_id,
    total_facts,
    duplicates_removed,
    conflicts_resolved,
    facts_decayed,
    processing_time_ms,
    created_at
FROM fact_quality_metrics
ORDER BY created_at DESC
LIMIT 10;

-- Deduplication effectiveness
SELECT 
    AVG(duplicates_removed * 100.0 / NULLIF(total_facts, 0)) as avg_dedup_rate,
    AVG(processing_time_ms) as avg_processing_ms,
    COUNT(*) as windows_processed
FROM fact_quality_metrics
WHERE total_facts > 0;
```

### Check for Duplicate Facts

```sql
-- Should be very rare (<1%)
SELECT 
    fact_type,
    fact_key,
    COUNT(*) as duplicate_count
FROM user_facts
WHERE is_active = 1
GROUP BY user_id, chat_id, fact_type, fact_key
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20;
```

## Activation Step 1: Enable Message Filtering

**When**: After successful testing (all tests pass)

**What**: Filter LOW/NOISE messages (stickers, reactions, greetings)

**Expected Impact**: 40-60% reduction in processed messages

### Enable Filtering

```bash
# Edit .env
ENABLE_MESSAGE_FILTERING=true

# Restart bot
python -m app.main
```

### Monitor Filtering

**Check logs for**:
```
INFO - ContinuousMonitor initialized
  extra={'enable_filtering': True, ...}

DEBUG - Message classified as NOISE
DEBUG - Message filtered out, skipping processing
```

**Get filtering stats**:
```python
# In bot logs, look for classifier stats
# Or query via admin interface (if implemented)
```

### Validate Filtering

1. Send sticker → Should be filtered (check logs: "Message filtered out")
2. Send short greeting "hi" → Should be filtered
3. Send meaningful message → Should be processed
4. Check windows still close and process correctly
5. Verify fact extraction still works

**Success Criteria**:
- ✅ LOW/NOISE messages filtered
- ✅ Meaningful messages still processed
- ✅ Windows still close and extract facts
- ✅ 40-60% reduction in "messages_monitored" stat

## Activation Step 2: Enable Async Processing

**When**: After filtering validated (Step 1 successful)

**What**: Start 3 background workers for non-blocking processing

**Expected Impact**: Message handler returns immediately, processing happens in background

### Enable Async

```bash
# Edit .env
ENABLE_ASYNC_PROCESSING=true

# Restart bot
python -m app.main
```

### Monitor Async Workers

**Check logs for**:
```
INFO - Event queue started with 3 workers
INFO - Continuous monitoring async processing started

# When window closes:
INFO - Conversation window closed: ...
# (Handler returns immediately)

# Later, in background:
INFO - Processing event: conversation_window_closed
INFO - Extracted N facts from window
```

### Validate Async Processing

1. Send 8 messages to create window
2. Window closes → Check handler returns quickly (<100ms)
3. Background processing happens (check logs for "Processing event")
4. Facts still extracted and stored
5. Check queue stats:
   ```python
   # In logs, look for queue health:
   # - queue_size < max_queue_size
   # - workers_active > 0
   # - circuit_breaker_state = "CLOSED"
   ```

**Success Criteria**:
- ✅ Message handler non-blocking (<100ms)
- ✅ Background workers processing events
- ✅ Facts still extracted and stored
- ✅ No queue backlog (queue_size stays low)
- ✅ Circuit breaker healthy ("CLOSED" state)

### Circuit Breaker Testing

**Trigger circuit breaker** (optional stress test):
1. Send many messages rapidly (50+ messages)
2. Create many windows quickly
3. Monitor logs for circuit breaker state changes
4. Verify:
   - "OPEN" → stops accepting new work
   - "HALF_OPEN" → testing recovery
   - "CLOSED" → back to normal

## Performance Monitoring

### Resource Usage (with psutil)

```python
from app.services.resource_monitor import get_resource_monitor

monitor = get_resource_monitor()
if monitor.is_available():
    monitor.log_resource_summary()
    # Check:
    # - Memory: Should stay <75% of available
    # - CPU: Brief spikes, then return to <20%
    # - Disk: Minimal (SQLite writes)
```

### Bot Statistics

```python
# Via continuous_monitor.get_stats()
# Look for:
stats = {
    'messages_monitored': N,
    'windows_processed': M,
    'facts_extracted': P,
    'classifier_stats': {
        'high_value': X,
        'medium_value': Y,
        'low_value': Z,
        'noise': W,
    },
    'analyzer_stats': {
        'active_windows': A,
        'closed_windows': B,
    },
    'queue_stats': {  # Only if async enabled
        'queue_size': Q,
        'processed_events': R,
        'failed_events': S,
        'circuit_breaker_state': 'CLOSED',
    },
    'system_healthy': True,
}
```

### Expected Ratios

**After filtering enabled**:
- `messages_monitored` : `windows_processed` ≈ 8:1 (8 messages per window)
- `windows_processed` : `facts_extracted` ≈ 1:10-50 (10-50 facts per window)
- `high_value` + `medium_value` ≈ 40-60% (rest filtered)

**After async enabled**:
- `queue_size` should stay < 10 (unless burst traffic)
- `failed_events` should be 0 (or very low)
- `circuit_breaker_state` = "CLOSED" (healthy)

## Troubleshooting

### Issue: High Processing Time (>5s per window)

**Symptoms**: Logs show "Extracted N facts" 5+ seconds after "Window closed"

**Causes**:
- Gemini API slow (network latency)
- Too many participants (N users = N extraction calls)
- Large windows (>8 messages)

**Solutions**:
1. Check network: `ping generativelanguage.googleapis.com`
2. Reduce window size: `CONVERSATION_WINDOW_SIZE=6`
3. Increase timeout: `CONVERSATION_WINDOW_TIMEOUT=240` (4 minutes)
4. Enable async (offload to background): `ENABLE_ASYNC_PROCESSING=true`

### Issue: Memory Growth

**Symptoms**: Bot memory usage increases over time

**Causes**:
- Windows not being closed (leak)
- Facts accumulating in memory
- Circuit breaker holding failed events

**Solutions**:
1. Check active windows: `analyzer_stats['active_windows']` (should be low)
2. Force close on stop: Already implemented in `stop()`
3. Restart bot periodically (temporary)
4. Check for leaks: Use `tracemalloc` module

### Issue: Queue Backlog

**Symptoms**: `queue_size` increasing, not decreasing

**Causes**:
- Processing slower than window creation
- Circuit breaker OPEN (not processing)
- Workers stuck

**Solutions**:
1. Check circuit breaker: Should be "CLOSED"
2. Increase workers: `MONITORING_WORKERS=5`
3. Enable filtering: Reduce incoming load
4. Check logs for worker errors

### Issue: No Facts Extracted

**Symptoms**: Logs show "No facts extracted from window"

**Causes**:
- Window has no text (only stickers/photos)
- Gemini API failing
- Fact extractor error

**Solutions**:
1. Check window content: Log `messages_text` in extraction
2. Check Gemini API: `gemini_client.is_healthy()`
3. Check fact extractor type: Should be "hybrid" with Gemini fallback
4. Lower confidence threshold: `min_confidence=0.5` (testing only)

## Rollback Procedures

### Disable Async Processing

```bash
# Edit .env
ENABLE_ASYNC_PROCESSING=false

# Restart bot
python -m app.main

# Result: Back to synchronous processing (blocking)
```

### Disable Filtering

```bash
# Edit .env
ENABLE_MESSAGE_FILTERING=false

# Restart bot
python -m app.main

# Result: All messages processed (Phase 1 behavior)
```

### Disable Continuous Monitoring Entirely

```bash
# Edit .env
ENABLE_CONTINUOUS_MONITORING=false

# Restart bot
python -m app.main

# Result: Only addressed messages processed (pre-Phase 3)
```

## Success Checklist

Before declaring Phase 3 production-ready:

**Testing**:
- ✅ All 5 tests pass
- ✅ Database validation clean
- ✅ No crashes or errors
- ✅ Performance acceptable

**Activation Step 1** (Filtering):
- ✅ Filtering works correctly
- ✅ 40-60% reduction in load
- ✅ Meaningful messages still processed
- ✅ Facts still extracted

**Activation Step 2** (Async):
- ✅ Non-blocking processing
- ✅ Background workers healthy
- ✅ No queue backlog
- ✅ Circuit breaker stable

**Production Validation**:
- ✅ 24 hours uptime without issues
- ✅ Memory/CPU stable
- ✅ Learning coverage increased (check fact count growth)
- ✅ User experience unchanged (no noticeable delays)

## Next Steps

**After Phase 3 Activation**:
1. **Monitor for 1 week**: Track stats, resource usage, errors
2. **Analyze impact**: Check fact growth rate, quality metrics
3. **Tune parameters**: Adjust thresholds, window size, timeouts
4. **Plan Phase 4**: Proactive responses (intent classification, triggers)

**Phase 4 Preview**:
- Intent classification: Detect when bot should respond
- User preference learning: Track reaction to proactive messages
- Response triggers: Conservative cooldowns (5+ minutes)
- Goal: Bot joins conversations naturally, not intrusively

---

**Testing Status**: Ready to begin  
**Activation Status**: Staged (Step 1 → Step 2)  
**Rollback**: Simple (config flags)  
**Risk**: Low → Medium (gradual increase with each step)
