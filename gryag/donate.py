"""«Підтримати бота»: the donate buttons and the /donate text.

The details live in the environment, not in the config table: they are the same for
every chat, and the admin menu has no business editing a card number. They are read at
call time rather than at import, so a test can set them and a restart picks up an edit.
"""

from __future__ import annotations

import html
import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from gryag import handlers

log = logging.getLogger(__name__)

_URL_SCHEMES = ("https://", "http://", "tg://")
_COPY_TEXT_LIMIT = 256


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _valid_url(value: str) -> bool:
    return value.startswith(_URL_SCHEMES)


def _row() -> list[InlineKeyboardButton]:
    row = []
    if jar := _env("DONATE_JAR_URL"):
        # A url button with a bad scheme makes Telegram reject the whole message, and
        # this row rides on the /pidor verdict and killboard posts — better to lose the
        # button than the post.
        if _valid_url(jar):
            row.append(InlineKeyboardButton(text="🫙 Підтримати бота", url=jar))
        else:
            log.warning("DONATE_JAR_URL is not a valid url, dropping the jar button")
    if card := _env("DONATE_CARD"):
        # copy_text rather than a callback: one tap puts the number on the clipboard,
        # which is the whole reason anybody presses it.
        if len(card) <= _COPY_TEXT_LIMIT:
            row.append(InlineKeyboardButton(text="💳 Картка", copy_text=CopyTextButton(text=card)))
        else:
            log.warning("DONATE_CARD is over the copy_text limit, dropping the card button")
    return row


def donate_keyboard() -> InlineKeyboardMarkup | None:
    row = _row()
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def with_donate_row(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """`markup` with the donate row underneath, leaving the original untouched."""
    row = _row()
    if not row:
        return markup
    rows = [list(r) for r in markup.inline_keyboard] if markup else []
    return InlineKeyboardMarkup(inline_keyboard=[*rows, row])


def donate_text() -> str | None:
    jar, card, site = _env("DONATE_JAR_URL"), _env("DONATE_CARD"), _env("DONATE_SITE_URL")
    if jar and not _valid_url(jar):
        jar = ""
    if card and len(card) > _COPY_TEXT_LIMIT:
        card = ""
    if site and not _valid_url(site):
        site = ""
    if not jar and not card:
        return None
    lines = ["💛 <b>Підтримати бота</b>", "", "Донати йдуть на сервер і розвиток ботів.", ""]
    if jar:
        lines.append(f'🫙 <a href="{html.escape(jar, quote=True)}">Банка</a>')
    if card:
        lines.append(f"💳 Картка: <code>{html.escape(card)}</code>")
    if site:
        label = site.split("://", 1)[-1].rstrip("/")
        lines.append(f'🌐 <a href="{html.escape(site, quote=True)}">{html.escape(label)}</a>')
    return "\n".join(lines)


async def show_command(message: Message, db) -> None:
    """`/donate`. Answered everywhere, like every other typed command: see accept_command."""
    if not await handlers.accept_command(message, db):
        return
    text = donate_text()
    if text is None:
        await handlers.answer(message, db, "реквізитів поки немає")
        return
    await handlers.answer(
        message,
        db,
        text,
        parse_mode="HTML",
        reply_markup=donate_keyboard(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def build_router() -> Router:
    router = Router(name="donate")
    router.message(Command("donate"))(show_command)
    return router
