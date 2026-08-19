"""Підрахуйка: the Unmanned Systems Forces public killboard.

A JSON API with no key, serving what their own site shows at https://sbs-group.army.
Verified 2026-08-19: robots.txt allows everything, and the two endpoints used here answer
any user agent.

Only the grouping total is read. Per-brigade figures exist, and reading them would mean
seventeen requests for a line nobody asked for.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from gryag import config, handlers, phrases, store
from gryag.handlers import LOCAL_TZ, kyiv_day

log = logging.getLogger(__name__)

API = "https://sbs-group.army/api/public"
GROUPING = "0"
"""`subdivision.division_id` of Угруповання СБС, as opposed to a single brigade."""

TIMEOUT = aiohttp.ClientTimeout(total=10)
USER_AGENT = "gryag-bot (+https://t.me/gryag_bot)"
TOP_N = 8
PERIODS_TTL = 6 * 3600

MONTHS = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)


@dataclass(frozen=True)
class Report:
    day: str
    killed: int
    wounded: int
    hit: int
    destroyed: int
    strike: int
    recon: int
    updated: str
    top: tuple[tuple[str, int, int], ...]
    collected: bool


def parse(payload: dict, day: str) -> Report:
    """Total tolerance for a missing key.

    This is somebody else's API, changed without notice and read unattended at nine in the
    morning. A shape change should cost the digest, not the process.
    """
    personnel = payload.get("personnel") or {}
    flights = payload.get("flights") or {}
    targets = [
        t for t in (payload.get("targetsByType") or []) if t.get("destroyed") or t.get("hit")
    ]
    ranked = sorted(
        targets, key=lambda t: (t.get("destroyed", 0), t.get("hit", 0)), reverse=True
    )
    return Report(
        day=day,
        killed=int(personnel.get("killed") or 0),
        wounded=int(personnel.get("wounded") or 0),
        hit=int(payload.get("totalTargetsHit") or sum(t.get("hit", 0) for t in targets)),
        destroyed=int(
            payload.get("totalTargetsDestroyed") or sum(t.get("destroyed", 0) for t in targets)
        ),
        strike=int(flights.get("strike") or 0),
        recon=int(flights.get("recon") or 0),
        updated=str(payload.get("lastUpdated") or ""),
        top=tuple(
            (t.get("targetClass", "?"), int(t.get("hit", 0)), int(t.get("destroyed", 0)))
            for t in ranked[:TOP_N]
        ),
        collected=payload.get("status") == "completed",
    )


def _date_line(day: str) -> str:
    parsed = datetime.strptime(day, "%Y-%m-%d")
    return f"{parsed.day} {MONTHS[parsed.month - 1]}"


def _delta(now: int, before: int | None) -> str:
    if before is None:
        return ""
    change = now - before
    return f" ({change:+d})" if change else " (як учора)"


def render(report: Report, previous: Report | None, comment: str) -> str:
    lines = [f"📊 Підрахуйка СБС за {_date_line(report.day)}", ""]
    lines.append(f"Особовий склад: {report.killed} ліквідовано, {report.wounded} поранено")
    lines.append(
        f"Уражено {report.hit}, знищено {report.destroyed}"
        + _delta(report.destroyed, previous.destroyed if previous else None)
    )
    lines.append(f"Вильоти: {report.strike} ударних, {report.recon} розвідувальних")
    if report.top:
        lines.append("")
        lines.append("Найбільше знищено:")
        lines.extend(f"  {name} — {dead} (уражено {hit})" for name, hit, dead in report.top)
    if report.updated:
        lines.append("")
        lines.append(f"дані на {report.updated[11:16]} UTC · sbs-group.army")
    if comment:
        lines.append(comment)
    return "\n".join(lines)


_cache: dict[str, object] = {"periods": {}, "at": 0.0}
"""A mutable box rather than two module globals, so nothing needs a `global` statement to
drop the cache — which is what a 404 has to do."""


async def _get(session: aiohttp.ClientSession, path: str) -> dict:
    async with session.get(f"{API}{path}", headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        return await response.json()


async def _resolve(session: aiohttp.ClientSession) -> dict[str, tuple[str, str]]:
    """{periodType: (subdivision_id, period_id)} for the grouping.

    Their IDs look stable, and hardcoding them would work until the day they rotate and
    the digest quietly reports somebody else's month.
    """
    if _cache["periods"] and time.monotonic() - _cache["at"] < PERIODS_TTL:
        return _cache["periods"]
    payload = await _get(session, "/periods")
    found: dict[str, tuple[str, str]] = {}
    for period in payload.get("data", {}).get("periods", []):
        subdivision = period.get("subdivision") or {}
        if subdivision.get("division_id") != GROUPING:
            continue
        kind = period.get("periodType")
        if kind in ("daily", "prev_day") and kind not in found:
            found[kind] = (subdivision["_id"], period["_id"])
    _cache["periods"], _cache["at"] = found, time.monotonic()
    return found


async def fetch_report(
    period_type: str, now: datetime | None = None
) -> tuple[Report, dict] | None:
    """(report, raw payload), or None if the board could not be read."""
    now = now or datetime.now(timezone.utc)
    day = kyiv_day(now - timedelta(days=1)) if period_type == "prev_day" else kyiv_day(now)
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            periods = await _resolve(session)
            if period_type not in periods:
                log.warning("killboard has no %s period for the grouping", period_type)
                return None
            subdivision, period = periods[period_type]
            payload = await _get(session, f"/statistics/{subdivision}/{period}")
    except Exception:
        # Dropped so the next call re-resolves: a 404 here usually means the IDs rotated.
        _cache["periods"] = {}
        log.warning("killboard did not answer", exc_info=True)
        return None
    data = payload.get("data") or {}
    return parse(data, day), data


async def digest_text(db, period_type: str, now: datetime) -> str | None:
    """The rendered digest, or None when the board could not be read at all."""
    got = await fetch_report(period_type, now)
    if got is None:
        return None
    report, payload = got
    if not report.collected:
        return "підрахуйку за цю добу ще не порахували"

    await store.pidrahuika_save(db, report.day, now.isoformat(timespec="seconds"), payload)
    day_before = (
        datetime.strptime(report.day, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    stored = await store.pidrahuika_payload(db, day_before)
    previous = parse(stored, day_before) if stored else None
    seed = int(report.day.replace("-", ""))
    return render(report, previous, phrases.pick(phrases.DIGEST, seed))


async def post_due(db, bot, now: datetime | None = None) -> int:
    """Post yesterday's figures in every chat whose hour has come. Returns how many."""
    now = now or datetime.now(timezone.utc)
    local_hour = now.astimezone(LOCAL_TZ).hour
    today = kyiv_day(now)
    posted = 0
    for chat_id in await store.enabled_chats(db):
        if await config.get(db, "pidrahuika_enabled", chat_id) != "1":
            continue
        if local_hour < await config.get_int(db, "pidrahuika_hour", chat_id):
            continue
        if await store.pidrahuika_posted(db, chat_id, today):
            continue
        if await store.muted_until(db, chat_id, now.isoformat(timespec="seconds")):
            continue
        text = await digest_text(db, "prev_day", now)
        if text is None:
            # Deliberately unmarked: the next tick is ten minutes away, and a board that
            # was down at nine is usually up at ten past.
            continue
        sent = await bot.send_message(chat_id, text)
        await store.save_message(
            db,
            chat_id=chat_id,
            message_id=sent.message_id,
            user_id=None,
            ts=now.isoformat(timespec="seconds"),
            text=text,
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=True,
        )
        await store.pidrahuika_mark(db, chat_id, today)
        posted += 1
    return posted


_last_asked: dict[int, tuple[float, str]] = {}
COOLDOWN = 60.0
"""The board itself refreshes every ten seconds, so a minute-old answer is as good as a
new one — and this doubles as the anti-spam measure."""


async def _answer(message: Message, db, text: str) -> None:
    """Reply, and store the reply.

    Everything else the bot says is persisted; a command answer that is not leaves a hole
    in the day the digest summarises, and in the context window the model reads.
    """
    sent = await message.reply(text)
    await handlers.persist(db, sent, is_bot=True)


async def show_command(message: Message, db) -> None:
    """`/pidrahuika` and `/sbs`.

    Deliberately not gated on `pidrahuika_enabled`. That flag governs the morning post —
    speech nobody asked for. Somebody typing the command *did* ask, reading a public board
    costs nothing, and staying silent is indistinguishable from being broken.
    """
    from gryag.screens import chat_is_enabled

    if not await chat_is_enabled(db, message.chat.id):
        return
    await handlers.persist(db, message)
    cached = _last_asked.get(message.chat.id)
    if cached and time.monotonic() - cached[0] < COOLDOWN:
        await _answer(message, db, cached[1])
        return
    text = await digest_text(db, "daily", datetime.now(timezone.utc))
    if text is None:
        await _answer(message, db, "табло не відповідає")
        return
    _last_asked[message.chat.id] = (time.monotonic(), text)
    await _answer(message, db, text)


def build_router() -> Router:
    router = Router(name="pidrahuika")
    router.message(Command("pidrahuika", "sbs"))(show_command)
    return router
