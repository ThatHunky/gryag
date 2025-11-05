from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from html import escape

from app.config import Settings
from app.persona import SYSTEM_PERSONA
from app.services.calculator import calculator_tool, CALCULATOR_TOOL_DEFINITION
from app.services.weather import weather_tool, WEATHER_TOOL_DEFINITION
from app.services.currency import currency_tool, CURRENCY_TOOL_DEFINITION
from app.services.polls import polls_tool, POLLS_TOOL_DEFINITION
from app.services.search_tool import search_web_tool, SEARCH_WEB_TOOL_DEFINITION
from app.services.image_generation import (
    ImageGenerationService,
    GENERATE_IMAGE_TOOL_DEFINITION,
    EDIT_IMAGE_TOOL_DEFINITION,
    QuotaExceededError,
    ImageGenerationError,
)
from app.services.system_prompt_manager import SystemPromptManager
from app.services.tools import (
    remember_memory_tool,
    recall_memories_tool,
    forget_memory_tool,
    forget_all_memories_tool,
    set_pronouns_tool,
    REMEMBER_MEMORY_DEFINITION,
    RECALL_MEMORIES_DEFINITION,
    FORGET_MEMORY_DEFINITION,
    FORGET_ALL_MEMORIES_DEFINITION,
    SET_PRONOUNS_DEFINITION,
)
from app.services.tools.moderation_tools import (
    build_tool_definitions as build_moderation_tool_definitions,
    build_tool_callbacks as build_moderation_tool_callbacks,
)
from app.handlers.chat_tools import (
    build_tool_definitions as build_tool_definitions_registry,
    build_tool_callbacks as build_tool_callbacks_registry,
    create_search_messages_tool,
)
from app.services.context_store import (
    ContextStore,
    MessageSender,
    TurnSender,  # Backward compatibility alias
    format_metadata,
    format_speaker_header,
)
from app.services.gemini import GeminiClient, GeminiError, GeminiContentBlockedError
from app.services.media import collect_media_parts
from app.services.redis_types import RedisLike
from app.services.triggers import addressed_to_bot
from app.services.user_profile import UserProfileStore
from app.repositories.memory_repository import MemoryRepository
from app.services import telemetry
from app.services.context import (
    MultiLevelContextManager,
    HybridSearchEngine,
    EpisodicMemoryStore,
)
from app.services.telegram_service import TelegramService
from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine
from app.services.rate_limiter import RateLimiter
from app.handlers.bot_learning_integration import (
    track_bot_interaction,
    process_potential_reaction,
    estimate_token_count,
)
from app.services.typing import typing_indicator
from app.services.conversation_formatter import sanitize_placeholder_text

router = Router()

# Default responses (will be overridden by PersonaLoader templates if enabled)
ERROR_FALLBACK = "Ґеміні знову тупить. Спробуй пізніше."
EMPTY_REPLY = "Я не вкурив, що ти хочеш. Розпиши конкретніше — і я вже кручусь."
BANNED_REPLY = "Ти для гряга в бані. Йди погуляй."
THROTTLED_REPLY = "Занадто багато повідомлень. Почекай {minutes} хв."


LOGGER = logging.getLogger(__name__)


def _safe_html_payload(
    text: str,
    *,
    wrap: tuple[str, str] | None = None,
    limit: int = 4096,
    ellipsis: bool = False,
    already_html: bool = False,
) -> str:
    """
    Escape text for Telegram HTML mode while respecting the length limit.

    Optionally wraps the escaped text and appends an ellipsis when truncation
    is required.

    Args:
        text: Text to format
        wrap: Optional prefix/suffix tuple to wrap the text
        limit: Maximum length for the payload
        ellipsis: Whether to append "..." when truncating
        already_html: If True, skip HTML escaping (text is already HTML-formatted)
    """
    prefix, suffix = wrap or ("", "")
    available = max(limit - len(prefix) - len(suffix), 0)
    truncated = text[:available]
    ellipsis_needed = ellipsis and len(text) > len(truncated)
    ellipsis_str = "..." if ellipsis_needed and available >= 3 else ""
    if ellipsis_str and len(truncated) >= len(ellipsis_str):
        truncated = truncated[: len(truncated) - len(ellipsis_str)]

    while True:
        if already_html:
            # Text is already HTML-formatted, just truncate if needed
            escaped = truncated
        else:
            escaped = escape(truncated)
            # Telegram HTML mode handles newlines automatically - no need to convert
        candidate_body = escaped + ellipsis_str
        candidate = f"{prefix}{candidate_body}{suffix}"
        if len(candidate) <= limit:
            return candidate
        if not truncated:
            fallback_body = ellipsis_str if ellipsis_str else ""
            fallback = f"{prefix}{fallback_body}{suffix}"
            return fallback[:limit]
        truncated = truncated[:-1]


def _get_response(
    key: str,
    persona_loader: Any | None,
    default: str,
    **kwargs: Any,
) -> str:
    """Get response from PersonaLoader if available, otherwise use default."""
    if persona_loader is not None:
        try:
            persona = getattr(persona_loader, "persona", None)
            bot_name = getattr(persona, "name", None) if persona is not None else None
            bot_display = (
                getattr(persona, "display_name", None) if persona is not None else None
            )
            if bot_name and "bot_name" not in kwargs:
                kwargs["bot_name"] = bot_name
            if bot_display and "bot_display_name" not in kwargs:
                kwargs["bot_display_name"] = bot_display
        except Exception:
            LOGGER.exception(
                "Failed to inject persona variables into response template"
            )

        return persona_loader.get_response(key, **kwargs)

    if kwargs:
        try:
            return default.format(**kwargs)
        except KeyError:
            LOGGER.warning(
                "Missing variable while formatting default response for key=%s", key
            )
    return default


_RECENT_CONTEXT: dict[tuple[int, int | None], deque[dict[str, Any]]] = {}
_CONTEXT_TTL_SECONDS = 120

_META_PREFIX_RE = re.compile(r"^\s*\[meta(?:\s+[^\]]*)?\]\s*", re.IGNORECASE)
_META_ANYWHERE_RE = re.compile(r"\[meta(?:\s+[^\]]*)?\]", re.IGNORECASE)
_TECHNICAL_INFO_RE = re.compile(
    r"\b(?:chat_id|user_id|message_id|thread_id|bot_id|conversation_id|request_id|turn_id)=[^\s\]]+",
    re.IGNORECASE,
)

_IMAGE_ACTION_KEYWORDS = (
    "згенеруй",
    "генеруй",
    "створи",
    "намалюй",
    "намалю",
    "намалювати",
    "зроби",
    "create",
    "make",
    "draw",
    "paint",
    "render",
    "generate",
)

_IMAGE_NOUN_KEYWORDS = (
    "картинку",
    "картинка",
    "зображення",
    "фото",
    "фотку",
    "малюнок",
    "постер",
    "арт",
    "art",
    "image",
    "picture",
    "photo",
)

_IMAGE_EDIT_KEYWORDS = (
    "редагуй",
    "відредагуй",
    "перероби",
    "перемалюй",
    "виправ",
    "зміни",
    "обнови",
    "edit",
    "remix",
    "adjust",
    "fix",
)


def _normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    normalized = username.strip().lstrip("@")
    return normalized.lower() if normalized else None


def _looks_like_image_edit_request(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(
        phrase in lowered
        for phrase in ("відредагуй фото", "перероби зображення", "edit photo")
    ):
        return True
    action_hit = any(keyword in lowered for keyword in _IMAGE_EDIT_KEYWORDS)
    noun_hit = any(keyword in lowered for keyword in _IMAGE_NOUN_KEYWORDS)
    return action_hit and noun_hit


def _looks_like_image_generation_request(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    action_hit = any(keyword in lowered for keyword in _IMAGE_ACTION_KEYWORDS)
    noun_hit = any(keyword in lowered for keyword in _IMAGE_NOUN_KEYWORDS)

    # Allow action-only if it's a strong generation verb (not just "create" or "make")
    strong_generation_keywords = (
        "згенеруй",
        "генеруй",
        "намалюй",
        "намалю",
        "намалювати",
        "generate",
        "draw",
        "paint",
        "render",
    )
    strong_action_hit = any(
        keyword in lowered for keyword in strong_generation_keywords
    )

    # Match if: (action + noun) OR (strong action alone)
    return (action_hit and noun_hit) or strong_action_hit


def _extract_text(message: Message | None) -> str | None:
    if message is None:
        return None
    text = message.text or message.caption
    if not text:
        return None
    cleaned = " ".join(text.strip().split())
    return cleaned if cleaned else None


def _summarize_media(media_items: list[dict[str, Any]] | None) -> str | None:
    """Create a Ukrainian summary of attached media."""
    if not media_items:
        return None

    # Count by type
    images = 0
    audio = 0
    videos = 0
    youtube = 0

    for item in media_items:
        if "file_uri" in item and "youtube.com" in item.get("file_uri", ""):
            youtube += 1
        else:
            kind = item.get("kind", "")
            if kind == "image":
                images += 1
            elif kind == "audio":
                audio += 1
            elif kind == "video":
                videos += 1

    parts = []
    if images > 0:
        parts.append(f"{images} фото" if images > 1 else "фото")
    if videos > 0:
        parts.append(f"{videos} відео" if videos > 1 else "відео")
    if audio > 0:
        parts.append(f"{audio} аудіо" if audio > 1 else "аудіо")
    if youtube > 0:
        parts.append(f"{youtube} YouTube" if youtube > 1 else "YouTube відео")

    if not parts:
        return None

    return "Прикріплення: " + ", ".join(parts)


def _media_marker_from_media(
    raw_media: list[dict[str, Any]] | None,
    gemini_media: list[dict[str, Any]] | None,
) -> str | None:
    """Return simple media placeholders like [Image], [Video] with counts."""

    def _consume(kind_counts: dict[str, int], kind: str) -> None:
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    if not raw_media and not gemini_media:
        return None

    counts: dict[str, int] = {}

    if raw_media:
        for item in raw_media:
            kind = (item.get("kind") or "").lower()
            mime = (item.get("mime") or "").lower()
            if "youtube" in (item.get("file_uri") or "").lower():
                _consume(counts, "youtube")
            elif kind:
                if kind in {"image", "photo"}:
                    _consume(counts, "image")
                elif kind in {"video"}:
                    _consume(counts, "video")
                elif kind in {"audio", "voice"}:
                    _consume(counts, "audio")
                elif kind in {"document"}:
                    _consume(counts, "document")
                else:
                    _consume(counts, "other")
            elif mime:
                if "image" in mime:
                    _consume(counts, "image")
                elif "video" in mime:
                    _consume(counts, "video")
                elif "audio" in mime:
                    _consume(counts, "audio")
                else:
                    _consume(counts, "other")

    if gemini_media:
        for item in gemini_media:
            if "file_uri" in item.get("file_data", {}):
                uri = item["file_data"].get("file_uri", "")
                if "youtube" in uri.lower():
                    _consume(counts, "youtube")
                else:
                    _consume(counts, "document")
            elif "inline_data" in item:
                mime = item["inline_data"].get("mime_type", "").lower()
                if "image" in mime:
                    _consume(counts, "image")
                elif "video" in mime:
                    _consume(counts, "video")
                elif "audio" in mime:
                    _consume(counts, "audio")
                else:
                    _consume(counts, "other")

    if not counts:
        return None

    markers: list[str] = []
    for key in ("image", "video", "audio", "youtube", "document", "other"):
        count = counts.get(key, 0)
        if count <= 0:
            continue
        label = {
            "image": "Image",
            "video": "Video",
            "audio": "Audio",
            "youtube": "YouTube",
            "document": "Document",
            "other": "Attachment",
        }[key]
        if count > 1:
            markers.append(f"[{label} x{count}]")
        else:
            markers.append(f"[{label}]")

    return " ".join(markers) if markers else None


def _extract_meta_value(meta_text: str, key: str) -> str | None:
    pattern = rf"{key}=\"([^\"]+)\"|{key}=([^ \]]+)"
    match = re.search(pattern, meta_text)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _extract_meta_and_text(
    parts: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    meta_text: str | None = None
    text_fragments: list[str] = []

    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        stripped = text.strip()
        if stripped.startswith("[meta"):
            if meta_text is None:
                meta_text = stripped
            continue
        if stripped.startswith("[speaker"):
            continue
        text_fragments.append(stripped)

    combined = " ".join(text_fragments).strip()
    if combined:
        combined = sanitize_placeholder_text(combined)
        combined = " ".join(combined.split())
    return meta_text, combined or None


def _format_role_label(role: str | None) -> str:
    normalized = (role or "user").lower()
    if normalized in {"assistant", "model"}:
        return "bot"
    if normalized == "tool":
        return "tool"
    if normalized == "system":
        return "system"
    return "user"


def _build_system_context_block(
    *,
    settings: Settings,
    history_messages: list[dict[str, Any]],
    trigger_meta: dict[str, Any],
    trigger_text: str | None,
    trigger_raw_media: list[dict[str, Any]] | None,
    trigger_media_parts: list[dict[str, Any]] | None,
    reply_context: dict[str, Any] | None,
    reply_raw_media: list[dict[str, Any]] | None,
    reply_media_parts: list[dict[str, Any]] | None,
    chat_id: int,
    thread_id: int | None,
) -> str | None:
    if not settings.enable_system_context_block:
        return None

    max_messages = max(1, settings.system_context_block_max_messages)
    include_meta = settings.system_context_block_include_meta

    reply_message_id: str | None = None
    reply_media_marker: str | None = None
    reply_text: str | None = None
    reply_user_id: int | None = None
    reply_name: str | None = None
    reply_username: str | None = None
    reply_is_bot: bool | None = None

    if reply_context:
        reply_message_id = (
            str(reply_context.get("message_id"))
            if reply_context.get("message_id")
            else None
        )
        reply_media_marker = _media_marker_from_media(
            reply_raw_media, reply_media_parts
        )
        reply_text = reply_context.get("text") or reply_context.get("excerpt")
        reply_user_id = reply_context.get("user_id")
        reply_name = reply_context.get("name")
        reply_username = reply_context.get("username")
        reply_is_bot = reply_context.get("is_bot")

    history_entries: list[tuple[str, str | None, str, str | None]] = []
    reply_in_history = False

    for message in history_messages:
        role = message.get("role")
        if role == "tool":
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        meta_text, text_content = _extract_meta_and_text(parts)
        if include_meta and not meta_text:
            continue
        if not include_meta:
            meta_text = None

        display_text = text_content or ""
        message_id = (
            _extract_meta_value(meta_text or "", "message_id") if meta_text else None
        )
        if message_id and reply_message_id and message_id == reply_message_id:
            reply_in_history = True
            if reply_media_marker:
                display_text = (display_text + " " + reply_media_marker).strip()

        history_entries.append(
            (
                _format_role_label(role),
                meta_text,
                display_text,
                message_id,
            )
        )

    trigger_media_marker = _media_marker_from_media(
        trigger_raw_media, trigger_media_parts
    )
    trigger_text = trigger_text or ""
    trigger_text = sanitize_placeholder_text(trigger_text)
    trigger_text = " ".join(trigger_text.split())
    if trigger_media_marker:
        trigger_text = (trigger_text + " " + trigger_media_marker).strip()
    if not trigger_text:
        trigger_text = "(no content)"
    trigger_text = trigger_text + " [REPLY TO THIS]"

    trigger_meta_text = format_metadata(trigger_meta) if include_meta else None

    reply_line: tuple[str, str | None, str, str | None] | None = None
    if reply_context and not reply_in_history and reply_message_id:
        reply_display = reply_text or ""
        reply_display = sanitize_placeholder_text(reply_display)
        reply_display = " ".join(reply_display.split())
        if reply_media_marker:
            reply_display = (reply_display + " " + reply_media_marker).strip()
        if not reply_display:
            reply_display = "(no content)"

        reply_meta_dict = {
            "chat_id": str(chat_id),
            "thread_id": str(thread_id) if thread_id is not None else None,
            "message_id": reply_message_id,
            "user_id": str(reply_user_id) if reply_user_id is not None else None,
            "name": reply_name,
            "username": reply_username,
            "is_bot": reply_is_bot,
        }
        reply_meta_text = format_metadata(reply_meta_dict) if include_meta else None
        reply_line = (
            "user" if not reply_is_bot else "bot",
            reply_meta_text,
            reply_display,
            reply_message_id,
        )

    extra_lines = 1 + (1 if reply_line is not None else 0)
    max_history_lines = max(0, max_messages - extra_lines)
    if len(history_entries) > max_history_lines:
        history_entries = history_entries[-max_history_lines:]

    lines: list[str] = []
    for role_label, meta_text, display_text, _ in history_entries:
        display = display_text or "(no content)"
        if include_meta and meta_text:
            lines.append(f"{role_label} {meta_text}: {display}")
        else:
            lines.append(f"{role_label}: {display}")

    if reply_line is not None:
        while len(lines) + 1 + 1 > max_messages:  # ensure capacity for reply + trigger
            if lines:
                lines.pop(0)
            else:
                break
        role_label, meta_text, display_text, _ = reply_line
        if include_meta and meta_text:
            lines.append(f"{role_label} {meta_text}: {display_text}")
        else:
            lines.append(f"{role_label}: {display_text}")

    while len(lines) + 1 > max_messages:  # ensure trigger fits
        if lines:
            lines.pop(0)
        else:
            break

    if include_meta and trigger_meta_text:
        lines.append(f"user {trigger_meta_text}: {trigger_text}")
    else:
        lines.append(f"user: {trigger_text}")

    header = (
        "Here’s the current conversation context (last up to "
        f"{max_messages} messages):"
    )
    block_body = "\n".join(lines)
    return f"{header}\n\n```\n{block_body}\n```\n\n[RESPOND]"


def _get_recent_context(chat_id: int, thread_id: int | None) -> dict[str, Any] | None:
    key = (chat_id, thread_id)
    queue = _RECENT_CONTEXT.get(key)
    if not queue:
        return None
    now = time.time()
    while queue:
        candidate = queue[-1]
        if now - candidate["ts"] <= _CONTEXT_TTL_SECONDS:
            return candidate
        queue.pop()
    return None


async def _remember_context_message(
    message: Message,
    bot: Bot,
    gemini_client: GeminiClient,
    store: ContextStore,
    settings: Settings,
) -> None:
    """Cache and persist unaddressed messages for potential context use."""
    if message.from_user is None or message.from_user.is_bot:
        return

    text = _extract_text(message)
    media_raw: list[dict[str, Any]] = []
    media_parts: list[dict[str, Any]] = []

    try:
        media_raw = await collect_media_parts(bot, message)

        # Also check for YouTube URLs in unaddressed messages
        from app.services.media import extract_youtube_urls

        youtube_urls = extract_youtube_urls(text)
        if youtube_urls:
            for url in youtube_urls:
                media_raw.append(
                    {"file_uri": url, "kind": "video", "mime": "video/mp4"}
                )
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.exception(f"Failed to collect media for message {message.message_id}")
        media_raw = []

    if media_raw:
        media_parts = gemini_client.build_media_parts(media_raw, logger=LOGGER)

    media_summary = _summarize_media(media_raw)

    if not text and not media_parts:
        return

    key = (message.chat.id, message.message_thread_id)
    bucket = _RECENT_CONTEXT.setdefault(key, deque(maxlen=5))
    bucket.append(
        {
            "ts": int(message.date.timestamp()) if message.date else int(time.time()),
            "message_id": message.message_id,
            "user_id": message.from_user.id,
            "name": message.from_user.full_name,
            "username": _normalize_username(message.from_user.username),
            "excerpt": (text or media_summary or "")[:200] or None,
            "text": text or media_summary,
            "media_parts": media_parts,
        }
    )

    # Persist unaddressed messages to database so they can be retrieved later
    # This is critical for multi-level context to see images in past messages
    try:
        text_content = text or media_summary or ""
        from_user = message.from_user

        # Generate embedding for semantic search
        user_embedding = None
        if text_content:
            user_embedding = await gemini_client.embed_text(text_content)

        # Build metadata (stringify external IDs in meta to avoid precision issues)
        user_meta = {
            "chat_id": str(message.chat.id),
            "thread_id": (
                str(message.message_thread_id)
                if message.message_thread_id is not None
                else None
            ),
            "message_id": str(message.message_id),
            "user_id": str(message.from_user.id),
            "name": message.from_user.full_name,
            "username": _normalize_username(message.from_user.username),
            "is_bot": bool(message.from_user.is_bot),
        }

        # Store in database for later retrieval
        await store.add_message(
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            user_id=message.from_user.id,
            role="user",
            text=text_content,
            media=media_parts,
            metadata=user_meta,
            embedding=user_embedding,
            retention_days=settings.retention_days,
            sender=MessageSender(
                role="user",
                name=from_user.full_name if from_user else None,
                username=_normalize_username(from_user.username) if from_user else None,
                is_bot=from_user.is_bot if from_user else None,
            ),
        )

        LOGGER.debug(
            "Persisted unaddressed message %s with %d media part(s)",
            message.message_id,
            len(media_parts),
        )
    except Exception as e:
        # Don't fail the whole flow if persistence fails
        LOGGER.error(
            "Failed to persist unaddressed message %s: %s",
            message.message_id,
            e,
            exc_info=True,
        )


def _build_user_metadata(
    message: Message,
    chat_id: int,
    thread_id: int | None,
    fallback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from_user = message.from_user
    # Stringify external IDs for storage inside message media/meta JSON
    meta: dict[str, Any] = {
        "chat_id": str(chat_id),
        "thread_id": str(thread_id) if thread_id is not None else None,
        "message_id": str(message.message_id),
        "user_id": str(from_user.id) if from_user else None,
        "name": from_user.full_name if from_user else None,
        "username": _normalize_username(from_user.username if from_user else None),
        "is_bot": bool(from_user.is_bot) if from_user else None,
    }
    reply = message.reply_to_message
    if reply:
        meta["reply_to_message_id"] = reply.message_id
        if reply.from_user:
            meta["reply_to_user_id"] = reply.from_user.id
            meta["reply_to_name"] = reply.from_user.full_name
            meta["reply_to_username"] = _normalize_username(reply.from_user.username)
        excerpt = _extract_text(reply)
        if excerpt:
            meta["reply_excerpt"] = excerpt[:200]
    elif fallback_context:
        # Only include essential fallback context to reduce confusion
        if fallback_context.get("message_id") is not None:
            meta["reply_to_message_id"] = fallback_context["message_id"]
        if fallback_context.get("name"):
            meta["reply_to_name"] = fallback_context["name"]
        if fallback_context.get("excerpt"):
            meta["reply_excerpt"] = fallback_context["excerpt"]
    return {key: value for key, value in meta.items() if value not in (None, "")}


def _build_clean_user_parts(
    raw_text: str,
    media_summary: str | None,
    fallback_text: str | None,
    media_parts: list[dict[str, Any]],
    fallback_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build user parts with better context prioritization."""
    parts: list[dict[str, Any]] = []

    # Prioritize actual user content over fallback
    if raw_text:
        parts.append({"text": raw_text})
    elif media_summary:
        parts.append({"text": media_summary})
    elif fallback_text:
        # Only use fallback if it's actually helpful and not just noise
        if len(fallback_text.strip()) > 5:  # Avoid very short/meaningless fallbacks
            parts.append({"text": f"[Context: {fallback_text}]"})

    # Add media content
    if media_parts:
        parts.extend(media_parts)
    elif fallback_context and fallback_context.get("media_parts"):
        # Only add fallback media if current message has no media
        if not raw_text or media_summary:
            parts.extend(list(fallback_context["media_parts"]))

    # Ensure we always have some content
    if not parts:
        parts.append({"text": "..."})

    return parts


def _build_model_metadata(
    response: Message,
    chat_id: int,
    thread_id: int | None,
    bot_username: str,
    original: Message,
    original_text: str,
) -> dict[str, Any]:
    origin_user = original.from_user
    # Stringify external IDs in meta JSON
    meta: dict[str, Any] = {
        "chat_id": str(chat_id),
        "thread_id": str(thread_id) if thread_id is not None else None,
        "message_id": str(response.message_id) if response is not None else None,
        "user_id": None,
        "name": "gryag",
        "username": _normalize_username(bot_username),
        "reply_to_message_id": str(original.message_id),
        "is_bot": True,
    }
    if origin_user:
        meta["reply_to_user_id"] = origin_user.id
        meta["reply_to_name"] = origin_user.full_name
        meta["reply_to_username"] = _normalize_username(origin_user.username)
    excerpt = original_text.strip()
    if excerpt:
        meta["reply_excerpt"] = " ".join(excerpt.split())[:200]
    return {key: value for key, value in meta.items() if value not in (None, "")}


def _strip_leading_metadata(text: str) -> str:
    """Remove metadata from the beginning of text."""
    match = _META_PREFIX_RE.match(text)
    if not match:
        return text
    return text[match.end() :].lstrip()


def _clean_response_text(text: str) -> str:
    """Comprehensively clean response text from any metadata or technical information."""
    if not text:
        return text

    # Remove any [meta] blocks anywhere in the text
    text = _META_ANYWHERE_RE.sub("", text)

    # Remove technical IDs and system information
    text = _TECHNICAL_INFO_RE.sub("", text)

    # Remove leading metadata
    text = _strip_leading_metadata(text)

    # Remove bracketed system markers that Gemini sometimes adds
    # Examples: [GENERATED_IMAGE], [ATTACHMENT], [IMAGE_GENERATED], etc.
    text = re.sub(
        r"\[(?:GENERATED_IMAGE|IMAGE_GENERATED|ATTACHMENT|GENERATED|IMAGE)\]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove tool call descriptions that the model might return instead of executing
    # Patterns: "tool_call:", "function_call:", "generate_image(...)", etc.
    tool_patterns = [
        r"tool_call\s*:\s*\w+",
        r"function_call\s*:\s*\w+",
        r"tool_call\s*\(\s*[^)]*\s*\)",
        r"\bgenerate_image\s*\([^)]*\)",
        r"\bedit_image\s*\([^)]*\)",
        r"\bsearch_web\s*\([^)]*\)",
        r"\bcalculate\s*\([^)]*\)",
        r"\bget_weather\s*\([^)]*\)",
        r"\bremember_memory\s*\([^)]*\)",
        r"\brecall_memories\s*\([^)]*\)",
    ]
    for pattern in tool_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Clean up extra whitespace and empty lines
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not line.startswith("[meta")]

    # Join lines and clean up spacing
    cleaned = "\n".join(lines).strip()

    # Remove any remaining metadata patterns that might have slipped through
    while "[meta]" in cleaned:
        cleaned = cleaned.replace("[meta]", "").strip()

    # Clean up multiple consecutive spaces while preserving newlines
    # Process each line separately to maintain line breaks
    lines = cleaned.split("\n")
    cleaned_lines = [" ".join(line.split()) for line in lines]
    cleaned = "\n".join(cleaned_lines)

    return cleaned


async def _get_video_description_from_history(
    store: ContextStore,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
) -> str | None:
    """
    Retrieve bot's description of a video from conversation history.

    Looks for the bot's response to a message containing video,
    and extracts relevant description text.

    Args:
        store: Context store to query
        chat_id: Chat ID
        thread_id: Thread ID (for supergroups)
        message_id: Message ID that contains the video

    Returns:
        Text description of the video, or None if not found
    """
    try:
        # Get recent conversation history
        messages = await store.recent(
            chat_id=chat_id,
            thread_id=thread_id,
            max_messages=20,  # Check last 20 messages
        )

        # Find the video message and the bot's response after it
        found_video_msg = False
        for message_item in messages:
            metadata = message_item.get("metadata", "")
            text = message_item.get("text", "")
            role = message_item.get("role", "")

            # Check if this is the video message we're looking for
            if not found_video_msg and f"message_id={message_id}" in metadata:
                found_video_msg = True
                continue

            # If we found the video message, next model response is the description
            if found_video_msg and role == "model":
                # Clean and return the description
                clean_text = text.strip()
                if clean_text.startswith("[meta]"):
                    lines = clean_text.split("\n")
                    clean_text = "\n".join(
                        line for line in lines if not line.strip().startswith("[meta")
                    ).strip()

                return clean_text if clean_text else None

        return None

    except Exception as e:
        LOGGER.debug(f"Could not retrieve video description: {e}")
        return None


async def _enrich_with_user_profile(
    profile_store: UserProfileStore,
    user_id: int,
    chat_id: int,
    settings: Settings,
) -> str:
    """Build user profile context string for injection into conversation."""
    if not settings.enable_user_profiling:
        return ""

    try:
        summary = await profile_store.get_user_summary(
            user_id=user_id,
            chat_id=chat_id,
            include_facts=True,
            include_relationships=True,
            min_confidence=settings.fact_confidence_threshold,
            max_facts=10,
        )

        if summary and len(summary) > 20:  # Has meaningful content
            telemetry.increment_counter("context_enrichment_used")
            return f"\n\n[User Context]\n{summary}"

        return ""
    except Exception as e:
        LOGGER.error(f"Failed to enrich context for user {user_id}: {e}", exc_info=True)
        return ""


async def _update_user_profile_background(
    profile_store: UserProfileStore,
    user_id: int,
    chat_id: int,
    thread_id: int | None,
    display_name: str | None,
    username: str | None,
    settings: Settings,
) -> None:
    """Background task to keep profile metadata fresh after each message."""
    try:
        if not settings.enable_user_profiling:
            return

        await profile_store.get_or_create_profile(
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            username=username,
        )

        await profile_store.update_interaction_count(
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
        )

        if settings.enable_tool_based_memory:
            LOGGER.debug(
                "Tool-based memory enabled; relying on Gemini tool calls for fact storage"
            )
    except Exception:
        LOGGER.exception(
            "Failed to update user profile metadata",
            extra={"user_id": user_id, "chat_id": chat_id},
        )


def _format_for_telegram(text: str) -> str:
    """
    Format text for Telegram HTML parse mode.

    Converts markdown/MarkdownV2 syntax to HTML:
    - **bold** or __bold__ -> <b>bold</b>
    - *italic* or _italic_ -> <i>italic</i>
    - ~~strikethrough~~ -> <s>strikethrough</s>
    - ||spoiler|| -> <tg-spoiler>spoiler</tg-spoiler>

    Escapes HTML special characters to prevent parsing errors.
    Preserves Telegram usernames (@username) without treating underscores as formatting.
    """
    if not text:
        return text

    import html
    import re

    # Storage for protected content
    protected = []

    def protect_content(content, tag=None):
        """Store content and return placeholder."""
        if tag:
            # For formatting tags, escape HTML
            escaped = html.escape(content)
            placeholder = f"\ue000TGFMT{len(protected)}\ue001"
            protected.append((tag, escaped))
        else:
            # For raw content (like usernames), don't escape yet
            placeholder = f"\ue000RAW{len(protected)}\ue001"
            protected.append((None, content))
        return placeholder

    # Step 0: Remove MarkdownV2 escape sequences (Gemini sometimes generates these)
    # MarkdownV2 requires escaping special chars with \, but we use HTML mode
    # Remove backslash before: _ * [ ] ( ) ~ ` > # + - = | { } . ! ,
    text = re.sub(r"\\([_*\[\]()~`>#+=\-|{}.!,])", r"\1", text)

    # Step 1: Protect Telegram usernames (@username) to prevent underscore processing
    # Match @username pattern (alphanumeric, underscore, 5-32 chars)
    text = re.sub(
        r"@([a-zA-Z0-9_]{5,32})\b",
        lambda m: protect_content(m.group(0)),
        text,
    )

    # Step 2: Extract and protect formatted blocks (order matters!)

    # Protect spoilers ||text||
    text = re.sub(
        r"\|\|(.*?)\|\|", lambda m: protect_content(m.group(1), "tg-spoiler"), text
    )

    # Protect strikethrough ~~text~~
    text = re.sub(r"~~(.*?)~~", lambda m: protect_content(m.group(1), "s"), text)

    # Protect bold **text** or __text__
    text = re.sub(r"\*\*(.*?)\*\*", lambda m: protect_content(m.group(1), "b"), text)
    text = re.sub(r"__(.*?)__", lambda m: protect_content(m.group(1), "b"), text)

    # Protect italic *text* or _text_ (but not ** or __)
    # Negative lookbehind/lookahead to avoid matching ** or __
    text = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        lambda m: protect_content(m.group(1), "i"),
        text,
    )
    text = re.sub(
        r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)",
        lambda m: protect_content(m.group(1), "i"),
        text,
    )

    # Step 3: HTML-escape the rest of the text
    text = html.escape(text)

    # Step 4: Restore protected content with HTML tags or as-is
    for i, (tag, content) in enumerate(protected):
        if tag:
            # Formatted content with tags
            placeholder = f"\ue000TGFMT{i}\ue001"
            text = text.replace(placeholder, f"<{tag}>{content}</{tag}>")
        else:
            # Raw content (usernames) - escape after restoring
            placeholder = f"\ue000RAW{i}\ue001"
            text = text.replace(placeholder, html.escape(content))

    # Step 5: Safety check - remove any leaked placeholder patterns
    # This catches cases where Unicode chars were stripped but pattern text remains
    text = re.sub(r"TGFMT\d+|RAW\d+", "", text)

    return text


def _escape_markdown(text: str) -> str:
    """
    Clean up text that might break Telegram Markdown parsing.

    Since we send replies using Markdown parse mode, we preserve intentional
    formatting (bold/italic) while escaping special characters that break parsing.

    NOTE: This function is deprecated. Use _format_for_telegram() with HTML parse mode instead.
    """
    if not text:
        return text

    # Strategy: Use regex to preserve markdown formatting while escaping special chars
    # We need to:
    # 1. Protect markdown formatting: **bold**, *bold*, __italic__, _italic_, `code`, ```code```
    # 2. Escape all MarkdownV2 special chars OUTSIDE of these formatting blocks
    # 3. Preserve list bullets

    # Characters that need escaping in MarkdownV2
    # Complete list from Telegram docs: _*[]()~`>#+-=|{}.!
    # We handle * and _ specially to preserve intentional formatting
    special_chars = set("_*[]()~`><#+-=|{}.!\\")

    result = []
    i = 0
    text_len = len(text)

    while i < text_len:
        # Check for code blocks (triple backticks)
        if i + 2 < text_len and text[i : i + 3] == "```":
            # Find closing triple backticks
            end = text.find("```", i + 3)
            if end != -1:
                # Include entire code block as-is
                result.append(text[i : end + 3])
                i = end + 3
                continue

        # Check for inline code (single backtick)
        if text[i] == "`":
            # Find closing backtick
            end = text.find("`", i + 1)
            if end != -1:
                # Escape backticks but include content
                result.append("\\`")
                result.append(text[i + 1 : end])
                result.append("\\`")
                i = end + 1
                continue

        # Check for bold (**text** or __text__)
        if i + 1 < text_len and text[i : i + 2] in ("**", "__"):
            marker = text[i : i + 2]
            # Find closing marker
            end = text.find(marker, i + 2)
            if end != -1 and end > i + 2:  # Must have content between markers
                # Include formatting as-is
                result.append(marker)
                # Recursively escape content inside (but keep nested formatting)
                inner_content = text[i + 2 : end]
                result.append(inner_content)  # Don't escape inside formatting
                result.append(marker)
                i = end + 2
                continue

        # Check for italic (*text* or _text_)
        if text[i] in ("*", "_"):
            marker = text[i]
            # Find closing marker (but not if it's part of ** or __)
            if not (i + 1 < text_len and text[i + 1] == marker):
                # Look for single marker
                j = i + 1
                while j < text_len:
                    if text[j] == marker:
                        # Make sure it's not part of double marker
                        if not (j + 1 < text_len and text[j + 1] == marker):
                            # Found closing marker
                            if j > i + 1:  # Must have content
                                result.append(marker)
                                result.append(
                                    text[i + 1 : j]
                                )  # Don't escape inside formatting
                                result.append(marker)
                                i = j + 1
                                break
                    j += 1
                else:
                    # No closing marker found, escape the character
                    result.append(f"\\{marker}")
                    i += 1
                continue

        # Check for list bullets at start of line
        if text[i] == "*" and (i == 0 or text[i - 1] == "\n"):
            # Check if it's a bullet (* followed by space)
            if i + 1 < text_len and text[i + 1] == " ":
                result.append("* ")
                i += 2
                continue

        # Regular character - escape if it's a special char
        char = text[i]
        if char in special_chars:
            result.append(f"\\{char}")
        else:
            result.append(char)
        i += 1

    return "".join(result)


def _summarize_long_context(
    history: list[dict[str, Any]], max_context: int = 30
) -> list[dict[str, Any]]:
    """Summarize older context to prevent confusion while keeping recent messages."""
    if len(history) <= max_context:
        return history

    # Keep the most recent messages and summarize older ones
    recent_messages = history[-max_context:]
    older_messages = history[:-max_context]

    if not older_messages:
        return recent_messages

    # Create a simple summary of older context
    summary_parts = []
    user_count = 0
    model_count = 0

    for item in older_messages:
        if item.get("role") == "user":
            user_count += 1
        elif item.get("role") == "model":
            model_count += 1

    if user_count > 0 or model_count > 0:
        summary_text = f"[Попередня розмова: {user_count} повідомлень користувачів, {model_count} відповідей]"
        summary_entry = {"role": "user", "parts": [{"text": summary_text}]}
        return [summary_entry] + recent_messages

    return recent_messages


def _truncate_history_to_tokens(
    history: list[dict[str, Any]], max_tokens: int
) -> list[dict[str, Any]]:
    """
    Truncate history to fit within token budget.

    Keeps most recent messages and truncates from the beginning.
    Uses rough token estimation: words * 1.3

    Args:
        history: List of message dicts with 'role' and 'parts'
        max_tokens: Maximum token budget

    Returns:
        Truncated history within token budget
    """
    if not history:
        return history

    def estimate_message_tokens(msg: dict[str, Any]) -> int:
        """Estimate tokens for a single message."""
        total = 0
        parts = msg.get("parts", [])
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text = part["text"]
                words = len(text.split())
                total += int(words * 1.3)
        return total

    # Start from the end (most recent) and work backwards
    truncated = []
    current_tokens = 0

    for msg in reversed(history):
        msg_tokens = estimate_message_tokens(msg)

        if current_tokens + msg_tokens > max_tokens:
            # Would exceed budget, stop here
            if truncated:
                # Add a summary message at the beginning
                summary_text = f"[Попередні {len(history) - len(truncated)} повідомлень пропущено через ліміт токенів]"
                summary_msg = {"role": "user", "parts": [{"text": summary_text}]}
                truncated.insert(0, summary_msg)
            break

        truncated.insert(0, msg)
        current_tokens += msg_tokens

    if len(truncated) < len(history):
        LOGGER.warning(
            f"Truncated history from {len(history)} to {len(truncated)} messages "
            f"(estimated {current_tokens}/{max_tokens} tokens)"
        )
        telemetry.increment_counter("context.token_truncation")

    return truncated if truncated else history[:1]  # Keep at least 1 message


@router.message()
async def handle_group_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    profile_store: UserProfileStore,
    bot_username: str,
    bot_id: int | None,
    hybrid_search: HybridSearchEngine | None = None,
    episodic_memory: EpisodicMemoryStore | None = None,
    episode_monitor: Any | None = None,
    bot_profile: BotProfileStore | None = None,
    bot_learning: BotLearningEngine | None = None,
    prompt_manager: SystemPromptManager | None = None,
    redis_client: RedisLike | None = None,
    rate_limiter: RateLimiter | None = None,
    multi_level_context_manager: MultiLevelContextManager | None = None,
    persona_loader: Any | None = None,
    image_gen_service: ImageGenerationService | None = None,
    feature_limiter: Any | None = None,
    memory_repo: MemoryRepository | None = None,
    chat_profile_store: Any | None = None,
    donation_scheduler: Any | None = None,
    telegram_service: TelegramService | None = None,
    data: dict[str, Any] | None = None,
):
    if message.from_user is None or message.from_user.is_bot:
        LOGGER.debug("Ignoring message: no from_user or is_bot")
        return

    telemetry.increment_counter("chat.incoming")

    LOGGER.info(
        "Processing message",
        extra={
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "user_id": message.from_user.id,
            "text": (message.text or message.caption or "")[:50],
        },
    )

    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # Bot Self-Learning: Check if message is a reaction to bot's previous response
    # This runs BEFORE is_addressed check so we can learn from all user messages
    if (
        settings.enable_bot_self_learning
        and bot_profile is not None
        and bot_learning is not None
        and bot_id is not None
    ):
        asyncio.create_task(
            process_potential_reaction(
                message=message,
                bot_profile=bot_profile,
                bot_learning=bot_learning,
                store=store,
                bot_id=bot_id,
                chat_id=chat_id,
                thread_id=thread_id,
                user_id=message.from_user.id,
                reaction_timeout_seconds=settings.bot_reaction_timeout_seconds,
            )
        )

    is_addressed = addressed_to_bot(message, bot_username, bot_id, chat_id)
    if not is_addressed:
        telemetry.increment_counter("chat.unaddressed")
        LOGGER.debug(
            "Message not addressed to bot",
            extra={
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "text": (message.text or message.caption or "")[:50],
            },
        )
        await _remember_context_message(message, bot, gemini_client, store, settings)
        return

    telemetry.increment_counter("chat.addressed")
    user_id = message.from_user.id

    # Ensure data dict exists (needed for processing lock check)
    if data is None:
        data = {}

    # Check if there's an unanswered trigger message from THIS USER before this one
    # If the bot didn't respond to the first trigger from this user, don't respond to subsequent ones
    # This prevents the bot from "catching up" and responding to messages it missed
    # This check is per-user: if user A's trigger wasn't answered, only user A's next triggers are skipped
    # Only block if the unanswered trigger is recent (within last 2 minutes) to allow reset after time passes
    # NOTE: This check runs BEFORE storing the current message, so we check the PREVIOUS message
    from app.infrastructure.db_utils import get_db_connection
    import time

    current_ts = int(time.time())
    unanswered_threshold_seconds = (
        120  # 2 minutes - after this, allow responses again (reduced from 5 min)
    )

    # Check if there's currently processing happening for this user
    # If so, we know a response is being generated, so don't skip the message
    lock_key = (chat_id, user_id)
    processing_check = data.get("_processing_lock_check")
    is_processing = False
    if processing_check:
        is_processing = await processing_check(lock_key)

    async with get_db_connection(store._database_url) as conn:
        # Query for the most recent message from this user in this chat/thread
        # This will be the PREVIOUS message (before the current one being processed)
        if thread_id is None:
            query = """
                SELECT id, role, user_id, external_user_id, ts
                FROM messages
                WHERE chat_id = $1 AND thread_id IS NULL AND user_id = $2
                ORDER BY id DESC
                LIMIT 1
            """
            params = (chat_id, user_id)
        else:
            query = """
                SELECT id, role, user_id, external_user_id, ts
                FROM messages
                WHERE chat_id = $1 AND thread_id = $2 AND user_id = $3
                ORDER BY id DESC
                LIMIT 1
            """
            params = (chat_id, thread_id, user_id)

        user_last_row = await conn.fetchrow(query, *params)

        if user_last_row and user_last_row["role"] == "user":
            # Check if the unanswered trigger is recent enough to still block
            trigger_age = current_ts - user_last_row["ts"]
            if trigger_age > unanswered_threshold_seconds:
                # Trigger is old enough - allow responses again (reset)
                LOGGER.debug(
                    f"Previous trigger from user {user_id} is old ({trigger_age}s), allowing response"
                )
            else:
                # Found a recent user message from this user - check if there's a bot response after it
                # Query for the next message after this user's message (in the same chat/thread)
                if thread_id is None:
                    next_query = """
                        SELECT role FROM messages
                        WHERE chat_id = $1 AND thread_id IS NULL AND id > $2
                        ORDER BY id ASC
                        LIMIT 1
                    """
                    next_params = (chat_id, user_last_row["id"])
                else:
                    next_query = """
                        SELECT role FROM messages
                        WHERE chat_id = $1 AND thread_id = $2 AND id > $3
                        ORDER BY id ASC
                        LIMIT 1
                    """
                    next_params = (chat_id, thread_id, user_last_row["id"])

                next_row = await conn.fetchrow(next_query, *next_params)

                # If there's no next message or the next message is not from the bot (role != 'model'),
                # that means the user's trigger wasn't answered (and it's recent)
                # BUT: If processing is currently active for this user, we know a response is being generated,
                # so don't skip the message (the response just hasn't been saved to DB yet)
                if (
                    next_row is None or next_row["role"] != "model"
                ) and not is_processing:
                    LOGGER.info(
                        "Skipping trigger message - previous trigger from this user was not answered (recent)",
                        extra={
                            "chat_id": message.chat.id,
                            "message_id": message.message_id,
                            "user_id": user_id,
                            "previous_trigger_id": user_last_row["id"],
                            "trigger_age_seconds": trigger_age,
                        },
                    )
                    telemetry.increment_counter("chat.skipped_unanswered_trigger")
                    # Do NOT store this message - it would create a blocking chain
                    # Only the first unanswered trigger should block subsequent ones
                    return
                elif (
                    next_row is None or next_row["role"] != "model"
                ) and is_processing:
                    LOGGER.debug(
                        "Previous trigger from this user appears unanswered, but processing is active - allowing message",
                        extra={
                            "chat_id": message.chat.id,
                            "message_id": message.message_id,
                            "user_id": user_id,
                            "previous_trigger_id": user_last_row["id"],
                        },
                    )

    LOGGER.info(
        "Message addressed to bot - processing",
        extra={
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "user_id": user_id,
        },
    )

    # Check admin status first (admins bypass rate limiting and processing locks)
    is_admin = user_id in settings.admin_user_ids_list
    lock_key = (chat_id, user_id)

    # Processing lock: Check if already processing a message from this user
    # (Skip for admins)
    if not is_admin:

        # Check if processing (via middleware data)
        processing_check = data.get("_processing_lock_check")
        if processing_check:
            is_processing = await processing_check(lock_key)
            if is_processing:
                # Drop the message silently
                LOGGER.info(
                    "Dropping bot-addressed message from user %s in chat %s "
                    "(already processing previous message) - message_id=%s",
                    user_id,
                    chat_id,
                    message.message_id,
                )
                telemetry.increment_counter(
                    "chat.dropped_during_processing",
                    user_id=user_id,
                    chat_id=chat_id,
                )
                return  # Drop message

        # Acquire lock
        processing_set = data.get("_processing_lock_set")
        if processing_set:
            await processing_set(lock_key, True)
            LOGGER.debug(
                "Processing lock acquired for user %s in chat %s (message_id=%s)",
                user_id,
                chat_id,
                message.message_id,
            )

    # Ensure lock is released in finally block
    try:
        try:
            await _handle_bot_message_locked(
                message=message,
                bot=bot,
                settings=settings,
                store=store,
                gemini_client=gemini_client,
                profile_store=profile_store,
                chat_profile_store=chat_profile_store,
                hybrid_search=hybrid_search,
                episodic_memory=episodic_memory,
                episode_monitor=episode_monitor,
                bot_profile=bot_profile,
                bot_learning=bot_learning,
                prompt_manager=prompt_manager,
                feature_limiter=feature_limiter,
                multi_level_context_manager=multi_level_context_manager,
                redis_client=redis_client,
                rate_limiter=rate_limiter,
                persona_loader=persona_loader,
                image_gen_service=image_gen_service,
                donation_scheduler=donation_scheduler,
                memory_repo=memory_repo,
                telegram_service=telegram_service,
                bot_username=bot_username,
                bot_id=bot_id,
                is_admin=is_admin,
                user_id=user_id,
                chat_id=message.chat.id,
                thread_id=message.message_thread_id,
                data=data,
            )
        except Exception as handler_exc:
            LOGGER.critical(
                f"Message handler crashed unexpectedly: {handler_exc}", exc_info=True
            )
            # Try to notify user of the error
            try:
                await message.reply(
                    "❌ Критична помилка при обробці. Будь ласка, спробуй пізніше.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as notify_exc:
                LOGGER.error(
                    f"Failed to send error notification to user: {notify_exc}",
                    exc_info=True,
                )
    finally:
        # Release lock
        if not is_admin:
            processing_set = data.get("_processing_lock_set")
            if processing_set:
                await processing_set(lock_key, False)
                LOGGER.debug(
                    "Processing lock released for user %s in chat %s (message_id=%s)",
                    user_id,
                    chat_id,
                    message.message_id,
                )


async def _handle_bot_message_locked(
    message: Message,
    bot: Bot,
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    profile_store: UserProfileStore,
    chat_profile_store: Any,
    hybrid_search: HybridSearchEngine,
    episodic_memory: EpisodicMemoryStore,
    episode_monitor: Any,
    bot_profile: Any,
    bot_learning: Any,
    prompt_manager: SystemPromptManager,
    feature_limiter: Any,
    multi_level_context_manager: MultiLevelContextManager,
    redis_client: RedisLike | None,
    rate_limiter: RateLimiter | None,
    persona_loader: Any,
    image_gen_service: ImageGenerationService | None,
    donation_scheduler: Any,
    memory_repo: MemoryRepository,
    telegram_service: TelegramService | None,
    bot_username: str,
    bot_id: int | None,
    is_admin: bool,
    user_id: int,
    chat_id: int,
    thread_id: int | None,
    data: dict[str, Any],
) -> None:
    """Handle bot-addressed message with processing lock acquired."""

    # Rate limiting (skip for admins)
    if not is_admin and rate_limiter is not None and message.from_user:
        allowed, remaining, retry_after = await rate_limiter.check_and_increment(
            user_id=message.from_user.id
        )
        LOGGER.info(
            f"Rate limit check: user_id={user_id}, allowed={allowed}, remaining={remaining}, retry_after={retry_after}"
        )
        if not allowed:
            # Only send error message if we haven't sent one recently (10 min cooldown)
            should_show_error = rate_limiter.should_send_error_message(
                message.from_user.id
            )
            if should_show_error:
                wait_minutes = max((retry_after + 59) // 60, 1)
                throttle_text = _get_response(
                    "throttle_notice",
                    persona_loader,
                    THROTTLED_REPLY,
                    minutes=wait_minutes,
                    bot_username=bot_username,
                )
                await message.reply(throttle_text)
            # Silently block otherwise (error already shown recently)
            telemetry.increment_counter(
                "chat.rate_limited",
                user_id=message.from_user.id,
                remaining=remaining,
            )
            return

    if not is_admin and await store.is_banned(chat_id, user_id):
        telemetry.increment_counter("chat.banned_user")
        # Only send ban notice if cooldown has passed (30 min default)
        if await store.should_send_ban_notice(chat_id, user_id):
            await message.reply(
                _get_response(
                    "banned_reply",
                    persona_loader,
                    BANNED_REPLY,
                    bot_username=bot_username,
                )
            )
        # Always return early for banned users (no processing)
        return

    # Start timing for performance monitoring
    processing_start_time = time.time()
    perf_timings: dict[str, int] = {}  # Track performance timings for summary

    # Build multi-level context if services are available
    context_manager = multi_level_context_manager
    use_multi_level = settings.enable_multi_level_context and (
        context_manager is not None
        or (hybrid_search is not None and episodic_memory is not None)
    )

    context_assembly = None

    if use_multi_level:
        # Phase 3: Use multi-level context manager
        if context_manager is None:
            context_manager = MultiLevelContextManager(
                db_path=settings.db_path,
                settings=settings,
                context_store=store,
                profile_store=profile_store,
                hybrid_search=hybrid_search,
                episode_store=episodic_memory,
                gemini_client=gemini_client,  # Pass for media capability detection
            )

        # Get query text for context retrieval
        text_content = (message.text or message.caption or "").strip()

        # Build multi-level context
        context_build_start = time.time()
        try:
            context_assembly = await context_manager.build_context(
                chat_id=chat_id,
                thread_id=thread_id,
                user_id=user_id,
                query_text=text_content or "conversation",
                max_tokens=settings.context_token_budget,
            )
            context_build_time = int((time.time() - context_build_start) * 1000)
            perf_timings["context_build_time_ms"] = context_build_time

            LOGGER.info(
                "Multi-level context assembled",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "total_tokens": context_assembly.total_tokens,
                    "immediate_count": len(context_assembly.immediate.messages),
                    "recent_count": (
                        len(context_assembly.recent.messages)
                        if context_assembly.recent
                        else 0
                    ),
                    "relevant_count": (
                        len(context_assembly.relevant.snippets)
                        if context_assembly.relevant
                        else 0
                    ),
                    "episodic_count": (
                        len(context_assembly.episodes.episodes)
                        if context_assembly.episodes
                        else 0
                    ),
                    "build_time_ms": context_build_time,
                },
            )
        except Exception as e:
            LOGGER.error(
                "Multi-level context assembly failed, falling back to simple history",
                exc_info=e,
                extra={"chat_id": chat_id, "user_id": user_id},
            )
            telemetry.increment_counter("context.fallback_to_simple")
            use_multi_level = False
            context_manager = None
            context_assembly = None

    if not use_multi_level:
        # Fallback: Use simple history retrieval
        context_build_start = time.time()
        history = await store.recent(
            chat_id=chat_id,
            thread_id=thread_id,
            max_messages=settings.max_messages,
        )
        context_build_time = int((time.time() - context_build_start) * 1000)
        perf_timings["context_build_time_ms"] = context_build_time
        LOGGER.info(
            "Simple history retrieved",
            extra={
                "chat_id": chat_id,
                "thread_id": thread_id,
                "history_count": len(history),
                "build_time_ms": context_build_time,
            },
        )

        # Apply token-based truncation to prevent overflow
        history = _truncate_history_to_tokens(
            history, max_tokens=settings.context_token_budget
        )

        # Summarize context if it's getting too long to prevent confusion
        history = _summarize_long_context(history, settings.context_summary_threshold)
        history = _summarize_long_context(history, settings.context_summary_threshold)
    else:
        # Multi-level context will be formatted later
        history = []

    # Track reply context for later injection and system context block
    reply_context_for_history: dict[str, Any] | None = None
    reply_context_for_block: dict[str, Any] | None = None
    reply_media_raw_for_block: list[dict[str, Any]] | None = None
    reply_media_parts_for_block: list[dict[str, Any]] | None = None

    history_messages_for_block: list[dict[str, Any]] = []
    use_system_context_block = settings.enable_system_context_block

    # Collect media from message (photos, videos, audio, etc.)
    media_collect_start = time.time()
    media_raw = await collect_media_parts(bot, message)
    media_collect_time = int((time.time() - media_collect_start) * 1000)
    perf_timings["media_collect_time_ms"] = media_collect_time
    if media_collect_time > 1000:  # Log if takes more than 1 second
        LOGGER.info(
            "Media collection completed",
            extra={
                "chat_id": chat_id,
                "message_id": message.message_id,
                "media_count": len(media_raw),
                "collect_time_ms": media_collect_time,
            },
        )

    raw_text = (message.text or message.caption or "").strip()

    # Check for YouTube URLs in the text
    from app.services.media import extract_youtube_urls

    youtube_urls = extract_youtube_urls(raw_text)
    if youtube_urls:
        LOGGER.info(
            "Detected %d YouTube URL(s) in message %s",
            len(youtube_urls),
            message.message_id,
        )
        # Add YouTube URLs as file_uri media items
        for url in youtube_urls:
            media_raw.append(
                {
                    "file_uri": url,
                    "kind": "video",
                    "mime": "video/mp4",  # YouTube videos
                }
            )

    # Build Gemini-compatible media parts
    media_parts = gemini_client.build_media_parts(media_raw, logger=LOGGER)

    # Log media types for debugging
    if media_parts:
        media_type_counts = {}
        for part in media_parts:
            if "inline_data" in part:
                mime = part["inline_data"].get("mime_type", "unknown")
                media_type_counts[mime] = media_type_counts.get(mime, 0) + 1
            elif "file_data" in part:
                media_type_counts["file_uri"] = media_type_counts.get("file_uri", 0) + 1
        LOGGER.debug(
            "Current message media types: %s (total: %d)",
            media_type_counts,
            len(media_parts),
        )

    # Limit number of media parts for the current message to prevent overload
    trimmed_media_count = 0
    try:
        max_current_media = getattr(
            settings,
            "gemini_max_media_items_current",
            getattr(settings, "gemini_max_media_items", 28),
        )
        if isinstance(max_current_media, int) and max_current_media > 0:
            if len(media_parts) > max_current_media:
                trimmed_media_count = len(media_parts) - max_current_media
                media_parts = media_parts[:max_current_media]
                LOGGER.info(
                    "Trimmed %d media part(s) from current message (limit: %d)",
                    trimmed_media_count,
                    max_current_media,
                )
    except Exception:
        LOGGER.debug(
            "Media trim step skipped due to configuration error", exc_info=True
        )

    # Check for poll voting (numbers like "1", "2", "1,3", etc.)
    poll_vote_result = await _handle_poll_vote_attempt(
        raw_text, chat_id, thread_id, user_id
    )
    if poll_vote_result:
        # FORMATTING DISABLED: Sending plain text, relying on system prompt
        # poll_formatted = _format_for_telegram(poll_vote_result)
        await message.reply(poll_vote_result, parse_mode=ParseMode.HTML)
        return

    reply_context = None
    reply_media_parts: list[dict[str, Any]] | None = None
    if message.reply_to_message:
        reply = message.reply_to_message
        key = (reply.chat.id, reply.message_thread_id)
        stored_queue = _RECENT_CONTEXT.get(key)
        if stored_queue:
            for item in reversed(stored_queue):
                if item.get("message_id") == reply.message_id:
                    reply_context = item
                    if item.get("media_parts"):
                        reply_media_parts_for_block = item.get("media_parts")
                    break

        # If we have a reply but no cached context, or cached context has no media,
        # try to collect media directly from the reply message
        if not reply_context or not reply_context.get("media_parts"):
            try:
                reply_media_raw = await collect_media_parts(bot, reply)
                if reply_media_raw:
                    reply_media_raw_for_block = reply_media_raw
                    reply_media_parts = gemini_client.build_media_parts(
                        reply_media_raw, logger=LOGGER
                    )
                    if reply_media_parts:
                        reply_media_parts_for_block = reply_media_parts
                        # Create or update reply_context with media
                        if not reply_context:
                            reply_text = _extract_text(reply)
                            reply_context = {
                                "ts": (
                                    int(reply.date.timestamp())
                                    if reply.date
                                    else int(time.time())
                                ),
                                "message_id": reply.message_id,
                                "user_id": (
                                    reply.from_user.id if reply.from_user else None
                                ),
                                "name": (
                                    reply.from_user.full_name
                                    if reply.from_user
                                    else None
                                ),
                                "username": _normalize_username(
                                    reply.from_user.username
                                    if reply.from_user
                                    else None
                                ),
                                "text": reply_text or _summarize_media(reply_media_raw),
                                "excerpt": (reply_text or "")[:200] or None,
                                "media_parts": reply_media_parts,
                            }
                        else:
                            # Update existing context with media
                            reply_context["media_parts"] = reply_media_parts

                        LOGGER.debug(
                            "Collected %d media part(s) from reply message %s",
                            len(reply_media_parts),
                            reply.message_id,
                        )
            except Exception:
                LOGGER.exception(
                    "Failed to collect media from reply message %s", reply.message_id
                )

        # If still no reply_context but we have a reply message, create minimal context from reply
        if not reply_context:
            reply_text = _extract_text(reply)
            if reply_text or reply.from_user:
                reply_context = {
                    "ts": (
                        int(reply.date.timestamp()) if reply.date else int(time.time())
                    ),
                    "message_id": reply.message_id,
                    "user_id": (reply.from_user.id if reply.from_user else None),
                    "name": (reply.from_user.full_name if reply.from_user else None),
                    "username": _normalize_username(
                        reply.from_user.username if reply.from_user else None
                    ),
                    "text": reply_text,
                    "excerpt": (reply_text or "")[:200] if reply_text else None,
                }

        if reply_context:
            reply_context_for_block = dict(reply_context)

    # Always store reply context for history injection if enabled and present
    if reply_context and settings.include_reply_excerpt:
        reply_context_for_history = reply_context

    if use_system_context_block:
        target_thread_for_block = (
            thread_id
            if (settings.system_context_block_thread_only and thread_id is not None)
            else None
        )
        max_messages_for_block = settings.system_context_block_max_messages
        try:
            history_messages_for_block = await store.recent(
                chat_id=chat_id,
                thread_id=target_thread_for_block,
                max_messages=max_messages_for_block,
            )
        except Exception:
            LOGGER.exception("Failed to load history for system context block")
            history_messages_for_block = []

    fallback_context = reply_context or _get_recent_context(chat_id, thread_id)
    fallback_text = fallback_context.get("text") if fallback_context else None
    media_summary = _summarize_media(media_raw)

    user_meta = _build_user_metadata(
        message,
        chat_id,
        thread_id,
        fallback_context=fallback_context,
    )

    # Build user parts with better context handling
    user_parts = _build_clean_user_parts(
        raw_text=raw_text,
        media_summary=media_summary,
        fallback_text=fallback_text,
        media_parts=media_parts,
        fallback_context=fallback_context,
    )

    # If we had to trim media attachments, add a short note for the model
    if trimmed_media_count > 0 and media_summary:
        user_parts.append(
            {
                "text": f"{media_summary} (деякі прикріплення опущено для ефективності)",
            }
        )

    # Add inline reply excerpt if enabled and available (after metadata)
    if settings.include_reply_excerpt and reply_context:
        reply_text = reply_context.get("text") or reply_context.get("excerpt")
        if reply_text:
            # Truncate to configured max
            max_chars = settings.reply_excerpt_max_chars
            excerpt = reply_text[:max_chars]
            if len(reply_text) > max_chars:
                excerpt = excerpt + "..."

            # Build inline snippet with username if available
            reply_username = reply_context.get("name") or reply_context.get("username")
            if reply_username:
                inline_reply = f"[↩︎ Відповідь на {reply_username}: {excerpt}]"
            else:
                inline_reply = f"[↩︎ Відповідь на: {excerpt}]"

            # Insert after metadata (which is at index 0)
            user_parts.insert(1, {"text": inline_reply})

            telemetry.increment_counter("context.reply_included_text")
            LOGGER.debug(
                "Added inline reply excerpt to user parts (first %d chars)",
                len(excerpt),
            )

    # Always prepend speaker header and metadata for Gemini context
    speaker_header = format_speaker_header(
        role="user",
        sender_id=user_meta.get("user_id"),
        name=user_meta.get("name"),
        username=user_meta.get("username"),
        is_bot=user_meta.get("is_bot"),
    )
    metadata_block = format_metadata(user_meta)
    prefix_parts: list[dict[str, Any]] = []
    if speaker_header:
        prefix_parts.append({"text": speaker_header})
    if metadata_block:
        prefix_parts.append({"text": metadata_block})
    if prefix_parts:
        user_parts[0:0] = prefix_parts

    text_content = raw_text or media_summary or fallback_text or ""

    embedding_start = time.time()
    user_embedding = await gemini_client.embed_text(text_content)
    embedding_time = int((time.time() - embedding_start) * 1000)
    perf_timings["embedding_time_ms"] = embedding_time

    from_user = message.from_user
    db_add_start = time.time()
    await store.add_message(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text=text_content,
        media=media_parts,
        metadata=user_meta,
        embedding=user_embedding,
        retention_days=settings.retention_days,
        sender=MessageSender(
            role="user",
            name=from_user.full_name if from_user else None,
            username=_normalize_username(from_user.username) if from_user else None,
            is_bot=from_user.is_bot if from_user else None,
        ),
    )
    db_add_time = int((time.time() - db_add_start) * 1000)
    perf_timings["db_add_time_ms"] = db_add_time
    if db_add_time > 500:  # Log if DB operation takes more than 500ms
        LOGGER.info(
            "Database add_message completed",
            extra={
                "chat_id": chat_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "db_time_ms": db_add_time,
            },
        )

    # Phase 4.2: Track message for episode creation
    if settings.auto_create_episodes and episode_monitor is not None:
        try:
            await episode_monitor.track_message(
                chat_id=chat_id,
                thread_id=thread_id,
                message={
                    "id": message.message_id,
                    "user_id": user_id,
                    "text": text_content,
                    "timestamp": int(time.time()),
                    "chat_id": chat_id,
                },
            )
            LOGGER.debug(
                "Message tracked for episode creation",
                extra={"chat_id": chat_id, "message_id": message.message_id},
            )
        except Exception as e:
            LOGGER.error(
                "Failed to track message for episodes",
                exc_info=e,
                extra={"chat_id": chat_id, "message_id": message.message_id},
            )

    # Centralized search tool implementation
    search_messages_tool = create_search_messages_tool(
        store=store, gemini_client=gemini_client, chat_id=chat_id, thread_id=thread_id
    )

    # Centralized tool definitions (registry) with caching
    # Note: Memory tools are already included in build_tool_definitions_registry
    # Note: Admin status affects moderation tool availability, so we don't cache across different admin statuses
    tool_definitions: list[dict[str, Any]] = build_tool_definitions_registry(
        settings, is_admin=is_admin
    )

    # Enrich with user profile context
    # Note: If using multi-level context, profile is already included
    if not use_multi_level:
        profile_context = await _enrich_with_user_profile(
            profile_store=profile_store,
            user_id=user_id,
            chat_id=chat_id,
            settings=settings,
        )
    else:
        profile_context = None

    # Add current timestamp to system prompt (Kyiv time)
    try:
        kyiv_tz = ZoneInfo("Europe/Kiev")
        current_time = datetime.now(kyiv_tz).strftime("%A, %B %d, %Y at %H:%M:%S")
    except Exception:
        # Fallback: add +3 hours to UTC for Kyiv time (EET/EEST)
        import datetime as dt

        utc_now = datetime.utcnow()
        kyiv_time = utc_now + dt.timedelta(hours=3)
        current_time = kyiv_time.strftime("%A, %B %d, %Y at %H:%M:%S")

    timestamp_context = f"\n\n# Current Time\n\nThe current time is: {current_time}"

    # System prompt caching (static persona only, dynamic persona disables cache)
    global _SYSTEM_PROMPT_CACHE, _SYSTEM_PROMPT_PERSONA_LOADER_CACHE, _SYSTEM_PROMPT_CHAT_ID_CACHE
    if "_SYSTEM_PROMPT_CACHE" not in globals():
        _SYSTEM_PROMPT_CACHE = None
        _SYSTEM_PROMPT_PERSONA_LOADER_CACHE = None
        _SYSTEM_PROMPT_CHAT_ID_CACHE = None
    cacheable = persona_loader is None and not prompt_manager
    if cacheable and _SYSTEM_PROMPT_CACHE is not None:
        base_system_prompt = _SYSTEM_PROMPT_CACHE
    else:
        base_system_prompt = SYSTEM_PERSONA
        # Use persona from loader if available
        if persona_loader is not None:
            try:
                base_system_prompt = persona_loader.get_system_prompt(
                    current_time=current_time
                )
            except Exception as e:
                LOGGER.warning(
                    f"Failed to get system prompt from persona loader, using default: {e}"
                )
        if prompt_manager:
            try:
                custom_prompt = await prompt_manager.get_active_prompt(chat_id=chat_id)
                if custom_prompt:
                    base_system_prompt = custom_prompt.prompt_text
                    LOGGER.debug(
                        f"Using custom system prompt: version={custom_prompt.version}, "
                        f"scope={custom_prompt.scope}, chat_id={custom_prompt.chat_id}"
                    )
            except Exception as e:
                LOGGER.warning(
                    f"Failed to fetch custom system prompt, using default: {e}"
                )
        if cacheable:
            _SYSTEM_PROMPT_CACHE = base_system_prompt
            _SYSTEM_PROMPT_PERSONA_LOADER_CACHE = persona_loader
            _SYSTEM_PROMPT_CHAT_ID_CACHE = chat_id
    # If we have profile context, inject it into the system prompt
    system_prompt_with_profile = base_system_prompt + timestamp_context

    # Format context for Gemini
    if use_multi_level and context_manager and context_assembly:
        # Check if compact format is enabled
        if settings.enable_compact_conversation_format and not use_system_context_block:
            # Use compact plain text format (70-80% token savings)
            formatted_context = context_manager.format_for_gemini_compact(
                context_assembly
            )

            # In compact format, conversation goes in user_parts, not history
            conversation_text = formatted_context["conversation_text"]
            history = []  # No separate history, all in current message

            # Append multi-level system context
            if formatted_context.get("system_context"):
                system_prompt_with_profile = (
                    base_system_prompt
                    + timestamp_context
                    + "\n\n"
                    + formatted_context["system_context"]
                )

            # Replace user_parts with compact conversation text
            # Add current message to conversation text
            current_message_line = ""
            if raw_text or media_summary:
                from app.services.conversation_formatter import format_message_compact

                current_username = (
                    message.from_user.full_name if message.from_user else "User"
                )
                current_user_id = message.from_user.id if message.from_user else None

                # Extract reply information for compact format
                reply_to_user_id = None
                reply_to_username = None
                reply_excerpt = None

                if settings.include_reply_excerpt and message.reply_to_message:
                    reply_to_msg = message.reply_to_message
                    if reply_to_msg.from_user:
                        reply_to_user_id = reply_to_msg.from_user.id
                        reply_to_username = reply_to_msg.from_user.full_name

                    # Get excerpt from reply context or extract directly
                    if reply_context and reply_context.get("excerpt"):
                        reply_excerpt = reply_context["excerpt"]
                    else:
                        reply_text = _extract_text(reply_to_msg)
                        if reply_text:
                            max_chars = min(
                                settings.reply_excerpt_max_chars, 160
                            )  # Compact format uses shorter excerpts
                            reply_excerpt = reply_text[:max_chars]
                            if len(reply_text) > max_chars:
                                reply_excerpt = reply_excerpt + "..."

                current_message_line = format_message_compact(
                    user_id=current_user_id,
                    username=current_username,
                    text=raw_text or media_summary or "",
                    media_description=(media_summary or "") if media_parts else "",
                    reply_to_user_id=reply_to_user_id,
                    reply_to_username=reply_to_username,
                    reply_excerpt=reply_excerpt,
                )

            # Combine conversation history with current message
            if conversation_text and current_message_line:
                full_conversation = (
                    f"{conversation_text}\n{current_message_line}\n[RESPOND]"
                )
            elif current_message_line:
                full_conversation = f"{current_message_line}\n[RESPOND]"
            else:
                full_conversation = conversation_text or "[RESPOND]"

            user_parts = [{"text": full_conversation}]

            # Add media with priority: current message first, then reply media, then historical
            max_media_total = (
                settings.gemini_max_media_items
            )  # Default 28 (Gemini API limit)
            # Strict behavior: do not include historical media in compact mode;
            # rely on text markers for awareness and only process media for current/replied messages
            max_historical = 0
            max_videos = settings.gemini_max_video_items  # Default 1

            all_media = []
            video_count = 0
            video_descriptions = []  # Collect descriptions for videos we skip

            # Priority 1: Current message media (highest priority)
            if media_parts:
                for media_item in media_parts:
                    mime = media_item.get("mime", "")
                    is_video = mime.startswith("video/")

                    if is_video and video_count >= max_videos:
                        # Skip this video but try to get description from history
                        LOGGER.debug(
                            f"Skipping video (limit {max_videos} reached): {mime}"
                        )
                        continue

                    all_media.append(media_item)
                    if is_video:
                        video_count += 1

            # Priority 2: Reply message media (if replying to older message not in context)
            reply_media_parts = []
            if reply_context_for_history and reply_context_for_history.get(
                "media_parts"
            ):
                # Check if reply message is already in historical_media
                reply_msg_id = reply_context_for_history.get("message_id")
                historical_media = formatted_context.get("historical_media", [])

                # Check if reply media is already in historical_media by comparing message_id in metadata
                reply_media_in_history = False
                # For now, we'll always include reply media to ensure it's visible
                # (historical_media doesn't track message_id, so we can't reliably detect duplicates)

                if not reply_media_in_history:
                    reply_media_parts = reply_context_for_history["media_parts"]
                    for media_item in reply_media_parts:
                        mime = media_item.get("mime", "")
                        is_video = mime.startswith("video/")

                        if is_video and video_count >= max_videos:
                            # Skip this video but try to get description
                            if reply_msg_id:
                                description = await _get_video_description_from_history(
                                    store=store,
                                    chat_id=chat_id,
                                    thread_id=thread_id,
                                    message_id=reply_msg_id,
                                )
                                if description:
                                    video_descriptions.append(
                                        f"[Раніше про відео в повідомленні {reply_msg_id}]: {description[:200]}"
                                    )
                                LOGGER.debug(
                                    f"Skipping reply video (limit {max_videos} reached), description: {bool(description)}"
                                )
                            continue

                        all_media.append(media_item)
                        if is_video:
                            video_count += 1

                    LOGGER.debug(
                        "Added %d media items from replied message (message_id=%s), videos: %d",
                        len([m for m in reply_media_parts if m in all_media]),
                        reply_msg_id,
                        video_count,
                    )

            # Priority 3: Historical media from context (limited to max_historical)
            historical_media = formatted_context.get("historical_media", [])
            if not use_system_context_block and historical_media and max_historical > 0:
                remaining_slots = min(
                    max_media_total - len(all_media),  # Don't exceed total limit
                    max_historical,  # Don't exceed historical limit
                )
                if remaining_slots > 0:
                    # Add historical media up to remaining slots, respecting video limit
                    historical_kept = 0
                    for media_item in historical_media[:remaining_slots]:
                        mime = media_item.get("mime", "")
                        is_video = mime.startswith("video/")

                        if is_video and video_count >= max_videos:
                            # Skip this video - no description available for historical media
                            # (we don't track message_id in historical_media)
                            LOGGER.debug(
                                f"Skipping historical video (limit {max_videos} reached)"
                            )
                            continue

                        all_media.append(media_item)
                        historical_kept += 1
                        if is_video:
                            video_count += 1

                    # Telemetry: Track historical media usage
                    if historical_kept > 0:
                        telemetry.increment_counter(
                            "context.historical_media_included", historical_kept
                        )

                    historical_dropped = len(historical_media) - historical_kept
                    if historical_dropped > 0:
                        telemetry.increment_counter(
                            "context.historical_media_dropped", historical_dropped
                        )
                        LOGGER.debug(
                            "Historical media: %d kept, %d dropped (video_limit: %d, historical_limit: %d, total_limit: %d)",
                            historical_kept,
                            historical_dropped,
                            max_videos,
                            max_historical,
                            max_media_total,
                        )
                else:
                    # No room for historical media
                    telemetry.increment_counter(
                        "context.historical_media_dropped", len(historical_media)
                    )
            elif (
                not use_system_context_block
                and historical_media
                and max_historical == 0
            ):
                # Historical media disabled via config
                telemetry.increment_counter(
                    "context.historical_media_dropped", len(historical_media)
                )
                LOGGER.debug(
                    "Historical media disabled (GEMINI_MAX_MEDIA_ITEMS_HISTORICAL=0), dropped %d items",
                    len(historical_media),
                )

            # Add video descriptions to conversation text if we skipped any
            if video_descriptions:
                conversation_with_descriptions = (
                    full_conversation + "\n\n" + "\n".join(video_descriptions)
                )
                user_parts[0] = {"text": conversation_with_descriptions}
                LOGGER.debug(
                    f"Added {len(video_descriptions)} video descriptions to conversation"
                )

            # Add all media to user_parts (respecting total limit)
            if all_media:
                user_parts.extend(all_media[:max_media_total])

                if len(all_media) > max_media_total:
                    telemetry.increment_counter("context.media_limit_exceeded")
                    LOGGER.warning(
                        "Media limit exceeded: %d items, kept first %d (current: %d, reply: %d, historical: %d, videos: %d)",
                        len(all_media),
                        max_media_total,
                        len(media_parts) if media_parts else 0,
                        len(reply_media_parts),
                        len(
                            [
                                m
                                for m in all_media
                                if m.get("mime", "").startswith("video/")
                            ]
                        ),
                        video_count,
                    )

            LOGGER.debug(
                "Using compact conversation format for Gemini",
                extra={
                    "conversation_lines": len(full_conversation.split("\n")),
                    "system_context_length": (
                        len(formatted_context.get("system_context") or "")
                    ),
                    "estimated_tokens": formatted_context.get("token_count", 0),
                },
            )
        else:
            # Use traditional JSON format
            formatted_context = context_manager.format_for_gemini(context_assembly)
            history = formatted_context["history"]

            # Append multi-level system context
            if formatted_context.get("system_context"):
                system_prompt_with_profile = (
                    base_system_prompt
                    + timestamp_context
                    + "\n\n"
                    + formatted_context["system_context"]
                )

            LOGGER.debug(
                "Using multi-level context for Gemini",
                extra={
                    "history_length": len(history),
                    "system_context_length": (
                        len(formatted_context.get("system_context") or "")
                    ),
                    "total_tokens": formatted_context.get("token_count", 0),
                },
            )
    elif profile_context:
        # Fallback: Simple history + profile context
        system_prompt_with_profile = (
            base_system_prompt + timestamp_context + profile_context
        )

    # JSON format path: strip media from history and add reply media to user_parts instead
    if (not settings.enable_compact_conversation_format) and history:
        try:
            new_history: list[dict[str, Any]] = []
            removed_media_count = 0
            for msg in history:
                parts = msg.get("parts", [])
                new_parts: list[dict[str, Any]] = []
                for part in parts:
                    if isinstance(part, dict) and (
                        ("inline_data" in part) or ("file_data" in part)
                    ):
                        # Drop historical media to save tokens; awareness preserved via text content
                        removed_media_count += 1
                        continue
                    new_parts.append(part)
                if new_parts:
                    new_history.append({**msg, "parts": new_parts})
                else:
                    # Keep a tiny placeholder to avoid empty message
                    new_history.append({**msg, "parts": [{"text": "[media omitted]"}]})

            if removed_media_count > 0:
                telemetry.increment_counter(
                    "context.historical_media_dropped", removed_media_count
                )
                LOGGER.debug(
                    "Stripped %d media item(s) from JSON history to enforce reply-only media",
                    removed_media_count,
                )
            history = new_history
        except Exception:
            LOGGER.exception(
                "Failed to strip media from history; proceeding with original history"
            )

    # Inject reply context with media into history if needed
    # This ensures media from replied-to messages is visible even if outside context window
    if reply_context_for_history:
        reply_msg_id = reply_context_for_history.get("message_id")
        # Check if this message is already in history
        message_in_history = False
        if reply_msg_id:
            for hist_msg in history:
                parts = hist_msg.get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text = part["text"]
                        if f"message_id={reply_msg_id}" in text:
                            message_in_history = True
                            break
                if message_in_history:
                    break

        # If not in history, inject it
        if not message_in_history:
            reply_parts: list[dict[str, Any]] = []

            # Add metadata if available
            reply_meta = {
                "chat_id": chat_id,
                "message_id": reply_msg_id,
            }
            if reply_context_for_history.get("user_id"):
                reply_meta["user_id"] = reply_context_for_history["user_id"]
            if reply_context_for_history.get("name"):
                reply_meta["name"] = reply_context_for_history["name"]
            if reply_context_for_history.get("username"):
                reply_meta["username"] = reply_context_for_history["username"]
            if reply_context_for_history.get("is_bot") is not None:
                reply_meta["is_bot"] = reply_context_for_history["is_bot"]

            reply_header = format_speaker_header(
                role=reply_context_for_history.get("role") or "user",
                sender_id=reply_meta.get("user_id"),
                name=reply_meta.get("name"),
                username=reply_meta.get("username"),
                is_bot=reply_meta.get("is_bot"),
            )
            if reply_header:
                reply_parts.append({"text": reply_header})

            meta_block = format_metadata(reply_meta)
            if meta_block:
                reply_parts.append({"text": meta_block})

            # Add text if available
            if reply_context_for_history.get("text"):
                reply_parts.append({"text": reply_context_for_history["text"]})

            # Do NOT add media parts to history in JSON mode; reply media will be attached to user_parts below

            # Insert at beginning of history (chronologically first)
            if reply_parts:
                history.insert(0, {"role": "user", "parts": reply_parts})

                # Track telemetry
                if reply_context_for_history.get("media_parts"):
                    telemetry.increment_counter("context.reply_included_media")

                LOGGER.debug(
                    "Injected reply context text/meta into history for message %s",
                    reply_msg_id,
                )

    # In JSON mode, attach reply media directly to user_parts (respecting total media cap)
    if (not settings.enable_compact_conversation_format) and reply_context_for_history:
        try:
            reply_media = reply_context_for_history.get("media_parts") or []
            if reply_media:
                # Count media already in user_parts
                current_media_count = sum(
                    1
                    for p in user_parts
                    if isinstance(p, dict) and ("inline_data" in p or "file_data" in p)
                )
                max_total = settings.gemini_max_media_items
                remaining = max(0, max_total - current_media_count)
                if remaining > 0:
                    to_add = reply_media[:remaining]
                    user_parts.extend(to_add)
                    dropped = len(reply_media) - len(to_add)
                    if dropped > 0:
                        user_parts.append(
                            {
                                "text": "[Деякі прикріплення з відповіді опущено для ефективності]",
                            }
                        )
                    telemetry.increment_counter(
                        "context.reply_included_media", len(to_add)
                    )
                    LOGGER.debug(
                        "Attached %d reply media item(s) to user_parts (dropped: %d)",
                        len(to_add),
                        max(dropped, 0),
                    )
        except Exception:
            LOGGER.exception("Failed to attach reply media to user_parts in JSON mode")

    system_context_block_text = None
    if use_system_context_block:
        trigger_text_source = raw_text or fallback_text or ""
        if not trigger_text_source and media_summary:
            trigger_text_source = media_summary

        system_context_block_text = _build_system_context_block(
            settings=settings,
            history_messages=history_messages_for_block,
            trigger_meta=user_meta,
            trigger_text=trigger_text_source,
            trigger_raw_media=media_raw,
            trigger_media_parts=media_parts,
            reply_context=reply_context_for_block,
            reply_raw_media=reply_media_raw_for_block,
            reply_media_parts=reply_media_parts_for_block,
            chat_id=chat_id,
            thread_id=thread_id,
        )

        if system_context_block_text:
            system_prompt_with_profile = (
                system_prompt_with_profile + "\n\n" + system_context_block_text
            )
            history = []

            # Inject reply media into user_parts when using system context block
            # System context block only includes text markers, not actual media data
            if reply_media_parts_for_block:
                current_media_count = sum(
                    1
                    for p in user_parts
                    if isinstance(p, dict) and ("inline_data" in p or "file_data" in p)
                )
                max_total = settings.gemini_max_media_items
                remaining = max(0, max_total - current_media_count)
                if remaining > 0:
                    to_add = reply_media_parts_for_block[:remaining]
                    user_parts.extend(to_add)
                    dropped = len(reply_media_parts_for_block) - len(to_add)
                    LOGGER.debug(
                        "Added %d reply media item(s) for system context block mode (dropped: %d)",
                        len(to_add),
                        max(dropped, 0),
                    )
                    telemetry.increment_counter(
                        "context.reply_media_system_block", len(to_add)
                    )

    # Track which tools were used in this request
    tools_used_in_request: list[str] = []

    # Centralized callbacks (registry) with tracking
    # Always build tool callbacks - memory_repo can be None and will be handled gracefully
    tracked_tool_callbacks = build_tool_callbacks_registry(
        settings=settings,
        store=store,
        gemini_client=gemini_client,
        profile_store=profile_store,
        memory_repo=memory_repo,  # Can be None, memory tools will be skipped
        chat_id=chat_id,
        thread_id=thread_id,
        message_id=message.message_id,
        tools_used_tracker=tools_used_in_request,
        user_id=user_id,
        bot=bot,
        message=message,
        image_gen_service=image_gen_service,
        feature_limiter=feature_limiter,
        is_admin=is_admin,
        telegram_service=telegram_service,
    )
    # Web search, image tools, and memory tool callbacks are provided by registry

    # Extract specific tool callbacks for fallback usage
    edit_image_tool = tracked_tool_callbacks.get("edit_image")
    generate_image_tool = tracked_tool_callbacks.get("generate_image")

    # Bot Self-Learning: Track generation timing
    response_time_ms = 0  # Initialize in case of error

    # NOTE: Deterministic memory capture DISABLED per user request (2025-10-26)
    # Previously intercepted "запам'ятай/remember" patterns
    # Now delegating all memory operations to LLM tool calling
    if False:  # DISABLED: Deterministic memory capture
        # Deterministic memory capture: handle explicit "remember" commands without LLM
        # This avoids tool-call loops where the model recalls instead of storing.
        try:
            if settings.enable_tool_based_memory and memory_repo is not None:
                text_for_intent = (raw_text or "").strip()
                if text_for_intent:
                    # Remove bot mention and leading slash commands
                    if bot_username:
                        text_for_intent = re.sub(
                            rf"@{re.escape(bot_username)}\\b",
                            "",
                            text_for_intent,
                            flags=re.IGNORECASE,
                        ).strip()
                    if text_for_intent.startswith("/"):
                        text_for_intent = text_for_intent[1:].strip()

                    # Match explicit remember intents (UA + EN)
                    # Supports different apostrophes: ' and ’
                    remember_patterns = [
                        r"^(?:запам['’]?ятай|пам['’]?ятай|запиши)\b\s*(?:що|шо)?\s*[:\-]?\s*(.+)",
                        r"^remember\b\s*(?:that)?\s*[:\-]?\s*(.+)",
                    ]

                    memory_text: str | None = None
                    for pat in remember_patterns:
                        m = re.search(pat, text_for_intent, flags=re.IGNORECASE)
                        if m:
                            candidate = (m.group(1) or "").strip()
                            # Avoid capturing empty or trivial strings
                            if len(candidate) >= 3:
                                memory_text = candidate
                                break

                    # If we didn't match the capturing group but the message starts with the intent
                    # fall back to using the rest of the message after the trigger word(s)
                    if memory_text is None:
                        starts_with_triggers = [
                            r"^(?:запам['’]?ятай|пам['’]?ятай|запиши)\b",
                            r"^remember\b",
                        ]
                        for trig in starts_with_triggers:
                            mt = re.sub(
                                trig, "", text_for_intent, flags=re.IGNORECASE
                            ).strip()
                            if mt and len(mt) >= 3:
                                memory_text = mt
                                break

                    if memory_text:
                        remember_cb = tracked_tool_callbacks.get("remember_memory")
                        if remember_cb is not None:
                            LOGGER.info(
                                "Rule-based memory intercept: storing memory without LLM",
                                extra={
                                    "chat_id": chat_id,
                                    "user_id": user_id,
                                    "len": len(memory_text),
                                },
                            )
                            try:
                                raw = await remember_cb(
                                    {"user_id": user_id, "memory_text": memory_text}
                                )
                                payload = json.loads(raw)
                            except Exception:
                                LOGGER.exception("remember_memory intercept failed")
                                payload = {
                                    "status": "error",
                                    "message": "Не вийшло запам'ятати.",
                                }

                            # Compose immediate confirmation and persist bot turn, then return
                            if payload.get("status") == "success":
                                reply_confirm = "Запам’ятав."
                                tools_used_in_request.append("remember_memory")
                            else:
                                reply_confirm = (
                                    payload.get("message") or "Не вийшло запам'ятати."
                                )

                            # Send reply now and store like normal
                            response_message = await message.reply(
                                reply_confirm,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )

                            model_meta = _build_model_metadata(
                                response=response_message,
                                chat_id=chat_id,
                                thread_id=thread_id,
                                bot_username=bot_username,
                                original=message,
                                original_text=text_for_intent,
                            )
                            bot_display_name = model_meta.get("name") or "gryag"

                            model_embedding = await gemini_client.embed_text(
                                reply_confirm
                            )

                            await store.add_message(
                                chat_id=chat_id,
                                thread_id=thread_id,
                                user_id=None,
                                role="model",
                                text=reply_confirm,
                                media=None,
                                metadata=model_meta,
                                embedding=model_embedding,
                                retention_days=settings.retention_days,
                                sender=MessageSender(
                                    role="assistant",
                                    name=bot_display_name,
                                    username=_normalize_username(bot_username),
                                    is_bot=True,
                                ),
                            )

                            # Short-circuit the rest of the handler
                            return
        except Exception:
            # Non-fatal: fall back to normal flow if the interceptor fails
            LOGGER.exception(
                "Memory intercept path error; continuing with normal generation"
            )

    async with typing_indicator(bot, chat_id):
        generation_start_time = time.time()

        # Log what we're sending to Gemini
        LOGGER.info(
            f"Sending to Gemini: history_length={len(history)}, "
            f"user_parts_count={len(user_parts)}, "
            f"tools_count={len(tool_definitions) if tool_definitions else 0}, "
            f"system_prompt_length={len(system_prompt_with_profile) if system_prompt_with_profile else 0}"
        )

        # Log first user part (text only, not media)
        if user_parts:
            first_part = user_parts[0]
            if isinstance(first_part, dict) and "text" in first_part:
                LOGGER.info(f"First user part text: {first_part['text'][:200]}")

            # Log media breakdown
            media_count = sum(
                1
                for p in user_parts
                if isinstance(p, dict) and ("inline_data" in p or "file_data" in p)
            )
            if media_count > 0:
                LOGGER.info(f"Sending {media_count} media items to Gemini")

        thinking_message_sent = False
        thinking_placeholder_sent = False
        thinking_msg: Message | None = None

        if settings.show_thinking_to_users:
            LOGGER.info("Thinking placeholder enabled; sending immediate reply")
            try:
                thinking_msg = await message.reply("🤔 Думаю...")
            except Exception as exc:
                LOGGER.warning(f"Failed to send thinking placeholder: {exc}")
                thinking_msg = None
            else:
                thinking_placeholder_sent = True
                thinking_message_sent = True
                # Placeholder sent; response generation will continue without blocking

        try:
            gemini_start = time.time()
            response_data = await gemini_client.generate(
                system_prompt=system_prompt_with_profile,
                history=history,
                user_parts=user_parts,
                tools=tool_definitions,
                tool_callbacks=tracked_tool_callbacks,  # type: ignore[arg-type]
            )
            gemini_time = int((time.time() - gemini_start) * 1000)
            perf_timings["gemini_time_ms"] = gemini_time
            reply_text = response_data.get("text", "")
            thinking_text = (response_data.get("thinking", "") or "").strip()

            LOGGER.info(
                "Gemini API call completed",
                extra={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "gemini_time_ms": gemini_time,
                    "response_length": len(reply_text),
                },
            )

            # If Gemini returned only thinking content, retry without thinking enabled
            if (not reply_text or reply_text.isspace()) and thinking_text:
                LOGGER.info(
                    "Gemini returned reasoning without final text; retrying without thinking output"
                )
                gemini_retry_start = time.time()
                response_data = await gemini_client.generate(
                    system_prompt=system_prompt_with_profile,
                    history=history,
                    user_parts=user_parts,
                    tools=tool_definitions,
                    tool_callbacks=tracked_tool_callbacks,  # type: ignore[arg-type]
                    include_thinking=False,
                )
                gemini_retry_time = int((time.time() - gemini_retry_start) * 1000)
                gemini_time += gemini_retry_time  # Add retry time to total
                perf_timings["gemini_time_ms"] = gemini_time  # Update with total
                reply_text = response_data.get("text", "")
                thinking_text = (response_data.get("thinking", "") or "").strip()

                LOGGER.info(
                    "Gemini API retry completed",
                    extra={
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "gemini_retry_time_ms": gemini_retry_time,
                        "total_gemini_time_ms": gemini_time,
                    },
                )

            # Handle responses with thinking content (show reasoning process)
            show_thinking = settings.show_thinking_to_users and bool(thinking_text)
            if show_thinking:
                LOGGER.info(
                    "Gemini returned thinking content, showing reasoning process to user"
                )
                if thinking_msg is None:
                    try:
                        thinking_msg = await message.reply("🤔 Думаю...")
                    except Exception as exc:
                        LOGGER.warning(f"Failed to send thinking placeholder: {exc}")
                        thinking_msg = None
                if thinking_msg is not None:
                    thinking_display = _safe_html_payload(
                        thinking_text,
                        wrap=("<i>", "</i>"),
                        ellipsis=True,
                    )

                    try:
                        await thinking_msg.edit_text(
                            thinking_display,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    except Exception as exc:
                        LOGGER.warning(f"Failed to edit thinking message: {exc}")
                        thinking_message_sent = False
                        thinking_placeholder_sent = False
                    else:
                        # Thinking content shown; continue to generate final response
                        thinking_placeholder_sent = True
                        thinking_message_sent = True
                else:
                    thinking_message_sent = False
                    thinking_placeholder_sent = False
            elif thinking_text:
                LOGGER.debug(
                    "Thinking content suppressed (length=%s)", len(thinking_text)
                )
                thinking_message_sent = thinking_placeholder_sent
            else:
                thinking_message_sent = thinking_placeholder_sent

            # Check if tools were disabled during generation (API overload fallback)
            if gemini_client.tools_fallback_disabled and tool_definitions:
                LOGGER.warning(
                    "Tools were disabled during Gemini call due to API errors. "
                    "Some features (image generation, web search, etc.) may not work."
                )
                # Check if user asked for a tool feature
                user_text_lower = (text_content or "").lower()
                tool_keywords = [
                    "намалюй",
                    "малюнок",
                    "зображення",
                    "картинк",
                    "фото",
                    "generate",
                    "draw",
                    "image",
                    "picture",
                    "photo",
                    "пошук",
                    "знайди",
                    "search",
                    "погода",
                    "weather",
                ]
                if any(keyword in user_text_lower for keyword in tool_keywords):
                    # User likely asked for a tool feature - provide helpful error
                    if not reply_text or reply_text.isspace():
                        # Empty response - replace entirely
                        reply_text = (
                            "⚠️ Зараз API перевантажений і ця функція тимчасово недоступна. "
                            "Спробуй пізніше (через 5-10 хвилин)."
                        )
                    else:
                        # Prepend warning to existing response
                        reply_text = (
                            "⚠️ Зараз API перевантажений і деякі функції тимчасово недоступні. "
                            "Спробуй пізніше.\n\n" + reply_text
                        )

            # Calculate response time
            generation_end_time = time.time()
            response_time_ms = int((generation_end_time - generation_start_time) * 1000)

            telemetry.increment_counter("chat.reply_success")

            # Update user profile in background (fire-and-forget)
            asyncio.create_task(
                _update_user_profile_background(
                    profile_store=profile_store,
                    user_id=user_id,
                    chat_id=chat_id,
                    thread_id=thread_id,
                    display_name=(
                        message.from_user.full_name if message.from_user else None
                    ),
                    username=message.from_user.username if message.from_user else None,
                    settings=settings,
                )
            )
        except GeminiContentBlockedError as exc:
            telemetry.increment_counter("chat.content_blocked")
            LOGGER.warning(
                "Content blocked by Gemini: block_reason=%s, chat=%s, user=%s",
                exc.block_reason,
                chat_id,
                user_id,
            )
            # Provide a user-friendly message that's more helpful
            reply_text = (
                "Вибач, але мої фільтри безпеки не дозволили мені обробити це повідомлення. "
                "Спробуй переформулювати або відправити інше повідомлення."
            )
        except GeminiError:
            telemetry.increment_counter("chat.reply_failure")
            reply_text = _get_response(
                "error_fallback",
                persona_loader,
                ERROR_FALLBACK,
                bot_username=bot_username,
            )

        # Comprehensive response cleaning
        original_reply = reply_text
        reply_text = _clean_response_text(reply_text)

        # Log if we had to clean metadata from the response
        if original_reply != reply_text and original_reply:
            LOGGER.warning(
                "Cleaned metadata from response in chat %s: original_length=%d, cleaned_length=%d",
                chat_id,
                len(original_reply),
                len(reply_text),
            )
            LOGGER.debug(f"Original response contained: {original_reply[:200]}")

        # Fallback: force image generation/edit if Gemini returned nothing but the user clearly asked for it
        # OR if the response contained tool call descriptions that got filtered out
        tool_description_detected = False
        if original_reply and original_reply != reply_text:
            lower_original = original_reply.lower()
            tool_keywords = [
                "tool_call",
                "function_call",
                "generate_image",
                "edit_image",
                "search_web",
            ]
            tool_description_detected = any(
                kw in lower_original for kw in tool_keywords
            )

        if (
            settings.enable_image_generation
            and image_gen_service is not None
            and (
                (not reply_text or reply_text.isspace())
                or (tool_description_detected and len(reply_text) < 20)
            )
        ):
            if tool_description_detected:
                LOGGER.warning(
                    "Tool call description detected in response instead of actual tool call. Triggering fallback."
                )
            fallback_prompt = (raw_text or "").strip()
            if fallback_prompt:
                if bot_username:
                    fallback_prompt = re.sub(
                        rf"@{re.escape(bot_username)}\\b",
                        "",
                        fallback_prompt,
                        flags=re.IGNORECASE,
                    ).strip()
                if fallback_prompt.startswith("/"):
                    fallback_prompt = fallback_prompt[1:].strip()

            fallback_payload: dict[str, Any] | None = None
            fallback_success = False

            # Try edit fallback first if it looks like an image edit request
            if (
                fallback_prompt
                and "edit_image" not in tools_used_in_request
                and _looks_like_image_edit_request(fallback_prompt)
                and edit_image_tool is not None
            ):
                LOGGER.info(
                    "Gemini skipped edit_image tool; performing fallback edit",
                    extra={
                        "chat_id": chat_id,
                        "message_id": message.message_id,
                    },
                )
                try:
                    fallback_raw = await edit_image_tool({"prompt": fallback_prompt})
                    fallback_payload = json.loads(fallback_raw)
                except json.JSONDecodeError as exc:
                    LOGGER.error(f"Failed to parse edit_image response: {exc}")
                    fallback_payload = {
                        "success": False,
                        "error": "Помилка парсингу відповіді",
                    }
                except Exception as exc:
                    LOGGER.error(f"Fallback edit_image failed: {exc}", exc_info=True)
                    fallback_payload = {
                        "success": False,
                        "error": "Не вийшло відредагувати, сервіс знову тупив.",
                    }
                else:
                    tools_used_in_request.append("edit_image")

            # If edit fallback didn't trigger, try generation fallback
            if (
                not fallback_payload
                and fallback_prompt
                and "generate_image" not in tools_used_in_request
                and _looks_like_image_generation_request(fallback_prompt)
                and generate_image_tool is not None
            ):
                LOGGER.info(
                    "Gemini skipped generate_image tool; performing fallback generation",
                    extra={
                        "chat_id": chat_id,
                        "message_id": message.message_id,
                    },
                )
                try:
                    fallback_raw = await generate_image_tool(
                        {"prompt": fallback_prompt}
                    )
                    fallback_payload = json.loads(fallback_raw)
                except json.JSONDecodeError as exc:
                    LOGGER.error(f"Failed to parse generate_image response: {exc}")
                    fallback_payload = {
                        "success": False,
                        "error": "Помилка парсингу відповіді",
                    }
                except Exception as exc:
                    LOGGER.error(
                        f"Fallback generate_image failed: {exc}",
                        exc_info=True,
                    )
                    fallback_payload = {
                        "success": False,
                        "error": "Не вийшло намалювати, щось перегрілося.",
                    }
                else:
                    tools_used_in_request.append("generate_image")

            if fallback_payload:
                fallback_success = bool(fallback_payload.get("success"))
                reply_text = fallback_payload.get(
                    "message" if fallback_success else "error",
                    reply_text,
                )
                if fallback_success and not reply_text:
                    reply_text = "Готово. Лови картинку."
                if not fallback_success and not reply_text:
                    reply_text = "Нічого не вийшло — сервіс брикнувся."

        # Memory-tool specific fallback: if Gemini returned nothing but a memory tool was used, confirm action
        if (not reply_text or reply_text.isspace()) and tools_used_in_request:
            if "forget_all_memories" in tools_used_in_request:
                reply_text = "Готово. Я забув усе про тебе в цьому чаті."
            elif "remember_memory" in tools_used_in_request:
                reply_text = "Запам’ятав."
            elif "update_memory" in tools_used_in_request:
                reply_text = "Оновив."
            elif "forget_memory" in tools_used_in_request:
                reply_text = "Видалив."

        if not reply_text or reply_text.isspace():
            reply_text = _get_response(
                "empty_reply", persona_loader, EMPTY_REPLY, bot_username=bot_username
            )

        reply_trimmed = reply_text[:4096]
        # Convert markdown to HTML (handles bold, italic, strikethrough, spoilers)
        formatted = _format_for_telegram(reply_trimmed)
        # Telegram HTML mode handles newlines automatically - no br tags needed
        reply_payload = _safe_html_payload(formatted, already_html=True)

        response_message: Message | None = None

        if thinking_message_sent and thinking_msg is not None:
            try:
                await thinking_msg.edit_text(
                    reply_payload,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                response_message = thinking_msg
            except Exception as exc:
                LOGGER.warning(
                    "Failed to replace thinking message with final answer: %s", exc
                )
                thinking_message_sent = False

        if not thinking_message_sent or thinking_msg is None:
            LOGGER.debug(
                f"Sending response to chat {chat_id}: "
                f"length={len(reply_payload)}, message_id={message.message_id}"
            )
            try:
                response_message = await message.reply(
                    reply_payload,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                if response_message is not None:
                    LOGGER.info(
                        f"Response sent successfully to chat {chat_id}: "
                        f"response_id={response_message.message_id}"
                    )
            except Exception as exc:
                LOGGER.error(
                    f"Failed to send response message to chat {chat_id}: {exc}",
                    exc_info=True,
                )
                response_message = None

        if response_message is None:
            LOGGER.warning(
                f"Response message is None for chat {chat_id} (message_id={message.message_id})"
            )

        model_meta = _build_model_metadata(
            response=response_message,
            chat_id=chat_id,
            thread_id=thread_id,
            bot_username=bot_username,
            original=message,
            original_text=text_content,
        )
        bot_display_name = model_meta.get("name") or "gryag"

        model_embedding_start = time.time()
        model_embedding = await gemini_client.embed_text(reply_trimmed)
        model_embedding_time = int((time.time() - model_embedding_start) * 1000)

        db_save_start = time.time()
        await store.add_message(
            chat_id=chat_id,
            thread_id=thread_id,
            user_id=None,
            role="model",
            text=reply_trimmed,
            media=None,
            metadata=model_meta,
            embedding=model_embedding,
            retention_days=settings.retention_days,
            sender=MessageSender(
                role="assistant",
                name=bot_display_name,
                username=_normalize_username(bot_username),
                is_bot=True,
            ),
        )
        db_save_time = int((time.time() - db_save_start) * 1000)
        perf_timings["db_save_time_ms"] = db_save_time

    # Log total processing time with breakdown
    total_processing_time = int((time.time() - processing_start_time) * 1000)
    perf_summary = {
        "chat_id": chat_id,
        "user_id": user_id,
        "message_id": message.message_id,
        "total_time_ms": total_processing_time,
        **perf_timings,  # Include all collected timing metrics
    }
    LOGGER.info(
        "Message processing completed",
        extra=perf_summary,
    )

    # Bot Self-Learning: Track this interaction for learning
    if (
        settings.enable_bot_self_learning
        and bot_profile is not None
        and bot_id is not None
    ):
        # Estimate token count
        estimated_tokens = estimate_token_count(reply_trimmed)

        # Track interaction in background (non-blocking)
        asyncio.create_task(
            track_bot_interaction(
                bot_profile=bot_profile,
                bot_id=bot_id,
                chat_id=chat_id,
                thread_id=thread_id,
                message_id=response_message.message_id,
                response_text=reply_trimmed,
                response_time_ms=response_time_ms,
                token_count=estimated_tokens,
                tools_used=tools_used_in_request if tools_used_in_request else None,
            )
        )


async def _handle_poll_vote_attempt(
    text: str, chat_id: int, thread_id: int | None, user_id: int
) -> str | None:
    """
    Check if the message is a poll vote and handle it.

    Returns:
        Reply text if this was a poll vote, None otherwise
    """
    import re

    # Check if the text looks like poll voting (just numbers and commas/spaces)
    if not re.match(r"^[\d\s,]+$", text.strip()):
        return None

    # Parse numbers from the text
    try:
        # Extract all numbers from the text
        numbers = []
        for part in re.findall(r"\d+", text):
            num = int(part)
            if 1 <= num <= 10:  # Valid poll option range
                numbers.append(num - 1)  # Convert to 0-based index

        if not numbers:
            return None

        # Try to find an active poll in this chat/thread
        # For now, we'll get the most recent poll
        from app.services.polls import _active_polls

        # Find the most recent poll for this chat/thread
        recent_poll_id = None
        recent_time = 0

        for poll_id, poll_data in _active_polls.items():
            if (
                poll_data["chat_id"] == chat_id
                and poll_data["thread_id"] == thread_id
                and not poll_data["is_closed"]
            ):

                # Check if poll is expired
                if poll_data.get("expires_at"):
                    from datetime import datetime

                    expires = datetime.fromisoformat(poll_data["expires_at"])
                    if datetime.now() > expires:
                        poll_data["is_closed"] = True
                        continue

                # Get creation time
                created = poll_data["created_at"]
                if isinstance(created, str):
                    from datetime import datetime

                    created_time = datetime.fromisoformat(created).timestamp()
                else:
                    created_time = created

                if created_time > recent_time:
                    recent_time = created_time
                    recent_poll_id = poll_id

        if not recent_poll_id:
            return None  # No active polls found

        # Vote on the poll
        vote_result = await polls_tool(
            {
                "action": "vote",
                "poll_id": recent_poll_id,
                "user_id": user_id,
                "option_indices": numbers,
            }
        )

        import json

        result_data = json.loads(vote_result)

        if result_data["success"]:
            return result_data.get("poll_text", "Ваш голос зараховано!")
        else:
            return result_data.get("error", "Помилка при голосуванні")

    except (ValueError, TypeError, KeyError):
        return None
