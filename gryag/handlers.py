"""aiogram wiring.

The message is written to the database before the gate decides anything. If it were written
afterwards, history would have holes exactly where the bot stayed quiet, and the digest job
would summarise an incomplete day.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import aiosqlite
from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from gryag import config, context, gate, llm, media, store

log = logging.getLogger(__name__)


def media_kind_and_file_id(message) -> tuple[str | None, str | None]:
    """Kept as the handler-facing name; the detection itself lives in `media`."""
    return media.detect(message)


async def persist(db: aiosqlite.Connection, message, *, is_bot: bool = False) -> None:
    kind, file_id = media_kind_and_file_id(message)
    user = message.from_user
    sender_is_bot = bool(is_bot or (user is not None and getattr(user, "is_bot", False)))
    if user is not None:
        await store.upsert_user(
            db,
            chat_id=message.chat.id,
            user_id=user.id,
            display_name=user.full_name,
            alias=context.alias_for(user.full_name),
        )
    await store.save_message(
        db,
        chat_id=message.chat.id,
        message_id=message.message_id,
        user_id=user.id if user else None,
        ts=message.date.isoformat(timespec="seconds"),
        text=(message.text or message.caption or ""),
        media_kind=kind,
        file_id=file_id,
        reply_to=(
            message.reply_to_message.message_id if message.reply_to_message else None
        ),
        is_bot=is_bot,
        sender_is_bot=sender_is_bot,
    )


async def _chat_enabled(db: aiosqlite.Connection, chat_id: int) -> bool:
    async with db.execute(
        "SELECT enabled FROM chats WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


async def _look_at_media(message) -> tuple[bytes, str] | None:
    """Fetch the file the bot is being asked about, if there is one.

    Only runs once the gate has decided to speak, so the 17% of this chat that is media
    costs nothing until somebody actually asks about a specific file.
    """
    bot = getattr(message, "bot", None)
    if bot is None:
        return None
    found = media.target(message)
    if found is None:
        return None
    file_id, mime, _source = found
    payload = await media.fetch(bot, file_id, mime)
    if payload is not None:
        log.info("looking at %s (%s, %s bytes)", file_id, mime, len(payload[0]))
    return payload


@asynccontextmanager
async def _typing(message) -> AsyncIterator[None]:
    """Show "typing…" while the model works.

    Generation takes about two seconds, which is long enough for the room to wonder
    whether the bot is alive. Degrades to a no-op when the message carries no bot, which
    is how the tests drive the handler.
    """
    bot = getattr(message, "bot", None)
    if bot is None:
        yield
        return
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        yield


async def handle_message(
    message: Message,
    db: aiosqlite.Connection,
    client,
    persona: str,
    bot_id: int,
) -> str | None:
    chat_id = message.chat.id
    await persist(db, message)

    now = message.date
    replies_today = await store.count_replies_since(
        db, chat_id, now.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    )
    replies_this_hour = await store.count_replies_since(
        db, chat_id, (now - timedelta(hours=1)).isoformat(timespec="seconds")
    )

    text = message.text or message.caption or ""
    replied = message.reply_to_message
    sender = message.from_user
    decision = gate.should_speak(
        gate.GateInput(
            text=text,
            is_bot=bool(sender and getattr(sender, "is_bot", False)),
            is_self=bool(sender and sender.id == bot_id),
            chat_enabled=await _chat_enabled(db, chat_id),
            mentions_bot=any(
                text[e.offset : e.offset + e.length].lstrip("@").lower().endswith("gryag_bot")
                for e in (message.entities or [])
                if e.type == "mention"
            ),
            replies_to_bot=bool(
                replied and replied.from_user and replied.from_user.id == bot_id
            ),
            keywords=tuple(
                k.strip()
                for k in (await config.get(db, "keywords", chat_id)).split(",")
                if k.strip()
            ),
            replies_today=replies_today,
            replies_this_hour=replies_this_hour,
            daily_cap=await config.get_int(db, "daily_reply_cap", chat_id),
            hourly_cap=await config.get_int(db, "hourly_reply_cap", chat_id),
            bot_streak=await store.bot_streak(db, chat_id),
            bot_exchange_limit=await config.get_int(db, "bot_exchange_limit", chat_id),
        )
    )
    if not decision.speak:
        # "not addressed" is the normal case and would drown the log. A safety valve
        # firing is not normal: it means the bot went quiet for a reason nobody in the
        # chat can see, which is exactly the failure that must be visible here.
        if decision.reason in ("daily_cap", "hourly_cap", "bot_exchange_limit"):
            log.warning(
                "silenced in %s by %s (today=%s, hour=%s)",
                chat_id,
                decision.reason,
                replies_today,
                replies_this_hour,
            )
        else:
            log.debug("silent in %s: %s", chat_id, decision.reason)
        return None

    window = await config.get_int(db, "context_messages", chat_id)
    messages = await store.recent_messages(db, chat_id, limit=window)
    chain = (
        await store.reply_chain(db, chat_id, replied.message_id) if replied else []
    )
    trigger = {
        "message_id": message.message_id,
        "text": text,
        "media_kind": media_kind_and_file_id(message)[0],
        "is_bot": False,
        "alias": context.alias_for(message.from_user.full_name),
    }
    prompt = context.build(
        messages=messages,
        chain=chain,
        trigger=trigger,
        now=now.strftime("%Y-%m-%d %H:%M"),
        chat_title=message.chat.title or "",
    )

    payload = await _look_at_media(message)

    model = await config.get(db, "speak_model", chat_id)
    async with _typing(message):
        result = await llm.generate(
            client,
            model=model,
            system=persona,
            user=prompt,
            max_output_tokens=await config.get_int(db, "max_output_tokens", chat_id),
            thinking_budget=await config.get_int(db, "thinking_budget", chat_id),
            media=payload,
            use_tools=await config.get(db, "tools_enabled", chat_id) == "1",
        )
    if result is None:
        return None

    await store.record_usage(
        db,
        chat_id=chat_id,
        purpose="reply",
        model=model,
        prompt_tok=result.prompt_tokens,
        cached_tok=result.cached_tokens,
        visible_tok=result.visible_tokens,
        thought_tok=result.thought_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        searched=result.searched,
    )

    sent = await message.reply(result.text)
    await persist(db, sent, is_bot=True)
    return result.text


def build_router() -> Router:
    router = Router(name="chat")

    @router.message(F.text | F.caption | F.photo | F.voice | F.video | F.sticker)
    async def on_message(message: Message, db, client, persona, bot_id) -> None:
        await handle_message(message, db, client, persona, bot_id)

    return router
