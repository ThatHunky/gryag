"""`/summary`: what you missed, in gryag's voice, with every point linking to its message.

"What you missed" is everything since the caller last wrote in the chat. Telegram does
not tell a bot what anybody has read, and the caller's own last line is the nearest thing
it does know. `/summary N` takes the last N instead. Either way one batch is at most
`summary_batch` messages; anything older is left out and the reply says so.

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

LINK = re.compile(r"\[([^\[\]\n]{1,200})\]\(\s*(\d{1,5}(?:\s*[,;]\s*\d{1,5})*)\s*\)")
"""`[words](17)`, and `[words](1, 2)`: asked for one number, Flash-Lite still sometimes
cites two, and the first live summary left four points as raw brackets because of it."""


@dataclass(frozen=True)
class Batch:
    messages: list[dict]
    skipped: int
    """Unread messages older than the batch, left out of it."""


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


async def select(
    db: aiosqlite.Connection,
    chat_id: int,
    user_id: int,
    before_message_id: int,
    count: int | None,
    batch: int,
) -> Batch:
    """The messages to summarise, oldest first, never including the command itself."""
    recent = [
        m
        for m in await store.recent_messages(db, chat_id, batch + 1 if count else batch * 5)
        if m["message_id"] != before_message_id
    ]
    if count:
        chosen = recent[-min(count, batch) :]
        return Batch([m for m in chosen if context.is_context_worthy(m)], 0)

    # Everything after the caller's own last line. Scanned in memory over a bounded
    # window: a person who has not written in five batches' worth gets the last batch.
    last_own = max(
        (i for i, m in enumerate(recent) if m.get("user_id") == user_id), default=-1
    )
    unread = recent[last_own + 1 :]
    if len(unread) > batch:
        skipped, unread = len(unread) - batch, unread[-batch:]
    else:
        skipped = 0
    return Batch([m for m in unread if context.is_context_worthy(m)], skipped)


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
    chosen = await select(
        db, chat_id, message.from_user.id, message.message_id, count, batch
    )
    if len(chosen.messages) < 3:
        _last_run.pop(chat_id, None)
        await handlers.answer(message, db, "та ти нічого не пропустив")
        return

    done = await summarise(db, client, message.bot, persona, chat_id, chosen.messages)
    if done is None:
        _last_run.pop(chat_id, None)
        await handlers.answer(message, db, "щось не склалось, спробуй пізніше")
        return
    text, _ = done
    note = f"\n\n<i>(ще {chosen.skipped} старіших не влізло)</i>" if chosen.skipped else ""
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
