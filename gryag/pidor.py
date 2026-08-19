"""Підарас дня: one chat member, chosen at random, once a day.

A joke with two constraints that are not jokes. It must never call the model — the pool of
phrases is generated offline and shipped as data. And it must be stable: the same day must
produce the same person no matter how many times anybody asks, or how many people ask at
once.
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from gryag import config, handlers, phrases, store
from gryag.handlers import LOCAL_TZ, kyiv_day

log = logging.getLogger(__name__)

SHOW_DELAY = 1.5
"""Seconds between the warm-up lines and the verdict. The pause is the joke; the tests set
it to zero."""


def choose(
    candidates: list[int], previous: int | None, roll: float, min_players: int
) -> int | None:
    """Who it is today. `roll` is a float in [0, 1]; passing it in keeps this testable.

    Yesterday's winner is dropped, but only while enough people remain: in a chat of four,
    refusing to repeat would be a stronger constraint than the randomness it protects.
    """
    if len(candidates) < min_players:
        return None
    pool = [c for c in candidates if c != previous]
    if len(pool) < min_players:
        pool = list(candidates)
    return pool[min(int(roll * len(pool)), len(pool) - 1)]


def mention(user_id: int, username: str | None, display_name: str) -> str:
    """HTML, because a person with no username can only be mentioned by link.

    The display name is text the person chose, going into a message sent with
    parse_mode="HTML", so it is escaped.
    """
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{html.escape(display_name)}</a>'


async def roll(db, chat_id: int, now) -> tuple[int, bool] | None:
    """(winner, is_new), or None when there are too few people to choose from."""
    day = kyiv_day(now)
    held = await store.pidor_winner(db, chat_id, day)
    if held is not None:
        return held, False

    window = await config.get_int(db, "pidor_window_days", chat_id)
    since = (now - timedelta(days=window)).isoformat(timespec="seconds")
    candidates = await store.active_user_ids(db, chat_id, since)
    previous = await store.pidor_winner(db, chat_id, kyiv_day(now - timedelta(days=1)))
    picked = choose(
        candidates,
        previous,
        random.random(),
        await config.get_int(db, "pidor_min_players", chat_id),
    )
    if picked is None:
        return None
    winner = await store.pidor_record(
        db, chat_id, day, picked, now.isoformat(timespec="seconds")
    )
    return winner, winner == picked


def announcement_seed(chat_id: int, day: str) -> int:
    """Which phrases a given chat's given day gets.

    Arithmetic rather than hash(): Python randomises string hashing per process, so a
    hash-derived seed changes at every restart — which is the one thing this is supposed
    to survive.
    """
    return abs(chat_id) + int(day.replace("-", ""))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _say(bot, db, chat_id: int, text: str, parse_mode: str | None = None) -> None:
    sent = await bot.send_message(chat_id, text, parse_mode=parse_mode)
    # Stored like any other thing the bot says, so it counts against the reply caps and
    # shows up in the context window. A drawing that skipped this once made the model
    # apologise for not having drawn it.
    await store.save_message(
        db,
        chat_id=chat_id,
        message_id=sent.message_id,
        user_id=None,
        ts=_now_iso(),
        text=text,
        media_kind=None,
        file_id=None,
        reply_to=None,
        is_bot=True,
    )


async def announce(bot, db, chat_id: int, user_id: int, is_new: bool, now) -> None:
    names = await store.user_names(db, chat_id, [user_id])
    username, display_name = names.get(user_id, (None, str(user_id)))
    who = mention(user_id, username, display_name)
    seed = announcement_seed(chat_id, kyiv_day(now))

    if not is_new:
        await _say(bot, db, chat_id, phrases.pick(phrases.ALREADY, seed).format(who=who), "HTML")
        return

    await _say(bot, db, chat_id, phrases.pick(phrases.WARMUP, seed))
    await asyncio.sleep(SHOW_DELAY)
    await _say(bot, db, chat_id, phrases.pick(phrases.WARMUP, seed + 1))
    await asyncio.sleep(SHOW_DELAY)
    await _say(bot, db, chat_id, phrases.pick(phrases.VERDICT, seed).format(who=who), "HTML")
    log.info("підарас дня in %s is %s", chat_id, user_id)


async def leaderboard_text(db, chat_id: int, now) -> str:
    year = kyiv_day(now)[:4]
    overall = await store.pidor_counts(db, chat_id)
    if not overall:
        return "ще нікого не обирали"
    yearly = dict(await store.pidor_counts(db, chat_id, since_day=f"{year}-01-01"))
    names = await store.user_names(db, chat_id, [u for u, _ in overall])

    lines = [f"🏆 підараси року {year}"]
    for place, (user_id, wins) in enumerate(overall[:10], start=1):
        _username, display_name = names.get(user_id, (None, str(user_id)))
        lines.append(f"{place}. {display_name} — {yearly.get(user_id, 0)} (всього {wins})")
    return "\n".join(lines)


async def play_command(message: Message, db) -> None:
    if not await handlers.accept_command(message, db):
        return
    if await config.get(db, "pidor_enabled", message.chat.id) != "1":
        # Not silence: a command that produces nothing reads as a broken bot, which is
        # how the killboard command was first reported.
        await handlers.answer(message, db, "гру тут вимкнено")
        return
    # Deliberately not message.date. A command replayed from the backlog would otherwise
    # roll for the day it was typed on, writing a winner into a day already over.
    now = datetime.now(timezone.utc)
    result = await roll(db, message.chat.id, now)
    if result is None:
        await handlers.answer(message, db, "нема з кого вибирати, хай хтось щось напише")
        return
    winner, is_new = result
    await announce(message.bot, db, message.chat.id, winner, is_new, now)


async def stats_command(message: Message, db) -> None:
    if not await handlers.accept_command(message, db):
        return
    await handlers.answer(
        message, db, await leaderboard_text(db, message.chat.id, datetime.now(timezone.utc))
    )


def build_router() -> Router:
    """Registered before the chat router, so a handled command stops there."""
    router = Router(name="pidor")
    router.message(Command("pidor"))(play_command)
    router.message(Command("pidorstats"))(stats_command)
    return router


async def announce_due(db, bot, now=None) -> int:
    """Roll and announce in every chat whose hour has come and whose day is still empty.

    The recorded winner is its own guard against announcing twice: a chat where somebody
    already typed the command has a row for today, and this walks past it.
    """
    now = now or datetime.now(timezone.utc)
    local_hour = now.astimezone(LOCAL_TZ).hour
    spoken = 0
    for chat_id in await store.enabled_chats(db):
        if await config.get(db, "pidor_enabled", chat_id) != "1":
            continue
        hour = await config.get_int(db, "pidor_announce_hour", chat_id)
        if hour < 0 or local_hour < hour:
            continue
        if await store.pidor_winner(db, chat_id, kyiv_day(now)) is not None:
            continue
        if await store.muted_until(db, chat_id, now.isoformat(timespec="seconds")):
            log.debug("not announcing in %s: muted", chat_id)
            continue
        # Take the chat the way a reply does, exactly as proactive.run_once does: an
        # unclaimed post interleaves with an answer already being generated, and its
        # messages consume the reply caps without ever being checked against them.
        if not handlers._claim(chat_id):
            log.debug("not announcing in %s: a reply is in flight", chat_id)
            continue
        try:
            result = await roll(db, chat_id, now)
            if result is None:
                continue
            await announce(bot, db, chat_id, result[0], result[1], now)
            spoken += 1
        finally:
            handlers._release(chat_id)
    return spoken
