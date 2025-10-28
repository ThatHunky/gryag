# Plan: Message Processing Lock to Prevent Multiple Simultaneous Responses

**Date**: 2025-10-28  
**Status**: Planning  
**Priority**: High

## Problem Statement

The bot experiences long processing delays when responding to messages. During this delay, users send multiple messages, and the bot processes all of them sequentially, leading to:

1. **Delayed responses**: First message takes a long time to process
2. **Queue buildup**: Messages sent during processing get queued
3. **Poor UX**: Bot responds to messages sent minutes ago, out of context
4. **Wasted resources**: Processing outdated/irrelevant messages

### Current Flow (Broken)

```
User sends message 1 at 18:19:14 → Bot starts processing (long delay)
User sends message 2 at 18:19:20 → Queued for processing
User sends message 3 at 18:19:39 → Queued for processing
User sends message 4 at 18:19:40 → Queued for processing
...
Bot finishes processing message 1 at 18:20:07 → Sends response
Bot processes message 2 → Sends response (now irrelevant)
Bot processes message 3 → Sends response (now irrelevant)
Bot processes message 4 → Sends response (now irrelevant)
```

### Desired Flow (Fixed)

```
User sends message 1 at 18:19:14 → Bot starts processing (lock acquired)
User sends message 2 at 18:19:20 → IGNORED (bot still processing)
User sends message 3 at 18:19:39 → IGNORED (bot still processing)
User sends message 4 at 18:19:40 → IGNORED (bot still processing)
Bot finishes message 1 at 18:20:07 → Sends response (lock released)
User sends message 5 at 18:20:10 → Bot starts processing (lock acquired)
```

## Solution Design

### Approach 1: Per-User Processing Lock (RECOMMENDED)

Track active processing state per user in a conversation. Only process one message at a time per user, drop all subsequent messages until processing completes.

**Implementation**:
1. Add a new middleware: `ProcessingLockMiddleware`
2. Maintain in-memory dict: `{(chat_id, user_id): is_processing}`
3. Before processing a message:
   - Check if user is already being processed
   - If yes: drop message silently (log it)
   - If no: acquire lock, process, release lock
4. Use Redis for distributed deployments (fallback to in-memory for single instance)

**Advantages**:
- Simple, effective
- No state persistence needed
- Works immediately
- Independent per user (doesn't block other users)

**Disadvantages**:
- Messages are dropped (user doesn't know)
- Could miss important follow-up clarifications

### Approach 2: Queue with "Cancel Previous" Logic

Instead of dropping, maintain a queue but cancel/replace previous unprocessed messages.

**Implementation**:
1. Track: `{(chat_id, user_id): last_message_id_being_processed}`
2. When new message arrives while processing:
   - Cancel previous queued messages from same user
   - Queue only the latest message

**Advantages**:
- User's latest intent is always processed
- No messages completely ignored

**Disadvantages**:
- More complex
- Requires cancellation mechanism
- May still process outdated context

### Approach 3: Smart Debouncing

Add a small delay before processing to collect rapid-fire messages, then process only the last one.

**Implementation**:
1. When message arrives, wait 2-3 seconds
2. If another message arrives during wait, reset timer and use new message
3. After timer expires, process the latest message

**Advantages**:
- Handles rapid corrections well
- User's final intent is processed

**Disadvantages**:
- Adds artificial delay
- Complex timing logic
- May feel sluggish for single messages

## Recommended Solution: Approach 1 (Processing Lock)

Simplest and most effective. Prevents the queue buildup problem directly.

### Implementation Plan

#### 1. Create New Middleware: `ProcessingLockMiddleware`

**Location**: `app/middlewares/processing_lock.py`

**Key Features**:
- Track processing state per (chat_id, user_id)
- Use asyncio.Lock for thread safety
- Redis support for distributed deployments
- Admin bypass (admins can always send messages)
- Logging for dropped messages

**Interface**:
```python
class ProcessingLockMiddleware(BaseMiddleware):
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisLike | None = None
    ):
        # In-memory fallback
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._processing: dict[tuple[int, int], bool] = {}
        self._redis = redis_client
        self._use_redis = redis_client is not None
    
    async def __call__(self, handler, event: Message, data):
        if not isinstance(event, Message):
            return await handler(event, data)
        
        # Extract user/chat info
        user_id = event.from_user.id
        chat_id = event.chat.id
        key = (chat_id, user_id)
        
        # Check admin bypass
        settings = data.get("settings")
        if settings and user_id in settings.admin_user_ids_list:
            return await handler(event, data)
        
        # Check if already processing
        is_processing = await self._check_processing(key)
        
        if is_processing:
            LOGGER.info(
                f"Dropping message from user {user_id} in chat {chat_id} "
                f"(already processing previous message)"
            )
            telemetry.increment_counter("chat.dropped_during_processing")
            return  # Drop message silently
        
        # Acquire lock and process
        try:
            await self._set_processing(key, True)
            return await handler(event, data)
        finally:
            await self._set_processing(key, False)
    
    async def _check_processing(self, key: tuple[int, int]) -> bool:
        if self._use_redis:
            # Redis: "chat:{chat_id}:user:{user_id}:processing"
            redis_key = f"chat:{key[0]}:user:{key[1]}:processing"
            return await self._redis.exists(redis_key)
        else:
            return self._processing.get(key, False)
    
    async def _set_processing(self, key: tuple[int, int], value: bool):
        if self._use_redis:
            redis_key = f"chat:{key[0]}:user:{key[1]}:processing"
            if value:
                await self._redis.setex(redis_key, 300, "1")  # 5 min TTL
            else:
                await self._redis.delete(redis_key)
        else:
            self._processing[key] = value
```

#### 2. Register Middleware in `app/main.py`

Add before `ChatMetaMiddleware` so it runs early:

```python
# Import
from app.middlewares.processing_lock import ProcessingLockMiddleware

# Register (in main() function)
processing_lock = ProcessingLockMiddleware(
    settings=settings,
    redis_client=redis_client if use_redis else None
)
dispatcher.message.middleware(processing_lock)
```

#### 3. Add Configuration Options

**File**: `app/config.py`

```python
# Add to Settings class
enable_processing_lock: bool = True  # Master switch
processing_lock_use_redis: bool = True  # Use Redis if available
processing_lock_ttl_seconds: int = 300  # Lock timeout (safety)
```

**File**: `.env.example`

```bash
# Message processing lock
ENABLE_PROCESSING_LOCK=true
PROCESSING_LOCK_USE_REDIS=true
PROCESSING_LOCK_TTL_SECONDS=300
```

#### 4. Add Telemetry/Monitoring

Track dropped messages:
- Counter: `chat.dropped_during_processing`
- Log level: INFO (not ERROR, this is expected behavior)
- Include: user_id, chat_id, message_id in logs

#### 5. Testing Strategy

**Unit Tests** (`tests/unit/test_processing_lock.py`):
- Test lock acquisition/release
- Test concurrent message handling
- Test admin bypass
- Test Redis vs in-memory behavior

**Integration Tests**:
- Send rapid-fire messages in real chat
- Verify only first message processed
- Verify lock released after response
- Verify subsequent message accepted

**Manual Testing Checklist**:
- [ ] Send 5 messages quickly → only first processed
- [ ] Send message, wait for response, send another → both processed
- [ ] Admin sends multiple messages → all processed (bypass)
- [ ] Multiple users send messages → each user independent
- [ ] Redis restart during processing → graceful fallback

## Alternatives Considered

### Use aiogram's FSM (Finite State Machine)

aiogram has built-in FSM for conversation state management. Could track "processing" state.

**Rejected because**:
- Overkill for this simple use case
- Adds complexity to message flow
- FSM is for multi-step conversations, not processing locks

### Rate Limiting Extension

Extend existing `RateLimiter` to block during processing.

**Rejected because**:
- Rate limiter is for spam prevention (different concern)
- Mixing concerns makes both features harder to maintain
- Processing lock needs different semantics (immediate drop vs retry-after)

### Message Queue with Deduplication

Use external queue (e.g., Redis Queue) with deduplication.

**Rejected because**:
- Too complex for the problem
- Adds infrastructure dependency
- Middleware-based solution is simpler and sufficient

## Rollout Plan

### Phase 1: Implementation (Day 1)
1. Create `ProcessingLockMiddleware`
2. Add configuration options
3. Write unit tests

### Phase 2: Testing (Day 2)
1. Deploy to staging/test environment
2. Manual testing with rapid messages
3. Load testing with multiple users
4. Redis failover testing

### Phase 3: Production Rollout (Day 3)
1. Deploy with feature flag `ENABLE_PROCESSING_LOCK=true`
2. Monitor metrics: `chat.dropped_during_processing`
3. Monitor logs for unexpected lock issues
4. Collect user feedback

### Phase 4: Iteration (Week 1)
1. Analyze drop rate vs processing time
2. Consider optional "typing..." indicator for dropped messages
3. Add optional "Please wait..." auto-reply for heavy droppers
4. Tune TTL settings based on actual processing times

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Lock never released (bug) | User permanently blocked | TTL timeout (300s default) |
| Redis unavailable | Lock system fails | Fallback to in-memory locks |
| Admin messages blocked | Admin can't debug | Admin bypass built-in |
| User confusion (dropped msgs) | Poor UX | Log drops, consider typing indicator |
| Multiple bot instances | Lock state inconsistent | Use Redis for distributed lock |

## Success Metrics

- **Drop rate**: Expect 20-40% of messages dropped during high-frequency usage
- **Response time**: No change (processing time unchanged)
- **User complaints**: Reduction in "bot responding to old messages" feedback
- **Resource usage**: Reduction in wasted API calls for stale messages

## Future Enhancements

### Optional: Typing Indicator for Dropped Messages

When dropping a message, send "typing..." indicator so user knows bot is busy:

```python
if is_processing:
    await bot.send_chat_action(chat_id, "typing")
    return  # Still drop, but show we're working
```

### Optional: "Please wait" Auto-Reply

For users who send 5+ messages while processing, send one-time notice:

```python
if drop_count > 5:
    await message.reply("Я ще обробляю попереднє повідомлення, зачекай секунду 😊")
```

### Optional: Queue Mode (Toggle)

Add alternative mode where messages are queued instead of dropped:

```python
# Config
PROCESSING_LOCK_MODE=drop  # or "queue"
```

## References

- Telegram Bot API docs: https://core.telegram.org/bots/api
- aiogram middleware docs: https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html
- Redis distributed locks: https://redis.io/docs/manual/patterns/distributed-locks/

## Appendix: Code Locations

- **Middleware**: `app/middlewares/processing_lock.py` (new file)
- **Registration**: `app/main.py` (modify)
- **Config**: `app/config.py` (modify)
- **Tests**: `tests/unit/test_processing_lock.py` (new file)
- **Integration**: `tests/integration/test_processing_flow.py` (new file)

---

## Bonus Fix: Thinking Mode Not Enabled Despite .env Configuration

### Problem

The bot logs show `thinking enabled: False` even though `.env` has:

```bash
GEMINI_ENABLE_THINKING=true
SHOW_THINKING_TO_USERS=true
```

Log evidence:
```
bot-1  | 2025-10-28 16:21:58 - INFO - app.services.gemini - Extracted text length: 165, is_empty: False, thinking enabled: False, thinking length: 0
```

### Root Cause

In `app/config.py`, the default values are explicitly `False`:

```python
gemini_enable_thinking: bool = Field(False, alias="GEMINI_ENABLE_THINKING")
show_thinking_to_users: bool = Field(False, alias="SHOW_THINKING_TO_USERS")
```

Pydantic may not be parsing string boolean values from `.env` correctly. The strings `"true"` and `"false"` need proper conversion.

### Solution

Change defaults to `True` to match the desired behavior in `.env`:

```python
gemini_enable_thinking: bool = Field(True, alias="GEMINI_ENABLE_THINKING")
show_thinking_to_users: bool = Field(True, alias="SHOW_THINKING_TO_USERS")
```

**Alternative**: Add explicit boolean parsing in field validator (if pydantic isn't handling it):

```python
@field_validator("gemini_enable_thinking", "show_thinking_to_users", mode="before")
@classmethod
def _parse_bool(cls, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)
```

### Implementation

**File**: `app/config.py`

Change line 35-36:

```python
# Before
gemini_enable_thinking: bool = Field(False, alias="GEMINI_ENABLE_THINKING")
show_thinking_to_users: bool = Field(False, alias="SHOW_THINKING_TO_USERS")

# After
gemini_enable_thinking: bool = Field(True, alias="GEMINI_ENABLE_THINKING")
show_thinking_to_users: bool = Field(True, alias="SHOW_THINKING_TO_USERS")
```

### Verification

After fix, logs should show:

```
app.services.gemini - Extracted text length: XXX, is_empty: False, thinking enabled: True, thinking length: XXX
```

And thinking content should appear in responses.

---

**Next Steps**: Review this plan, approve approach, then proceed with implementation.
