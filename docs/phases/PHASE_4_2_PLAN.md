# What's Next: Phase 4.2 - Automatic Episode Creation

**Current Status**: Phase 4.1 Complete ✅  
**Next Phase**: Phase 4.2 - Automatic Episode Creation  
**Estimated Time**: 2-3 days

## Overview

Now that we can **detect** episode boundaries (Phase 4.1), the next step is to **automatically create episodes** when boundaries are detected.

## Phase 4.2 Goals

### 1. Background Monitoring Service

Create a service that periodically checks active conversations for boundaries.

**Key Components**:
- Conversation window tracker (groups recent messages)
- Periodic boundary checking (every 5 minutes)
- Active conversation identification
- Window closure on inactivity

**Files to Create**:
- `app/services/context/episode_monitor.py` (~300 lines)
- `tests/unit/test_episode_monitor.py` (~200 lines)

### 2. Automatic Episode Creation

When a boundary is detected, automatically create an episode.

**Key Components**:
- Boundary detection integration
- Episode metadata generation
- Participant extraction
- Message range identification

**Files to Modify**:
- `app/services/context/episodic_memory.py` (add auto-create logic)
- `tests/unit/test_episodic_memory.py` (add auto-create tests)

### 3. Episode Summarization

Use Gemini to generate topic and summary for each episode.

**Key Components**:
- Message content extraction
- Prompt engineering for summarization
- Topic extraction
- Tag generation

**Files to Create/Modify**:
- `app/services/context/episode_summarizer.py` (~200 lines)
- `tests/unit/test_episode_summarizer.py` (~150 lines)

### 4. Integration with Chat Handler

Wire the monitoring service into the main message processing flow.

**Files to Modify**:
- `app/main.py` (initialize monitor)
- `app/handlers/chat.py` (trigger boundary checks)

## Implementation Plan

### Step 1: Create Episode Monitor (Day 1)

**Goal**: Service that tracks conversation windows and checks for boundaries.

**Tasks**:
1. Create `ConversationWindow` dataclass
2. Implement window management (add messages, check timeout)
3. Add periodic boundary checking
4. Integrate with boundary detector
5. Write comprehensive tests

**Acceptance Criteria**:
- Windows track messages for active conversations
- Windows close after inactivity timeout
- Boundary checks run periodically
- All tests pass

### Step 2: Implement Auto-Creation (Day 2)

**Goal**: Automatically create episodes when boundaries detected.

**Tasks**:
1. Add `auto_create_episode` method to EpisodicMemoryStore
2. Extract participants from message window
3. Calculate importance score
4. Store episode in database
5. Write tests for auto-creation

**Acceptance Criteria**:
- Episodes created when boundaries detected
- Participant lists accurate
- Importance scores calculated
- Database records correct

### Step 3: Add Episode Summarization (Day 2-3)

**Goal**: Use Gemini to generate episode topics and summaries.

**Tasks**:
1. Create prompt template for episode summarization
2. Extract message content for context
3. Call Gemini API for summarization
4. Parse response (topic, summary, tags)
5. Update episode with generated metadata
6. Write tests with mocked Gemini

**Acceptance Criteria**:
- Episodes have meaningful topics
- Summaries capture key points
- Tags reflect content
- Error handling for API failures

### Step 4: Integration & Testing (Day 3)

**Goal**: Wire everything together and test end-to-end.

**Tasks**:
1. Initialize monitor in `main.py`
2. Pass monitor to chat handler
3. Trigger boundary checks on new messages
4. Add integration tests
5. Test in development environment
6. Document configuration

**Acceptance Criteria**:
- Episodes created automatically in real conversations
- Summaries are accurate
- Performance acceptable (<1s overhead)
- All tests pass

## Configuration to Add

```bash
# Episode monitoring
ENABLE_AUTO_EPISODE_CREATION=true
EPISODE_MONITOR_INTERVAL=300           # Check every 5 minutes
EPISODE_WINDOW_TIMEOUT=1800            # Close windows after 30 min inactivity
EPISODE_WINDOW_MAX_MESSAGES=50         # Max messages per window

# Episode summarization
ENABLE_EPISODE_SUMMARIZATION=true
EPISODE_SUMMARY_MAX_TOKENS=200         # Max summary length
EPISODE_SUMMARY_PROMPT_TEMPLATE="..."  # Custom prompt
```

## Expected File Structure

```
app/services/context/
├── episode_boundary_detector.py      # ✅ Phase 4.1
├── episode_monitor.py                # 📝 New (Phase 4.2)
├── episode_summarizer.py             # 📝 New (Phase 4.2)
└── episodic_memory.py                # 🔧 Modified

tests/unit/
├── test_episode_boundary_detector.py # ✅ Phase 4.1
├── test_episode_monitor.py           # 📝 New
├── test_episode_summarizer.py        # 📝 New
└── test_episodic_memory.py           # 🔧 Modified

docs/phases/
├── PHASE_4_1_COMPLETE.md             # ✅ Phase 4.1
└── PHASE_4_2_COMPLETE.md             # 📝 New
```

## API Design Sketch

### Episode Monitor

```python
class EpisodeMonitor:
    """Monitors conversations for episode boundaries."""
    
    async def track_message(
        self, 
        chat_id: int, 
        thread_id: int | None, 
        message: dict
    ) -> None:
        """Add message to conversation window."""
        
    async def check_boundaries(self) -> list[Episode]:
        """Check all windows for boundaries, create episodes."""
        
    async def get_active_windows(self) -> list[ConversationWindow]:
        """Get all active conversation windows."""
```

### Episode Summarizer

```python
class EpisodeSummarizer:
    """Generates episode topics and summaries using Gemini."""
    
    async def summarize_window(
        self, 
        window: ConversationWindow
    ) -> EpisodeSummary:
        """Generate topic, summary, and tags for window."""
```

### Auto-Creation Flow

```python
# In message handler
await episode_monitor.track_message(chat_id, thread_id, message)

# Periodic background task
async def check_episodes_task():
    while True:
        await asyncio.sleep(settings.episode_monitor_interval)
        
        # Check all windows
        created_episodes = await episode_monitor.check_boundaries()
        
        # Summarize new episodes
        for episode in created_episodes:
            summary = await episode_summarizer.summarize_episode(episode)
            await episodic_memory.update_episode(episode.id, summary)
```

## Success Metrics

By end of Phase 4.2:

- ✅ Episodes created automatically during conversations
- ✅ Boundary detection integrated into message flow
- ✅ Episode summaries generated with Gemini
- ✅ Participants tracked correctly
- ✅ <1s overhead per message
- ✅ All tests passing
- ✅ Documentation complete

## Dependencies

### Phase 4.1 (Complete) ✅
- Episode boundary detection
- Signal scoring
- Configuration

### Required Services
- ✅ EpisodeBoundaryDetector (Phase 4.1)
- ✅ EpisodicMemoryStore (existing)
- ✅ GeminiClient (existing)
- ✅ ContextStore (existing)

## Risks & Mitigations

### Risk: Gemini API Rate Limits

**Impact**: Can't summarize all episodes  
**Mitigation**: 
- Queue summarization requests
- Fallback to simple heuristic summaries
- Rate limit to 1 request/second

### Risk: Performance Overhead

**Impact**: Message processing slows down  
**Mitigation**:
- Run boundary checks in background
- Use asyncio for parallelization
- Cache recent boundary checks

### Risk: False Boundaries

**Impact**: Too many small episodes  
**Mitigation**:
- Tune threshold in Phase 4.1
- Add minimum episode size (5+ messages)
- Monitor false positive rate

## Testing Strategy

### Unit Tests
- Window management (add/remove/timeout)
- Boundary checking logic
- Summarization prompts
- Auto-creation flow

### Integration Tests
- End-to-end episode creation
- Real conversation scenarios
- Gemini API integration
- Database persistence

### Performance Tests
- Message processing overhead
- Boundary check latency
- Memory usage with many windows

## Documentation to Create

1. **PHASE_4_2_COMPLETE.md**: Full implementation details
2. **EPISODE_AUTO_CREATION_GUIDE.md**: User guide
3. **API_REFERENCE.md**: Episode monitor & summarizer API

## Questions to Resolve

1. **Window Scope**: Per-chat or per-thread?
   - Recommendation: Per-thread (more granular)

2. **Summary Length**: How long should summaries be?
   - Recommendation: 2-3 sentences (~200 tokens)

3. **Tag Generation**: Automatic or manual?
   - Recommendation: Automatic with Gemini

4. **Failure Handling**: What if summarization fails?
   - Recommendation: Create episode with basic metadata, retry later

## Ready to Start?

Phase 4.1 provides the foundation. Phase 4.2 builds on it to create a fully automated episodic memory system.

**Checklist before starting**:
- ✅ Phase 4.1 tests passing (24/24)
- ✅ Boundary detector working
- ✅ Configuration in place
- ✅ Documentation reviewed
- ✅ Development environment ready

**First task**: Create `app/services/context/episode_monitor.py` with `ConversationWindow` and basic window management.

---

Let me know when you're ready to proceed with Phase 4.2! 🚀
