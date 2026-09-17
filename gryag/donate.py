"""«Підтримати бота»: the donate buttons and the /donate text.

The details live in the environment, not in the config table: they are the same for
every chat, and the admin menu has no business editing a card number. They are read at
call time rather than at import, so a test can set them and a restart picks up an edit.
"""

from __future__ import annotations

import html
import os

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _row() -> list[InlineKeyboardButton]:
    row = []
    if jar := _env("DONATE_JAR_URL"):
        row.append(InlineKeyboardButton(text="🫙 Підтримати бота", url=jar))
    if card := _env("DONATE_CARD"):
        # copy_text rather than a callback: one tap puts the number on the clipboard,
        # which is the whole reason anybody presses it.
        row.append(InlineKeyboardButton(text="💳 Картка", copy_text=CopyTextButton(text=card)))
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
