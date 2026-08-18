"""The once-a-day background job.

This is where every token the bot spends thinking *about* the chat is spent, as opposed
to speaking in it. The legacy bot did this work on every message — fact extraction,
episode grouping, self-learning — which is why a chat of 3,000 messages a day cost what
it cost. Here it is one call per chat per day.

Two deliberate economies:

* The weekly summary is rebuilt from the seven daily summaries, not from raw messages.
  That is ~2,100 tokens of input instead of ~200,000, and it does not rewrite history
  from scratch every night.
* There is no 30-day summary. At this volume it would compress ~850,000 tokens into 800,
  a ratio of 1000:1 that can only yield generalities the persona already contains. It was
  measured as the largest block of the legacy prompt, crowding out the live conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

import aiosqlite
from google.genai import types

from gryag import config, context, llm, store

log = logging.getLogger(__name__)

DAY_SUMMARY_TOKENS = 300
WEEK_SUMMARY_TOKENS = 400
CHUNK_TOKENS = 2000
"""A day goes to the model in pieces.

Sending the whole day at once was refused outright: 8,000 tokens of this chat's real
transcript came back with `block_reason: PROHIBITED_CONTENT` and no candidates at all.
That filter is not configurable — BLOCK_NONE on the four harm categories does not touch
it. Chunking means one refused stretch costs that stretch, not the whole day."""

DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"who": {"type": "string"}, "fact": {"type": "string"}},
                "required": ["who", "fact"],
            },
        },
    },
    "required": ["summary", "facts"],
}

DAY_PROMPT = """Нижче — переписка групового чату за одну добу, у форматі `нік: текст`.

Зроби дві речі.

1. `summary` — стислий переказ дня українською, до 900 символів. Що обговорювали, хто з
   ким сварився, які жарти пішли в обіг, що вирішили. Пиши по суті, без вступів на кшталт
   «у цьому чаті». Це читатиме бот, щоб розуміти контекст, а не людина.

2. `facts` — сталі факти про учасників, які варто пам'ятати й завтра: робота, місто,
   навчання, стосунки, стійкі вподобання й ненависті, прізвиська. Поле `who` — точний нік
   зі списку нижче. Не записуй одноразові події, настрій, чи те, що вже не буде правдою
   завтра. Краще нічого, ніж сміття. Максимум 10 фактів.

Ніки, які існують у цьому чаті: {aliases}
Про самого бота (гряг) фактів не пиши — тільки про людей.

Переписка:
{transcript}"""

WEEK_PROMPT = """Нижче — щоденні перекази одного групового чату, кожен за свою добу.

Зроби з них один зв'язний переказ тижня українською, до 1200 символів: наскрізні теми,
хто чим живе, які жарти протрималися кілька днів, що змінилося. Викинь те, що було
важливим один день і згасло. Без вступів — одразу по суті.

{days}"""


def yesterday(today: date | None = None) -> str:
    return ((today or datetime.now(timezone.utc).date()) - timedelta(days=1)).isoformat()


def render_transcript(messages: list[dict]) -> str:
    lines = [
        context.render_line(m) for m in messages if context.is_context_worthy(m)
    ]
    return "\n".join(lines)


def chunk_transcript(messages: list[dict], max_tokens: int = CHUNK_TOKENS) -> list[str]:
    """Split a day into transcript chunks, never breaking a message across two."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for message in messages:
        if not context.is_context_worthy(message):
            continue
        line = context.render_line(message)
        cost = context.estimate_tokens(line) + 1
        if current and size + cost > max_tokens:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += cost
    if current:
        chunks.append("\n".join(current))
    return chunks


async def _generate_json(client, model: str, prompt: str, schema: dict) -> dict | None:
    cfg = types.GenerateContentConfig(
        max_output_tokens=4000,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        response_mime_type="application/json",
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
        log.exception("digest call failed on %s", model)
        return None

    if not response.candidates:
        feedback = getattr(response, "prompt_feedback", None)
        log.warning(
            "digest chunk refused: %s", getattr(feedback, "block_reason", "no candidates")
        )
        return None

    text = (response.text or "").strip()
    if not text:
        # An empty body used to be parsed as `{}` and stored as an empty summary, which
        # the weekly pass then dutifully summarised. Silence must fail loudly here.
        log.warning("digest returned an empty body on %s", model)
        return None
    try:
        return json.loads(text), response.usage_metadata
    except json.JSONDecodeError:
        log.error("digest returned unparseable json: %s", text[:200])
        return None


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
        purpose="digest",
        model=model,
        prompt_tok=counts[0],
        cached_tok=counts[1],
        visible_tok=counts[2],
        thought_tok=counts[3],
        latency_ms=0,
        cost_usd=llm.cost_usd(model, *counts),
    )


async def summarise_day(
    db: aiosqlite.Connection, client, chat_id: int, day: str, model: str
) -> bool:
    messages = await store.messages_for_day(db, chat_id, day)
    if not messages:
        log.info("nothing to summarise for %s on %s", chat_id, day)
        return False

    # Facts about gryag itself are noise: the persona already says who it is, and a
    # stored "гряг is sarcastic" would be fed back to it as something to live up to.
    alias_by_id = {
        m["user_id"]: (m["alias"] or "хтось")
        for m in messages
        if m["user_id"] and not m["is_bot"] and m["alias"] != context.BOT_ALIAS
    }
    id_by_alias = {alias: user_id for user_id, alias in alias_by_id.items()}
    aliases = ", ".join(sorted(id_by_alias)) or "—"

    chunks = chunk_transcript(messages)
    pieces: list[str] = []
    raw_facts: list[dict] = []
    refused = 0
    for chunk in chunks:
        result = await _generate_json(
            client,
            model,
            DAY_PROMPT.format(aliases=aliases, transcript=chunk),
            DAY_SCHEMA,
        )
        if result is None:
            refused += 1
            continue
        payload, usage = result
        piece = str(payload.get("summary", "")).strip()
        if piece:
            pieces.append(piece)
        raw_facts.extend(payload.get("facts", []))
        await _record(db, chat_id, model, usage)

    if refused:
        log.warning("%s of %s chunks refused for %s on %s", refused, len(chunks), chat_id, day)
    if not pieces:
        log.error("nothing usable for %s on %s: every chunk failed", chat_id, day)
        return False

    summary = context.clamp(" ".join(pieces), DAY_SUMMARY_TOKENS)
    await store.save_summary(
        db,
        chat_id=chat_id,
        kind="day",
        period_start=day,
        period_end=day,
        text=summary,
        tokens=context.estimate_tokens(summary),
    )

    facts: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for item in raw_facts:
        user_id = id_by_alias.get(str(item.get("who", "")).strip())
        text = str(item.get("fact", "")).strip()
        if user_id and text and (user_id, text) not in seen:
            seen.add((user_id, text))
            facts.append((user_id, text))
    await store.replace_facts(db, chat_id, day, facts)
    log.info(
        "summarised %s messages for %s on %s in %s chunks, %s facts",
        len(messages),
        chat_id,
        day,
        len(chunks) - refused,
        len(facts),
    )
    return True


async def rebuild_week(
    db: aiosqlite.Connection, client, chat_id: int, model: str
) -> bool:
    days = await store.recent_daily_summaries(db, chat_id, limit=7)
    if not days:
        return False

    result = await _generate_json(
        client,
        model,
        WEEK_PROMPT.format(
            days="\n\n".join(f"{day}:\n{text}" for day, text in days)
        ),
        {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    )
    if result is None:
        return False
    payload, usage = result

    summary = context.clamp(payload.get("summary", "").strip(), WEEK_SUMMARY_TOKENS)
    await _record(db, chat_id, model, usage)
    await store.save_summary(
        db,
        chat_id=chat_id,
        kind="week",
        period_start=days[0][0],
        period_end=days[-1][0],
        text=summary,
        tokens=context.estimate_tokens(summary),
    )
    log.info("rebuilt week summary for %s from %s days", chat_id, len(days))
    return True


async def run(db: aiosqlite.Connection, client, day: str | None = None) -> None:
    target = day or yesterday()
    for chat_id in await store.enabled_chats(db):
        model = await config.get(db, "digest_model", chat_id)
        if await summarise_day(db, client, chat_id, target, model):
            await rebuild_week(db, client, chat_id, model)


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
