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

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from google.genai import types

from gryag import config, context, digest, handlers, llm, store
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


REWRITE_PROMPT = """Ти ведеш одну живу сторінку — лор групового чату «{title}».
Вона не дописується знизу, вона щоразу переписується цілком.

Ось поточна версія:
---
{current}
---

Ось що сталося відтоді:
{beats}

Ось цифри за той самий період. Вони пораховані точно — не перераховуй їх, не округлюй і
не вигадуй інших:
{stats}

Хто є хто в цьому чаті:
{cast}

Перепиши сторінку. Правила:

* Українською, у тому ж розмовному регістрі, що й сам чат, — це має бути смішно тому, хто
  там сидить, а не схоже на протокол зборів.
* Markdown: заголовки, списки, цитати. Без обгортки та без коду.
* Це одна сторінка, а не хроніка по датах. Можеш переписати рядок, злити два в один,
  викинути жарт, який помер. Але викидати — тільки коли є за що: місце звільняється
  стисканням, а не обрізанням.
* Нове не важливіше за старе тільки тому, що воно нове.
* Цитати наводь дослівно, як їх подано вище.
* Не звертайся до читача, не пояснюй, що це за документ, і не підписуйся.
* Максимум {max_chars} символів."""


async def rewrite(
    db: aiosqlite.Connection,
    client,
    chat_id: int,
    *,
    current: str,
    beats: list[dict],
    stats: str,
    cast: str,
    title: str,
    model: str,
    thinking: int,
    max_chars: int,
) -> str | None:
    """The whole document, rewritten, or None if it did not come back usable.

    The voice lives in the prompt above rather than in `eval/persona-v3.txt`: that persona
    is tuned for one-line chat replies and fights this format.
    """
    result = await _call(
        client,
        model,
        REWRITE_PROMPT.format(
            title=title,
            current=current or "(сторінки ще нема — напиши першу)",
            beats=render_beats(beats) or "(нічого нового)",
            stats=stats,
            cast=cast or "(нічого не відомо)",
            max_chars=max_chars,
        ),
        schema=None,
        thinking=thinking,
        # Thinking bills against the same allowance, so the budget has to cover both the
        # document and however long the model decides to think about it.
        max_tokens=int(max_chars / context.CHARS_PER_TOKEN) + HARVEST_MAX_TOKENS,
    )
    if result is None:
        return None
    text, usage = result
    await _record(db, chat_id, model, usage)
    return text


async def generate(
    db: aiosqlite.Connection,
    client,
    chat_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    """Rewrite one chat's lore. Returns whether a new version was stored.

    Every early exit above the first model call is free, which is the point: the timer
    fires daily and most days have nothing to do.
    """
    now = now or datetime.now(timezone.utc)
    if not force and await config.get(db, "lore_enabled", chat_id) != "1":
        return False

    previous = await store.latest_lore(db, chat_id)
    interval = await config.get_int(db, "lore_interval_days", chat_id)
    if not force and previous and previous["created_at"]:
        age = now - datetime.fromisoformat(previous["created_at"])
        if age < timedelta(days=interval):
            log.info("lore for %s is %s old, nothing to do", chat_id, age)
            return False

    window = pick_window(previous, await store.oldest_message_ts(db, chat_id), now)
    if window is None:
        log.info("nothing stored for %s to write a lore from", chat_id)
        return False
    start, end = window

    messages = await store.messages_between(db, chat_id, start, end)
    if not messages:
        log.info("nothing said in %s between %s and %s", chat_id, start, end)
        return False

    model = await config.get(db, "lore_model", chat_id)
    thinking = await config.get_int(db, "lore_thinking", chat_id)
    beats = await harvest(db, client, chat_id, messages, model, thinking)
    if beats is None:
        return False

    span = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    stats = render_stats(
        await store.lore_stats(
            db,
            chat_id,
            start,
            end,
            (datetime.fromisoformat(start) - span).isoformat(timespec="seconds"),
        )
    )
    present = await store.active_user_ids(db, chat_id, start)
    cast = "; ".join(
        f"{who} — {fact}" for who, fact in await store.facts_for_users(db, chat_id, present)
    )

    max_chars = await config.get_int(db, "lore_max_chars", chat_id)
    text = await rewrite(
        db,
        client,
        chat_id,
        current=(previous or {}).get("text", ""),
        beats=beats,
        stats=stats,
        cast=cast,
        title=await store.chat_title(db, chat_id),
        model=model,
        thinking=thinking,
        max_chars=max_chars,
    )
    if not text:
        log.error("the rewrite failed for %s; the previous version stands", chat_id)
        return False

    # `clamp` takes a token budget; the knob is in characters, and the ratio is the same
    # measured 2.5 the rest of the project uses.
    text = context.clamp(text, int(max_chars / context.CHARS_PER_TOKEN))
    version = await store.save_lore(
        db,
        chat_id=chat_id,
        text=text,
        model=model,
        tokens=context.estimate_tokens(text),
        window_start=start,
        window_end=end,
        created_at=now.isoformat(timespec="seconds"),
    )
    log.info(
        "wrote lore version %s for %s: %s characters from %s messages",
        version,
        chat_id,
        len(text),
        len(messages),
    )
    return True


async def run(db: aiosqlite.Connection, client, now: datetime | None = None) -> None:
    for chat_id in await store.enabled_chats(db):
        try:
            await generate(db, client, chat_id, now=now)
        except Exception:
            # One chat's failure is not a reason for the next to go a week without a
            # rewrite. The timer is the only thing that ever calls this.
            log.exception("writing the lore for %s failed", chat_id)


async def send_command(message: Message, db: aiosqlite.Connection) -> None:
    """`/lore`, and `/лор` for the one people actually type.

    Open to anybody in an enabled chat, because the document is the chat's own. Writing it
    is what spends money and what can degrade it, and that stays with the timer and the
    admin.
    """
    if not await handlers.accept_command(message, db):
        return
    chat_id = message.chat.id

    cooldown = await config.get_int(db, "lore_cooldown", chat_id)
    since = await handlers._since(await store.lore_sent_at(db, chat_id))
    if since < cooldown:
        # A line rather than silence: from inside the chat, being ignored and being broken
        # look exactly the same.
        await handlers.answer(
            message, db, f"щойно кидав, наступний через {round((cooldown - since) / 60)} хв"
        )
        return

    latest = await store.latest_lore(db, chat_id)
    if latest is None:
        await handlers.answer(message, db, "лору ще нема, зачекай")
        return

    written = datetime.fromisoformat(latest["created_at"]).astimezone(LOCAL_TZ)
    sent = await message.reply_document(
        BufferedInputFile(latest["text"].encode("utf-8"), filename="lore.md"),
        caption=f"лор чату, версія {latest['version']}, від {written:%d.%m}",
    )
    await handlers.persist(db, sent, is_bot=True)
    await store.mark_lore_sent(db, chat_id, handlers._utcnow().isoformat(timespec="seconds"))


def build_router() -> Router:
    """Registered before the chat router, so a handled command stops there."""
    router = Router(name="lore")
    router.message(Command("lore"))(send_command)
    # Telegram only registers ASCII commands with BotFather, so the Cyrillic one is
    # matched as ordinary text.
    router.message(F.text.regexp(r"^/лор(?:@\w+)?(?:\s|$)"))(send_command)
    return router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    secrets = config.secrets()
    db = await store.connect(secrets.db_path)
    try:
        await run(db, llm.build_client(secrets.gemini_api_key))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
