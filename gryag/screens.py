"""What the admin menu looks like.

Split out of `admin` when the hub arrived: that module now does routing and commands, and
this one turns the database into text and buttons. Neither needs the other's internals,
and both fit in a reader's head.
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from gryag import config, images, llm, menu, store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def chat_is_enabled(db: aiosqlite.Connection, chat_id: int) -> bool:
    async with db.execute(
        "SELECT enabled FROM chats WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


PERIODS: dict[str, str] = {"day": "-1 day", "week": "-7 days", "all": ""}


async def spend_report(
    db: aiosqlite.Connection, chat_id: int | None = None, period: str = "all"
) -> str:
    clauses, params = [], []
    if chat_id is not None:
        clauses.append("chat_id = ?")
        params.append(chat_id)
    window = PERIODS.get(period, "")
    if window:
        clauses.append("ts >= datetime('now', ?)")
        params.append(window)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    async with db.execute(
        f"""
        SELECT model, purpose, COUNT(*), SUM(cost_usd), AVG(prompt_tok), AVG(visible_tok),
               AVG(thought_tok), AVG(latency_ms),
               SUM(cached_tok) * 1.0 / NULLIF(SUM(prompt_tok), 0), SUM(searched)
        FROM usage {where}
        GROUP BY model, purpose ORDER BY SUM(cost_usd) DESC
        """,
        params,
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "Витрат поки нічого немає."

    lines: list[str] = []
    total = 0.0
    searches = 0
    for model, purpose, calls, cost, prompt, visible, thoughts, latency, cache, found in rows:
        total += cost or 0.0
        searches += found or 0
        lines.append(
            f"{model} ({purpose})\n"
            f"  викликів {calls}, разом ${cost:.4f}\n"
            f"  промпт {prompt:.0f}, видимих {visible:.0f}, думання {thoughts:.0f}\n"
            f"  латентність {latency:.0f} мс, кеш {100 * (cache or 0):.1f}%"
        )
    lines.append(f"Разом: ${total:.4f}")
    lines.append(f"Пошуків: {searches} з {llm.SEARCH_FREE_PER_MONTH} безкоштовних на місяць")
    return "\n".join(lines)


async def drift_warning(db: aiosqlite.Connection) -> str | None:
    """`gemini-flash-latest` can be repointed with no notice and no API signal.

    A step change in how much the model thinks, or how long it takes, is the only
    evidence available that the thing behind the alias is not the thing that was there
    last week.
    """
    async with db.execute(
        """
        SELECT AVG(thought_tok), AVG(latency_ms) FROM usage
        WHERE purpose = 'reply' AND model = 'gemini-flash-latest' AND ts >= datetime('now', '-2 days')
        """
    ) as cur:
        recent = await cur.fetchone()
    async with db.execute(
        """
        SELECT AVG(thought_tok), AVG(latency_ms) FROM usage
        WHERE purpose = 'reply' AND model = 'gemini-flash-latest'
          AND ts < datetime('now', '-2 days') AND ts >= datetime('now', '-9 days')
        """
    ) as cur:
        older = await cur.fetchone()

    if not recent or not older or not recent[0] or not older[0]:
        return None
    if recent[0] > older[0] * 1.5 or recent[0] < older[0] * 0.66:
        return (
            f"⚠️ Думання змінилось: було {older[0]:.0f} токенів, стало {recent[0]:.0f}. "
            "Схоже, аліас перевели на іншу модель."
        )
    return None


_persona_size_hint = {"chars": 0}
"""A mutable box, like the persona itself: the menu shows how big the current one is, and
the reload button changes it without a restart."""


def _persona_size() -> int:
    return _persona_size_hint["chars"]


async def _chat_title(db: aiosqlite.Connection, chat_id: int) -> str:
    async with db.execute("SELECT title FROM chats WHERE chat_id = ?", (chat_id,)) as cur:
        row = await cur.fetchone()
    return row[0] if row and row[0] else str(chat_id)


async def root_text(db: aiosqlite.Connection, chat_id: int) -> str:
    """Everything worth knowing without tapping anything."""
    lines = [f"⚙️ гряг у «{await _chat_title(db, chat_id)}»"]
    lines.append(
        "чат увімкнено" if await chat_is_enabled(db, chat_id) else "чат вимкнено — тут я мовчу"
    )
    lines.append(f"модель: {await config.get(db, 'speak_model', chat_id)}")
    muted = await store.muted_until(db, chat_id, _now())
    if muted:
        lines.append(f"мовчу до {muted[11:16]} UTC")
    async with db.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM usage
        WHERE chat_id = ? AND ts >= datetime('now', '-1 day')
        """,
        (chat_id,),
    ) as cur:
        cost, calls = await cur.fetchone()
    lines.append(f"за добу: ${cost:.4f} за {calls} викликів")
    warning = await drift_warning(db)
    if warning:
        lines.append(warning)
    return "\n".join(lines)


async def screen_text(db: aiosqlite.Connection, chat_id: int, screen: menu.Screen) -> str:
    header = f"{screen.icon} {screen.title}"
    if screen.key == "spend":
        # Opening the screen shows the day; the buttons below widen it.
        return await spend_report(db, chat_id, "day")
    if screen.key == "people":
        bans = await store.active_bans(db, chat_id, _now())
        allowed = images.parse_whitelist(await config.get(db, "image_whitelist", chat_id))
        return "\n".join(
            [
                header,
                "заблоковані: "
                + (", ".join(f"{who} до {until[11:16]}" for who, until, _ in bans) or "ніхто"),
                "малюють: " + (", ".join(map(str, allowed)) or "ніхто"),
                "/nb у відповідь — дати або забрати малювання, /unban — зняти бан",
            ]
        )
    if screen.key == "voice":
        return f"{header}\nперсона: {_persona_size()} символів"
    return header


_ACTIONS: dict[str, list[list[InlineKeyboardButton]]] = {
    "voice": [[
        InlineKeyboardButton(text="↻ персона", callback_data="reload"),
        InlineKeyboardButton(text="↻ самарі", callback_data="digest"),
    ]],
    "game": [[
        InlineKeyboardButton(text="🎲 розіграти", callback_data="pidor:roll"),
        InlineKeyboardButton(text="🏆 топ", callback_data="pidor:top"),
    ]],
    "board": [[
        InlineKeyboardButton(text="📊 показати", callback_data="board:now"),
    ]],
    "spend": [[
        InlineKeyboardButton(text="доба", callback_data="spend:day"),
        InlineKeyboardButton(text="тиждень", callback_data="spend:week"),
        InlineKeyboardButton(text="усе", callback_data="spend:all"),
    ]],
}


def _back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="← назад", callback_data="nav:root")]


async def root_markup(db: aiosqlite.Connection, chat_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{s.icon} {s.title}", callback_data=f"nav:{s.key}")
        for s in menu.SCREENS
    ]
    # Three per row. A fourth fits only until a title as long as "Налаштування" shares the
    # row with it, at which point Telegram ellipsises all of them.
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    enabled = await chat_is_enabled(db, chat_id)
    rows.append([
        InlineKeyboardButton(
            text=("✅ чат увімкнено" if enabled else "❌ чат вимкнено"),
            callback_data="chat:toggle",
        )
    ])
    muted = await store.muted_until(db, chat_id, _now())
    # Four buttons per row is the practical maximum before Telegram starts truncating,
    # which is why these read "1 год" rather than "замовкни на 1 годину".
    rows.append(
        [
            InlineKeyboardButton(
                text=("🔇 " if muted else "") + c.label, callback_data=f"mute:{c.value}"
            )
            for c in menu.MUTE_CHOICES
        ]
        + [InlineKeyboardButton(text="🔊", callback_data="mute:0")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def screen_markup(
    db: aiosqlite.Connection, chat_id: int, screen: menu.Screen, section: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if screen.tabs and section:
        for setting in menu.SECTIONS[section][1]:
            current = await config.get(db, setting.key, chat_id)
            rows.append([
                InlineKeyboardButton(
                    text=f"{setting.title}: {setting.label_for(current)}",
                    callback_data=f"set:{section}:{setting.key}",
                )
            ])
    if len(screen.tabs) > 1:
        rows.append([
            InlineKeyboardButton(
                text=("● " if name == section else "") + menu.SECTIONS[name][0],
                callback_data=f"sec:{screen.key}:{name}",
            )
            for name in screen.tabs
        ])
    rows.extend(_ACTIONS.get(screen.key, []))
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


