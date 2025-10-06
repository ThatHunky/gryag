# Phase 4.2 Integration Checklist

**Date**: October 6, 2025  
**Status**: ✅ Implementation Complete, ⏳ Integration Pending

## Pre-Integration Verification

### ✅ Code Complete

- [x] `app/services/context/episode_monitor.py` (450+ lines)
- [x] `tests/unit/test_episode_monitor.py` (600+ lines)
- [x] `app/config.py` updated with 3 new settings
- [x] All 27 tests passing
- [x] 100% test coverage of public methods

### ✅ Documentation Complete

- [x] `docs/phases/PHASE_4_2_COMPLETE.md` - Full implementation guide
- [x] `docs/guides/EPISODE_MONITORING_QUICKREF.md` - Quick reference
- [x] `PHASE_4_2_COMPLETE_SUMMARY.md` - Executive summary
- [x] `docs/CHANGELOG.md` updated

### ✅ Configuration Ready

```bash
# Existing (Phase 4.1)
AUTO_CREATE_EPISODES=true
EPISODE_MIN_MESSAGES=5
EPISODE_BOUNDARY_THRESHOLD=0.70
EPISODE_TEMPORAL_GAP=7200
EPISODE_TOPIC_MARKER_WEIGHT=0.25

# New (Phase 4.2)
EPISODE_WINDOW_TIMEOUT=1800              # 30 minutes
EPISODE_WINDOW_MAX_MESSAGES=50           # 50 messages
EPISODE_MONITOR_INTERVAL=300             # 5 minutes
```

## Integration Steps

### Step 1: Update main.py (Initialize EpisodeMonitor)

**File**: `app/main.py`

**Location**: After `episodic_memory` initialization (around line 150)

**Code to Add**:

```python
# Initialize Episode Monitor (Phase 4.2)
from app.services.context.episode_monitor import EpisodeMonitor

episode_monitor = EpisodeMonitor(
    db_path=settings.database_path,
    settings=settings,
    gemini_client=gemini_client,
    episodic_memory=episodic_memory,
    boundary_detector=boundary_detector,
)

logger.info("Episode monitor initialized")

# Start background monitoring if enabled
if settings.auto_create_episodes:
    await episode_monitor.start()
    logger.info("Episode monitoring started")
```

**Verification**:

```bash
# Check logs for:
# "Episode monitor initialized"
# "Episode monitoring started"
```

### Step 2: Update main.py (Pass to Middleware)

**File**: `app/main.py`

**Location**: In `ChatMetaMiddleware` initialization (around line 180)

**Code to Modify**:

```python
# OLD
ChatMetaMiddleware(
    settings=settings,
    context_store=context_store,
    gemini_client=gemini_client,
    redis_client=redis_client if settings.use_redis else None,
    hybrid_search=hybrid_search,
    episodic_memory=episodic_memory,
)

# NEW - Add episode_monitor parameter
ChatMetaMiddleware(
    settings=settings,
    context_store=context_store,
    gemini_client=gemini_client,
    redis_client=redis_client if settings.use_redis else None,
    hybrid_search=hybrid_search,
    episodic_memory=episodic_memory,
    episode_monitor=episode_monitor,  # NEW
)
```

### Step 3: Update Middleware (Accept & Inject)

**File**: `app/middlewares/chat_meta.py`

**Location**: `__init__` method and `__call__` method

**Code to Add**:

```python
# In __init__
from app.services.context.episode_monitor import EpisodeMonitor

def __init__(
    self,
    settings: Settings,
    context_store: ContextStore,
    gemini_client: GeminiClient,
    hybrid_search: HybridSearchEngine,
    episodic_memory: EpisodicMemoryStore,
    episode_monitor: EpisodeMonitor,  # NEW
    redis_client: Redis | None = None,
):
    # ...existing code...
    self._episode_monitor = episode_monitor  # NEW

# In __call__ (inject into handler data)
data["episode_monitor"] = self._episode_monitor  # NEW
```

### Step 4: Update Chat Handler (Track Messages)

**File**: `app/handlers/chat.py`

**Location**: In `handle_group_message` and `handle_private_message`

**Code to Add** (at start of handler, after extracting message data):

```python
from app.services.context.episode_monitor import EpisodeMonitor

async def handle_group_message(
    message: Message,
    settings: Settings,
    context_store: ContextStore,
    gemini_client: GeminiClient,
    hybrid_search: HybridSearchEngine,
    episodic_memory: EpisodicMemoryStore,
    episode_monitor: EpisodeMonitor,  # NEW parameter
    # ...other parameters...
):
    # Track message for episode creation (if enabled)
    if settings.auto_create_episodes:
        try:
            await episode_monitor.track_message(
                chat_id=message.chat.id,
                thread_id=message.message_thread_id,
                message={
                    "id": message.message_id,
                    "user_id": message.from_user.id,
                    "text": message.text or message.caption or "",
                    "timestamp": int(time.time()),
                    "chat_id": message.chat.id,
                }
            )
        except Exception as e:
            logger.error(f"Failed to track message for episodes: {e}")
            # Continue processing - don't fail the handler
    
    # ...rest of handler...
```

**Apply same changes to `handle_private_message`**

### Step 5: Update Shutdown Handler (Stop Monitor)

**File**: `app/main.py`

**Location**: In shutdown handler or cleanup function

**Code to Add**:

```python
async def shutdown():
    """Cleanup on bot shutdown."""
    logger.info("Shutting down...")
    
    # Stop episode monitoring
    if episode_monitor:
        await episode_monitor.stop()
        logger.info("Episode monitoring stopped")
    
    # ...other cleanup...
```

## Testing Plan

### Unit Tests (Already Complete ✅)

```bash
python -m pytest tests/unit/test_episode_monitor.py -v
# Should show: 27 passed
```

### Integration Test (After Integration)

**Create**: `tests/integration/test_episode_integration.py`

**Test Scenarios**:

1. Bot receives messages → Monitor tracks them
2. Boundary detected → Episode created automatically
3. Window expires → Episode created on timeout
4. Window reaches max size → Boundary check triggered
5. Background task runs → Processes all windows
6. Shutdown → Monitor stops gracefully

**Manual Test**:

```python
# Quick test script
import asyncio
from app.main import main

async def test():
    # Start bot
    # Send test messages to a chat
    # Wait for window timeout or boundary
    # Check database for created episodes
    pass

asyncio.run(test())
```

### Verification Queries

**Check Episodes Created**:

```sql
SELECT 
    id,
    chat_id,
    topic,
    summary,
    message_count,
    participant_count,
    importance,
    tags,
    created_at
FROM episodes
ORDER BY created_at DESC
LIMIT 10;
```

**Check Episode Statistics**:

```sql
SELECT 
    COUNT(*) as total_episodes,
    AVG(message_count) as avg_messages,
    AVG(participant_count) as avg_participants,
    AVG(importance) as avg_importance,
    SUM(CASE WHEN tags LIKE '%boundary%' THEN 1 ELSE 0 END) as boundary_episodes,
    SUM(CASE WHEN tags LIKE '%timeout%' THEN 1 ELSE 0 END) as timeout_episodes
FROM episodes;
```

**Check Window Activity** (during runtime):

```python
# In Python REPL or admin command
windows = await episode_monitor.get_active_windows()
for w in windows:
    print(f"Chat {w.chat_id}: {len(w.messages)} messages, "
          f"{len(w.participant_ids)} participants, "
          f"last activity: {w.last_activity}")
```

## Rollback Plan

If issues occur during integration:

### Quick Disable (No Code Changes)

```bash
# In .env
AUTO_CREATE_EPISODES=false
```

Restart bot. Monitor will not track messages.

### Full Rollback

1. Comment out `episode_monitor.start()` in `main.py`
2. Remove `track_message()` calls from handlers
3. Restart bot

**No database changes needed** - episodes table exists from Phase 1.

## Monitoring & Logs

### Expected Log Messages

**Startup**:
```
Episode monitor initialized
Episode monitoring started
Background monitoring task created
```

**Runtime**:
```
Creating episode for chat 123, thread None: 15 messages, importance 0.75
Episode 42 created successfully
Background monitoring check completed: 3 windows checked
```

**Shutdown**:
```
Episode monitoring stopped
Background monitoring task cancelled
```

### Warning Signs

```
Window for chat 123 has no messages to create episode
Failed to create episode: <error>
Background monitoring task failed: <error>
```

**Action**: Check configuration, database connection, boundary detector status

## Performance Monitoring

### Metrics to Watch

1. **Message Tracking Latency**: Should be <1ms
2. **Background Task Duration**: Check every 5 minutes, should complete <1s per window
3. **Memory Usage**: Monitor window count and size
4. **Database Load**: Episodes created per hour

### Tuning If Needed

**Too many episodes**:
```bash
EPISODE_BOUNDARY_THRESHOLD=0.80        # Less sensitive
EPISODE_MIN_MESSAGES=10                 # Longer episodes
```

**Too few episodes**:
```bash
EPISODE_BOUNDARY_THRESHOLD=0.60        # More sensitive
EPISODE_WINDOW_TIMEOUT=900              # 15 min instead of 30
```

**Performance issues**:
```bash
EPISODE_MONITOR_INTERVAL=600           # Check every 10 min instead of 5
EPISODE_WINDOW_MAX_MESSAGES=30         # Smaller windows
```

## Success Criteria

### ✅ Integration Successful When:

- [ ] Bot starts without errors
- [ ] Logs show "Episode monitoring started"
- [ ] Messages tracked (check logs or window count)
- [ ] Episodes created (check database)
- [ ] Background task runs (check logs every 5 min)
- [ ] No performance degradation (<50ms added latency)
- [ ] No memory leaks (stable memory over hours)
- [ ] Bot shuts down gracefully

### ✅ Quality Indicators:

- [ ] Episodes have meaningful topics (first message preview)
- [ ] Episode importance scores are reasonable (0.3-0.8 range)
- [ ] Episode boundaries align with conversation shifts
- [ ] No duplicate episodes created
- [ ] Timeouts work as expected (30 min default)

## Next Steps After Integration

### Phase 4.2.1: Enhanced Summarization

**Goal**: Replace heuristic topic/summary with Gemini-powered generation

**Tasks**:
1. Create `EpisodeSummarizer` service
2. Design prompts for topic/summary extraction
3. Add emotional valence detection
4. Generate smart tags
5. Integrate with episode creation

**Estimated**: 1-2 days

### Phase 4.3: Episode Refinement

- Episode merging (combine related episodes)
- Episode splitting (break up too-large episodes)
- Episode re-summarization (improve old summaries)

### Phase 4.4: Proactive Retrieval

- Automatic episode retrieval in context assembly
- Episode relevance scoring
- Integration with multi-level context (Phase 3)

## Resources

- **Implementation**: `app/services/context/episode_monitor.py`
- **Tests**: `tests/unit/test_episode_monitor.py`
- **Full Docs**: `docs/phases/PHASE_4_2_COMPLETE.md`
- **Quick Ref**: `docs/guides/EPISODE_MONITORING_QUICKREF.md`
- **Summary**: `PHASE_4_2_COMPLETE_SUMMARY.md`
- **Changelog**: `docs/CHANGELOG.md`

## Approval Checklist

Before integrating:

- [ ] Code reviewed
- [ ] Tests passing (27/27) ✅
- [ ] Documentation reviewed
- [ ] Configuration validated
- [ ] Integration plan approved
- [ ] Rollback plan documented
- [ ] Success criteria defined
- [ ] Monitoring strategy ready

---

**Status**: ✅ Ready for Integration  
**Risk Level**: Low (graceful degradation, easy rollback)  
**Estimated Integration Time**: 30-60 minutes  
**Next Action**: Integrate into main.py and chat handler

---

*Phase 4.2 Integration Checklist*  
*Created: October 6, 2025*
