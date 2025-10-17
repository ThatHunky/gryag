"""
Compact plain text conversation formatter for reduced token usage.

Converts verbose JSON-based Gemini API format to efficient plain text:
- Basic: `Username#UserID: Message text`
- Replies: `Bob#111222 → Alice#987654: Reply text`
- Media: `Alice#987654: [Image: description]`

Expected token savings: 70-80% compared to JSON format.
"""

from __future__ import annotations

import re
from typing import Any


def parse_user_id_short(user_id: int | None) -> str:
    """
    Get last 6 digits of user_id for compact format.

    Args:
        user_id: Telegram user ID (or None for bot)

    Returns:
        Last 6 digits as string, or empty string if None
    """
    if user_id is None:
        return ""
    return str(abs(user_id))[-6:]


def build_collision_map(user_ids: list[int]) -> dict[int, str]:
    """
    Build mapping of user_id to short_id, handling collisions.

    If two users have the same last 6 digits, adds a suffix (a, b, c...).

    Args:
        user_ids: List of all user IDs in conversation

    Returns:
        Dict mapping full user_id to display short_id
    """
    short_to_full: dict[str, list[int]] = {}

    # Group by short ID
    for uid in user_ids:
        short = parse_user_id_short(uid)
        if short:
            short_to_full.setdefault(short, []).append(uid)

    # Build mapping with collision handling
    result: dict[int, str] = {}
    for short, full_ids in short_to_full.items():
        if len(full_ids) == 1:
            # No collision
            result[full_ids[0]] = short
        else:
            # Collision: add suffix
            for idx, uid in enumerate(sorted(full_ids)):
                suffix = chr(ord("a") + idx)  # a, b, c...
                result[uid] = f"{short}{suffix}"

    return result


def sanitize_username(name: str | None, max_length: int = 30) -> str:
    """
    Sanitize and truncate username for compact format.

    Args:
        name: Display name or username
        max_length: Maximum characters to keep

    Returns:
        Sanitized name suitable for compact format
    """
    if not name:
        return "Unknown"

    # Remove problematic characters
    sanitized = (
        name.replace("\n", " ")
        .replace(":", "")
        .replace("→", "")
        .replace("[", "")
        .replace("]", "")
        .strip()
    )

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[: max_length - 2] + ".."

    return sanitized or "User"


def describe_media(media_items: list[dict[str, Any]]) -> str:
    """
    Convert media objects to compact text descriptions.

    Args:
        media_items: List of media dictionaries with 'kind' and 'mime' fields

    Returns:
        Compact media description like "[Image]" or "[Video 1:23]"
    """
    if not media_items:
        return ""

    descriptions = []

    for item in media_items:
        kind = item.get("kind", "media")
        mime = item.get("mime", "")

        if kind == "photo" or "image" in mime.lower():
            descriptions.append("[Image]")
        elif kind == "video" or "video" in mime.lower():
            # Could add duration if available
            descriptions.append("[Video]")
        elif kind == "audio" or "audio" in mime.lower():
            descriptions.append("[Audio]")
        elif kind == "document":
            filename = item.get("filename", "file")
            # Truncate long filenames
            if len(filename) > 20:
                filename = filename[:17] + "..."
            descriptions.append(f"[Document: {filename}]")
        else:
            descriptions.append(f"[{kind.title()}]")

    return " ".join(descriptions)


def extract_metadata_from_parts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract metadata from message parts (first text part with [meta] prefix).

    Args:
        parts: List of message parts from Gemini format

    Returns:
        Dictionary with extracted metadata fields
    """
    metadata: dict[str, Any] = {}

    for part in parts:
        if not isinstance(part, dict):
            continue

        text = part.get("text", "")
        if text.startswith("[meta]"):
            # Parse key=value pairs
            meta_text = text[6:].strip()  # Remove "[meta]" prefix

            # Simple regex-based parsing
            for match in re.finditer(r'(\w+)=(?:"([^"]*)"|(\S+))', meta_text):
                key = match.group(1)
                value = match.group(2) or match.group(3)

                # Convert numeric values
                if value and value.isdigit():
                    metadata[key] = int(value)
                else:
                    metadata[key] = value

            break  # Only process first metadata block

    return metadata


def extract_text_from_parts(parts: list[dict[str, Any]], skip_meta: bool = True) -> str:
    """
    Extract plain text from message parts, optionally skipping metadata.

    Args:
        parts: List of message parts from Gemini format
        skip_meta: Whether to skip [meta] blocks

    Returns:
        Combined text content
    """
    texts = []

    for part in parts:
        if not isinstance(part, dict):
            continue

        text = part.get("text", "")
        if text:
            if skip_meta and text.startswith("[meta]"):
                continue
            texts.append(text)

    return " ".join(texts).strip()


def format_message_compact(
    user_id: int | None,
    username: str,
    text: str,
    media_description: str = "",
    reply_to_user_id: int | None = None,
    reply_to_username: str | None = None,
    user_id_map: dict[int, str] | None = None,
    is_bot: bool = False,
) -> str:
    """
    Format a single message in compact plain text format.

    Args:
        user_id: Telegram user ID (None for bot)
        username: Display name
        text: Message text content
        media_description: Optional media description like "[Image]"
        reply_to_user_id: User ID being replied to
        reply_to_username: Username being replied to
        user_id_map: Optional collision map for short IDs
        is_bot: Whether this is a bot message

    Returns:
        Formatted message line like "Alice#987654: Hello world"
    """
    # Sanitize username
    clean_username = sanitize_username(username)

    # Build speaker identifier
    if is_bot:
        speaker = "gryag"
    else:
        if user_id_map and user_id in user_id_map:
            short_id = user_id_map[user_id]
        else:
            short_id = parse_user_id_short(user_id)
        speaker = f"{clean_username}#{short_id}"

    # Add reply chain if present
    if reply_to_user_id is not None and reply_to_username:
        reply_username = sanitize_username(reply_to_username)
        if user_id_map and reply_to_user_id in user_id_map:
            reply_short_id = user_id_map[reply_to_user_id]
        else:
            reply_short_id = parse_user_id_short(reply_to_user_id)

        if reply_short_id:
            speaker = f"{speaker} → {reply_username}#{reply_short_id}"
        else:
            # Replying to bot
            speaker = f"{speaker} → gryag"

    # Combine media description and text
    content_parts = []
    if media_description:
        content_parts.append(media_description)
    if text:
        content_parts.append(text)

    content = " ".join(content_parts) if content_parts else "(no content)"

    return f"{speaker}: {content}"


def format_history_compact(
    messages: list[dict[str, Any]],
    bot_name: str = "gryag",
) -> str:
    """
    Format conversation history as plain text.

    Args:
        messages: List of message dicts in Gemini format with 'role' and 'parts'
        bot_name: Name to use for bot messages (default "gryag")

    Returns:
        Plain text conversation with one message per line
    """
    if not messages:
        return ""

    # Extract all user IDs for collision detection
    user_ids: list[int] = []
    for msg in messages:
        parts = msg.get("parts", [])
        metadata = extract_metadata_from_parts(parts)
        user_id = metadata.get("user_id")
        if user_id and isinstance(user_id, int):
            user_ids.append(user_id)

    # Build collision map
    user_id_map = build_collision_map(user_ids) if user_ids else {}

    # Format each message
    lines = []
    for msg in messages:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])

        # Extract metadata
        metadata = extract_metadata_from_parts(parts)

        # Extract text (skip metadata blocks)
        text = extract_text_from_parts(parts, skip_meta=True)

        # Count media parts
        media_parts = [p for p in parts if "inline_data" in p or "file_uri" in p]
        media_description = ""
        if media_parts:
            # Simple count-based description
            if len(media_parts) == 1:
                media_description = "[Media]"
            else:
                media_description = f"[{len(media_parts)} media items]"

        # Build formatted line
        is_bot = role == "model"
        user_id = metadata.get("user_id")
        username = metadata.get("name") or metadata.get("username") or "User"
        reply_to_user_id = metadata.get("reply_to_user_id")
        reply_to_username = metadata.get("reply_to_name") or metadata.get(
            "reply_to_username"
        )

        formatted = format_message_compact(
            user_id=user_id,
            username=username,
            text=text,
            media_description=media_description,
            reply_to_user_id=reply_to_user_id,
            reply_to_username=reply_to_username,
            user_id_map=user_id_map,
            is_bot=is_bot,
        )

        lines.append(formatted)

    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text (rough approximation).

    Uses word count * 1.3 as a simple heuristic.
    For better accuracy, use actual tokenizer.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Simple word-based estimation
    # Gemini tokens are roughly 1.3 words per token
    words = len(text.split())
    return int(words * 1.3)
