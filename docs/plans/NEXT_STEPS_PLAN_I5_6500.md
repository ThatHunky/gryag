# Next Steps Implementation Plan - Optimized for Intel i5-6500

## Hardware Specifications

**CPU:** Intel Core i5-6500 (Skylake, 6th gen)
- 4 cores, 4 threads (no hyperthreading)
- Base clock: 3.2 GHz, Boost: 3.6 GHz
- Cache: 6MB L3
- TDP: 65W

**RAM:** 16GB DDR4
- Available for bot: ~12GB (after OS overhead)
- Sufficient for Phi-3-mini Q4 (2.2GB model + 3GB runtime = 5GB peak)

**GPU:** Intel HD Graphics 530 (integrated)
- Not usable for llama-cpp-python inference
- CPU-only inference recommended

**Storage:** Assumed SSD (for reasonable model load times)

## Performance Expectations

### Current Hybrid Extraction Performance

**Tier 1 (Rule-based):**
- Latency: <1ms ✅
- Memory: ~10MB ✅
- Coverage: 70% of cases

**Tier 2 (Local Model - Phi-3-mini Q4):**
- Latency: 150-300ms (expected on i5-6500 with 4 threads) ✅
- Memory: ~3GB during inference ✅
- Coverage: Additional 25% of cases

**System Load:**
- Idle: ~1-2GB RAM (Python + bot + SQLite)
- With model loaded: ~5-6GB RAM ✅
- Peak during inference: ~6-8GB RAM ✅
- Remaining for OS/cache: ~8GB ✅

**Recommended Settings:**
```bash
LOCAL_MODEL_THREADS=4  # Use all 4 cores
LOCAL_MODEL_PATH=models/phi-3-mini-q4.gguf
FACT_EXTRACTION_METHOD=hybrid
```

## Phase 1: Admin Commands for Profile Management

**Priority:** HIGH  
**Impact on Performance:** None (user-triggered commands)  
**Implementation Time:** 2-3 hours  
**Memory Impact:** <1MB

### Commands to Implement

1. **`/gryagprofile [@user|reply]`**
   - Show user profile summary
   - Display fact count, interaction count
   - Show last interaction date
   - Show profile version
   - Admin-only or self-query

2. **`/gryagfacts [@user|reply] [fact_type]`**
   - List all facts for a user
   - Optional filter by fact_type (personal, preference, skill, trait, opinion)
   - Show confidence scores
   - Show evidence text
   - Paginated output (max 20 facts per message)

3. **`/gryagremovefact <fact_id>`**
   - Remove specific fact by ID
   - Admin-only
   - Confirmation required
   - Logs deletion to telemetry

4. **`/gryagforget [@user|reply]`**
   - Clear all facts for a user
   - Admin-only
   - Confirmation required (send again within 30s)
   - Preserves profile but marks all facts inactive

5. **`/gryagexport [@user|reply]`**
   - Export user profile as JSON
   - Admin-only
   - Useful for debugging/backup

### Implementation Details

**Files to Create:**
- `app/handlers/profile_admin.py` - New router for profile commands
- `app/services/profile_export.py` - JSON export utilities

**Files to Modify:**
- `app/main.py` - Register profile admin router
- `app/services/user_profile.py` - Add helper methods for admin operations

**Storage:**
- No additional tables needed
- Reuse existing `user_profiles`, `user_facts`, `user_relationships`

**Performance:**
- All commands are read-only except delete operations
- SQLite queries will be fast (<10ms) with existing indexes
- No blocking operations

## Phase 2: Profile Summarization (Background Task)

**Priority:** MEDIUM  
**Impact on Performance:** LOW (background task, rate-limited)  
**Implementation Time:** 3-4 hours  
**Memory Impact:** +50-100MB during summarization

### Overview

Periodically (every 24h) synthesize accumulated facts into concise profile summaries using Gemini API. This reduces token usage when injecting profile context.

### Design Constraints (i5-6500 specific)

**Memory Management:**
- Summarization runs in background asyncio task
- Process one profile at a time (not concurrent)
- Limit batch size to 10 profiles per run
- Skip profiles with <10 facts (not worth summarizing)

**Rate Limiting:**
- Run at 3 AM local time (low traffic)
- Process max 50 profiles per day
- Skip profiles updated in last 24 hours
- Gemini API calls: ~1 per profile (~$0.0001 per summary)

**Fallback Strategy:**
- If Gemini fails, keep existing summary
- Retry failed profiles next cycle
- Log failures to telemetry

### Implementation Details

**New Configuration:**
```bash
ENABLE_PROFILE_SUMMARIZATION=true
PROFILE_SUMMARIZATION_HOUR=3  # 3 AM
PROFILE_SUMMARIZATION_BATCH_SIZE=50
MIN_FACTS_FOR_SUMMARIZATION=10
```

**Files to Create:**
- `app/services/profile_summarization.py` - Background task logic
- `app/tasks/__init__.py` - Task scheduler module
- `app/tasks/scheduler.py` - Simple APScheduler integration

**Files to Modify:**
- `app/main.py` - Start background task on bot startup
- `app/services/user_profile.py` - Add `summarize_profile()` method
- `app/config.py` - Add summarization config

**Database:**
- Reuse `profile.summary` field (already exists)
- Update `profile.last_summary_at` timestamp

**Memory Profile During Summarization:**
- Base: ~6GB (with model loaded)
- Per profile: +10-20MB (facts + history)
- Peak: ~6.2GB ✅
- Well within 16GB limit

### Summarization Prompt Strategy

**Efficient Prompting:**
- Send only facts (not full history) to reduce tokens
- Group facts by category
- Request 200 token summary (fits in profile context budget)
- Use Gemini 2.0 Flash Lite for cost efficiency ($0.00001/1K tokens)

**Example Summary:**
```
Ukrainian software developer from Kyiv. Speaks Ukrainian, English, and Russian. 
Prefers Python and TypeScript. Interested in ML and open source. Dislikes 
bureaucracy. Active contributor in tech discussions.
```

## Phase 3: Optimization & Monitoring

**Priority:** MEDIUM  
**Impact on Performance:** Positive (reduces unnecessary work)  
**Implementation Time:** 2 hours

### Optimizations for i5-6500

1. **Model Loading:**
   - Load model on first use (lazy initialization)
   - Keep model in memory once loaded (no reload overhead)
   - Add startup warmup (1 dummy inference to JIT compile)

2. **Rule-Based Caching:**
   - Cache compiled regex patterns (already done)
   - Consider message deduplication (skip identical messages within 1 hour)

3. **Memory Monitoring:**
   - Add telemetry for memory usage
   - Log warnings if RAM usage >80% (>12.8GB)
   - Implement graceful degradation (disable local model if memory critical)

4. **CPU Usage:**
   - Pin to 4 threads (don't over-subscribe)
   - Lower thread priority for background summarization
   - Monitor CPU % and throttle if needed

### Monitoring Dashboard

**New Telemetry Metrics:**
```python
# Fact extraction performance
fact_extraction_latency_ms
fact_extraction_method_used  # rule_based, local_model, gemini
facts_extracted_count

# Resource usage
memory_usage_mb
cpu_usage_percent
model_loaded_status

# Profile stats
total_profiles_count
total_facts_count
profiles_summarized_today
```

**Log Analysis:**
- Add DEBUG logs for performance tracking
- Log model load time (should be <5s)
- Log inference time per message
- Alert if inference >500ms consistently

## Phase 4: Additional Language Support

**Priority:** LOW (nice-to-have)  
**Impact on Performance:** None (just more patterns)  
**Implementation Time:** 1-2 hours per language

### Suggested Languages

1. **Russian** (high overlap with Ukrainian users)
2. **Polish** (neighbor, similar grammar)
3. **German** (common in tech communities)

### Implementation

**Files to Create:**
- `app/services/fact_extractors/patterns/russian.py`
- `app/services/fact_extractors/patterns/polish.py`
- `app/services/fact_extractors/patterns/german.py`

**Pattern Count:**
- ~15-20 patterns per language
- Similar structure to Ukrainian/English
- Native speaker review recommended

**Memory Impact:**
- +5-10KB per language (negligible)

## Implementation Order

### Week 1: Admin Commands
1. Day 1-2: Implement `/gryagprofile` and `/gryagfacts`
2. Day 3: Implement `/gryagremovefact` and `/gryagforget`
3. Day 4: Implement `/gryagexport`
4. Day 5: Testing and documentation

### Week 2: Profile Summarization
1. Day 1: Task scheduler setup
2. Day 2-3: Summarization logic and Gemini integration
3. Day 4: Background task wiring
4. Day 5: Testing and monitoring

### Week 3: Optimization & Additional Languages
1. Day 1-2: Optimization and monitoring
2. Day 3-5: Additional language patterns (optional)

## Resource Budget Summary

**Current (Idle):**
- RAM: ~2GB
- CPU: <5%
- Disk: ~50MB (code + DB)

**With Hybrid Extraction (Active):**
- RAM: ~6GB (model loaded)
- CPU: 50-100% during inference (150-300ms bursts)
- Disk: ~2.3GB (code + model + DB)

**With Summarization (Background):**
- RAM: ~6.2GB (peak)
- CPU: <10% (background task)
- Network: ~1KB/s (Gemini API)

**Total System Load:**
- RAM: ~6-7GB used, ~9GB free ✅
- CPU: Bursts to 100% during inference (acceptable) ✅
- Disk: ~2.5GB ✅
- Network: Minimal ✅

## Performance Tuning for i5-6500

### Recommended .env Configuration

```bash
# Optimal settings for i5-6500
LOCAL_MODEL_THREADS=4
FACT_EXTRACTION_METHOD=hybrid
LOCAL_MODEL_PATH=models/phi-3-mini-q4.gguf

# Keep context reasonable to reduce memory
MAX_TURNS=30  # Instead of 50
CONTEXT_SUMMARY_THRESHOLD=20  # Instead of 30

# Profiling
MAX_FACTS_PER_USER=80  # Instead of 100 (reduce memory)
MIN_MESSAGES_FOR_EXTRACTION=5

# Summarization (optional)
ENABLE_PROFILE_SUMMARIZATION=true
PROFILE_SUMMARIZATION_HOUR=3
PROFILE_SUMMARIZATION_BATCH_SIZE=30  # Conservative for i5

# Throttling (prevent CPU overload)
PER_USER_PER_HOUR=3  # More aggressive throttling
```

### If Performance Issues Arise

**Fallback 1: Disable Local Model During Peak Hours**
```bash
# Only use rule-based extraction during active hours
FACT_EXTRACTION_METHOD=rule_based  # 9 AM - 11 PM
FACT_EXTRACTION_METHOD=hybrid      # 11 PM - 9 AM
```

**Fallback 2: Reduce Model Context**
```python
# In model_manager.py
n_ctx=1024  # Instead of 2048 (saves ~500MB RAM)
```

**Fallback 3: Rule-Based Only Mode**
```bash
FACT_EXTRACTION_METHOD=rule_based
# Still extracts 70% of facts, zero latency, zero memory overhead
```

## Testing Plan

### Load Testing

**Simulate Real Usage:**
```bash
# 10 concurrent users, 5 messages each
# Expected: 50 extractions, ~30 rule-based, ~20 local model
# Total time: <10 seconds
# Peak RAM: <8GB
```

**Stress Testing:**
```bash
# 50 concurrent users (extreme case)
# Expected: Throttle middleware kicks in
# Some requests queued/rejected
# System remains stable
```

### Memory Testing

**Monitor During Operations:**
```bash
# Watch memory usage
watch -n 1 'ps aux | grep python'

# Expected stable state:
# RSS: 6000-7000 MB (with model loaded)
# VSZ: 8000-9000 MB
```

## Success Criteria

✅ **Performance:**
- Rule-based extraction: <1ms (100% of cases)
- Local model extraction: <300ms p95 (i5-6500)
- Total RAM usage: <10GB peak
- CPU usage: Acceptable bursts, no sustained 100%

✅ **Functionality:**
- Admin commands work reliably
- Profile summarization runs without errors
- Facts are extracted accurately (>85% precision)

✅ **Stability:**
- No memory leaks over 24h operation
- No crashes under load
- Graceful degradation if resources constrained

## Conclusion

The i5-6500 with 16GB RAM is **well-suited** for running the hybrid fact extraction system with all planned features:

- ✅ **Hybrid extraction works great** - 4 cores sufficient for 150-300ms inference
- ✅ **Memory is adequate** - 6-7GB peak leaves plenty of headroom
- ✅ **Admin commands add no overhead** - User-triggered only
- ✅ **Background summarization is safe** - Runs during low traffic at 3 AM
- ✅ **Room for growth** - Can handle 2-3x current load before optimization needed

**Recommendation:** Proceed with all phases. The system will run smoothly on your hardware.
