from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from typing import Any
import logging

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.config import Settings
from app.persona import SYSTEM_PERSONA
from app.services.calculator import calculator_tool, CALCULATOR_TOOL_DEFINITION
from app.services.weather import weather_tool, WEATHER_TOOL_DEFINITION
from app.services.currency import currency_tool, CURRENCY_TOOL_DEFINITION
from app.services.polls import polls_tool, POLLS_TOOL_DEFINITION
from app.services.context_store import ContextStore, format_metadata
from app.services.gemini import GeminiClient, GeminiError
from app.services.media import collect_media_parts
from app.services.redis_types import RedisLike
from app.services.triggers import addressed_to_bot
from app.services.user_profile import UserProfileStore
from app.services.fact_extractors import FactExtractor
from app.services import telemetry

router = Router()

ERROR_FALLBACK = "Ґеміні знову тупить. Спробуй пізніше."
EMPTY_REPLY = "Скажи конкретніше, бо зараз з цього нічого не зробити."
BANNED_REPLY = "Ти для гряга в бані. Йди погуляй."


LOGGER = logging.getLogger(__name__)


_META_PREFIX_RE = re.compile(
    r'^\s*\[meta\](?:\s+[\w.-]+=(?:"(?:\\.|[^"])*"|[^\s]+))*\s*'
)

# Enhanced regex to catch metadata that might appear anywhere in the response
_META_ANYWHERE_RE = re.compile(
    r'\[meta\](?:\s+[\w.-]+=(?:"(?:\\.|[^"])*"|[^\s]+))*', re.MULTILINE
)

# Regex to catch technical IDs and system information
_TECHNICAL_INFO_RE = re.compile(
    r"\b(?:chat_id|user_id|thread_id|message_id)[:=]\s*\d+\b|"
    r"\b(?:reply_to_message_id|reply_to_user_id)[:=]\s*\d+\b|"
    r'"(?:name|username|reply_to_name|reply_to_username)"[:=]\s*"[^"]*"',
    re.IGNORECASE,
)

_TELEGRAM_MARKDOWN_ESCAPE_RE = re.compile(r"([_*\[\]()`])")

_RECENT_CONTEXT: dict[tuple[int, int | None], deque[dict[str, Any]]] = {}
_CONTEXT_TTL_SECONDS = 300


def _normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    return f"@{username.lstrip('@')}"


def _extract_text(message: Message | None) -> str | None:
    if message is None:
        return None
    text = message.text or message.caption
    if not text:
        return None
    cleaned = " ".join(text.strip().split())
    return cleaned if cleaned else None


def _summarize_media(media_items: list[dict[str, Any]] | None) -> str | None:
    if not media_items:
        return None
    labels: list[str] = []
    seen: set[str] = set()
    for item in media_items:
        kind = str(item.get("kind") or "media")
        mime = item.get("mime")
        label = kind
        if isinstance(mime, str) and mime:
            label = f"{kind} ({mime})"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    if not labels:
        return None
    return "Прикріплення: " + ", ".join(labels)


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
) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return

    text = _extract_text(message)
    media_raw: list[dict[str, Any]] = []
    media_parts: list[dict[str, Any]] = []

    try:
        media_raw = await collect_media_parts(bot, message)
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to collect media for message %s", message.message_id)
        media_raw = []

    if media_raw:
        media_parts = gemini_client.build_media_parts(media_raw)

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


def _build_user_metadata(
    message: Message,
    chat_id: int,
    thread_id: int | None,
    fallback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from_user = message.from_user
    meta: dict[str, Any] = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "message_id": message.message_id,
        "user_id": from_user.id if from_user else None,
        "name": from_user.full_name if from_user else None,
        "username": _normalize_username(from_user.username if from_user else None),
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
    meta: dict[str, Any] = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "message_id": response.message_id,
        "user_id": None,
        "name": "gryag",
        "username": _normalize_username(bot_username),
        "reply_to_message_id": original.message_id,
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

    # Clean up extra whitespace and empty lines
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not line.startswith("[meta")]

    # Join lines and clean up spacing
    cleaned = "\n".join(lines).strip()

    # Remove any remaining metadata patterns that might have slipped through
    while "[meta]" in cleaned:
        cleaned = cleaned.replace("[meta]", "").strip()

    # Clean up multiple consecutive spaces
    cleaned = " ".join(cleaned.split())

    return cleaned


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
    fact_extractor: FactExtractor,
    user_id: int,
    chat_id: int,
    thread_id: int | None,
    user_message: str,
    display_name: str | None,
    username: str | None,
    settings: Settings,
    history: list[dict[str, Any]],
) -> None:
    """Background task to update user profile after message handling."""
    try:
        # Skip if profiling disabled
        if not settings.enable_user_profiling:
            return

        # Get or create profile
        profile = await profile_store.get_or_create_profile(
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            username=username,
        )

        # Update interaction count
        await profile_store.update_interaction_count(
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
        )

        # Check if we should extract facts
        if not settings.fact_extraction_enabled:
            return

        interaction_count = profile.get("interaction_count", 0)
        if interaction_count < settings.min_messages_for_extraction:
            return

        # Check fact count limit
        fact_count = await profile_store.get_fact_count(user_id, chat_id)
        if fact_count >= settings.max_facts_per_user:
            LOGGER.debug(
                f"User {user_id} has reached max facts limit ({settings.max_facts_per_user})"
            )
            return

        # Extract facts from message
        if not user_message or len(user_message) < 10:
            return

        facts = await fact_extractor.extract_facts(
            message=user_message,
            user_id=user_id,
            username=username,
            context=history,
            min_confidence=settings.fact_confidence_threshold,
        )

        # Store facts
        for fact in facts:
            await profile_store.add_fact(
                user_id=user_id,
                chat_id=chat_id,
                fact_type=fact["fact_type"],
                fact_key=fact["fact_key"],
                fact_value=fact["fact_value"],
                confidence=fact["confidence"],
                evidence_text=fact.get("evidence_text"),
            )

        if facts:
            LOGGER.info(
                f"Extracted and stored {len(facts)} facts for user {user_id}",
                extra={"user_id": user_id, "fact_count": len(facts)},
            )

    except Exception as e:
        LOGGER.error(
            f"Failed to update user profile for {user_id}: {e}",
            extra={"user_id": user_id, "error": str(e)},
            exc_info=True,
        )
        telemetry.increment_counter("profile_update_errors")


def _escape_markdown(text: str) -> str:
    """Escape characters that break Telegram Markdown parsing."""
    if not text:
        return text

    text = text.replace("\\", "\\\\")
    return _TELEGRAM_MARKDOWN_ESCAPE_RE.sub(lambda match: "\\" + match.group(1), text)


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


@router.message()
async def handle_group_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    profile_store: UserProfileStore,
    fact_extractor: FactExtractor,
    bot_username: str,
    bot_id: int | None,
    continuous_monitor: Any | None = None,
    redis_client: RedisLike | None = None,
    redis_quota: tuple[str, int] | None = None,
    throttle_blocked: bool | None = None,
    throttle_reason: dict[str, Any] | None = None,
):
    if message.from_user is None or message.from_user.is_bot:
        return

    telemetry.increment_counter("chat.incoming")

    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # Phase 1+: Process message through continuous monitoring
    # This runs for ALL messages (addressed and unaddressed)
    if continuous_monitor is not None:
        is_addressed = addressed_to_bot(message, bot_username, bot_id)
        try:
            monitor_result = await continuous_monitor.process_message(
                message, is_addressed=is_addressed
            )
            LOGGER.debug(
                "Continuous monitoring processed message", extra=monitor_result
            )
        except Exception as e:
            LOGGER.error(
                "Error in continuous monitoring",
                exc_info=e,
                extra={"chat_id": chat_id, "message_id": message.message_id},
            )

    if not addressed_to_bot(message, bot_username, bot_id):
        telemetry.increment_counter("chat.unaddressed")
        await _remember_context_message(message, bot, gemini_client)
        return
    telemetry.increment_counter("chat.addressed")
    user_id = message.from_user.id
    blocked = bool(throttle_blocked)

    is_admin = user_id in settings.admin_user_ids

    if not is_admin and await store.is_banned(chat_id, user_id):
        telemetry.increment_counter("chat.banned_user")
        await message.reply(BANNED_REPLY)
        return

    if not is_admin and not blocked:
        await store.log_request(chat_id, user_id)

    if redis_client is not None and redis_quota is not None:
        key, ts = redis_quota
        member = f"{ts}:{message.message_id}"
        try:
            await redis_client.zadd(key, {member: ts})
            await redis_client.expire(key, 3600)
        except Exception:
            pass

    history = await store.recent(
        chat_id=chat_id,
        thread_id=thread_id,
        max_turns=settings.max_turns,
    )

    # Summarize context if it's getting too long to prevent confusion
    history = _summarize_long_context(history, settings.context_summary_threshold)

    media_raw = await collect_media_parts(bot, message)
    media_parts = gemini_client.build_media_parts(media_raw)

    raw_text = (message.text or message.caption or "").strip()

    # Check for poll voting (numbers like "1", "2", "1,3", etc.)
    poll_vote_result = await _handle_poll_vote_attempt(
        raw_text, chat_id, thread_id, user_id
    )
    if poll_vote_result:
        await message.reply(poll_vote_result, parse_mode="Markdown")
        return

    reply_context = None
    if message.reply_to_message:
        reply = message.reply_to_message
        key = (reply.chat.id, reply.message_thread_id)
        stored_queue = _RECENT_CONTEXT.get(key)
        if stored_queue:
            for item in reversed(stored_queue):
                if item.get("message_id") == reply.message_id:
                    reply_context = item
                    break
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

    # Always prepend metadata as first part for Gemini context
    user_parts.insert(0, {"text": format_metadata(user_meta)})

    text_content = raw_text or media_summary or fallback_text or ""

    user_embedding = await gemini_client.embed_text(text_content)

    await store.add_turn(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        text=text_content,
        media=media_parts,
        metadata=user_meta,
        embedding=user_embedding,
        retention_days=settings.retention_days,
    )

    if blocked:
        if throttle_reason:
            LOGGER.debug(
                "Skipping reply due to throttle: chat=%s user=%s details=%s",
                chat_id,
                user_id,
                throttle_reason,
            )
        telemetry.increment_counter("chat.throttled")
        return

    async def search_messages_tool(params: dict[str, Any]) -> str:
        query = (params or {}).get("query", "")
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"results": []})
        limit = params.get("limit", 5)
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 5
        limit_int = max(1, min(limit_int, 10))
        thread_only = params.get("thread_only", True)
        target_thread = thread_id if thread_only else None
        embedding = await gemini_client.embed_text(query)
        matches = await store.semantic_search(
            chat_id=chat_id,
            thread_id=target_thread,
            query_embedding=embedding,
            limit=limit_int,
        )
        payload = []
        for item in matches:
            meta_dict = item.get("metadata", {})
            payload.append(
                {
                    "score": round(float(item.get("score", 0.0)), 4),
                    "metadata": meta_dict,
                    "metadata_text": format_metadata(meta_dict),
                    "text": (item.get("text") or "")[:400],
                    "role": item.get("role"),
                    "message_id": item.get("message_id"),
                }
            )
        return json.dumps({"results": payload})

    tool_definitions: list[dict[str, Any]] = []
    if settings.enable_search_grounding:
        retrieval_tool: dict[str, Any] = {
            "google_search_retrieval": {
                "dynamic_retrieval_config": {
                    "mode": "MODE_DYNAMIC",
                    "dynamic_threshold": 0.5,
                }
            }
        }
        tool_definitions.append(retrieval_tool)

    tool_definitions.append(
        {
            "function_declarations": [
                {
                    "name": "search_messages",
                    "description": (
                        "Шукати релевантні повідомлення в історії чату за семантичною подібністю."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Запит або фраза для пошуку",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Скільки результатів повернути (1-10)",
                            },
                            "thread_only": {
                                "type": "boolean",
                                "description": "Чи обмежуватися поточним тредом",
                            },
                        },
                        "required": ["query"],
                    },
                }
            ]
        }
    )

    # Add calculator tool
    tool_definitions.append(CALCULATOR_TOOL_DEFINITION)

    # Add weather tool
    tool_definitions.append(WEATHER_TOOL_DEFINITION)

    # Add currency tool
    tool_definitions.append(CURRENCY_TOOL_DEFINITION)

    # Add polls tool
    tool_definitions.append(POLLS_TOOL_DEFINITION)

    # Enrich with user profile context
    profile_context = await _enrich_with_user_profile(
        profile_store=profile_store,
        user_id=user_id,
        chat_id=chat_id,
        settings=settings,
    )

    # If we have profile context, inject it into the system prompt
    system_prompt_with_profile = SYSTEM_PERSONA
    if profile_context:
        system_prompt_with_profile = SYSTEM_PERSONA + profile_context

    try:
        reply_text = await gemini_client.generate(
            system_prompt=system_prompt_with_profile,
            history=history,
            user_parts=user_parts,
            tools=tool_definitions,
            tool_callbacks={
                "search_messages": search_messages_tool,
                "calculator": calculator_tool,
                "weather": weather_tool,
                "currency": currency_tool,
                "polls": polls_tool,
            },
        )
        telemetry.increment_counter("chat.reply_success")

        # Update user profile in background (fire-and-forget)
        asyncio.create_task(
            _update_user_profile_background(
                profile_store=profile_store,
                fact_extractor=fact_extractor,
                user_id=user_id,
                chat_id=chat_id,
                thread_id=thread_id,
                user_message=text_content,
                display_name=message.from_user.full_name if message.from_user else None,
                username=message.from_user.username if message.from_user else None,
                settings=settings,
                history=history,
            )
        )
    except GeminiError:
        telemetry.increment_counter("chat.reply_failure")
        if not await store.should_send_notice(
            chat_id, user_id, "api_limit", ttl_seconds=1800
        ):
            return
        reply_text = ERROR_FALLBACK

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
        LOGGER.debug("Original response contained: %s", original_reply[:200])

    if not reply_text or reply_text.isspace():
        reply_text = EMPTY_REPLY

    reply_trimmed = reply_text[:4096]
    reply_markdown_safe = _escape_markdown(reply_trimmed)
    try:
        response_message = await message.reply(
            reply_markdown_safe,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        LOGGER.warning(
            "Failed to render Markdown reply; falling back to plain text",
            exc_info=True,
        )
        response_message = await message.reply(reply_trimmed)

    model_meta = _build_model_metadata(
        response=response_message,
        chat_id=chat_id,
        thread_id=thread_id,
        bot_username=bot_username,
        original=message,
        original_text=text_content,
    )

    model_embedding = await gemini_client.embed_text(reply_trimmed)

    await store.add_turn(
        chat_id=chat_id,
        thread_id=thread_id,
        user_id=None,
        role="model",
        text=reply_trimmed,
        media=None,
        metadata=model_meta,
        embedding=model_embedding,
        retention_days=settings.retention_days,
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
