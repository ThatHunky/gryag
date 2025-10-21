# Plan: Always Include Replied (Chain) Message As Context

Problem: When a user replies to a message in Telegram (a chain/quote), gryag often ignores the replied message’s content. The model only sees minimal metadata (reply ids) and, in compact mode, only the arrow (A → B) without the original text. As a result, answers miss the referenced content.

Goal: Ensure the model reliably sees the replied-to message content (text and, when useful, media) for every addressed turn, across both JSON and Compact conversation formats, without showing extra noise to end‑users.

Out of scope: UI changes in Telegram; persistence schema changes (we already store reply metadata and external IDs).

## Current Behavior (Root Cause)

- JSON path (`app/handlers/chat.py`):
  - `reply_context_for_history` is only set when the replied message has media. Text‑only replies are not injected into history.
  - `_build_clean_user_parts()` only uses `fallback_text` (reply text) when the user’s current message has no text or media. Thus, the reply text is dropped whenever the user types anything.
  - Only minimal reply metadata is included via `[meta]` and `reply_excerpt`, which the model may underweight.

- Compact path (`ENABLE_MULTI_LEVEL_CONTEXT && ENABLE_COMPACT_CONVERSATION_FORMAT`):
  - `format_message_compact()` is called for the current user message without `reply_to_*` info and without the `reply_excerpt` content.
  - `format_history_compact()` doesn’t render `reply_excerpt` from metadata; it only shows the arrow `A → B`, losing the quoted content.

- Result: The model frequently lacks the replied message’s text unless it had media, or unless the user sends an empty message.

## Design Principles

- Always include a short textual summary of the replied message when present.
- Keep the addition compact, capped, and positionally consistent (before the user’s new text).
- Prefer chronological injection into history; fallback to inline “reply context” in the current turn.
- Never expose internal metadata or raw IDs to end users (cleaning remains intact).
- Respect token budgets and media caps.

## Proposed Changes

1) JSON conversation path (no compact format)
   - Build `reply_context` for every reply (current code already does) and set `reply_context_for_history = reply_context` even when there is only text.
   - If the replied message is not already present in `history`, inject a synthetic user message at the beginning with:
     - first part: `format_metadata({chat_id, message_id, user_id/name})`
     - second part: replied text (trim to 200–300 chars)
     - followed by replied media parts if present (respect a small cap, e.g. 2)
   - Additionally, prepend to the current `user_parts` a short inline marker:
     - `{ "text": "[↩︎ Відповідь на: <excerpt>]" }` placed right after the metadata part
     - This guarantees the model always sees a short reference even if history gets trimmed later.

2) Compact format path
   - When constructing `current_message_line`, pass `reply_to_user_id` and `reply_to_username` (from `message.reply_to_message`) to `format_message_compact()`.
   - Prepend `text` with a short inline snippet if available: `"[↩︎ <reply_username>: <excerpt>] " + text` (excerpt ~120–160 chars, sanitized).
   - Optionally, update `format_history_compact()` to render `reply_excerpt` when present in metadata so older lines also show the quoted snippet (kept concise).

3) Token and media controls
   - `reply_excerpt_max_chars = 200` default (setting if needed later).
   - Do not duplicate a large amount of media: inject at most 2 media parts from the replied message into history; do not mix into current `user_parts` to keep the current turn small.
   - Maintain existing trimming of current‑message media via `GEMINI_MAX_MEDIA_ITEMS_CURRENT`.

4) Telemetry
   - Increment counters:
     - `context.reply_included_text` when a reply excerpt is added.
     - `context.reply_included_media` when media from reply is injected.
   - DEBUG log the first 80 chars of the injected excerpt and the reason path (history vs inline).

5) Backward compatibility & safety
   - Users never see these inline snippets because `_clean_response_text()` strips `[meta]` and we do not echo user parts back. Telegram output is unaffected.
   - If the replied message already exists in `history`, skip synthetic injection to avoid duplication (check via `message_id` metadata as done now).
   - Works whether multi‑level context is enabled or not.

## Implementation Steps

1. chat.py — JSON path
   - Set `reply_context_for_history = reply_context` unconditionally when a reply exists.
   - Always add an inline `reply-excerpt` user part right after metadata when `reply_context.text` exists.
   - Keep existing media collection for replies; inject into history when missing.

2. chat.py — Compact path
   - When building `current_message_line`, derive:
     - `reply_to_user_id`, `reply_to_username` from `message.reply_to_message`.
     - `reply_excerpt = _extract_text(message.reply_to_message)` (fallback to media summary via `_summarize_media(collect_media_parts())` only if cheap/safe).
   - Prepend `"[↩︎ <reply_username>: <excerpt>] "` to `text` before calling `format_message_compact()`.

3. conversation_formatter.py (optional but recommended)
   - In `format_history_compact()`, read `reply_excerpt` from metadata and, if present, prepend it to the text before formatting. This makes compact history self‑contained.

4. Settings (optional)
   - Add `INCLUDE_REPLY_EXCERPT=true` and `REPLY_EXCERPT_MAX_CHARS=200` (defaults baked‑in even if setting absent).

5. Tests
   - Unit: `tests/unit/test_reply_context.py`
     - JSON path: verify `user_parts` contains the inline `[↩︎ …]` part when replying with text.
     - Compact path: verify `current_message_line` contains the `[↩︎ …]` snippet and arrow `→`.
     - History injection: verify synthetic reply message is added when not present.
   - Integration: extend compact format tests to include a reply chain with missing prior message and confirm Gemini payload includes the snippet.

6. Verification (manual)
   - Send: reply to an old message (>5 min) with “що таке ROE?” and observe logs:
     - `Injected reply context into history` or `Inline reply-excerpt added`.
     - Payload preview shows the `[↩︎ …]` line.

## Acceptance Criteria

- For any addressed message that is a reply, Gemini input contains:
  - A short inline reply snippet in the current turn, and
  - The original replied message content in `history` if it wasn’t already there.
- Compact format shows both the `→` chain and a short `[↩︎ …]` snippet.
- No metadata leaks to end users; responses remain clean.
- Token growth stays bounded (< +220 tokens per reply on average).

## Rollback Plan

- Feature‑flag the behavior via `INCLUDE_REPLY_EXCERPT`; if issues appear, disable the flag.
- Revert synthetic history injection first (keep inline snippet), then revert inline snippet if needed.

## File Touch Points

- app/handlers/chat.py — set/unset `reply_context_for_history`, add inline snippet, pass reply info to compact builder.
- app/services/conversation_formatter.py — (optional) render `reply_excerpt` from metadata in compact history.
- app/config.py — (optional) add settings with safe defaults.
- tests/unit/* — new tests described above.

## Risks & Mitigations

- Token bloat in long reply chains → cap excerpt, prefer history injection over duplicating large media.
- Duplicate injection → keep “already‑in‑history” check via `message_id` search in metadata line.
- Non‑text replies (stickers, GIFs) → summarize as `[Sticker]`/`[GIF]` or omit; do not block.

---

Owner: Context/Conversation subsystem
ETA: 0.5–1 day implementation + 0.5 day tests
Release: behind `INCLUDE_REPLY_EXCERPT` feature flag (default: on)

