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

import json
import logging
from datetime import datetime, timedelta, timezone

import aiosqlite
from google.genai import types

from gryag import digest, llm, store
from gryag.handlers import LOCAL_TZ

log = logging.getLogger(__name__)

MAX_WINDOW_DAYS = 4
"""A missed run must not silently produce a 130,000-token harvest, and four days of this
chat is already more than the document can absorb in one rewrite."""

CHUNK_TOKENS = 2000
"""Blast-radius control, not a token economy. A stretch of this chat's real transcript has
already come back `PROHIBITED_CONTENT` with no candidates at all, and that filter is not
configurable — BLOCK_NONE on the four harm categories does not touch it."""

MAX_BEATS = 8

HARVEST_MAX_TOKENS = 8000
"""Thinking tokens count against max_output_tokens on these models, so a budget sized for
the JSON alone comes back empty as soon as thinking is on."""

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


BEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "who": {"type": "array", "items": {"type": "string"}},
                    "what": {"type": "string"},
                    "quote": {"type": "string"},
                    "kind": {"type": "string", "enum": ["joke", "drama", "event", "gag"]},
                },
                "required": ["who", "what", "kind"],
            },
        }
    },
    "required": ["beats"],
}

HARVEST_PROMPT = """Нижче — шматок переписки групового чату, у форматі `нік: текст`.

Витягни те, що варто пам'ятати як історію цього чату: жарти, які пішли в обіг, сварки,
події, дурні витівки. Максимум {max_beats} записів, і краще менше — беззмістовний обмін
репліками не подія.

У кожному записі:
* `who` — ніки учасників, яких це стосується, точно як у переписці;
* `what` — що сталося, одним-двома реченнями українською;
* `quote` — дослівна фраза з переписки, без якої це не смішно. Не вигадуй і не
  переписуй. Якщо такої фрази нема — не заповнюй поле;
* `kind` — `joke`, `drama`, `event` або `gag`.

Переписка:
{transcript}"""


async def _call(
    client,
    model: str,
    prompt: str,
    *,
    schema: dict | None,
    thinking: int,
    max_tokens: int,
) -> tuple[str, object] | None:
    """One model call, or None for anything that did not come back usable.

    Shaped like `digest._generate_json`, with thinking and the output budget as
    parameters: the digest runs with thinking off and the lore does not.
    """
    cfg = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking),
        response_mime_type="application/json" if schema else None,
        response_schema=schema,
        safety_settings=[
            types.SafetySetting(category=c, threshold="BLOCK_NONE")
            for c in llm.HARM_CATEGORIES
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    try:
        response = await client.aio.models.generate_content(
            model=model, contents=prompt, config=cfg
        )
    except Exception:
        log.exception("lore call failed on %s", model)
        return None

    if not response.candidates:
        feedback = getattr(response, "prompt_feedback", None)
        log.warning(
            "lore chunk refused: %s", getattr(feedback, "block_reason", "no candidates")
        )
        return None

    text = (response.text or "").strip()
    if not text:
        # An empty body is what a thinking budget that ate the whole output allowance
        # looks like. Storing it would replace the document with nothing.
        log.warning("lore returned an empty body on %s", model)
        return None
    return text, response.usage_metadata


async def _record(db: aiosqlite.Connection, chat_id: int, model: str, usage) -> None:
    counts = (
        usage.prompt_token_count or 0,
        usage.cached_content_token_count or 0,
        usage.candidates_token_count or 0,
        usage.thoughts_token_count or 0,
    )
    await store.record_usage(
        db,
        chat_id=chat_id,
        purpose="lore",
        model=model,
        prompt_tok=counts[0],
        cached_tok=counts[1],
        visible_tok=counts[2],
        thought_tok=counts[3],
        latency_ms=0,
        cost_usd=llm.cost_usd(model, *counts),
    )


def pick_window(
    previous: dict | None, oldest: str | None, now: datetime
) -> tuple[str, str] | None:
    """(start, end) for this run, or None when there is nothing to read."""
    end = now.isoformat(timespec="seconds")
    start = (previous or {}).get("window_end") or oldest
    if not start:
        return None
    floor = (now - timedelta(days=MAX_WINDOW_DAYS)).isoformat(timespec="seconds")
    start = max(start, floor)
    if start >= end:
        return None
    return start, end


async def harvest(
    db: aiosqlite.Connection,
    client,
    chat_id: int,
    messages: list[dict],
    model: str,
    thinking: int,
) -> list[dict] | None:
    """Every beat worth keeping from the window, or None if the whole harvest failed."""
    chunks = digest.chunk_transcript(messages, max_tokens=CHUNK_TOKENS)
    beats: list[dict] = []
    refused = 0
    for chunk in chunks:
        result = await _call(
            client,
            model,
            HARVEST_PROMPT.format(max_beats=MAX_BEATS, transcript=chunk),
            schema=BEAT_SCHEMA,
            thinking=thinking,
            max_tokens=HARVEST_MAX_TOKENS,
        )
        if result is None:
            refused += 1
            continue
        text, usage = result
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            log.error("lore harvest returned unparseable json: %s", text[:200])
            refused += 1
            continue
        # Capped here as well as asked for in the prompt: the ceiling is the design's,
        # not the model's to negotiate.
        beats.extend(list(payload.get("beats") or [])[:MAX_BEATS])
        await _record(db, chat_id, model, usage)

    if chunks and refused == len(chunks):
        log.error("every one of %s chunks failed for %s", len(chunks), chat_id)
        return None
    if refused:
        log.warning("%s of %s chunks refused for %s", refused, len(chunks), chat_id)
    log.info("harvested %s beats from %s chunks for %s", len(beats), len(chunks), chat_id)
    return beats


def render_beats(beats: list[dict]) -> str:
    lines: list[str] = []
    for beat in beats:
        who = ", ".join(str(w) for w in (beat.get("who") or [])) or "хтось"
        quote = str(beat.get("quote") or "").strip()
        tail = f" «{quote}»" if quote else ""
        lines.append(f"- [{beat.get('kind', 'event')}] {who}: {beat.get('what', '')}{tail}")
    return "\n".join(lines)
