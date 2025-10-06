# Continuous Learning System Improvements Plan

**Created**: 2025-10-06  
**Status**: Planning  
**Priority**: High - System currently underperforming

## Executive Summary

The continuous fact and context learning system is currently underperforming due to several configuration and architectural issues:

1. **Limited fact extraction method** - Using only rule-based patterns (~70% coverage) instead of hybrid method (~85% coverage)
2. **Overly aggressive filtering** - High confidence threshold (0.8) and message filtering blocking too many potential facts
3. **Window-based extraction delays** - 3-minute timeout means facts aren't learned in real-time
4. **No observability** - Lack of runtime logs and metrics to verify system operation
5. **Throttling may interfere** - Though continuous monitoring runs before throttle checks, unaddressed messages might be discarded

## Current State Analysis

### Configuration Issues

From `.env` file:
```bash
# GOOD - System is enabled
ENABLE_CONTINUOUS_MONITORING=true
ENABLE_MESSAGE_FILTERING=true
ENABLE_ASYNC_PROCESSING=true

# PROBLEMATIC - Limited extraction
FACT_EXTRACTION_METHOD=rule_based  # Should be 'hybrid'
ENABLE_GEMINI_FALLBACK=false       # Should be true for complex cases

# PROBLEMATIC - Too strict
FACT_CONFIDENCE_THRESHOLD=0.8      # Should be 0.7 (default)
```

### Architecture Issues

**1. Window-Based Extraction Only**

Current flow:
```
Message → Classify → Add to Window → Wait for window close (3 min) → Extract facts
```

Problems:
- Facts only extracted when windows close (3-minute timeout or 8 messages)
- Short conversations may never reach window closure
- Important facts delayed by up to 3 minutes
- No real-time learning from addressed messages

**2. Message Filtering Too Aggressive**

`MessageClassifier` filters out:
- ALL NOISE messages (stickers, reactions, media-only)
- Most LOW value messages (greetings, short messages <3 words, acknowledgments)
- Only HIGH and MEDIUM messages processed

Result: 40-60% of messages never analyzed for facts.

**3. No Dual-Path Extraction**

Current system only extracts from windows. Better approach:
- **Immediate extraction**: Addressed messages (user wants bot attention → likely contains important info)
- **Window extraction**: Unaddressed messages (background learning from conversations)

This is similar to how `_update_user_profile_background()` works for addressed messages, but it's not integrated with continuous monitoring.

## Improvement Plan

### Phase 1: Quick Wins (Configuration Changes) - 1 hour

**Goal**: Improve fact extraction coverage without code changes

**Changes**:

1. **Enable hybrid extraction** (`.env`):
   ```bash
   FACT_EXTRACTION_METHOD=hybrid  # Enable local model + rules
   ENABLE_GEMINI_FALLBACK=true    # Fallback for complex cases
   ```

2. **Lower confidence threshold** (`.env`):
   ```bash
   FACT_CONFIDENCE_THRESHOLD=0.7  # More lenient (was 0.8)
   ```

3. **Add debug logging** (`.env`):
   ```bash
   LOGLEVEL=DEBUG  # See detailed extraction logs
   ```

4. **Reduce message filtering** (`.env`):
   ```bash
   ENABLE_MESSAGE_FILTERING=false  # Temporarily disable to see full impact
   ```

**Expected Impact**:
- Fact extraction coverage: 70% → 85% (hybrid method)
- More facts stored (lower threshold)
- Full visibility into system operation (debug logs)
- All messages processed (no filtering)

**Verification**:
```bash
# Watch logs for fact extraction
python -m app.main 2>&1 | grep -E "facts|window|extract|classification"

# Check database for new facts
sqlite3 gryag.db "SELECT COUNT(*) FROM user_facts WHERE created_at > datetime('now', '-1 hour');"
```

### Phase 2: Dual-Path Extraction (Code Changes) - 4 hours

**Goal**: Extract facts from both addressed messages (immediately) and windows (background)

**Implementation**:

**2.1. Extract facts from addressed messages immediately** (~2 hours)

Modify `app/handlers/chat.py` in `handle_group_message`:

```python
# After continuous_monitor.process_message() call
# Add immediate fact extraction for addressed messages
if is_addressed and continuous_monitor is not None:
    # Fire-and-forget fact extraction
    asyncio.create_task(
        _extract_facts_from_addressed_message(
            message=message,
            continuous_monitor=continuous_monitor,
            settings=settings,
        )
    )
```

New helper function:
```python
async def _extract_facts_from_addressed_message(
    message: Message,
    continuous_monitor: ContinuousMonitor,
    settings: Settings,
) -> None:
    """
    Extract facts from addressed messages immediately.
    
    Addressed messages are high-priority: user is directly talking to bot,
    so content is likely relevant and should be learned right away.
    """
    try:
        # Skip if no text content
        if not (message.text or message.caption):
            return
        
        # Get recent context (last 5 messages) for better extraction
        from app.services.context_store import ContextStore
        
        # Note: Need to pass context_store through parameters
        # For now, use empty context (still better than nothing)
        context = []
        
        # Extract via continuous monitor's fact extractor
        facts = await continuous_monitor.fact_extractor.extract_facts(
            message=message.text or message.caption or "",
            user_id=message.from_user.id,
            username=message.from_user.username,
            context=context,
            min_confidence=settings.fact_confidence_threshold,
        )
        
        if facts:
            LOGGER.info(
                f"Extracted {len(facts)} facts from addressed message (immediate)",
                extra={
                    "chat_id": message.chat.id,
                    "user_id": message.from_user.id,
                    "message_id": message.message_id,
                }
            )
            
            # Store via user profile store
            for fact in facts:
                fact["extracted_immediately"] = True
                fact["addressed_message"] = True
            
            # Use continuous monitor's store method (reuse quality processing)
            from app.services.monitoring.conversation_analyzer import MessageContext
            
            # Create fake window for storage (reuse existing code)
            # Better: Refactor _store_facts to accept facts directly
            await _store_immediate_facts(
                facts=facts,
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                continuous_monitor=continuous_monitor,
            )
    
    except Exception as e:
        LOGGER.error(
            "Failed to extract facts from addressed message",
            exc_info=e,
            extra={
                "chat_id": message.chat.id,
                "message_id": message.message_id,
            }
        )
```

**2.2. Refactor fact storage** (~1 hour)

Create standalone fact storage method in `ContinuousMonitor`:

```python
async def store_facts_for_user(
    self,
    facts: list[dict[str, Any]],
    user_id: int,
    chat_id: int,
) -> int:
    """
    Store facts for a user with quality processing.
    
    Can be called from:
    - Window processing (existing)
    - Immediate extraction (new)
    - Manual fact addition (future)
    
    Returns:
        Number of facts stored after quality processing
    """
    # Extract logic from _store_facts but for single user
    # Apply quality processing, deduplication, etc.
    # Return count of stored facts
```

**2.3. Add metrics and logging** (~1 hour)

Add to `ContinuousMonitor._stats`:
```python
self._stats = {
    "messages_monitored": 0,
    "windows_processed": 0,
    "facts_extracted": 0,
    "facts_extracted_immediate": 0,  # NEW
    "facts_extracted_window": 0,      # NEW
    "facts_stored": 0,                # NEW
    "facts_deduplicated": 0,          # NEW
    "proactive_responses": 0,
}
```

Add periodic stats logging to `app/main.py`:
```python
async def log_continuous_monitor_stats():
    """Log continuous monitor statistics every 10 minutes."""
    while True:
        await asyncio.sleep(600)  # 10 minutes
        stats = continuous_monitor.get_stats()
        logging.info(
            "Continuous learning statistics",
            extra=stats,
        )
```

**Expected Impact**:
- Addressed messages: Facts extracted immediately (0 delay vs 3 min)
- Better coverage: Dual path catches both interactive and background conversations
- Observability: Clear metrics on what's working

### Phase 3: Adaptive Window Timing (Code Changes) - 2 hours

**Goal**: Reduce window timeout for active conversations, increase for inactive

**Implementation**:

Modify `ConversationAnalyzer` to use adaptive timeouts:

```python
class ConversationAnalyzer:
    def __init__(
        self,
        max_window_size: int = 8,
        window_timeout_seconds: int = 180,  # Base timeout
        adaptive_timeout: bool = True,      # NEW
    ):
        self.adaptive_timeout = adaptive_timeout
        self.base_timeout = window_timeout_seconds
    
    def _get_timeout_for_window(self, window: ConversationWindow) -> int:
        """Calculate adaptive timeout based on message frequency."""
        if not self.adaptive_timeout:
            return self.base_timeout
        
        # If window has high message frequency, use shorter timeout
        if len(window.messages) >= 5:
            message_times = [msg.timestamp for msg in window.messages]
            time_span = max(message_times) - min(message_times)
            
            if time_span < 60:  # 5+ messages in 1 minute = very active
                return 60  # Close after 1 minute of inactivity
            elif time_span < 180:  # 5+ messages in 3 minutes = active
                return 120  # Close after 2 minutes
        
        return self.base_timeout  # Default 3 minutes
```

**Expected Impact**:
- Active conversations: Windows close faster (1-2 min vs 3 min)
- Inactive conversations: Still get 3-minute window
- Faster fact extraction without losing context

### Phase 4: Observability Dashboard (Code Changes) - 3 hours

**Goal**: Admin command to view continuous learning stats

**Implementation**:

Add to `app/handlers/profile_admin.py`:

```python
@router.message(Command("gryaglearning"))
async def cmd_learning_stats(
    message: Message,
    settings: Settings,
    continuous_monitor: ContinuousMonitor | None = None,
):
    """Show continuous learning system statistics (admin only)."""
    if message.from_user.id not in settings.admin_user_ids_list:
        await message.reply("Тільки для адмінів")
        return
    
    if continuous_monitor is None:
        await message.reply("Continuous monitoring not enabled")
        return
    
    stats = continuous_monitor.get_stats()
    
    # Format stats nicely
    report = f"""📊 **Continuous Learning Stats**

**Messages**:
• Monitored: {stats['messages_monitored']}
• Windows processed: {stats['windows_processed']}

**Facts**:
• Total extracted: {stats['facts_extracted']}
• From immediate: {stats.get('facts_extracted_immediate', 0)}
• From windows: {stats.get('facts_extracted_window', 0)}
• Stored: {stats.get('facts_stored', 0)}
• Deduplicated: {stats.get('facts_deduplicated', 0)}

**Classification** (last 100 messages):
• High value: {stats['classifier_stats']['high']}
• Medium: {stats['classifier_stats']['medium']}
• Low: {stats['classifier_stats']['low']}
• Noise: {stats['classifier_stats']['noise']}

**Windows**:
• Active: {stats['analyzer_stats'].get('active_windows', 0)}
• Closed: {stats['analyzer_stats'].get('windows_closed', 0)}

**System**:
• Healthy: {'✅' if stats['system_healthy'] else '❌'}
• Filtering: {'✅' if settings.enable_message_filtering else '❌'}
• Async: {'✅' if settings.enable_async_processing else '❌'}
"""
    
    await message.reply(report, parse_mode=ParseMode.MARKDOWN)
```

**Expected Impact**:
- Admins can check system health
- Quick debugging of extraction issues
- Visibility into what messages are being processed

## Throttling Analysis

**Current behavior**:
```python
# In handle_group_message:

# Step 1: Continuous monitoring (BEFORE throttle check) ✅
if continuous_monitor is not None:
    await continuous_monitor.process_message(message, is_addressed=is_addressed)

# Step 2: Check if addressed
if not is_addressed:
    return  # Unaddressed messages stop here

# Step 3: Throttle check (ONLY for addressed messages)
if throttle_blocked and not is_admin:
    return  # Blocked users stop here
```

**Analysis**:
- ✅ Continuous monitoring runs for ALL messages (addressed + unaddressed)
- ✅ Throttle only affects addressed messages (replies to user)
- ❌ BUT: Unaddressed messages don't participate in immediate extraction (Phase 2 fix)
- ✅ Unaddressed messages DO participate in window-based extraction

**Conclusion**: Throttling is NOT blocking continuous learning. The issue is that:
1. Only rule-based extraction is enabled (limited coverage)
2. Confidence threshold is too high (0.8)
3. Window timeouts are too long (3 minutes)
4. No immediate extraction for addressed messages

## Rollout Strategy

### Week 1: Configuration Changes + Monitoring

1. **Day 1**: Apply Phase 1 config changes
   - Enable hybrid extraction
   - Lower confidence threshold
   - Enable debug logging
   - Disable message filtering temporarily

2. **Day 2-3**: Monitor logs and database
   - Check for increased fact extraction
   - Verify no performance issues
   - Look for quality issues (bad facts)

3. **Day 4-5**: Re-enable filtering (if needed)
   - If too many low-quality facts, re-enable filtering
   - Adjust confidence threshold based on quality

4. **Day 6-7**: Baseline metrics
   - Document facts/hour rate
   - Document window processing rate
   - Identify remaining gaps

### Week 2: Dual-Path Extraction (Phase 2)

1. **Day 1-2**: Implement immediate extraction
2. **Day 3**: Testing in dev environment
3. **Day 4**: Deploy to production
4. **Day 5-7**: Monitor and adjust

### Week 3: Polish (Phases 3-4)

1. **Day 1-2**: Adaptive window timing
2. **Day 3-4**: Observability dashboard
3. **Day 5-7**: Documentation and optimization

## Success Metrics

**Before (Baseline)**:
- Facts extracted/hour: Unknown (need to measure)
- Coverage: ~70% (rule-based only)
- Latency: 3 minutes (window timeout)
- Visibility: Low (no metrics)

**After (Target)**:
- Facts extracted/hour: 2-3x increase
- Coverage: ~85% (hybrid extraction)
- Latency: 0s for addressed, 1-2 min for windows
- Visibility: High (admin dashboard + logs)

## Risks and Mitigations

**Risk 1: Too many facts**
- Mitigation: Quality processing (deduplication) should handle this
- Fallback: Re-enable message filtering

**Risk 2: Performance degradation**
- Mitigation: Immediate extraction is fire-and-forget (async)
- Fallback: Resource optimizer should detect pressure

**Risk 3: Gemini API costs**
- Mitigation: Hybrid uses local model first, Gemini only for fallback
- Monitor: Track Gemini API calls in logs

**Risk 4: Bad facts from aggressive extraction**
- Mitigation: Quality processing + confidence threshold
- Monitor: Manual review via `/gryagfacts` command

## How to Verify

### Phase 1 (Config Changes)

```bash
# 1. Update .env
nano .env

# 2. Restart bot
python -m app.main

# 3. Watch logs (separate terminal)
python -m app.main 2>&1 | tee bot.log | grep -E "facts|window|extract"

# 4. Send test messages in Telegram
# - Short messages: "я з Києва"
# - Long messages: "я програміст, працюю з Python вже 5 років"

# 5. Check facts in database (after 3 minutes)
sqlite3 gryag.db "
SELECT fact_type, fact_key, fact_value, confidence, 
       datetime(created_at, 'localtime') as created
FROM user_facts 
WHERE created_at > datetime('now', '-10 minutes')
ORDER BY created_at DESC;
"

# 6. Check extraction logs
grep "Extracted.*facts" bot.log
grep "Quality processing" bot.log
```

### Phase 2 (Dual-Path)

```bash
# 1. Send addressed message (should see immediate extraction)
# Expected log: "Extracted N facts from addressed message (immediate)"

# 2. Check time difference
sqlite3 gryag.db "
SELECT fact_value, 
       json_extract(evidence_text, '$.extracted_immediately') as immediate,
       datetime(created_at, 'localtime') as created
FROM user_facts 
WHERE created_at > datetime('now', '-5 minutes');
"

# 3. Verify stats
# Use /gryaglearning command in Telegram
```

## Next Steps

1. **Immediate**: Apply Phase 1 config changes (1 hour)
2. **This week**: Monitor and establish baseline (rest of week)
3. **Next week**: Implement Phase 2 dual-path extraction
4. **Future**: Phases 3-4 as needed based on results

## References

- Phase 3 implementation: `docs/phases/PHASE_3_IMPLEMENTATION_COMPLETE.md`
- Configuration docs: `.github/copilot-instructions.md`
- Fact extraction: `app/services/fact_extractors/`
- Continuous monitor: `app/services/monitoring/continuous_monitor.py`
