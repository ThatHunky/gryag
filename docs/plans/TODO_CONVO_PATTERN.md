# TODO: Migration to Compact Plain Text Conversation Pattern

**Status**: Planning Phase  
**Created**: 2025-10-17  
**Target**: Phase 6 or later

---

## Executive Summary

Migrate from verbose JSON-based Gemini API format to a compact plain text conversation pattern to reduce token usage by ~70-80% while maintaining context quality.

**Current format** (JSON with metadata parts):
```json
{
  "role": "user",
  "parts": [
    {"text": "[meta] chat_id=-123456789 thread_id=12 message_id=456 user_id=987654321 name=\"Alice\" username=\"alice_ua\""},
    {"text": "Як справи, гряг?"}
  ]
}
```

**Proposed format** (Compact plain text):
```
Alice#987654: Як справи, гряг?
gryag: Не набридай.
Bob#111222 → gryag: А що тут відбувається?
[RESPOND]
```

---

## Motivation

### Token Savings
- **Current**: ~150-200 tokens per message (metadata + structure overhead)
- **Proposed**: ~20-40 tokens per message (plain text)
- **Savings**: 70-80% reduction in context tokens
- **Impact**: Fit 3-4x more conversation history in same token budget

### Simplicity Benefits
1. **Easier debugging**: Human-readable conversation logs
2. **Faster processing**: No JSON parsing overhead
3. **Better compression**: Plain text compresses better in context
4. **Clearer replies**: Arrow notation shows reply chains

### Trade-offs
- **Loss**: Structured metadata (chat_id, message_id, timestamps)
- **Loss**: Native media support (need to describe media in text)
- **Gain**: Significantly more conversation history
- **Gain**: Simpler prompt engineering

---

## Proposed Format Specification

### Basic Message
```
Username#UserID: Message text
```

- **Username**: Display name (sanitized, max 30 chars)
- **UserID**: Last 6 digits of Telegram user_id (collision detection via full ID mapping)
- **Colon**: Separator between speaker and message
- **Message**: Actual content

### Bot Messages
```
gryag: Bot response text
```
- Bot always uses name "gryag" (no user ID needed)

### Reply Chains
```
Bob#111222 → Alice#987654: Replying to your message
```
- **Arrow** (`→`): Indicates reply-to relationship
- **Target**: Username#UserID being replied to
- **Optional**: Can include `→ [msg_id]` for precise message reference

### Media Messages
```
Alice#987654: [Image: sunset over Kyiv]
Bob#111222: [Video 0:45] Check out this song!
Carol#333444: [Photo] Look at my cat → Alice#987654
```
- **Media descriptor**: `[Image]`, `[Photo]`, `[Video HH:MM]`, `[Audio]`, `[Document: filename]`
- **Optional description**: Brief content summary for context
- **Position**: Inline with text or standalone

### System Markers
- **`[RESPOND]`**: Marks end of context, bot should generate response
- **`[SYSTEM]`**: System instructions/context (rare, for critical updates)
- **`[SUMMARY]`**: Condensed older messages (if needed)

### Thread Context (Optional)
```
=== Thread: "Planning birthday party" ===
Alice#987654: When should we meet?
Bob#111222: Saturday works for me
```
- Only included if thread context is critical
- Most threads can be inferred from conversation flow

---

## Implementation Plan

### Phase 1: Add Compact Format Builder (Parallel Path)
**Goal**: Implement new format without breaking existing system.

#### 1.1 Create Formatter Module
**File**: `app/services/conversation_formatter.py`

```python
def format_message_compact(
    user_id: int,
    username: str,
    name: str,
    text: str,
    media: list[dict[str, Any]] | None = None,
    reply_to_user_id: int | None = None,
    reply_to_username: str | None = None,
) -> str:
    """Format a single message in compact plain text format."""
    
def format_history_compact(
    messages: list[dict[str, Any]],
    bot_name: str = "gryag",
) -> str:
    """Format conversation history as plain text."""
    
def parse_user_id_short(user_id: int) -> str:
    """Get last 6 digits of user_id for compact format."""
    
def build_collision_map(user_ids: list[int]) -> dict[int, str]:
    """Build mapping of user_id to short_id, handling collisions."""
```

**Functions**:
- `format_message_compact()`: Convert single message to plain text
- `format_history_compact()`: Convert full history to plain text
- `parse_user_id_short()`: Extract last 6 digits from user_id
- `build_collision_map()`: Handle user_id collisions (rare but possible)
- `describe_media()`: Convert media objects to text descriptions

**Tests**: `tests/unit/test_conversation_formatter.py`

#### 1.2 Add Feature Flag
**File**: `app/config.py`

```python
class Settings:
    # ...
    enable_compact_conversation_format: bool = Field(
        default=False,
        description="Use compact plain text format instead of JSON for Gemini",
    )
    compact_format_max_history: int = Field(
        default=50,
        description="Max messages in compact format (higher than JSON due to efficiency)",
    )
```

**Env var**: `ENABLE_COMPACT_CONVERSATION_FORMAT=false` (default off for testing)

---

### Phase 2: Integrate with Context Assembly
**Goal**: Make compact format available in multi-level context manager.

#### 2.1 Update MultiLevelContextManager
**File**: `app/services/context/multi_level_context.py`

Add new method alongside `format_for_gemini()`:

```python
def format_for_gemini_compact(self, context: LayeredContext) -> dict[str, Any]:
    """
    Format layered context using compact plain text format.
    
    Returns dict with:
    - conversation_text: Plain text conversation
    - system_context: Profile/episodes as before
    - token_count: Estimated tokens
    """
    from app.services.conversation_formatter import format_history_compact
    
    # Combine immediate + recent into single list
    all_messages = []
    if context.immediate:
        all_messages.extend(context.immediate.messages)
    if context.recent:
        all_messages.extend(context.recent.messages)
    
    # Convert to compact format
    conversation_text = format_history_compact(all_messages, bot_name="gryag")
    
    # Add [RESPOND] marker
    conversation_text += "\n[RESPOND]\n"
    
    # Keep system context (profile, episodes) as-is
    # ... (same as current implementation)
    
    return {
        "conversation_text": conversation_text,
        "system_context": system_context,
        "token_count": estimate_tokens(conversation_text + (system_context or "")),
    }
```

**Changes**:
- New method `format_for_gemini_compact()` 
- Old method `format_for_gemini()` remains unchanged (backward compatibility)
- Compact format increases history from 30→50 messages (same token budget)

#### 2.2 Update Chat Handler
**File**: `app/handlers/chat.py`

```python
# Around line 1235 (format_for_gemini call)
if settings.enable_compact_conversation_format:
    formatted_context = context_manager.format_for_gemini_compact(context_assembly)
    
    # Build single user message with conversation text
    conversation_text = formatted_context["conversation_text"]
    if formatted_context.get("system_context"):
        system_prompt_with_profile = (
            base_system_prompt
            + timestamp_context
            + "\n\n"
            + formatted_context["system_context"]
        )
    
    # User parts become single text block
    user_parts_final = [{"text": conversation_text}]
    history = []  # No history, everything in current message
else:
    # Existing JSON format path
    formatted_context = context_manager.format_for_gemini(context_assembly)
    history = formatted_context["history"]
    # ... (current implementation)
```

**Changes**:
- Check feature flag `settings.enable_compact_conversation_format`
- Use `format_for_gemini_compact()` when enabled
- Pass conversation as single user message instead of history array
- Maintain backward compatibility with JSON format

---

### Phase 3: Update Gemini Client (Minor Changes)
**Goal**: Handle compact format in `generate()` method.

#### 3.1 Gemini Client Changes
**File**: `app/services/gemini.py`

```python
async def generate(
    self,
    system_prompt: str,
    history: Iterable[dict[str, Any]] | None,
    user_parts: Iterable[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_callbacks: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] | None = None,
) -> str:
    # ... existing code ...
    
    def assemble(include_prompt: bool) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        if include_prompt and system_prompt:
            payload.append({"role": "user", "parts": [{"text": system_prompt}]})
        
        # Handle compact format (no history, everything in user_parts)
        if history:
            payload.extend(list(history))
        
        payload.append({"role": "user", "parts": list(user_parts)})
        return payload
```

**Changes**: Minimal! The compact format reuses existing code path.
- Compact format: `history=[]`, all conversation in `user_parts`
- JSON format: `history=[...]`, current message in `user_parts`
- Both work with existing `assemble()` logic

---

### Phase 4: Media Handling Strategy
**Goal**: Handle media in compact format.

#### 4.1 Media Description
**File**: `app/services/conversation_formatter.py`

```python
def describe_media(media_items: list[dict[str, Any]]) -> str:
    """Convert media objects to compact text descriptions."""
    descriptions = []
    
    for item in media_items:
        kind = item.get("kind", "media")
        mime = item.get("mime", "")
        
        if kind == "photo" or "image" in mime:
            descriptions.append("[Image]")
        elif kind == "video" or "video" in mime:
            # Try to extract duration if available
            descriptions.append("[Video]")
        elif kind == "audio" or "audio" in mime:
            descriptions.append("[Audio]")
        elif kind == "document":
            filename = item.get("filename", "file")
            descriptions.append(f"[Document: {filename}]")
        else:
            descriptions.append(f"[{kind}]")
    
    return " ".join(descriptions)
```

#### 4.2 Media Attachment Strategy
For critical media (images that need to be analyzed):

**Option A**: Keep media in parts alongside text
```python
user_parts_final = [
    {"text": conversation_text},
    *media_parts,  # Actual image data for current message
]
```

**Option B**: Use file_uri with descriptive text
```python
conversation_text = f"""
Alice#987654: [Image: photo.jpg] What is this?
[RESPOND]
"""
# But still attach the actual image for Gemini to analyze
user_parts_final = [
    {"text": conversation_text},
    {"file_uri": "gs://..."} or {"inline_data": {...}}
]
```

**Recommendation**: Use Option B for backward compatibility.
- Compact text shows "what" happened in conversation
- Actual media parts let Gemini analyze images when needed
- Best of both worlds: context efficiency + multimodal capability

---

### Phase 5: Testing & Validation
**Goal**: Ensure compact format maintains quality while reducing tokens.

#### 5.1 Unit Tests
**File**: `tests/unit/test_conversation_formatter.py`

Test cases:
- ✅ Basic message formatting
- ✅ Reply chain formatting
- ✅ Media description formatting
- ✅ User ID collision handling
- ✅ Unicode/emoji handling
- ✅ Long username truncation
- ✅ Empty message handling

#### 5.2 Integration Tests
**File**: `tests/integration/test_compact_format.py`

Test cases:
- ✅ End-to-end message flow with compact format
- ✅ Multi-level context with compact format
- ✅ Token count reduction verification
- ✅ Media messages with compact format
- ✅ Tool calling with compact format
- ✅ Fallback to JSON on errors

#### 5.3 A/B Testing Strategy
**Phase 5a: Pilot (1 week)**
- Enable for 1-2 test chats only
- Compare response quality (manual review)
- Measure token usage reduction
- Monitor Gemini errors/failures

**Phase 5b: Gradual Rollout (2 weeks)**
- Enable for 10% of chats (random selection)
- Automated metrics: token usage, response latency, error rate
- User feedback: response quality (via `/gryagfeedback`)

**Phase 5c: Full Rollout (1 week)**
- Enable for all chats if metrics are positive
- Keep feature flag for emergency rollback

#### 5.4 Quality Metrics
Track before/after:
- **Token usage**: Average tokens per request (target: -70%)
- **Context depth**: Average messages in context (target: +200%)
- **Response quality**: Manual review + user feedback (target: neutral or better)
- **Error rate**: Gemini API failures (target: same or lower)
- **Latency**: Response time (target: same or faster)

---

### Phase 6: Optimization & Cleanup
**Goal**: Refine compact format based on testing results.

#### 6.1 Potential Optimizations
After initial testing, consider:

**User ID collision handling**:
- Current: Last 6 digits (1 in 1M collision chance)
- If collisions occur: Add distinguishing character (e.g., `Alice#987654a`)

**Reply chain optimization**:
- Current: `Bob → Alice: message`
- Alternative: `Bob→Alice: message` (no spaces, save tokens)

**Media description refinement**:
- Add AI-generated image descriptions for important images
- Example: `[Image: person at sunset, outdoor setting]`
- Use separate Gemini call to describe media, cache descriptions

**Temporal markers** (if needed):
- Add relative timestamps for context: `[5 min ago]`, `[yesterday]`
- Only for messages >1 hour old

#### 6.2 Deprecation Plan
Once compact format is stable (Phase 5c complete):

1. **Keep JSON format for 1 month** (backward compatibility)
2. **Announce deprecation** in `docs/CHANGELOG.md`
3. **Remove JSON format code** after 1 month + no issues
4. **Update documentation** to reflect compact format as standard

---

## Code Changes Summary

### New Files
- `app/services/conversation_formatter.py` - Compact format logic
- `tests/unit/test_conversation_formatter.py` - Unit tests
- `tests/integration/test_compact_format.py` - Integration tests

### Modified Files
- `app/config.py` - Add feature flags
- `app/services/context/multi_level_context.py` - Add `format_for_gemini_compact()`
- `app/handlers/chat.py` - Branch on feature flag
- `app/services/gemini.py` - Minor adjustment (if needed)

### Configuration
- `.env.example` - Add `ENABLE_COMPACT_CONVERSATION_FORMAT=false`

### Documentation
- `docs/overview/CURRENT_CONVERSATION_PATTERN.md` - Update with compact format
- `docs/CHANGELOG.md` - Add migration entry
- `AGENTS.md` - Reference compact format as default
- `.github/copilot-instructions.md` - Update conversation pattern reference

---

## Rollback Plan

If compact format causes issues:

1. **Immediate**: Set `ENABLE_COMPACT_CONVERSATION_FORMAT=false` (env var)
2. **Service restart**: All instances revert to JSON format
3. **Investigation**: Review logs for errors, response quality issues
4. **Fix or abandon**: Either fix bugs and re-enable, or abandon compact format

**Rollback safety**:
- Feature flag allows instant disable
- JSON format code remains intact during testing
- No database schema changes (both formats use same storage)
- No Gemini API contract changes (both use same endpoints)

---

## Success Criteria

**Phase 1-2**: Implementation complete
- ✅ Compact format builder functional
- ✅ Feature flag working
- ✅ Unit tests passing

**Phase 3-4**: Integration complete
- ✅ Chat handler uses compact format when enabled
- ✅ Media handling strategy implemented
- ✅ Integration tests passing

**Phase 5**: Quality validated
- ✅ Token usage reduced by 60%+ (target 70%)
- ✅ Response quality maintained or improved
- ✅ No increase in error rate
- ✅ User feedback neutral or positive

**Phase 6**: Production ready
- ✅ A/B testing shows clear benefits
- ✅ Compact format enabled for all chats
- ✅ Documentation updated
- ✅ Deprecated JSON format removed (or scheduled)

---

## Timeline Estimate

- **Phase 1**: 3-5 days (implementation + unit tests)
- **Phase 2**: 2-3 days (integration with context manager)
- **Phase 3**: 1-2 days (Gemini client updates)
- **Phase 4**: 2-3 days (media handling)
- **Phase 5**: 2-3 weeks (testing + gradual rollout)
- **Phase 6**: 1 week (optimization + cleanup)

**Total**: 4-6 weeks from start to full production rollout.

---

## Open Questions

1. **User ID collisions**: What happens if two users have same last 6 digits?
   - **Answer**: Track full user_id internally, add suffix if collision detected
   
2. **Media analysis**: How to maintain image analysis capability?
   - **Answer**: Keep media parts alongside compact text (Option B)
   
3. **Tool calling**: Does compact format work with function calling?
   - **Answer**: Yes, tool responses go in conversation text: `[Tool: calculator] Result: 345`
   
4. **Multilingual**: Does compact format work for Ukrainian/English/etc?
   - **Answer**: Yes, plain text handles all Unicode; no JSON escaping issues
   
5. **Backward compatibility**: What about old messages in database?
   - **Answer**: Convert on-the-fly when retrieved; no database migration needed

---

## References

- Current pattern: `docs/overview/CURRENT_CONVERSATION_PATTERN.md`
- Context assembly: `app/services/context/multi_level_context.py`
- Gemini client: `app/services/gemini.py`
- Chat handler: `app/handlers/chat.py`
- Token counting: https://ai.google.dev/gemini-api/docs/tokens

---

## Approval Checklist

Before starting implementation:
- [ ] Review by maintainer
- [ ] Confirm token savings are worth complexity
- [ ] Confirm response quality risk is acceptable
- [ ] Allocate time for testing (2-3 weeks)
- [ ] Prepare rollback communication plan

**Status**: ⏸️ Awaiting approval to proceed with Phase 1
