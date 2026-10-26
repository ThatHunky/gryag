"""`/summary`: what you missed, in gryag's voice, with every point linking to its message.

"What you missed" is what was said while the caller was last away. Telegram does not tell
a bot what anybody has read, so absence is read off the caller's own lines: the last one
followed by `summary_away_minutes` of their silence is where they left, the next one is
where they came back, and the batch is what lies between. What came after their return
they were there for. The first version took the caller's very last line, which for
anybody actually chatting was a minute ago — five messages, or "nothing missed", while
they had come back from three hours away. `/summary N` takes the last N instead. Either
way one batch is at most `summary_batch` messages; anything older is left out and the
reply says so.

Earlier summaries and the commands that asked for them are left out of the batch, or the
model summarises its own summary.

The transcript goes to the model either as text or drawn onto pages (`gryag.pages`),
chosen by `summary_input`. The pages exist for the token bill: see that module for the
measurement. Photos in the batch are tiled onto contact sheets, several to a page, so the
summary can say what was in a picture rather than only that there was one.

The model cites messages by their position in the batch — `[тут](17)` — never by
Telegram's ids. A two-digit number survives being read off a page; a six-digit id is
exactly what an image misreads. Positions are mapped back to links here, and a position
outside the batch loses its link and keeps its words.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, Message
from google.genai import types

from gryag import config, context, handlers, llm, lore, media, pages, store

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096

RESOLUTIONS = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}

INSTRUCTIONS = (
    "---\n"
    "Вище — переписка чату{source}. Кожне повідомлення має номер у квадратних дужках."
    "{photos}\n\n"
    "Зроби короткий підсумок того, що тут було, для когось, хто це пропустив. "
    "Своїм голосом, як ти розповів би другу: хто що казав, про що сперечались, "
    "що було смішного чи важливого. Пропускай порожній флуд, стікери й команди ботам.\n\n"
    "Формат: пункти, кожен з нового рядка і з «• », по одному-два речення. "
    "Від 6 до 10 пунктів, якщо є про що; весь текст не довший за 2500 символів. "
    "Без заголовків, без markdown, без жирного. Тут можна довше, ніж зазвичай.\n"
    "У кожному пункті зроби посилання на повідомлення, звідки це взялося: "
    "візьми кілька слів пункту в квадратні дужки, а номер повідомлення — у круглі, "
    "ось так: [Олег знову про крипту](17). Один номер на посилання — того самого "
    "повідомлення, де це сказано, а не сусіднього. Треба два повідомлення — зроби два "
    "посилання на різні слова. Більше нічого в круглих дужках після квадратних не пиши."
)

COMMAND = re.compile(r"^/(?:summary|підсумок|самарі)(?:@\w+)?(?:\s|$)", re.IGNORECASE)

MIN_MESSAGES = 10
"""Fewer than this and there is nothing to summarise, only something to make up."""

LINK = re.compile(r"\[([^\[\]\n]{1,200})\]\(\s*(\d{1,5}(?:\s*[,;]\s*\d{1,5})*)\s*\)")
"""`[words](17)`, and `[words](1, 2)`: asked for one number, Flash-Lite still sometimes
cites two, and the first live summary left four points as raw brackets because of it."""


@dataclass(frozen=True)
class Batch:
    messages: list[dict]
    skipped: int
    """Unread messages older than the batch, left out of it."""
    away_since: str | None = None
    """When the caller left, if that is where the batch starts."""


def numbered_lines(messages: list[dict]) -> list[str]:
    """`[n] Ім'я: текст`, numbered from 1 within the batch."""
    return [
        f"[{n}]" + lore.render_line(m).split("]", 1)[1]
        for n, m in enumerate(messages, 1)
    ]


def to_html(text: str, chat_id: int, messages: list[dict]) -> str:
    """The model's `[words](n)` become links; everything else is escaped. Of several
    numbers the first one that is in the batch wins.

    Escaping happens per piece, between the matches, so a `<` somebody typed into the
    chat and the model quoted cannot open a tag.
    """
    out: list[str] = []
    cursor = 0
    for match in LINK.finditer(text):
        out.append(html.escape(text[cursor : match.start()], quote=False))
        words = match.group(1)
        positions = [int(n) for n in re.findall(r"\d+", match.group(2))]
        valid = [p for p in positions if 1 <= p <= len(messages)]
        url = lore.message_link(chat_id, messages[valid[0] - 1]["message_id"]) if valid else None
        if url:
            out.append(f'<a href="{url}">{html.escape(words, quote=False)}</a>')
        else:
            out.append(html.escape(words, quote=False))
        cursor = match.end()
    out.append(html.escape(text[cursor:], quote=False))
    return "".join(out).strip()


def _without_summaries(messages: list[dict]) -> list[dict]:
    """Drop `/summary` commands and the bot's answers to them."""
    commands = {
        m["message_id"] for m in messages if COMMAND.match((m.get("text") or "").strip())
    }
    return [
        m
        for m in messages
        if m["message_id"] not in commands
        and not (m.get("is_bot") and m.get("reply_to") in commands)
    ]


def missed_span(
    messages: list[dict], user_id: int, now: datetime, away: timedelta
) -> tuple[int, int, str | None]:
    """`messages[start:end]` is what the caller missed, plus when they left (or None).

    Walks the caller's own lines from the newest, pairing each with the moment they next
    spoke (the command itself, for the newest). The first pair far enough apart is the
    absence: it starts after the earlier line and ends at the later one. With no such
    pair the caller was here all along, and missed only what came before their first
    line in the window — all of it, if they never wrote there.
    """
    own = [i for i, m in enumerate(messages) if m.get("user_id") == user_id]
    returned, next_spoke = len(messages), now
    for i in reversed(own):
        said = datetime.fromisoformat(messages[i]["ts"])
        if next_spoke - said >= away:
            return i + 1, returned, messages[i]["ts"]
        returned, next_spoke = i, said
    return 0, own[0] if own else len(messages), None


async def select(
    db: aiosqlite.Connection,
    chat_id: int,
    user_id: int,
    before_message_id: int,
    count: int | None,
    batch: int,
    *,
    now: datetime,
    away: timedelta,
) -> Batch:
    """The messages to summarise, oldest first, never including the command itself."""
    recent = [
        m
        for m in await store.recent_messages(db, chat_id, batch + 1 if count else batch * 5)
        if m["message_id"] != before_message_id
    ]
    if count:
        chosen = _without_summaries(recent)[-min(count, batch) :]
        return Batch([m for m in chosen if context.is_context_worthy(m)], 0)

    start, end, away_since = missed_span(recent, user_id, now, away)
    unread = _without_summaries(recent[start:end])
    if len(unread) > batch:
        skipped, unread = len(unread) - batch, unread[-batch:]
    else:
        skipped = 0
    return Batch([m for m in unread if context.is_context_worthy(m)], skipped, away_since)


async def _photo_sheets(bot, messages: list[dict], limit: int) -> list[bytes]:
    if limit <= 0:
        return []
    candidates = [
        (n, m) for n, m in enumerate(messages, 1)
        if m.get("media_kind") == "photo" and m.get("file_id")
    ][-limit:]
    fetched = await asyncio.gather(
        *(media.fetch(bot, m["file_id"], media.MIME_BY_KIND["photo"]) for _, m in candidates)
    )
    photos = [
        (f"[{n}]", got[0]) for (n, _), got in zip(candidates, fetched) if got is not None
    ]
    # Decoding and tiling a dozen photos is CPU work; on the loop it would stall every
    # other chat while a summary is prepared.
    return await asyncio.to_thread(pages.contact_sheet, photos) if photos else []


async def build_parts(
    lines: list[str],
    sheets: list[bytes],
    *,
    mode: str,
    resolution: str,
) -> list[types.Part]:
    """Everything the model is handed, in reading order: transcript, photos, the ask."""
    level = RESOLUTIONS.get(resolution, RESOLUTIONS["medium"])

    def image(data: bytes, mime_type: str) -> types.Part:
        return types.Part(
            inline_data=types.Blob(data=data, mime_type=mime_type),
            media_resolution={"level": level},
        )

    parts: list[types.Part] = []
    if mode == "pages":
        rendered = await asyncio.to_thread(pages.render, lines)
        parts.extend(image(p, "image/png") for p in rendered)
        source = ", намальована на сторінках по дві колонки"
    else:
        parts.append(types.Part.from_text(text="\n".join(lines)))
        source = ""
    parts.extend(image(s, "image/jpeg") for s in sheets)
    photos = (
        " Далі — фото з цієї переписки, підписані номерами повідомлень; "
        "кажи, що на них, якщо це важливо."
        if sheets
        else ""
    )
    parts.append(
        types.Part.from_text(text=INSTRUCTIONS.format(source=source, photos=photos))
    )
    return parts


async def summarise(
    db: aiosqlite.Connection,
    client,
    bot,
    persona: dict,
    chat_id: int,
    messages: list[dict],
) -> tuple[str, llm.LlmResult] | None:
    """The model's text, still with `[words](n)` links, and the call it cost. None if the
    model gave nothing back."""
    model = await config.get(db, "summary_model", chat_id)
    sheets = await _photo_sheets(
        bot, messages, await config.get_int(db, "summary_photos", chat_id)
    )
    parts = await build_parts(
        numbered_lines(messages),
        sheets,
        mode=await config.get(db, "summary_input", chat_id),
        resolution=await config.get(db, "summary_resolution", chat_id),
    )
    result = await llm.generate(
        client,
        model=model,
        system=persona["text"],
        user="",
        parts=parts,
        max_output_tokens=await config.get_int(db, "summary_max_tokens", chat_id),
        thinking_budget=0,
        thinking_level=await config.get(db, "summary_thinking", chat_id),
        use_tools=False,
    )
    if result is None:
        return None
    await store.record_usage(
        db,
        chat_id=chat_id,
        purpose="summary",
        model=model,
        prompt_tok=result.prompt_tokens,
        cached_tok=result.cached_tokens,
        visible_tok=result.visible_tokens,
        thought_tok=result.thought_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )
    return result.text, result


def fit(text: str, chat_id: int, messages: list[dict], note: str = "") -> str:
    """HTML that fits one Telegram message, cut at whole points.

    Cut before conversion, never after: cutting the HTML can end inside a tag or an
    entity, and Telegram rejects the whole message for it. A single point too long for
    the limit is cut in the raw text, where the worst case is a link that loses its
    closing bracket and stays plain words.
    """
    lines = text.split("\n")
    while True:
        body = to_html("\n".join(lines), chat_id, messages) + note
        if len(body) <= TELEGRAM_LIMIT:
            return body
        if len(lines) > 1:
            lines.pop()
        else:
            lines = [lines[0][: len(lines[0]) * 3 // 4]]


def messages_word(n: int) -> str:
    """1, 2-4 and 22 take «повідомлення»; 5-20, 11-14 and 25 take «повідомлень»."""
    if n % 10 in (1, 2, 3, 4) and n % 100 not in (11, 12, 13, 14):
        return "повідомлення"
    return "повідомлень"


def scope(chosen: Batch, count: int | None) -> str:
    """One line saying what the summary covers, so a short one is not a mystery."""
    n = len(chosen.messages)
    if count:
        line = f"останні {n} {messages_word(n)}"
    elif chosen.away_since:
        # Gender-neutral on purpose: "поки тебе не було", not "як ти пішов".
        left = datetime.fromisoformat(chosen.away_since).astimezone(handlers.LOCAL_TZ)
        when = (
            f"{left:%H:%M}"
            if left.date() == datetime.now(handlers.LOCAL_TZ).date()
            else f"{left:%d.%m %H:%M}"
        )
        line = f"{n} {messages_word(n)} з {when}, поки тебе не було"
    else:
        line = f"останні {n} {messages_word(n)}"
    if chosen.skipped:
        line += f", ще {chosen.skipped} старіших не влізло"
    return f"({line})"


_last_run: dict[int, float] = {}


async def send_command(
    message: Message,
    db: aiosqlite.Connection,
    client,
    persona: dict,
    command: CommandObject | None = None,
) -> None:
    """`/summary` for what you missed, `/summary 300` for the last 300."""
    if not await handlers.accept_command(message, db):
        return
    chat_id = message.chat.id
    if await config.get(db, "summary_enabled", chat_id) != "1":
        return

    # In memory, not in the database: a restart forgiving a cooldown costs one summary.
    cooldown = await config.get_int(db, "summary_cooldown", chat_id)
    now = handlers._utcnow().timestamp()
    waited = now - _last_run.get(chat_id, 0.0)
    if waited < cooldown:
        await handlers.answer(message, db, f"почекай ще {round(cooldown - waited)} с")
        return
    # Claimed before the first await below, so two commands arriving together cannot
    # both get past the check above. Released again when nothing was spent.
    _last_run[chat_id] = now

    raw = (command.args if command else None) or (message.text or "").partition(" ")[2]
    count = int(raw.strip()) if raw.strip().isdigit() else None
    batch = await config.get_int(db, "summary_batch", chat_id)
    away = timedelta(minutes=await config.get_int(db, "summary_away_minutes", chat_id))
    chosen = await select(
        db, chat_id, message.from_user.id, message.message_id, count, batch,
        now=message.date, away=away,
    )
    if len(chosen.messages) < MIN_MESSAGES:
        _last_run.pop(chat_id, None)
        await handlers.answer(
            message,
            db,
            "там нічого підсумовувати"
            if count
            else "ти нічого не пропустив, ти ж тут сидиш. останні 300 — /summary 300",
        )
        return

    done = await summarise(db, client, message.bot, persona, chat_id, chosen.messages)
    if done is None:
        _last_run.pop(chat_id, None)
        await handlers.answer(message, db, "щось не склалось, спробуй пізніше")
        return
    text, _ = done
    note = f"\n\n<i>{html.escape(scope(chosen, count))}</i>"
    await handlers.answer(
        message,
        db,
        fit(text, chat_id, chosen.messages, note),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def build_router() -> Router:
    """Registered before the chat router, so a handled command stops there."""
    router = Router(name="summary")
    router.message(Command("summary"))(send_command)
    router.message(F.text.regexp(r"^/(?:підсумок|самарі)(?:@\w+)?(?:\s|$)"))(send_command)
    return router
