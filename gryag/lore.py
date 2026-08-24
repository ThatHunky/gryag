"""Лор чату: one living page, rewritten every couple of days from the raw transcript.

The second thing in this project that spends tokens thinking *about* the chat rather than
speaking in it. The governing rule is untouched — the model is called only when the bot
speaks, and reading the lore never calls it. Writing happens on a timer, off the message
path, exactly like the digest.

Why the raw transcript and not the daily summaries, which would be a hundredth of the
cost: those are written to a prompt that says the reader is a bot and not a person. They
are deliberately dry, quote-free and stripped of the wording that makes a joke a joke, so
a lore assembled from them reads like meeting minutes. `facts` are used, but only as a
cast list, so the model does not rediscover who everybody is on every run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from gryag.handlers import LOCAL_TZ

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "join": "прийшли",
    "leave": "пішли",
    "pin": "закріпили",
    "title": "перейменували чат",
    "migrate": "чат став супергрупою",
    "boost": "бустнули",
    "topic": "тема",
}


def local_hours(buckets: list[tuple[str, int]]) -> list[int]:
    """24 counts, indexed by the chat's own hour.

    SQL groups by UTC hour because Kyiv is +03:00 in summer and +02:00 in winter, and a
    fixed offset in SQL is silently an hour wrong for four months of the year. A window is
    at most four days and never spans both, so converting each bucket here is exact.
    """
    counts = [0] * 24
    for bucket, number in buckets:
        moment = datetime.fromisoformat(f"{bucket}:00:00").replace(tzinfo=timezone.utc)
        counts[moment.astimezone(LOCAL_TZ).hour] += number
    return counts


def _duration(seconds: int) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours} год {minutes} хв" if hours else f"{minutes} хв"


def _local_time(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")


def _events_line(events: list[dict]) -> str:
    parts: list[str] = []
    for action, label in ACTION_LABELS.items():
        matching = [e for e in events if e["action"] == action]
        if not matching:
            continue
        if action in ("join", "leave"):
            people = [
                name for e in matching for name in (e["payload"].get("members") or [e["alias"]])
            ]
            parts.append(f"{label}: {', '.join(people)}")
        elif action in ("title", "topic"):
            titles = [str(e["payload"].get("title") or "") for e in matching]
            parts.append(f"{label}: {', '.join(t for t in titles if t)}")
        else:
            parts.append(f"{label}: {len(matching)}")
    return "; ".join(parts)


def render_stats(stats: dict) -> str:
    """The figures, as a block the rewrite prompt quotes verbatim."""
    lines = [f"Повідомлень за період: {stats['total']}"]

    if stats["per_person"]:
        people = ", ".join(
            f"{who} {count} ({delta:+d})" for who, count, delta in stats["per_person"]
        )
        lines.append(f"Хто скільки написав (у дужках — зміна проти минулого разу): {people}")

    for alias, text, total, reactions in stats["top_reacted"]:
        emojis = ", ".join(f"{emoji} {count}" for emoji, count in reactions)
        body = " ".join((text or "[без тексту]").split())[:200]
        lines.append(f"Найбільше реакцій — {alias}: «{body}» — {emojis} (разом {total})")

    counts = local_hours(stats["hours"])
    if any(counts):
        busiest = max(range(24), key=lambda h: counts[h])
        deadest = min(range(24), key=lambda h: counts[h])
        lines.append(
            f"Найгаласливіша година: {busiest}:00 ({counts[busiest]}), "
            f"найтихіша: {deadest}:00 ({counts[deadest]})"
        )

    if stats["longest_silence"]:
        seconds, from_ts, to_ts = stats["longest_silence"]
        lines.append(
            f"Найдовша тиша: {_duration(seconds)}, "
            f"з {_local_time(from_ts)} до {_local_time(to_ts)}"
        )

    events = _events_line(stats["events"])
    if events:
        lines.append(f"Події: {events}")

    if stats["stickers"]:
        lines.append(f"Найбільше стікерів: {stats['stickers'][0]} ({stats['stickers'][1]})")
    if stats["edits"]:
        lines.append(f"Найбільше редагувань: {stats['edits'][0]} ({stats['edits'][1]})")

    return "\n".join(lines)
