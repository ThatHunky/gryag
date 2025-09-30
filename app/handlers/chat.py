from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import Any
import logging

from aiogram import Bot, Router
from aiogram.types import Message

from app.config import Settings
from app.persona import SYSTEM_PERSONA
from app.services.context_store import ContextStore, format_metadata
from app.services.gemini import GeminiClient, GeminiError
from app.services.media import collect_media_parts
from app.services.redis_types import RedisLike
from app.services.triggers import addressed_to_bot
from app.services import telemetry

router = Router()

ERROR_FALLBACK = "Ґеміні знову тупить. Спробуй пізніше."
EMPTY_REPLY = "Скажи конкретніше, бо зараз з цього нічого не зробити."
BANNED_REPLY = "Ти для гряга в бані. Йди погуляй."


LOGGER = logging.getLogger(__name__)


_META_PREFIX_RE = re.compile(
    r'^\s*\[meta\](?:\s+[\w.-]+=(?:"(?:\\.|[^"])*"|[^\s]+))*\s*'
)

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
        if fallback_context.get("message_id") is not None:
            meta["reply_to_message_id"] = fallback_context["message_id"]
        if fallback_context.get("user_id") is not None:
            meta["reply_to_user_id"] = fallback_context["user_id"]
        if fallback_context.get("name"):
            meta["reply_to_name"] = fallback_context["name"]
        if fallback_context.get("username"):
            meta["reply_to_username"] = fallback_context["username"]
        if fallback_context.get("excerpt"):
            meta["reply_excerpt"] = fallback_context["excerpt"]
    return {key: value for key, value in meta.items() if value not in (None, "")}


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
    match = _META_PREFIX_RE.match(text)
    if not match:
        return text
    return text[match.end() :].lstrip()


@router.message()
async def handle_group_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    bot_username: str,
    bot_id: int | None,
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

    media_raw = await collect_media_parts(bot, message)
    media_parts = gemini_client.build_media_parts(media_raw)

    raw_text = (message.text or message.caption or "").strip()

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
    user_parts: list[dict[str, Any]] = [{"text": format_metadata(user_meta)}]
    if raw_text:
        user_parts.append({"text": raw_text})
    elif media_summary:
        user_parts.append({"text": media_summary})
    elif fallback_text:
        user_parts.append({"text": fallback_text})

    if media_parts:
        user_parts.extend(media_parts)
    else:
        context_media = []
        if fallback_context and fallback_context.get("media_parts"):
            context_media = list(fallback_context["media_parts"])
        if context_media:
            user_parts.extend(context_media)
    if not user_parts:
        user_parts.append({"text": ""})

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

    try:
        reply_text = await gemini_client.generate(
            system_prompt=SYSTEM_PERSONA,
            history=history,
            user_parts=user_parts,
            tools=tool_definitions,
            tool_callbacks={"search_messages": search_messages_tool},
        )
        telemetry.increment_counter("chat.reply_success")
    except GeminiError:
        telemetry.increment_counter("chat.reply_failure")
        if not await store.should_send_notice(
            chat_id, user_id, "api_limit", ttl_seconds=1800
        ):
            return
        reply_text = ERROR_FALLBACK

    reply_text = _strip_leading_metadata(reply_text)

    if not reply_text:
        reply_text = EMPTY_REPLY

    reply_trimmed = reply_text[:4096]
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
