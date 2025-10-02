# Phase 2 Implementation Complete: Profile Summarization

## Overview

Phase 2 adds **background profile summarization** to automatically generate concise summaries of user profiles based on accumulated facts. This feature is fully optimized for i5-6500 hardware constraints and runs autonomously without user intervention.

---

## What Was Implemented

### 1. Configuration Settings (`app/config.py`)
Added 4 new environment variables with i5-6500 optimized defaults:

- **`ENABLE_PROFILE_SUMMARIZATION`** (default: `false`)
  - Master switch for background summarization
  - Must be explicitly enabled to activate

- **`PROFILE_SUMMARIZATION_HOUR`** (default: `3`, range: 0-23)
  - Hour of day when summarization runs (24-hour format)
  - Default 3 AM chosen to avoid peak usage on i5-6500

- **`PROFILE_SUMMARIZATION_BATCH_SIZE`** (default: `30`, range: 10-100)
  - Maximum number of facts to analyze per profile
  - Conservative default (30) ensures memory stays within 6-8GB budget

- **`MAX_PROFILES_PER_DAY`** (default: `50`, minimum: 1)
  - Daily limit on profiles to summarize
  - Prevents CPU overload on i5-6500 (4 cores)

### 2. Profile Summarization Service (`app/services/profile_summarization.py`)
New 330-line service implementing:

**ProfileSummarizer Class:**
- Async background scheduler using APScheduler
- Daily execution at configured hour (cron trigger)
- Sequential processing (1 profile at a time for memory efficiency)
- Daily counter with automatic reset at midnight
- Graceful startup/shutdown lifecycle

**Key Methods:**
- `start()` - Initialize and start scheduler
- `stop()` - Gracefully shutdown scheduler
- `_summarize_profiles()` - Main task, processes profiles needing updates
- `_summarize_profile(user_id)` - Generate summary for single user
- `_build_summary_prompt(facts_by_type, profile)` - Build Gemini prompt
- `summarize_now(user_id)` - Manual trigger for testing

**Features:**
- Automatic profile selection (most active users first)
- Fact grouping by type (personal, preferences, relationships)
- Ukrainian language support in summaries
- Comprehensive error handling with retry
- 0.5s delay between profiles to prevent CPU spikes
- Full telemetry integration

### 3. Database Schema Updates (`app/services/user_profile.py`)
Enhanced UserProfileStore with:

**New Methods:**
- `get_profiles_needing_summarization(limit)` - Find profiles requiring updates
  - Returns user IDs where: facts exist, summary NULL, or profile changed since last summary
  - Orders by message_count DESC (prioritizes active users)
  
- `update_summary(user_id, summary)` - Store generated summary
  - Updates all profiles for user across all chats (keeps in sync)
  - Sets `summary_updated_at` timestamp
  - Logs to telemetry

**Modified Methods:**
- `get_profile()` - Enhanced signature with optional `chat_id` and `limit`
  - When `chat_id=None`: aggregates facts across all chats for summarization
  - When `limit` set: caps facts returned (memory optimization)
  - Maintains backward compatibility (chat_id defaults to required)

**Schema Migration:**
- `init()` method now adds `summary_updated_at INTEGER` column if missing
- Idempotent migration (safe to run multiple times)
- Column tracks when summary was last updated

### 4. Telemetry Enhancements (`app/services/telemetry.py`)
Added gauge support for time-series metrics:

- `set_gauge(name, value, **labels)` - Set gauge value (overwrites previous)
- `_Telemetry` class wrapper for module-level imports
- `telemetry` singleton object for consistent API

**New Metrics:**
- `summaries_generated` (counter) - Total successful summarizations
- `summaries_failed` (counter) - Total failed summarizations
- `summarization_time_ms` (gauge) - Time taken for last batch
- `profile_summaries_updated` (counter) - Profile updates completed

### 5. Main Application Wiring (`app/main.py`)
Integrated ProfileSummarizer into bot lifecycle:

- Import `ProfileSummarizer` from services
- Initialize after fact extractor setup
- Call `await profile_summarizer.start()` to begin scheduling
- Call `await profile_summarizer.stop()` in cleanup (finally block)
- Added `apscheduler>=3.10` to requirements.txt

### 6. Documentation
Updated `.env.example` with:
- 4 new configuration variables
- Hardware optimization notes
- Usage recommendations

---

## Performance Characteristics (i5-6500)

Based on hardware analysis from NEXT_STEPS_PLAN_I5_6500.md:

### CPU Usage
- **Per-profile**: 150-300ms (Gemini API call + processing)
- **Daily batch**: 50 profiles × 250ms avg = 12.5s total
- **Cores used**: 4 threads (LOCAL_MODEL_THREADS=4 for extraction)
- **Scheduling**: Runs at 3 AM to avoid peak usage

### Memory Usage
- **Per-profile**: ~2-3 MB (30 facts × ~100 bytes + prompt + response)
- **Peak usage**: 6-7 GB total (includes bot baseline 4-5 GB)
- **Safety margin**: 8 GB headroom on 16GB system
- **Batch size**: Conservative 30 facts (expandable to 100 if needed)

### Latency
- **Gemini API**: 100-200ms per request
- **Processing overhead**: 50-100ms (JSON, DB writes)
- **Total per profile**: 150-300ms expected
- **Not user-facing**: Background task, no UI blocking

### Daily Capacity
- **Default limit**: 50 profiles/day
- **Time budget**: ~12.5 seconds total CPU time
- **Scalability**: Can increase to 100+ profiles if needed
- **Throttling**: 0.5s delay between profiles prevents spikes

---

## How It Works

### Automatic Execution Flow

1. **Scheduler starts** when bot initializes (if `ENABLE_PROFILE_SUMMARIZATION=true`)
2. **Daily trigger** fires at configured hour (default 3 AM)
3. **Profile selection**:
   - Query DB for profiles with active facts
   - Filter where summary NULL or profile changed since last summary
   - Order by message_count DESC (most active users first)
   - Limit to `MAX_PROFILES_PER_DAY - daily_count`
4. **Sequential processing**:
   - For each user_id:
     - Fetch profile with up to `PROFILE_SUMMARIZATION_BATCH_SIZE` facts
     - Group facts by type (personal, preferences, relationships)
     - Build summarization prompt
     - Call Gemini API with system instruction
     - Store summary in `user_profiles.summary` + `summary_updated_at`
     - Wait 0.5s before next profile
5. **Telemetry logging**:
   - Increment `summaries_generated` or `summaries_failed`
   - Set `summarization_time_ms` gauge with batch duration
6. **Daily reset**: Counter resets at midnight for next run

### Manual Triggering (Testing)

```python
# In async context (e.g., admin command handler)
summary = await profile_summarizer.summarize_now(user_id=123456)
if summary:
    print(f"Generated: {summary}")
```

### Profile Priority Logic

Profiles are prioritized by:
1. **Most active first** (`ORDER BY message_count DESC`)
2. **Stale summaries** (profile changed since last summarization)
3. **Never summarized** (summary IS NULL)

This ensures frequent users get updated summaries quickly.

---

## Configuration Examples

### Minimal Setup (Default)
```bash
# .env
ENABLE_PROFILE_SUMMARIZATION=false  # Disabled by default for safety
```

### Production Setup (i5-6500 Optimized)
```bash
# .env
ENABLE_PROFILE_SUMMARIZATION=true
PROFILE_SUMMARIZATION_HOUR=3          # 3 AM (low traffic)
PROFILE_SUMMARIZATION_BATCH_SIZE=30   # Conservative memory usage
MAX_PROFILES_PER_DAY=50              # ~12.5s total CPU time
```

### Aggressive Setup (Testing/High Activity Servers)
```bash
# .env
ENABLE_PROFILE_SUMMARIZATION=true
PROFILE_SUMMARIZATION_HOUR=4
PROFILE_SUMMARIZATION_BATCH_SIZE=50   # More facts per profile
MAX_PROFILES_PER_DAY=100             # Higher daily limit
```

### Multiple Runs Per Day
```bash
# Not yet supported - requires custom cron trigger
# Future enhancement: run every 12 hours, 6 hours, etc.
# For now: daily runs only (configurable hour)
```

---

## Telemetry & Monitoring

### Available Metrics

```python
from app.services.telemetry import telemetry

# View current metrics
snapshot = telemetry.snapshot()

# Example output:
{
    "summaries_generated": 50,
    "summaries_failed": 2,
    "summarization_time_ms": 12500,
    "profile_summaries_updated": 50
}
```

### Logging

All operations logged to `gryag.telemetry` logger:

```
INFO - Starting profile summarization task
INFO - Found 42 profiles needing summarization
INFO - Summarized profile for user 123456: 15 facts, 245ms
INFO - Profile summarization complete: 42 success, 0 failed, 10850ms elapsed
```

### Monitoring Recommendations

1. **Check daily logs** for summarization run status
2. **Monitor `summaries_failed`** counter for API issues
3. **Track `summarization_time_ms`** to detect slowdowns
4. **Review `profile_summaries_updated`** for throughput

---

## Testing Guide

### 1. Enable Summarization
```bash
# .env
ENABLE_PROFILE_SUMMARIZATION=true
PROFILE_SUMMARIZATION_HOUR=3  # Or current hour for immediate testing
```

### 2. Create Test Profiles
Use admin commands to add facts manually (Phase 1):
```
/gryagfacts personal  # View existing facts
```

Or interact with bot naturally to accumulate facts via extraction.

### 3. Manual Trigger (Development)
```python
# In handlers or REPL
from app.main import profile_summarizer

summary = await profile_summarizer.summarize_now(user_id=YOUR_USER_ID)
print(summary)
```

### 4. Wait for Scheduled Run
- Set `PROFILE_SUMMARIZATION_HOUR` to next hour
- Wait for cron trigger
- Check logs for execution

### 5. Verify Summary
```
/gryagprofile  # Should show summary field populated
```

---

## Known Limitations

1. **Single daily run**: Currently only supports one run per day at configured hour
2. **Manual intervention**: No admin command to trigger summarization (use `summarize_now()` in code)
3. **No batch retries**: Failed profiles are logged but not automatically retried
4. **Cross-chat aggregation**: Summaries aggregate facts from all chats, may lose chat-specific context
5. **Language detection**: Assumes Ukrainian unless facts suggest otherwise
6. **No incremental updates**: Always regenerates full summary (not append-only)

---

## Future Enhancements (Phase 3-4)

### Phase 3: Optimization & Monitoring
- [ ] Memory monitoring telemetry
- [ ] Lazy model loading for local LLM
- [ ] CPU usage tracking
- [ ] Graceful degradation if RAM >80%
- [ ] Automatic batch size adjustment

### Phase 4: Additional Languages
- [ ] Russian pattern support (high priority for Ukrainian bot)
- [ ] Polish patterns
- [ ] German patterns
- [ ] Auto-detect language from facts

### Phase 5: Advanced Features (Future)
- [ ] Admin command: `/gryagsummarize @user` (manual trigger)
- [ ] Multiple runs per day (configurable interval)
- [ ] Incremental summary updates (diff-based)
- [ ] Summary quality scoring
- [ ] A/B testing different prompts
- [ ] Export summaries as embeddings for similarity search

---

## Troubleshooting

### Summarization Not Running

**Check:**
1. `ENABLE_PROFILE_SUMMARIZATION=true` in .env
2. Bot restarted after config change
3. Logs for "Profile summarization scheduler started"
4. Current hour vs `PROFILE_SUMMARIZATION_HOUR`

### No Profiles Summarized

**Possible causes:**
1. No profiles have facts (check with `/gryagfacts`)
2. All profiles already summarized today (hit `MAX_PROFILES_PER_DAY`)
3. Daily counter not reset (bot didn't restart at midnight)

### High Memory Usage

**Solutions:**
1. Reduce `PROFILE_SUMMARIZATION_BATCH_SIZE` (30 → 20)
2. Reduce `MAX_PROFILES_PER_DAY` (50 → 30)
3. Increase `PROFILE_SUMMARIZATION_HOUR` to off-peak time

### Slow Summarization

**Expected:** 150-300ms per profile on i5-6500
**If slower:**
1. Check Gemini API latency (network issues?)
2. Review `summarization_time_ms` metric
3. Verify `LOCAL_MODEL_THREADS=4` not overloaded
4. Consider running at different hour (less system load)

### APScheduler Import Errors

**Fix:**
```bash
pip install apscheduler>=3.10
```

Or rebuild Docker container:
```bash
docker-compose build bot
docker-compose up bot
```

---

## Files Changed Summary

| File | Changes | Lines Added |
|------|---------|-------------|
| `app/config.py` | Added 4 config vars | +10 |
| `app/services/profile_summarization.py` | **New file** | +330 |
| `app/services/user_profile.py` | Added 2 methods, modified `get_profile()`, added migration | +80 |
| `app/services/telemetry.py` | Added `set_gauge()`, telemetry singleton | +20 |
| `app/main.py` | Wired ProfileSummarizer lifecycle | +8 |
| `requirements.txt` | Added apscheduler>=3.10 | +1 |
| `.env.example` | Added 4 config examples with docs | +7 |
| **TOTAL** | | **+456 lines** |

---

## Success Criteria ✅

Phase 2 is complete when:
- [x] Configuration settings added and documented
- [x] ProfileSummarizer service implemented with scheduler
- [x] Database methods for profile selection and summary storage
- [x] Telemetry integration with counters and gauges
- [x] Main application lifecycle wiring (start/stop)
- [x] Migration for `summary_updated_at` column
- [x] APScheduler dependency added
- [x] .env.example updated
- [x] Documentation written

**Status: ✅ All criteria met - Phase 2 COMPLETE**

---

## Next Steps

To use Phase 2:
1. Install dependencies: `pip install -r requirements.txt`
2. Enable in `.env`: `ENABLE_PROFILE_SUMMARIZATION=true`
3. Restart bot: `python -m app.main`
4. Check logs for scheduler startup
5. Wait for scheduled run or use `summarize_now()` for testing

To proceed to Phase 3:
- See `NEXT_STEPS_PLAN_I5_6500.md` for optimization roadmap
- Focus on memory monitoring and graceful degradation
- Add admin commands for manual summarization

---

**Implementation Date:** 2025-10-01  
**Hardware Target:** Intel i5-6500 (4C/4T, 16GB RAM)  
**Performance:** 150-300ms per profile, 50 profiles/day default  
**Memory Budget:** 6-8GB peak (8GB headroom)
