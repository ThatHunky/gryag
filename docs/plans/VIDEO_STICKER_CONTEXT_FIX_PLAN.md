# Plan: Fix Missing Videos and Stickers in Message Context

**Problem**: Videos and stickers are not appearing in conversation context when users send them in chat. The bot doesn't "see" these media types even though they're being collected.

**Created**: October 19, 2025  
**Status**: PLANNING  
**Priority**: HIGH (media context is a core feature)

## Problem Analysis

### Current State Investigation

After analyzing the codebase, I found that:

1. ✅ **Media Collection Works**: `app/services/media.py::collect_media_parts()` correctly handles:
   - Videos (via `message.video`)
   - Video notes (round videos via `message.video_note`)
   - Animations/GIFs (via `message.animation`)
   - Stickers: static WebP, animated TGS (thumbnail), and video WebM

2. ✅ **Media Building Works**: `app/services/gemini.py::build_media_parts()` correctly converts raw media to Gemini format with proper filtering based on model capabilities

3. ✅ **Token Estimation Fixed**: Previously broken `_estimate_tokens()` was fixed (October 17) to count media tokens (~258 for inline_data, ~100 for file_uri)

4. ❓ **Potential Issue #1 - Media Not Persisted in Recent Context**:
   - In `_remember_context_message()`, media is collected but may not be properly stored
   - Need to verify that `media_parts` is actually being added to the in-memory cache

5. ❓ **Potential Issue #2 - Compact Format May Drop Media**:
   - The compact format uses text-based rendering
   - May not be including media parts when building conversation history
   - `describe_media()` exists but may not be called in the right place

6. ❓ **Potential Issue #3 - Model Capability Filtering**:
   - Videos/stickers might be filtered out if model doesn't support them
   - Need to check `_is_media_supported()` logic for gemini-2.5-flash

### Root Cause Hypothesis

**Primary suspect**: The in-memory context cache (`_RECENT_CONTEXT`) is not properly storing `media_parts` for unaddressed messages, causing them to be unavailable when assembling reply context.

**Evidence**:
- `_remember_context_message()` (lines 267-359) collects `media_raw` and builds `media_parts`
- BUT: The in-memory cache entry only includes `text` and `excerpt`, not `media_parts`
- When building reply context, there's logic to fetch media from reply messages, but the cached context won't have it

**Secondary suspect**: Compact format may not be rendering media even when present in history.

## Detailed Code Review

### 1. In-Memory Context Cache (`_RECENT_CONTEXT`)

**Location**: `app/handlers/chat.py` lines 254-319

**Current behavior**:
```python
bucket.append({
    "ts": int(message.date.timestamp()) if message.date else int(time.time()),
    "message_id": message.message_id,
    "user_id": message.from_user.id,
    "name": message.from_user.full_name,
    "username": _normalize_username(message.from_user.username),
    "excerpt": (text or media_summary or "")[:200] or None,
    "text": text or media_summary,
    "media_parts": media_parts,  # ✅ THIS IS STORED
})
```

So media_parts IS being stored in the cache! Let me check where it's being used...

### 2. Reply Context Building

**Location**: `app/handlers/chat.py` lines 1062-1143

**Current behavior**:
- Looks up message in `_RECENT_CONTEXT`
- If found, uses the cached `media_parts`
- If not found OR cached context has no media, tries to collect media directly from reply message

This looks correct too! So the issue must be elsewhere...

### 3. Multi-Level Context Assembly

**Location**: `app/services/context/multi_level_context.py` lines 317-397

**Observation**: Has extensive debug logging for media items:
```python
media_count = sum(
    1 for msg in messages
    for part in msg.get("parts", [])
    if isinstance(part, dict) and ("inline_data" in part or "file_data" in part)
)
if media_count > 0:
    LOGGER.debug(f"Immediate context (cached) contains {media_count} media items")
```

This suggests media IS being tracked through context assembly.

### 4. Compact Format Rendering

**Location**: `app/services/conversation_formatter.py` lines 267-352

**Issue Found**: In `format_history_compact()`, media is counted:
```python
# Count media parts
media_parts = [p for p in parts if "inline_data" in p or "file_uri" in p]
media_description = ""
if media_parts:
    # Simple count-based description
    if len(media_parts) == 1:
        media_description = "[Media]"
    else:
        media_description = f"[{len(media_parts)} media items]"
```

But this is a GENERIC description! Videos and stickers are just labeled "[Media]" without type information.

**This is problematic because**:
1. The model can't see the media itself in compact format (only the text description)
2. The actual media parts are sent separately but may not be connected to the context

### 5. Compact Format Integration

**Location**: `app/handlers/chat.py` lines 1308-1380

**Critical Discovery**:
```python
user_parts = [{"text": full_conversation}]
# Add media parts if present (for analysis)
if media_parts:
    user_parts.extend(media_parts)
```

So in compact format:
- The conversation history is TEXT ONLY (no media embedded)
- Current message media is added separately
- **BUT**: Historical media from context is NOT included!

## Root Causes Identified

### Root Cause #1: Compact Format Drops Historical Media
**Impact**: HIGH  
**Severity**: CRITICAL for compact format users

When `ENABLE_COMPACT_CONVERSATION_FORMAT=true`:
1. Conversation history is rendered as plain text via `format_history_compact()`
2. Media in historical messages is only mentioned as "[Media]" text
3. The actual `inline_data`/`file_data` parts from historical messages are NOT added to `user_parts`
4. Result: Bot can describe current message media, but cannot "see" videos/stickers from previous messages

### Root Cause #2: Generic Media Descriptions
**Impact**: MEDIUM  
**Severity**: MINOR but reduces context quality

The `describe_media()` function exists and can differentiate media types:
```python
if kind == "photo" or "image" in mime.lower():
    descriptions.append("[Image]")
elif kind == "video" or "video" in mime.lower():
    descriptions.append("[Video]")
```

But in `format_history_compact()`, it uses a generic counter:
```python
if len(media_parts) == 1:
    media_description = "[Media]"  # ❌ No type info!
else:
    media_description = f"[{len(media_parts)} media items]"  # ❌ No type info!
```

### Root Cause #3: Media Type Detection in describe_media()
**Impact**: LOW  
**Severity**: EDGE CASE

The `describe_media()` function checks for:
- `kind == "photo"` (but media collection sets `kind = "image"` for photos)
- This mismatch might cause photos to be labeled as generic "[Media]"

## Proposed Solution

### Phase 1: Fix Compact Format Historical Media (HIGH PRIORITY)

**Goal**: Ensure compact format includes actual media from historical messages, not just text descriptions

**Implementation**:

1. **Update `format_for_gemini_compact()` in MultiLevelContextManager**:
   - After building `conversation_text`, collect all media parts from history
   - Return them separately in the formatted context
   - Structure: `{"conversation_text": str, "system_context": str, "historical_media": list[dict]}`

2. **Update compact format integration in chat handler**:
   - When using compact format, extend `user_parts` with `historical_media`
   - Limit total media items to `GEMINI_MAX_MEDIA_ITEMS` (28 default)
   - Prioritize: current message media > recent historical media > older historical media

**Code changes**:
- `app/services/context/multi_level_context.py::format_for_gemini_compact()`
- `app/handlers/chat.py` (compact format branch around line 1365)

**Example**:
```python
# In format_for_gemini_compact()
historical_media = []
for msg in context_assembly.immediate.messages + context_assembly.recent.messages if context_assembly.recent else []:
    parts = msg.get("parts", [])
    for part in parts:
        if isinstance(part, dict) and ("inline_data" in part or "file_data" in part):
            historical_media.append(part)

return {
    "conversation_text": conversation_text,
    "system_context": system_context,
    "historical_media": historical_media,  # NEW
    "token_count": total_tokens,
}

# In chat.py compact format branch
formatted_context = context_manager.format_for_gemini_compact(context_assembly)
historical_media = formatted_context.get("historical_media", [])

user_parts = [{"text": full_conversation}]
# Add current message media first (highest priority)
if media_parts:
    user_parts.extend(media_parts)
# Add historical media (up to limit)
if historical_media:
    max_media = settings.gemini_max_media_items
    remaining_slots = max_media - len(media_parts)
    if remaining_slots > 0:
        user_parts.extend(historical_media[:remaining_slots])
        if len(historical_media) > remaining_slots:
            LOGGER.info(f"Trimmed {len(historical_media) - remaining_slots} historical media items due to limit")
```

### Phase 2: Improve Media Type Descriptions (MEDIUM PRIORITY)

**Goal**: Show specific media types in compact format text

**Implementation**:

1. **Fix `describe_media()` kind matching**:
   - Change `kind == "photo"` to `kind == "image"` to match actual usage
   - Add sticker detection

2. **Use `describe_media()` in `format_history_compact()`**:
   - Replace generic "[Media]" counter with specific type descriptions
   - Pass media parts to `describe_media()` function

**Code changes**:
- `app/services/conversation_formatter.py::describe_media()` (fix kind matching)
- `app/services/conversation_formatter.py::format_history_compact()` (use describe_media)

**Example**:
```python
# In format_history_compact()
media_parts_raw = [
    {"kind": p.get("kind", "media"), "mime": p.get("mime", "")}
    for p in parts
    if "inline_data" in p or "file_uri" in p
]
media_description = describe_media(media_parts_raw) if media_parts_raw else ""

# In describe_media()
if kind == "image" or "image" in mime.lower():  # ✅ Changed from "photo"
    descriptions.append("[Image]")
elif kind == "sticker" or mime.lower() in ("image/webp", "video/webm"):  # ✅ Added
    descriptions.append("[Sticker]")
```

### Phase 3: Add Media Type to In-Memory Cache (LOW PRIORITY)

**Goal**: Preserve media type information in cached context

**Implementation**:

1. **Add `media_summary` to cache entry**:
   - Store the result of `_summarize_media()` in cache
   - Use this when building reply context

**Code changes**:
- `app/handlers/chat.py::_remember_context_message()` (add media_summary to cache)
- `app/handlers/chat.py` reply context building (use cached media_summary)

### Phase 4: Add Debug Logging (IMMEDIATE)

**Goal**: Help diagnose media issues in production

**Implementation**:

1. **Add logging when media is dropped**:
   - Log in compact format when historical media is available but not included
   - Log media type distribution (N images, M videos, K stickers)
   - Log when media limit is hit

**Code changes**:
- Throughout media handling pipeline

## Testing Strategy

### Unit Tests

1. **Test `describe_media()` with videos and stickers**:
   ```python
   def test_describe_media_videos():
       media = [{"kind": "video", "mime": "video/mp4"}]
       assert describe_media(media) == "[Video]"
   
   def test_describe_media_stickers():
       media = [{"kind": "image", "mime": "image/webp"}]
       result = describe_media(media)
       assert "[Sticker]" in result or "[Image]" in result
   ```

2. **Test compact format includes historical media**:
   ```python
   def test_compact_format_includes_video_from_history():
       # Build context with video in history
       # Format for Gemini compact
       # Verify result["historical_media"] contains video
   ```

### Integration Tests

1. **Manual test scenario**:
   - User sends video message
   - Wait 2 minutes
   - User sends "what was in that video?" (addressed)
   - Bot should be able to describe it (currently might not)

2. **Sticker test scenario**:
   - User sends sticker
   - User replies to sticker with "what does this show?"
   - Bot should see the sticker

### Verification Commands

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Check if media is being collected
grep "Collected video:" logs/gryag.log
grep "Collected.*sticker:" logs/gryag.log

# Check if media is in context
grep "media items" logs/gryag.log
grep "Immediate context.*contains.*media" logs/gryag.log

# Check compact format
grep "historical_media" logs/gryag.log  # After Phase 1

# Check media descriptions
grep "\[Video\]" logs/gryag.log  # After Phase 2
grep "\[Sticker\]" logs/gryag.log  # After Phase 2
```

## Implementation Priority

### Immediate (This Week)
1. ✅ Create this plan document
2. ⚠️ Add debug logging (Phase 4) - helps diagnose in production
3. 🔴 Fix compact format historical media (Phase 1) - critical for compact mode users

### Short Term (Next Week)
4. 🟡 Improve media type descriptions (Phase 2) - better UX
5. 🟢 Add media type to cache (Phase 3) - optimization

### Success Criteria

- [ ] Bot can "see" videos in conversation history (not just current message)
- [ ] Bot can "see" stickers in conversation history
- [ ] Compact format includes actual media, not just text placeholders
- [ ] Debug logs show media flowing through context pipeline
- [ ] Media type descriptions are specific ([Video], [Sticker], not generic [Media])

## Rollback Plan

If Phase 1 causes issues:
1. Set `ENABLE_COMPACT_CONVERSATION_FORMAT=false` (disables compact mode)
2. Revert changes to `format_for_gemini_compact()`
3. Users fall back to JSON format (which already works with media)

## Token Impact

**Current state** (compact format):
- Historical messages: ~6 tokens/message (text only)
- Current message: ~6 tokens (text) + 258 per media item

**After Phase 1** (with historical media):
- Historical messages: ~6 tokens (text) + 258 per media item
- Impact: +258 tokens per historical message with media
- Example: 5 recent messages with 2 videos = +516 tokens
- Still well within 8000 token budget

**Mitigation**:
- Limit historical media to most recent N items
- Respect `GEMINI_MAX_MEDIA_ITEMS` global limit (28 default)
- Prefer current message media over historical

## Related Issues

- ✅ October 17: Fixed media token estimation (was counting as 0)
- ✅ October 19: Implemented reply chain context inclusion
- 🔴 This issue: Videos and stickers missing from context

## Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `app/services/context/multi_level_context.py` | Add historical_media to compact format output | HIGH |
| `app/handlers/chat.py` | Include historical_media in user_parts (compact) | HIGH |
| `app/services/conversation_formatter.py` | Fix describe_media() kind matching, use in format_history_compact() | MEDIUM |
| `app/handlers/chat.py` | Add debug logging for media | LOW |
| `tests/unit/test_conversation_formatter.py` | Add tests for video/sticker descriptions | MEDIUM |
| `tests/integration/test_media_context.py` | Add tests for historical media in compact format | HIGH |

## Next Steps

1. Review this plan with maintainer
2. Create feature branch: `fix/video-sticker-context`
3. Implement Phase 4 (debug logging) first for diagnostics
4. Implement Phase 1 (historical media in compact format)
5. Test manually with videos and stickers
6. Implement Phase 2 (media type descriptions)
7. Write tests
8. Deploy to staging
9. Monitor logs for media flow
10. Deploy to production

---

**Status**: READY FOR REVIEW  
**Assignee**: TBD  
**Estimated effort**: 4-6 hours implementation + 2 hours testing
