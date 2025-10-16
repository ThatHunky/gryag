"""
Token optimization utilities for efficient context management.

Provides tools to reduce token usage while maintaining response quality:
- Compact metadata formatting
- Icon-based media summaries
- Accurate token counting
- Content deduplication
- Dynamic budget allocation
"""

from __future__ import annotations

import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)

# Media type icons for compact summaries
MEDIA_ICONS = {
    "image": "📷",
    "photo": "📷",
    "video": "🎬",
    "audio": "🎵",
    "voice": "🎵",
    "youtube": "🎞️",
    "document": "📄",
    "file": "📎",
}


def format_metadata_compact(meta: dict[str, Any]) -> str:
    """
    Format metadata in compact form.

    Instead of: [meta] chat_id=123 user_id=456 name="Alice" username="alice"
    Returns: @alice:

    Args:
        meta: Metadata dictionary

    Returns:
        Compact metadata string (just username/name)
    """
    username = meta.get("username", "").lstrip("@")
    name = meta.get("name", "")

    if username:
        return f"@{username}:"
    elif name:
        # Shorten long names
        if len(name) > 20:
            name = name[:17] + "..."
        return f"{name}:"
    return ""


def summarize_media_compact(media_items: list[dict[str, Any]] | None) -> str | None:
    """
    Create compact icon-based media summary.

    Instead of: "Прикріплення: 2 фото, 1 відео, 1 YouTube відео"
    Returns: "📷×2 🎬 🎞️"

    Args:
        media_items: List of media item dicts with 'kind' and optionally 'file_uri'

    Returns:
        Compact media summary or None if no media
    """
    if not media_items:
        return None

    counts: dict[str, int] = {}

    for item in media_items:
        # Detect YouTube videos
        if "file_uri" in item and "youtube.com" in item.get("file_uri", "").lower():
            kind = "youtube"
        else:
            kind = item.get("kind", "file")

        counts[kind] = counts.get(kind, 0) + 1

    if not counts:
        return None

    # Build compact summary
    parts = []
    for kind, count in counts.items():
        icon = MEDIA_ICONS.get(kind, "📎")
        if count > 1:
            parts.append(f"{icon}×{count}")
        else:
            parts.append(icon)

    return " ".join(parts)


def estimate_tokens_accurate(text: str) -> int:
    """
    Estimate token count more accurately than simple word count.

    Uses character-based heuristic that's closer to actual tokenization:
    - English: ~4 chars per token
    - Ukrainian: ~5 chars per token (Cyrillic is less efficient)
    - Code/symbols: ~3 chars per token

    For production, consider using tiktoken:
    ```python
    import tiktoken
    encoder = tiktoken.get_encoding("cl100k_base")
    return len(encoder.encode(text))
    ```

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Count Cyrillic characters (Ukrainian/Russian)
    cyrillic_chars = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    total_chars = len(text)

    # Calculate weighted average
    if cyrillic_chars > total_chars * 0.5:
        # Mostly Cyrillic
        chars_per_token = 5.0
    elif cyrillic_chars > 0:
        # Mixed
        chars_per_token = 4.5
    else:
        # Latin/English
        chars_per_token = 4.0

    # Adjust for code-like content (lots of symbols)
    symbol_ratio = sum(1 for c in text if not c.isalnum() and not c.isspace()) / max(
        total_chars, 1
    )
    if symbol_ratio > 0.2:
        chars_per_token = 3.5

    return max(1, int(total_chars / chars_per_token))


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """
    Estimate total tokens in a message dict.

    Handles both text and media parts.

    Args:
        message: Message dict with 'parts' list

    Returns:
        Estimated token count
    """
    total = 0

    parts = message.get("parts", [])
    for part in parts:
        if isinstance(part, dict):
            # Text part
            if "text" in part:
                total += estimate_tokens_accurate(part["text"])

            # Media parts (rough estimate)
            elif "inline_data" in part or "file_data" in part:
                # Images are typically ~250 tokens in Gemini
                # Videos can be 500-1000 tokens
                mime = part.get("inline_data", {}).get("mime_type", "") or part.get(
                    "file_data", {}
                ).get("mime_type", "")
                if "image" in mime:
                    total += 250
                elif "video" in mime:
                    total += 500
                elif "audio" in mime:
                    total += 300
                else:
                    total += 100  # Default

    return total


def deduplicate_messages(
    messages: list[dict[str, Any]],
    similarity_threshold: float = 0.85,
) -> list[dict[str, Any]]:
    """
    Remove semantically duplicate messages.

    Uses Jaccard similarity on words to detect duplicates.
    Keeps the first occurrence of each message.

    Args:
        messages: List of message dicts
        similarity_threshold: Threshold for considering messages duplicates (0.0-1.0)

    Returns:
        Deduplicated list of messages
    """
    if not messages or len(messages) < 2:
        return messages

    seen_texts: list[set[str]] = []
    deduplicated = []

    for msg in messages:
        # Extract text from message
        text = _extract_text_from_message(msg)
        if not text:
            deduplicated.append(msg)
            continue

        # Normalize text
        text_norm = " ".join(text.lower().split())
        if not text_norm:
            deduplicated.append(msg)
            continue

        words = set(text_norm.split())

        # Check similarity with seen texts
        is_duplicate = False
        for seen_words in seen_texts:
            if not words or not seen_words:
                continue

            # Jaccard similarity
            intersection = len(words & seen_words)
            union = len(words | seen_words)
            similarity = intersection / union if union > 0 else 0.0

            if similarity >= similarity_threshold:
                is_duplicate = True
                LOGGER.debug(
                    f"Deduplicated message (similarity={similarity:.2f}): {text_norm[:50]}..."
                )
                break

        if not is_duplicate:
            deduplicated.append(msg)
            seen_texts.append(words)

    removed = len(messages) - len(deduplicated)
    if removed > 0:
        LOGGER.info(f"Removed {removed} duplicate message(s) from context")

    return deduplicated


def _extract_text_from_message(message: dict[str, Any]) -> str:
    """Extract all text from a message's parts."""
    texts = []
    for part in message.get("parts", []):
        if isinstance(part, dict) and "text" in part:
            texts.append(part["text"])
    return " ".join(texts)


def calculate_dynamic_budget(
    query_text: str,
    recent_message_count: int,
    has_profile_facts: bool,
    has_episodes: bool,
    base_budgets: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Calculate optimal budget allocation based on conversation context.

    Adjusts from base allocations based on:
    - Conversation activity level
    - Query type (lookup, follow-up, etc.)
    - Available context sources

    Args:
        query_text: Current user query
        recent_message_count: Number of messages in last 5 minutes
        has_profile_facts: Whether user has profile facts
        has_episodes: Whether episodes exist
        base_budgets: Base budget percentages (defaults to standard allocation)

    Returns:
        Dict of budget percentages (must sum to 1.0)
    """
    # Default base allocations
    if base_budgets is None:
        budgets = {
            "immediate": 0.20,
            "recent": 0.30,
            "relevant": 0.25,
            "background": 0.15,
            "episodic": 0.10,
        }
    else:
        budgets = base_budgets.copy()

    query_lower = query_text.lower()

    # Detect conversation characteristics
    is_active = recent_message_count > 3
    is_lookup = any(
        word in query_lower for word in ["що", "коли", "хто", "де", "what", "when"]
    )
    is_followup = len(query_text.split()) < 5

    # Adjust for active conversation
    if is_active:
        # Need more recent context, less episodic
        budgets["recent"] += 0.10
        budgets["episodic"] -= 0.05
        budgets["relevant"] -= 0.05

    # Adjust for lookup queries
    if is_lookup:
        # Need more search results, less recent chat
        budgets["relevant"] += 0.15
        budgets["recent"] -= 0.10
        budgets["episodic"] -= 0.05

    # Adjust for sparse profiles
    if not has_profile_facts:
        # Reduce background budget, redistribute to recent
        budgets["background"] = 0.05
        budgets["recent"] += 0.10

    # Adjust if no episodes exist
    if not has_episodes:
        # Redistribute episodic budget
        freed = budgets["episodic"]
        budgets["episodic"] = 0.0
        budgets["relevant"] += freed * 0.6
        budgets["recent"] += freed * 0.4

    # Adjust for brief follow-ups
    if is_followup:
        # Focus on immediate context
        budgets["immediate"] += 0.15
        budgets["relevant"] -= 0.10
        budgets["episodic"] = max(0.0, budgets["episodic"] - 0.05)

    # Normalize to ensure sum = 1.0
    total = sum(budgets.values())
    if total > 0:
        budgets = {k: v / total for k, v in budgets.items()}

    LOGGER.debug(
        f"Dynamic budget allocation: immediate={budgets['immediate']:.2f}, "
        f"recent={budgets['recent']:.2f}, relevant={budgets['relevant']:.2f}, "
        f"background={budgets['background']:.2f}, episodic={budgets['episodic']:.2f}"
    )

    return budgets


def summarize_old_messages(
    messages: list[dict[str, Any]],
    threshold_index: int = 20,
) -> list[dict[str, Any]]:
    """
    Compress old messages beyond threshold into summary.

    Instead of including all old messages, creates a compact summary like:
    "[Раніше: 15 повідомлень, 12 відповідей]"

    Args:
        messages: List of message dicts
        threshold_index: Index beyond which to summarize

    Returns:
        Summarized message list (summary + recent messages)
    """
    if len(messages) <= threshold_index:
        return messages

    # Split into old and recent
    old = messages[:-threshold_index]
    recent = messages[-threshold_index:]

    # Count message types in old section
    user_count = sum(1 for m in old if m.get("role") == "user")
    model_count = sum(1 for m in old if m.get("role") == "model")

    if user_count == 0 and model_count == 0:
        return recent

    # Create compact summary
    summary_text = f"[Раніше: {user_count} повідомлень, {model_count} відповідей]"

    summary_entry = {"role": "user", "parts": [{"text": summary_text}]}

    LOGGER.debug(
        f"Summarized {len(old)} old messages into compact summary "
        f"({user_count} user, {model_count} model)"
    )

    return [summary_entry] + recent


def prune_low_relevance(
    snippets: list[dict[str, Any]],
    min_score: float = 0.4,
) -> list[dict[str, Any]]:
    """
    Remove low-relevance search results.

    Args:
        snippets: List of search result dicts with 'score' field
        min_score: Minimum relevance score to keep

    Returns:
        Filtered list of snippets
    """
    pruned = [s for s in snippets if s.get("score", 0.0) >= min_score]

    removed = len(snippets) - len(pruned)
    if removed > 0:
        LOGGER.debug(f"Pruned {removed} low-relevance snippet(s) (score < {min_score})")

    return pruned


def limit_consecutive_messages(
    messages: list[dict[str, Any]],
    max_consecutive: int = 3,
) -> list[dict[str, Any]]:
    """
    Limit consecutive messages from the same role.

    Prevents long runs of user messages or bot messages from taking up too much context.

    Args:
        messages: List of message dicts with 'role' field
        max_consecutive: Maximum consecutive messages from same role

    Returns:
        Filtered list of messages
    """
    if len(messages) <= max_consecutive:
        return messages

    filtered = []
    consecutive_count = 0
    prev_role = None

    for msg in messages:
        role = msg.get("role")

        if role == prev_role:
            consecutive_count += 1
        else:
            consecutive_count = 1
            prev_role = role

        # Keep message if under limit
        if consecutive_count <= max_consecutive:
            filtered.append(msg)
        else:
            LOGGER.debug(
                f"Skipped consecutive message #{consecutive_count} from role={role}"
            )

    removed = len(messages) - len(filtered)
    if removed > 0:
        LOGGER.debug(
            f"Removed {removed} consecutive message(s) (max={max_consecutive})"
        )

    return filtered
