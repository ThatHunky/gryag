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
    Convert user_id to string for compact format.

    Previously truncated to last 6 digits, but this caused confusion.
    Now returns full ID for clarity and accurate user identification.

    Args:
        user_id: Telegram user ID (or None for bot)

    Returns:
        Full user ID as string, or empty string if None
    """
    if user_id is None:
        return ""
    return str(abs(user_id))


def build_collision_map(user_ids: list[int]) -> dict[int, str]:
    """
    Build mapping of user_id to display string.

    With full IDs, collisions are extremely rare (only if same user appears).
    This function primarily serves as a passthrough now, but maintains
    collision handling for compatibility.

    Args:
        user_ids: List of all user IDs in conversation

    Returns:
        Dict mapping full user_id to display string
    """
    result: dict[int, str] = {}

    # Simply convert each ID to string
    for uid in user_ids:
        result[uid] = str(abs(uid))

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

        if kind == "image" or "image" in mime.lower():
            # Check for stickers (WebP or WebM with image or video mime)
            if "webp" in mime.lower() or (
                "webm" in mime.lower() and "video" in mime.lower()
            ):
                descriptions.append("[Sticker]")
            else:
                descriptions.append("[Image]")
        elif kind == "video" or "video" in mime.lower():
            # Could add duration if available
            descriptions.append("[Video]")
        elif kind == "audio" or "audio" in mime.lower():
            descriptions.append("[Audio]")
        elif kind == "document":
            filename = item.get("filename", "file")
            # Truncate long filenames so overall token stays short
            # "[Document: " prefix = 11 chars, "]" suffix = 1 => allow filename <= 17
            if len(filename) > 17:
                filename = filename[:14] + "..."
            descriptions.append(f"[Document: {filename}]")
        else:
            descriptions.append(f"[{kind.title()}]")

    # Return only specific media descriptors; callers may prefix a general marker
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
                if value and re.fullmatch(r"-?\d+", value):
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
    reply_excerpt: str | None = None,
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
        reply_excerpt: Optional excerpt from the replied message
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
    if (reply_to_user_id is not None and reply_to_username) or (
        reply_to_user_id is None and reply_to_username
    ):
        reply_username = sanitize_username(reply_to_username)
        if user_id_map and reply_to_user_id in user_id_map:
            reply_short_id = user_id_map[reply_to_user_id]
        else:
            reply_short_id = (
                parse_user_id_short(reply_to_user_id)
                if reply_to_user_id is not None
                else ""
            )

        if reply_short_id:
            speaker = f"{speaker} → {reply_username}#{reply_short_id}"
        else:
            # Replying to bot or unknown target
            speaker = f"{speaker} → gryag"

    # Combine media description and text
    content_parts = []

    # Add reply excerpt if present (inline context)
    if reply_excerpt:
        # Truncate and sanitize reply excerpt
        clean_excerpt = reply_excerpt.replace("\n", " ").strip()
        if len(clean_excerpt) > 120:
            clean_excerpt = clean_excerpt[:117] + "..."
        if reply_to_username:
            excerpt_label = (
                f"[↩︎ {sanitize_username(reply_to_username)}: {clean_excerpt}]"
            )
        else:
            excerpt_label = f"[↩︎ {clean_excerpt}]"
        content_parts.append(excerpt_label)

    if media_description:
        # Prefix with a general media marker for readability in compact history
        if not media_description.startswith("[Media]"):
            content_parts.append(f"[Media] {media_description}")
        else:
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

        # Count media parts and describe them
        media_parts_list = [p for p in parts if "inline_data" in p or "file_data" in p]
        media_description = ""
        if media_parts_list:
            # Build media_items list with kind inferred from mime for describe_media()
            media_items = []
            for part in media_parts_list:
                if "inline_data" in part:
                    mime = part["inline_data"].get("mime_type", "")
                    # Infer kind from mime type
                    if "image" in mime:
                        kind = "image"
                    elif "video" in mime:
                        kind = "video"
                    elif "audio" in mime:
                        kind = "audio"
                    else:
                        kind = "media"
                    media_items.append({"kind": kind, "mime": mime})
                elif "file_data" in part:
                    # File URIs are typically videos
                    media_items.append({"kind": "video", "mime": "video/mp4"})

            media_description = describe_media(media_items)

        # Build formatted line
        is_bot = role == "model"
        user_id = metadata.get("user_id")
        username = metadata.get("name") or metadata.get("username") or "User"
        reply_to_user_id = metadata.get("reply_to_user_id")
        reply_to_username = metadata.get("reply_to_name") or metadata.get(
            "reply_to_username"
        )
        # Get reply excerpt from metadata
        reply_excerpt = metadata.get("reply_excerpt")

        formatted = format_message_compact(
            user_id=user_id,
            username=username,
            text=text,
            media_description=media_description,
            reply_to_user_id=reply_to_user_id,
            reply_to_username=reply_to_username,
            reply_excerpt=reply_excerpt,
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
