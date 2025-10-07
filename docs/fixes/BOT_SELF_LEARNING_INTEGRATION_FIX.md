# Bot Self-Learning Integration Fix Plan

**Issue**: Bot self-learning profile shows 0 interactions despite feature being enabled  
**Root Cause**: Missing integration between chat handler and bot learning services  
**Status**: 🔴 Critical - Feature designed but never wired up  
**Date**: October 7, 2025

---

## Problem Analysis

### What's Working ✅

1. **Database Schema** - All tables exist and are correct:
   - `bot_profiles` - Bot profile per chat
   - `bot_facts` - Facts bot learns about itself
   - `bot_interaction_outcomes` - Individual interaction tracking
   - `bot_insights` - Gemini-generated self-reflections

2. **Service Layer** - All components implemented:
   - `BotProfileStore` - CRUD for bot learning data
   - `BotLearningEngine` - Learning extraction logic
   - Middleware injection - Services available in handlers

3. **Admin Interface** - Commands work (but show empty data):
   - `/gryagself` - View bot profile
   - `/gryaginsights` - Generate Gemini insights

4. **Configuration** - Feature enabled by default:
   - `ENABLE_BOT_SELF_LEARNING=true`
   - All related settings present

### What's Missing ❌

**The entire integration layer between message handling and learning services**:

1. ❌ No call to `bot_profile.record_interaction_outcome()` after bot responses
2. ❌ No user reaction detection when users respond
3. ❌ No sentiment analysis of user messages
4. ❌ No tool usage effectiveness tracking
5. ❌ No profile effectiveness score updates
6. ❌ No bot fact extraction from patterns

### Evidence from Code

**`app/handlers/chat.py`** - Main chat handler:
```bash
$ grep -n "bot_learning\|bot_profile" app/handlers/chat.py
# NO MATCHES - Services are injected but never used!
```

**Middleware injects services** (`app/middlewares/chat_meta.py:77-78`):
```python
data["bot_profile"] = self._bot_profile
data["bot_learning"] = self._bot_learning
```

**Handler signature has parameters** (`app/handlers/chat.py:944-948`):
```python
async def handle_group_message(
    message: Message,
    # ... other params ...
    bot_profile: BotProfileStore | None = None,  # ← Injected but unused
    bot_learning: BotLearningEngine | None = None,  # ← Injected but unused
```

---

## Fix Plan

### Phase 1: Basic Integration (High Priority)

**Goal**: Track all bot responses and calculate effectiveness score

#### 1.1 Record Interaction Outcomes

After bot sends response in `handle_group_message()`:

```python
# After: response_message = await message.reply(...)

# Track bot interaction
if settings.enable_bot_self_learning and bot_profile:
    asyncio.create_task(
        _track_bot_interaction_background(
            bot_profile=bot_profile,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=response_message.message_id,
            response_text=reply_trimmed,
            response_time_ms=response_time_ms,  # Need to add timing
            token_count=estimated_tokens,  # Need to estimate
            tools_used=tools_used_list,  # Need to track
        )
    )
```

#### 1.2 Detect User Reactions

When user sends message, check if it's a reaction to recent bot message:

```python
# Early in handle_group_message(), before is_addressed check
if settings.enable_bot_self_learning and bot_profile and bot_learning:
    # Check if this might be a reaction to bot's previous message
    await _process_potential_reaction(
        message=message,
        bot_profile=bot_profile,
        bot_learning=bot_learning,
        store=store,
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
    )
```

#### 1.3 Update Profile Stats

Background task to update effectiveness:

```python
async def _track_bot_interaction_background(
    bot_profile: BotProfileStore,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
    response_text: str,
    response_time_ms: int,
    token_count: int,
    tools_used: list[str] | None,
) -> None:
    """Record bot interaction outcome (fire-and-forget)."""
    try:
        # Get or create bot profile
        await bot_profile.get_or_create_profile(
            bot_id=bot_id,  # From middleware
            chat_id=chat_id,
        )
        
        # Record interaction with initial "neutral" outcome
        await bot_profile.record_interaction_outcome(
            chat_id=chat_id,
            message_id=message_id,
            interaction_type="response",
            outcome="neutral",  # Will be updated if user reacts
            response_text=response_text,
            response_time_ms=response_time_ms,
            token_count=token_count,
            tools_used=tools_used or [],
        )
        
    except Exception as e:
        LOGGER.error(f"Failed to track bot interaction: {e}", exc_info=True)
```

### Phase 2: Reaction Analysis (High Priority)

**Goal**: Learn from user feedback on bot responses

#### 2.1 Reaction Detection Logic

```python
async def _process_potential_reaction(
    message: Message,
    bot_profile: BotProfileStore,
    bot_learning: BotLearningEngine,
    store: ContextStore,
    chat_id: int,
    thread_id: int | None,
    user_id: int,
) -> None:
    """Check if message is a reaction to bot's previous message."""
    
    # Get bot's last message in this chat/thread (from last 5 minutes)
    recent_messages = await store.recent(
        chat_id=chat_id,
        thread_id=thread_id,
        max_turns=5,  # Last 5 turns
    )
    
    # Find most recent bot message
    bot_message = None
    bot_timestamp = None
    for msg in reversed(recent_messages):
        if msg.get("role") == "model":
            bot_message = msg.get("text")
            bot_timestamp = msg.get("ts")
            break
    
    if not bot_message or not bot_timestamp:
        return  # No recent bot message
    
    # Calculate reaction delay
    current_timestamp = int(time.time())
    reaction_delay = current_timestamp - bot_timestamp
    
    # Only consider as reaction if within timeout
    if reaction_delay > 300:  # 5 minutes
        return
    
    # Analyze user sentiment
    user_text = (message.text or message.caption or "").strip()
    if not user_text:
        return
    
    # Extract context tags
    from datetime import datetime
    now = datetime.now()
    context_tags = bot_learning.get_context_tags(
        hour_of_day=now.hour,
        is_weekend=(now.weekday() >= 5),
    )
    
    # Learn from reaction
    await bot_learning.learn_from_user_reaction(
        user_message=user_text,
        bot_previous_response=bot_message,
        chat_id=chat_id,
        reaction_delay_seconds=reaction_delay,
        context_tags=context_tags,
    )
    
    # Update interaction outcome (need to find the outcome record)
    # This requires getting the message_id of bot's response
    # We can add this to the recent messages metadata
```

### Phase 3: Tool Effectiveness Tracking (Medium Priority)

**Goal**: Learn which tools work well in which contexts

#### 3.1 Track Tool Usage

Modify tool calling section to track which tools were used:

```python
# Before tool execution
tools_used_in_request: list[str] = []

# In tool callback wrapper
def tracked_tool_callback(tool_name: str, original_callback):
    async def wrapper(params: dict[str, Any]) -> str:
        tools_used_in_request.append(tool_name)
        return await original_callback(params)
    return wrapper

# Wrap all tool callbacks
tool_callbacks_tracked = {
    name: tracked_tool_callback(name, callback)
    for name, callback in tool_callbacks.items()
}
```

#### 3.2 Learn from Tool Results

After user reacts to tool-based response:

```python
# In reaction processing
if tools_used and bot_learning:
    for tool_name in tools_used:
        await bot_learning.learn_from_tool_usage(
            tool_name=tool_name,
            tool_result=None,  # Could extract from response
            user_reaction=user_text,
            chat_id=chat_id,
            success=True,  # Infer from sentiment
            context_tags=context_tags,
        )
```

### Phase 4: Performance Metrics (Low Priority)

**Goal**: Track response time and token usage patterns

#### 4.1 Add Timing

```python
# At start of Gemini generation
generation_start = time.time()

# After generation
generation_end = time.time()
response_time_ms = int((generation_end - generation_start) * 1000)
```

#### 4.2 Estimate Tokens

```python
# Simple token estimation (4 chars ≈ 1 token for English/Ukrainian)
estimated_tokens = len(reply_text) // 4
```

#### 4.3 Record Metrics

```python
if bot_learning:
    await bot_learning.learn_from_performance_metrics(
        response_time_ms=response_time_ms,
        token_count=estimated_tokens,
        outcome="neutral",  # Will be updated from reactions
        chat_id=chat_id,
        context_tags=context_tags,
    )
```

---

## Implementation Strategy

### Step 1: Add Helper Functions (New file)

Create `app/handlers/bot_learning_integration.py`:

```python
"""Integration helpers for bot self-learning in chat handler."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from aiogram.types import Message

from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine
from app.services.context_store import ContextStore

LOGGER = logging.getLogger(__name__)

async def track_bot_interaction(...):
    """Track bot's interaction after response."""
    pass

async def process_potential_reaction(...):
    """Check if user message is reaction to bot."""
    pass

def get_context_tags(...) -> list[str]:
    """Generate context tags for learning."""
    pass
```

### Step 2: Modify Chat Handler (Minimal changes)

Add imports and calls to existing `app/handlers/chat.py`:

1. Import helper functions
2. Add timing tracking (2 lines)
3. Add tool usage tracking (5 lines)
4. Call `track_bot_interaction()` after response (1 line)
5. Call `process_potential_reaction()` early in handler (1 line)

**Total: ~10 new lines in main handler**

### Step 3: Test Incrementally

1. **Test Phase 1**: Verify interactions are recorded
   - Send message to bot
   - Check `/gryagself` shows total_interactions > 0

2. **Test Phase 2**: Verify reactions are detected
   - Bot responds
   - Reply with "thanks!" (positive)
   - Check effectiveness score increases

3. **Test Phase 3**: Verify tool tracking
   - Use weather tool
   - Reply positively
   - Check tool_effectiveness facts

### Step 4: Update Documentation

1. Update `docs/features/BOT_SELF_LEARNING.md` with integration details
2. Add verification steps
3. Update `docs/README.md` with fix entry

---

## Migration Considerations

### Database

✅ No migrations needed - all tables already exist

### Configuration

✅ No new config needed - all settings already defined

### Backward Compatibility

✅ All changes are additive - existing functionality unaffected

### Performance Impact

⚠️ **Minimal**:
- Background tasks (non-blocking)
- 1 extra DB insert per bot response (~10ms)
- 1 sentiment analysis per user message if follows bot (~5ms)
- Total overhead: <20ms per interaction

---

## Verification Steps

### 1. Check Initialization

```bash
# Look for bot profile init in logs
docker-compose logs bot | grep "Bot self-learning initialized"
```

### 2. Test Interaction Tracking

```python
# In chat, send message to bot
/gryag привіт

# Check profile
/gryagself

# Should show:
# Total interactions: 1+
# Effectiveness score: 0.5 (neutral)
```

### 3. Test Positive Reaction

```python
# Bot responds to something
/gryag який курс долара?

# Reply positively
дякую!

# Check again
/gryagself

# Should show:
# Positive interactions: 1+
# Effectiveness score: >0.5
```

### 4. Test Tool Learning

```python
# Use weather tool
/gryag яка погода в києві?

# Reply with praise
супер, дякую!

# Check facts
/gryagfacts

# Should show tool_effectiveness facts
```

### 5. Test Insights

```python
# After some interactions (10+), generate insights
/gryaginsights

# Should return Gemini-generated analysis
```

---

## Risk Assessment

### Low Risk ✅
- All new code in background tasks
- No changes to core message flow
- Services already tested in admin commands
- Easy to disable via `ENABLE_BOT_SELF_LEARNING=false`

### Medium Risk ⚠️
- Sentiment detection accuracy (regex-based initially)
- Reaction timeout tuning (false positives/negatives)
- DB write volume (1 extra write per bot response)

### Mitigation
- Start with conservative thresholds
- Monitor logs for errors
- Add circuit breaker to learning tasks
- Provide manual correction via admin commands

---

## Timeline Estimate

### Development
- Phase 1 (Basic Integration): **2-3 hours**
- Phase 2 (Reaction Analysis): **2-3 hours**
- Phase 3 (Tool Tracking): **1-2 hours**
- Phase 4 (Performance Metrics): **1 hour**

**Total: 6-9 hours** (1-2 days)

### Testing
- Unit tests for helpers: **1-2 hours**
- Integration tests: **2-3 hours**
- Manual verification: **1 hour**

**Total: 4-6 hours**

### Documentation
- Update BOT_SELF_LEARNING.md: **30 min**
- Add verification guide: **30 min**
- Update README: **15 min**

**Total: ~1 hour**

---

## Success Criteria

1. ✅ Bot profile shows non-zero interactions after bot responses
2. ✅ Effectiveness score changes based on user reactions
3. ✅ Bot facts are created from patterns
4. ✅ Tool effectiveness is tracked
5. ✅ `/gryagself` shows meaningful data
6. ✅ `/gryaginsights` generates useful insights
7. ✅ No performance degradation in message handling
8. ✅ Feature can be disabled without side effects

---

## Next Steps

1. **Immediate**: Create helper functions file
2. **Immediate**: Add basic interaction tracking (Phase 1)
3. **Short-term**: Add reaction analysis (Phase 2)
4. **Short-term**: Add tool tracking (Phase 3)
5. **Optional**: Add performance metrics (Phase 4)

---

## References

- **Design Doc**: `docs/features/BOT_SELF_LEARNING.md`
- **Schema**: `db/schema.sql` (lines 448-565)
- **Service**: `app/services/bot_learning.py`
- **Store**: `app/services/bot_profile.py`
- **Admin**: `app/handlers/profile_admin.py`
