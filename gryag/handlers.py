"""aiogram wiring.

The message is written to the database before the gate decides anything. If it were written
afterwards, history would have holes exactly where the bot stayed quiet, and the digest job
would summarise an incomplete day.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Router
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from gryag import config, context, gate, images, llm, media, store

log = logging.getLogger(__name__)

OWN_COMMANDS = ("gryag", "nb", "unban")
"""Everything else starting with a slash belongs to another bot; see gate.foreign_command."""


try:
    LOCAL_TZ = ZoneInfo("Europe/Kyiv")
except Exception:  # pragma: no cover - only if tzdata is missing
    LOCAL_TZ = timezone(timedelta(hours=3))
"""Kyiv. The measured quiet window — 03:00-07:00 carrying 0-11 messages an hour against a
peak of 958 at 22:00 — is in the chat's local time, not UTC.

A fixed +3 offset was wrong from the last Sunday of October onwards, which would have
shifted quiet hours by an hour without anything failing visibly."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_hour() -> int:
    return _utcnow().astimezone(LOCAL_TZ).hour


WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя")


def _render_now(moment: datetime) -> str:
    """Local time, with the day of the week spelled out.

    Telegram sends UTC. Passing that through told the bot it was three hours earlier than
    the room it was sitting in, which is wrong for the obvious question and wrong for
    knowing whether it is the middle of the night.
    """
    local = moment.astimezone(LOCAL_TZ)
    return f"{local:%Y-%m-%d %H:%M}, {WEEKDAYS[local.weekday()]}"


async def _since(ts: str | None) -> float:
    if not ts:
        return 1e9
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max((_utcnow() - parsed).total_seconds(), 0.0)


async def _ambient_probability(db, chat_id: int) -> float:
    """Chance per candidate message, derived from how many candidates a day this chat
    actually produces. Pinning a constant would swamp a quiet chat and vanish in a loud one."""
    wanted = await config.get_int(db, "ambient_per_day", chat_id)
    candidates = await store.ambient_candidates_per_day(db, chat_id)
    if candidates <= 0:
        return 0.0
    return min(wanted / candidates, 1.0)


_busy: set[int] = set()


def _claim(chat_id: int) -> bool:
    """Take the chat for one reply, or report that somebody already has it.

    Generation takes about two seconds, and this chat has a median gap of six seconds
    between messages, so several people can address the bot inside one generation.

    An asyncio.Lock was wrong for this. Checking `locked()` while building the gate input
    and acquiring it a dozen awaits later is a race: a batch of updates — exactly what a
    restart replays — all see it free, then queue on the lock and each produces a reply.
    Five landed in the same second that way.

    A set works because the check and the add happen with no await between them, which on
    a single-threaded event loop is atomic. Whoever loses simply says nothing.
    """
    if chat_id in _busy:
        return False
    _busy.add(chat_id)
    return True


def _release(chat_id: int) -> None:
    _busy.discard(chat_id)


_pending: dict[int, tuple[object, datetime]] = {}

_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Run something after the reply without holding the webhook request open.

    The reference matters: asyncio keeps only a weak one, so a bare create_task can be
    collected while suspended.
    """
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _remember_missed(chat_id: int, message, max_age: int = 60) -> None:
    """Keep the one message that lost the race, so it can be picked up afterwards.

    Only ever one: catching up on a backlog of five would recreate exactly the burst the
    claim exists to prevent.

    Stale entries from other chats are dropped here. The drain only runs after a
    successful reply in the same chat, so a chat that then goes quiet — or hits a cap —
    would otherwise pin a live Message object, and its whole update payload, forever.
    """
    now = _utcnow()
    for other, (_msg, seen_at) in list(_pending.items()):
        if (now - seen_at).total_seconds() > max_age:
            del _pending[other]
    _pending[chat_id] = (message, now)


def _take_missed(chat_id: int, max_age: int) -> object | None:
    entry = _pending.pop(chat_id, None)
    if entry is None:
        return None
    message, seen_at = entry
    if (_utcnow() - seen_at).total_seconds() > max_age:
        return None
    return message


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
            username=getattr(user, "username", None),
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


def _ban_handler(db, chat_id: int, sender):
    """Let the bot ignore somebody for a while, capped at two days.

    The length is the model's call; the ceiling is not. A ban only stops replies — the
    person's messages keep being stored and keep appearing in the context window.
    """

    async def handle(name: str, args: dict) -> str:
        if name != "ban_user" or sender is None:
            return "не вийшло"
        minutes = max(1, min(int(args.get("minutes") or 60), llm.MAX_BAN_MINUTES))
        reason = str(args.get("reason") or "")
        until = _utcnow() + timedelta(minutes=minutes)
        await store.ban_user(
            db, chat_id, sender.id, until.isoformat(timespec="seconds"), reason
        )
        log.info("banned %s in %s for %s minutes: %s", sender.id, chat_id, minutes, reason)
        return f"заблоковано на {minutes} хв"

    return handle


async def _maybe_draw(message, db, client, text: str, payload) -> str | None:
    """Draw instead of talking, when a whitelisted person asks for a picture.

    Deciding this in code rather than by function call keeps the reply path at one model
    call and costs nothing when nobody is asking for an image — which is almost always.
    """
    sender = message.from_user
    if sender is None:
        return None
    asked = images.wants_image(text)
    if asked is None:
        return None
    chat_id = message.chat.id
    whitelist = await config.get(db, "image_whitelist", chat_id)
    if not images.is_allowed(sender.id, whitelist):
        log.info("image request from %s refused: not whitelisted", sender.id)
        return None

    # "намалюй" on its own, in reply to something, means draw *that*. Work out what
    # "that" is before deciding whether this is a fresh drawing or an edit.
    replied = getattr(message, "reply_to_message", None)
    quote = getattr(message, "quote", None)
    parent_text = (
        (getattr(replied, "text", None) or getattr(replied, "caption", None) or "")
        if replied is not None
        else ""
    )
    # The trigger is already persisted by the time we get here, so it would otherwise
    # come back as its own subject and the model would draw the words "гряг намалюй".
    recent = await store.recent_messages(db, chat_id, limit=7)
    recent_text = " ".join(
        (m.get("text") or "").strip()
        for m in recent
        if (m.get("text") or "").strip() and m.get("message_id") != message.message_id
    )
    subject = images.subject_from(
        asked, getattr(quote, "text", None), parent_text, recent_text or None
    )
    if subject is None:
        log.info("draw request with nothing to draw in %s", chat_id)
        return None

    editing = payload is not None and (images.wants_edit(text) or not asked)
    prompt = (
        images.EDIT_INSTRUCTION + subject
        if editing
        else (images.PARENT_INSTRUCTION + subject if not asked else subject)
    )

    model = await config.get(db, "image_model", chat_id)
    async with _typing(message):
        result = await images.generate(
            client, model=model, prompt=prompt, source=payload if editing else None
        )
    if result is None:
        return None

    await store.record_usage(
        db,
        chat_id=chat_id,
        purpose="image",
        model=model,
        prompt_tok=result.prompt_tokens,
        cached_tok=0,
        visible_tok=result.output_tokens,
        thought_tok=0,
        latency_ms=result.latency_ms,
        cost_usd=images.PRICE_PER_IMAGE,
    )
    sent = await message.reply_photo(
        BufferedInputFile(result.payload, filename="gryag.jpg")
    )
    # Persist it like any other reply. Skipping this left the drawing out of history —
    # so the next prompt showed a request nobody answered and the model apologised for
    # not having drawn it — and out of the caps, the throttle and the ambient cooldown.
    await persist(db, sent, is_bot=True)
    log.info(
        "drew %s KB for %s in %s ms", len(result.payload) // 1024, sender.id, result.latency_ms
    )
    return ""


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


async def _maybe_answer_missed(message, db, client, persona, bot_id, chat_id: int) -> None:
    """Sometimes go back to whoever was skipped while the bot was busy.

    Sometimes is the point. Always coming back turns the bot into a queue that services
    every request in order; never coming back means a direct address vanishes in silence,
    which from inside the chat is indistinguishable from the bot being broken.
    """
    chance = await config.get_int(db, "deferred_chance", chat_id)
    if chance <= 0 or random.randrange(100) >= chance:
        _pending.pop(chat_id, None)
        return
    missed = _take_missed(chat_id, await config.get_int(db, "deferred_max_age", chat_id))
    if missed is None:
        return
    log.info("going back to a message that was skipped in %s", chat_id)
    await handle_message(missed, db, client, persona, bot_id, deferred=True)


async def handle_message(
    message: Message,
    db: aiosqlite.Connection,
    client,
    persona: str,
    bot_id: int,
    deferred: bool = False,
) -> str | None:
    chat_id = message.chat.id

    # The whitelist governs storage, not just speech. Being added to a group is not
    # consent to have it recorded: until somebody switches the chat on, nothing about it
    # is written down. Inside an enabled chat the message is still stored before the gate
    # runs, so history has no holes where the bot chose to stay quiet.
    if not await _chat_enabled(db, chat_id):
        log.debug("ignoring %s entirely: not on the whitelist", chat_id)
        return None
    await persist(db, message)

    now = message.date
    # Midnight means the chat's midnight. On UTC the daily budget rolled over at 03:00
    # Kyiv, in the hours where a runaway would be least visible.
    local_midnight = (
        now.astimezone(LOCAL_TZ)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
    )
    replies_today = await store.count_replies_since(
        db, chat_id, local_midnight.isoformat(timespec="seconds")
    )
    replies_this_hour = await store.count_replies_since(
        db, chat_id, (now - timedelta(hours=1)).isoformat(timespec="seconds")
    )

    window_start = (
        now - timedelta(seconds=await config.get_int(db, "throttle_window", chat_id))
    ).isoformat(timespec="seconds")
    sender = message.from_user
    user_replies, last_user_reply = await store.replies_to_user(
        db, chat_id, sender.id if sender else 0, window_start
    )
    since_user_reply = 1e9
    if last_user_reply:
        parsed = datetime.fromisoformat(last_user_reply)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        since_user_reply = max((_utcnow() - parsed).total_seconds(), 0.0)

    text = message.text or message.caption or ""
    replied = message.reply_to_message
    # Entity offsets are UTF-16 code units, not Python characters. Slicing the string
    # directly shifts by one per emoji before the mention, so "😀 @gryag_bot" read as
    # "gryag_bot " and the bot ignored a direct address. aiogram ships extract_from for
    # exactly this.
    mentions_bot = any(
        e.extract_from(text).lstrip("@").lower().endswith("gryag_bot")
        for e in (message.entities or [])
        if e.type == "mention"
    )
    replies_to_bot = bool(replied and replied.from_user and replied.from_user.id == bot_id)
    keywords = tuple(
        k.strip()
        for k in (await config.get(db, "keywords", chat_id)).split(",")
        if k.strip()
    )
    # Only a direct address is worth returning to after losing the race for the chat.
    decision_addressed = (
        mentions_bot or replies_to_bot or gate.mentions_keyword(text, keywords)
    )
    decision = gate.should_speak(
        gate.GateInput(
            text=text,
            is_bot=bool(sender and getattr(sender, "is_bot", False)),
            is_self=bool(sender and sender.id == bot_id),
            chat_enabled=True,  # checked above, before anything was written down
            mentions_bot=mentions_bot,
            replies_to_bot=replies_to_bot,
            keywords=keywords,
            replies_today=replies_today,
            replies_this_hour=replies_this_hour,
            daily_cap=await config.get_int(db, "daily_reply_cap", chat_id),
            hourly_cap=await config.get_int(db, "hourly_reply_cap", chat_id),
            bot_streak=await store.bot_streak(db, chat_id),
            bot_exchange_limit=await config.get_int(db, "bot_exchange_limit", chat_id),
            age_seconds=max((_utcnow() - now).total_seconds(), 0.0),
            max_reply_age=await config.get_int(db, "max_reply_age", chat_id),
            busy=chat_id in _busy,
            user_recent_replies=user_replies,
            seconds_since_user_reply=since_user_reply,
            throttle_after=await config.get_int(db, "throttle_after", chat_id),
            throttle_step=await config.get_int(db, "throttle_step", chat_id),
            own_commands=OWN_COMMANDS,
            ambient_enabled=await config.get(db, "ambient_enabled", chat_id) == "1",
            ambient_roll=random.random(),
            ambient_probability=await _ambient_probability(db, chat_id),
            seconds_since_bot_spoke=await _since(
                await store.last_message_ts(db, chat_id, from_bot=True)
            ),
            ambient_cooldown=await config.get_int(db, "ambient_cooldown", chat_id),
            is_reply_to_other=bool(
                replied and replied.from_user and replied.from_user.id != bot_id
            ),
            media_only=not text.strip() and bool(media_kind_and_file_id(message)[0]),
            local_hour=_local_hour(),
            quiet_from=await config.get_int(db, "quiet_from", chat_id),
            quiet_to=await config.get_int(db, "quiet_to", chat_id),
            chat_muted=bool(
                await store.muted_until(
                    db, chat_id, _utcnow().isoformat(timespec="seconds")
                )
            ),
            sender_banned=bool(
                sender
                and await store.ban_until(
                    db, chat_id, sender.id, _utcnow().isoformat(timespec="seconds")
                )
            ),
        )
    )
    if not decision.speak:
        if decision.reason == "busy" and not deferred:
            # Only a direct address is worth coming back to. An ambient interjection that
            # lost the race was optional to begin with.
            if decision_addressed:
                _remember_missed(chat_id, message)
        # "not addressed" is the normal case and would drown the log. A safety valve
        # firing is not normal: it means the bot went quiet for a reason nobody in the
        # chat can see, which is exactly the failure that must be visible here.
        if decision.reason in ("daily_cap", "hourly_cap", "bot_exchange_limit", "too_old"):
            log.warning(
                "silenced in %s by %s (today=%s, hour=%s)",
                chat_id,
                decision.reason,
                replies_today,
                replies_this_hour,
            )
        elif decision.reason == "user_banned":
            log.info("ignoring %s in %s: banned", sender.id if sender else "?", chat_id)
        elif decision.reason == "throttled":
            log.info(
                "throttling %s in %s: %s replies in the window, %.0fs since the last",
                sender.id if sender else "?",
                chat_id,
                user_replies,
                since_user_reply,
            )
        else:
            log.debug("silent in %s: %s", chat_id, decision.reason)
        return None

    # Claimed before any of the slow work and held until the reply is sent. Doing it
    # here rather than around the model call is the point: everything between the
    # gate and the call is an await, and a batch of updates would otherwise all pass.
    if not _claim(chat_id):
        # The gate's `busy` check and this claim happen at different moments, and this is
        # the one that actually decides. A direct address losing here is the common case,
        # so it is remembered here too — not only on the gate's branch.
        if not deferred and decision_addressed:
            _remember_missed(chat_id, message)
        log.debug("already answering in %s", chat_id)
        return None
    try:
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
            # A channel post or automatic forward carries no from_user; the same guard
            # is applied three lines down and was missed here.
            "alias": context.alias_for(sender.full_name) if sender else "хтось",
        }
        present = {m["user_id"] for m in messages if m.get("user_id")}
        if sender is not None:
            present.add(sender.id)
        facts = await store.facts_for_users(db, chat_id, sorted(present))

        quote = getattr(message, "quote", None)
        prompt = context.build(
            messages=messages,
            chain=chain,
            trigger=trigger,
            now=_render_now(now),
            chat_title=message.chat.title or "",
            week_summary=await store.latest_summary(db, chat_id, "week"),
            today_summary=await store.latest_summary(db, chat_id, "day"),
            facts=facts,
            quote=getattr(quote, "text", None),
            quote_author=(
                context.BOT_ALIAS
                if replied and replied.from_user and replied.from_user.id == bot_id
                else (
                    context.alias_for(replied.from_user.full_name)
                    if replied and replied.from_user
                    else None
                )
            ),
        )

        payload = await _look_at_media(message)

        drawn = await _maybe_draw(message, db, client, text, payload)
        if drawn is not None:
            return drawn

        model = await config.get(db, "speak_model", chat_id)
        async with _typing(message):
            result = await llm.generate(
                client,
                model=model,
                system=persona["text"] if isinstance(persona, dict) else persona,
                user=prompt,
                max_output_tokens=await config.get_int(db, "max_output_tokens", chat_id),
                thinking_budget=await config.get_int(db, "thinking_budget", chat_id),
                media=payload,
                use_tools=await config.get(db, "tools_enabled", chat_id) == "1",
                tool_handler=_ban_handler(db, chat_id, sender),
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
    finally:
        _release(chat_id)
        if not deferred:
            # Deliberately not awaited here. Awaiting a second generation inside `finally`
            # replaced any propagating exception with the deferred one, and held the
            # webhook request open for both replies — long enough for Telegram to time
            # out, redeliver, and get answered twice.
            _spawn(_maybe_answer_missed(message, db, client, persona, bot_id, chat_id))


async def handle_edit(message, db) -> bool:
    """Follow an edit, never answer it.

    Answering edits would let anyone re-trigger the bot by editing an old message, and
    would double up on a conversation that already got its reply.
    """
    return await store.update_message_text(
        db,
        message.chat.id,
        message.message_id,
        (message.text or message.caption or ""),
    )


def build_router() -> Router:
    router = Router(name="chat")

    # No content filter. An earlier one listed six types and silently dropped GIFs,
    # video notes, documents and audio — they never reached the database at all, so the
    # conversation had holes the bot could not see.
    @router.message()
    async def on_message(message: Message, db, client, persona, bot_id) -> None:
        await handle_message(message, db, client, persona, bot_id)

    @router.edited_message()
    async def on_edit(message: Message, db) -> None:
        await handle_edit(message, db)

    return router
