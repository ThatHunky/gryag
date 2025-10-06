# Episode Monitoring Quick Reference

**Phase 4.2**: Automatic Episode Creation  
**Last Updated**: October 6, 2025

## Quick Start

### 1. Enable Auto-Creation

```bash
# In .env
AUTO_CREATE_EPISODES=true
EPISODE_MIN_MESSAGES=5
EPISODE_WINDOW_TIMEOUT=1800        # 30 minutes
EPISODE_WINDOW_MAX_MESSAGES=50
EPISODE_MONITOR_INTERVAL=300       # 5 minutes
```

### 2. Integration (main.py)

```python
from app.services.context.episode_monitor import EpisodeMonitor

# Initialize
episode_monitor = EpisodeMonitor(
    db_path="./gryag.db",
    settings=settings,
    gemini_client=gemini_client,
    episodic_memory=episodic_memory,
    boundary_detector=boundary_detector,
)

# Start background task
await episode_monitor.start()

# Track messages in handler
await episode_monitor.track_message(
    chat_id=message.chat.id,
    thread_id=message.message_thread_id,
    message={
        "id": message.message_id,
        "user_id": message.from_user.id,
        "text": message.text,
        "timestamp": int(time.time()),
    }
)
```

## Configuration Guide

### Episode Creation Triggers

| Trigger | Config | Default | Description |
|---------|--------|---------|-------------|
| Boundary Detected | `EPISODE_BOUNDARY_THRESHOLD` | 0.70 | Topic shift detected |
| Window Timeout | `EPISODE_WINDOW_TIMEOUT` | 1800s | No activity for 30 min |
| Window Full | `EPISODE_WINDOW_MAX_MESSAGES` | 50 | Max messages reached |

### Tuning Patterns

**More Frequent Episodes**:

```bash
EPISODE_WINDOW_TIMEOUT=900           # 15 minutes
EPISODE_WINDOW_MAX_MESSAGES=30
EPISODE_BOUNDARY_THRESHOLD=0.60      # More sensitive
```

**Fewer Episodes**:

```bash
EPISODE_WINDOW_TIMEOUT=3600          # 1 hour
EPISODE_WINDOW_MAX_MESSAGES=100
EPISODE_BOUNDARY_THRESHOLD=0.80      # Less sensitive
```

**Quality Over Quantity**:

```bash
EPISODE_MIN_MESSAGES=10              # Longer episodes
EPISODE_WINDOW_TIMEOUT=2700          # 45 minutes
```

## Monitoring Commands

### Check Active Windows

```python
# Get all active windows
windows = await episode_monitor.get_active_windows()

for w in windows:
    print(f"Chat {w.chat_id}: {len(w.messages)} msgs, {len(w.participant_ids)} users")

# Get count
count = await episode_monitor.get_window_count()
print(f"Active windows: {count}")
```

### Manual Window Management

```python
# Clear window without creating episode
cleared = await episode_monitor.clear_window(
    chat_id=123,
    thread_id=None
)
```

## Episode Metadata

### Current Implementation (Phase 4.2)

**Topic**: First 50 characters of first message

```
"I love programming in Python" → "I love programming in Python"
"A very long message..." → "A very long message that exceeds fifty cha..."
```

**Summary**: Template with counts

```
"Conversation with 3 participant(s) over 15 message(s)"
```

**Importance**: Calculated from:

- Message count (up to 0.4)
- Participant count (up to 0.3)
- Duration (up to 0.3)

**Tags**: Creation reason only

- `"boundary"`: Created by boundary detection
- `"timeout"`: Created by window timeout

### Future (Phase 4.2.1)

- Gemini-generated topic and summary
- Emotional valence detection
- Smart tag extraction

## Troubleshooting

### Too Many Episodes

**Symptoms**: Episodes created for every few messages

**Fixes**:

1. Raise `EPISODE_BOUNDARY_THRESHOLD` (e.g., 0.80)
2. Raise `EPISODE_MIN_MESSAGES` (e.g., 10)
3. Raise `EPISODE_WINDOW_MAX_MESSAGES` (e.g., 100)

### Too Few Episodes

**Symptoms**: Long conversations never become episodes

**Fixes**:

1. Lower `EPISODE_WINDOW_TIMEOUT` (e.g., 900 = 15 min)
2. Lower `EPISODE_BOUNDARY_THRESHOLD` (e.g., 0.60)
3. Lower `EPISODE_WINDOW_MAX_MESSAGES` (e.g., 30)

### Episodes Without Context

**Symptoms**: Episodes created with only 1-2 messages

**Fixes**:

1. Raise `EPISODE_MIN_MESSAGES` (e.g., 5-10)
2. Check boundary detection sensitivity
3. Review conversation patterns

### Background Task Not Running

**Symptoms**: No automatic episode creation

**Debug**:

```python
# Check if started
if episode_monitor._monitor_task is None:
    await episode_monitor.start()

# Check logs
# Should see: "Episode monitoring started" in logs
```

### Memory Usage High

**Symptoms**: Many active windows consuming memory

**Fixes**:

1. Lower `EPISODE_WINDOW_MAX_MESSAGES` (e.g., 30)
2. Lower `EPISODE_WINDOW_TIMEOUT` (e.g., 900)
3. Manually clear inactive windows

## Performance Tips

### Optimize Message Tracking

```python
# Only track meaningful messages
if message.text and len(message.text) > 10:
    await episode_monitor.track_message(...)
```

### Adjust Monitor Interval

```bash
# High-traffic bot: Check more often
EPISODE_MONITOR_INTERVAL=180         # 3 minutes

# Low-traffic bot: Check less often
EPISODE_MONITOR_INTERVAL=600         # 10 minutes
```

### Batch Window Operations

```python
# Get all windows once
windows = await episode_monitor.get_active_windows()

# Process batch
for window in windows:
    # Check conditions
    # Take action
```

## Testing

### Run Tests

```bash
# All episode monitor tests
python -m pytest tests/unit/test_episode_monitor.py -v

# Specific test
python -m pytest tests/unit/test_episode_monitor.py::test_boundary_detected -v

# With coverage
python -m pytest tests/unit/test_episode_monitor.py --cov=app.services.context.episode_monitor
```

### Manual Testing

```python
import asyncio
from app.services.context.episode_monitor import EpisodeMonitor

async def test():
    monitor = EpisodeMonitor(...)
    await monitor.start()
    
    # Track some messages
    for i in range(10):
        await monitor.track_message(
            chat_id=1,
            thread_id=None,
            message={
                "id": i,
                "user_id": 1,
                "text": f"Message {i}",
                "timestamp": int(time.time()),
            }
        )
    
    # Check windows
    windows = await monitor.get_active_windows()
    print(f"Windows: {len(windows)}")
    
    await monitor.stop()

asyncio.run(test())
```

## Common Patterns

### Pattern 1: Single-Chat Bot

```bash
# Focus on quality episodes
EPISODE_MIN_MESSAGES=10
EPISODE_WINDOW_TIMEOUT=3600          # 1 hour
EPISODE_BOUNDARY_THRESHOLD=0.75
```

### Pattern 2: Multi-Chat Bot

```bash
# Balance responsiveness and quality
EPISODE_MIN_MESSAGES=5
EPISODE_WINDOW_TIMEOUT=1800          # 30 min
EPISODE_MONITOR_INTERVAL=300         # 5 min
```

### Pattern 3: High-Traffic Bot

```bash
# Prevent memory bloat
EPISODE_WINDOW_MAX_MESSAGES=30
EPISODE_WINDOW_TIMEOUT=900           # 15 min
EPISODE_MONITOR_INTERVAL=180         # 3 min
```

### Pattern 4: Analysis-Focused Bot

```bash
# Capture all meaningful exchanges
EPISODE_MIN_MESSAGES=3
EPISODE_WINDOW_TIMEOUT=1200          # 20 min
EPISODE_BOUNDARY_THRESHOLD=0.60      # Sensitive
```

## Integration Checklist

- [ ] Initialize `EpisodeMonitor` in `main.py`
- [ ] Start background task with `await monitor.start()`
- [ ] Track messages in chat handler
- [ ] Stop monitor on shutdown with `await monitor.stop()`
- [ ] Configure environment variables
- [ ] Test with sample conversations
- [ ] Monitor logs for episodes created
- [ ] Verify episode quality in database

## Logs to Watch

### Success Indicators

```
Episode monitoring started
Creating episode for chat 123, thread None: 15 messages, importance 0.75
Episode 42 created successfully
Background monitoring check completed: 3 windows checked
```

### Warning Signs

```
Window for chat 123 has no messages to create episode
Failed to create episode: <error>
Background monitoring task cancelled
```

## SQL Queries

### Check Recent Episodes

```sql
SELECT id, chat_id, topic, summary, message_count, importance, created_at
FROM episodes
ORDER BY created_at DESC
LIMIT 10;
```

### Find Episodes by Tags

```sql
SELECT * FROM episodes
WHERE tags LIKE '%boundary%';
```

### Episode Statistics

```sql
SELECT 
    COUNT(*) as total_episodes,
    AVG(message_count) as avg_messages,
    AVG(importance) as avg_importance,
    AVG(participant_count) as avg_participants
FROM episodes;
```

## Resources

- **Full Documentation**: `docs/phases/PHASE_4_2_COMPLETE.md`
- **Boundary Detection**: `docs/guides/EPISODE_BOUNDARY_DETECTION_QUICKREF.md`
- **Test Suite**: `tests/unit/test_episode_monitor.py`
- **Source Code**: `app/services/context/episode_monitor.py`

## Next Steps

After Phase 4.2 is stable:

1. **Phase 4.2.1**: Implement Gemini-based summarization
2. **Phase 4.3**: Episode refinement and merging
3. **Phase 4.4**: Proactive episode retrieval

---

*Quick Reference for Phase 4.2 Automatic Episode Creation*  
*Created: October 6, 2025*
