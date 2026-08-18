"""The admin surface: inline menu, spend panel, whitelist and bans.

Everything the admin can change lives in the `config` table and is read at decision time,
so nothing here needs a restart. That is the whole reason config is in the database rather
than the environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from gryag import config, images, llm, menu, store

MODEL_CHOICES = tuple(
    c.value for c in menu.SECTIONS["model"][1][0].choices
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def enable_chat(db: aiosqlite.Connection, chat_id: int, title: str) -> None:
    await db.execute(
        """
        INSERT INTO chats (chat_id, title, enabled, added_at)
        VALUES (?, ?, 1, datetime('now'))
        ON CONFLICT (chat_id) DO UPDATE SET enabled = 1, title = excluded.title
        """,
        (chat_id, title),
    )
    await db.commit()


async def disable_chat(db: aiosqlite.Connection, chat_id: int) -> None:
    await db.execute("UPDATE chats SET enabled = 0 WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def chat_is_enabled(db: aiosqlite.Connection, chat_id: int) -> bool:
    async with db.execute(
        "SELECT enabled FROM chats WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


async def spend_report(db: aiosqlite.Connection, chat_id: int | None = None) -> str:
    where, params = "", []
    if chat_id is not None:
        where, params = "WHERE chat_id = ?", [chat_id]
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


async def _menu_markup(db: aiosqlite.Connection, chat_id: int, section: str) -> InlineKeyboardMarkup:
    title, settings = menu.SECTIONS[section]
    rows: list[list[InlineKeyboardButton]] = []
    for setting in settings:
        current = await config.get(db, setting.key, chat_id)
        rows.append([
            InlineKeyboardButton(
                text=f"{setting.title}: {setting.label_for(current)}",
                callback_data=f"set:{section}:{setting.key}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=("● " if name == section else "") + label,
            callback_data=f"sec:{name}",
        )
        for name, (label, _s) in menu.SECTIONS.items()
    ])
    enabled = await chat_is_enabled(db, chat_id)
    muted = await store.muted_until(db, chat_id, _now())

    rows.append([
        InlineKeyboardButton(
            text=("✅ чат увімкнено" if enabled else "❌ чат вимкнено"),
            callback_data="chat:toggle",
        )
    ])
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
    rows.append([
        InlineKeyboardButton(text="💰 витрати", callback_data="panel"),
        InlineKeyboardButton(text="↻ персона", callback_data="reload"),
        InlineKeyboardButton(text="↻ самарі", callback_data="digest"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _header(db: aiosqlite.Connection, chat_id: int) -> str:
    muted = await store.muted_until(db, chat_id, _now())
    parts = [f"Розділ: {menu.SECTIONS['model'][0]}"]
    if muted:
        parts.append(f"Мовчить до {muted[11:16]}")
    warning = await drift_warning(db)
    if warning:
        parts.append(warning)
    return "\n".join(parts)


def build_router(admin_ids: tuple[int, ...], on_reload=None, on_digest=None) -> Router:
    router = Router(name="admin")
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))

    async def show(target, db, section: str, edit: bool) -> None:
        chat_id = target.chat.id
        lines = [f"⚙️ {menu.SECTIONS[section][0]}"]
        if not await chat_is_enabled(db, chat_id):
            lines.append("Цей чат вимкнений — бот тут мовчить.")
        muted = await store.muted_until(db, chat_id, _now())
        if muted:
            lines.append(f"Мовчить до {muted[11:16]} UTC")
        warning = await drift_warning(db)
        if warning:
            lines.append(warning)
        text = "\n".join(lines)
        markup = await _menu_markup(db, target.chat.id, section)
        if not edit:
            await target.answer(text, reply_markup=markup)
            return
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            # Tapping the section you are already in produces identical content, and
            # Telegram treats an edit that changes nothing as an error.
            if "message is not modified" not in str(exc):
                raise

    @router.message(Command("gryag"))
    async def open_menu(message: Message, db) -> None:
        await show(message, db, "model", edit=False)

    @router.callback_query(F.data.startswith("sec:"))
    async def switch_section(query: CallbackQuery, db) -> None:
        await show(query.message, db, query.data.split(":", 1)[1], edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("set:"))
    async def cycle_setting(query: CallbackQuery, db) -> None:
        _, section, key = query.data.split(":", 2)
        setting = next(s for s in menu.SECTIONS[section][1] if s.key == key)
        current = await config.get(db, key, query.message.chat.id)
        value = menu.cycle(setting, current)
        await config.set(db, key, value, chat_id=query.message.chat.id)
        await show(query.message, db, section, edit=True)
        await query.answer(f"{setting.title}: {setting.label_for(value)}")

    @router.callback_query(F.data == "chat:toggle")
    async def toggle_chat(query: CallbackQuery, db) -> None:
        chat = query.message.chat
        if await chat_is_enabled(db, chat.id):
            await disable_chat(db, chat.id)
            note = "чат вимкнено"
        else:
            await enable_chat(db, chat.id, chat.title or "")
            note = "чат увімкнено"
        await show(query.message, db, "model", edit=True)
        await query.answer(note)

    @router.callback_query(F.data.startswith("mute:"))
    async def mute(query: CallbackQuery, db) -> None:
        hours = int(query.data.split(":", 1)[1])
        chat_id = query.message.chat.id
        if hours == 0:
            await store.set_mute(db, chat_id, None)
            await query.answer("говорю")
        else:
            until = datetime.now(timezone.utc) + timedelta(hours=hours)
            await store.set_mute(db, chat_id, until.isoformat(timespec="seconds"))
            await query.answer(f"мовчу {hours} год")
        await show(query.message, db, "model", edit=True)

    @router.callback_query(F.data == "panel")
    async def show_panel(query: CallbackQuery, db) -> None:
        await query.message.answer(await spend_report(db, query.message.chat.id))
        await query.answer()

    @router.callback_query(F.data == "reload")
    async def reload_persona(query: CallbackQuery) -> None:
        if on_reload is None:
            await query.answer("нема що перечитувати")
            return
        await query.answer(f"персона: {on_reload()} токенів приблизно")

    @router.callback_query(F.data == "digest")
    async def rerun_digest(query: CallbackQuery, db) -> None:
        if on_digest is None:
            await query.answer("недоступно")
            return
        await query.answer("рахую, це небистро")
        await on_digest(db, query.message.chat.id)
        await query.message.answer("Самарі перегенеровано.")

    @router.message(Command("nb"))
    async def toggle_whitelist(message: Message, db) -> None:
        """Reply to somebody with /nb to let them draw, or /nb alone to see the list.

        Never registered with setMyCommands, so it appears in nobody's menu.
        """
        raw = await config.get(db, "image_whitelist", message.chat.id)
        allowed = images.parse_whitelist(raw)
        target = message.reply_to_message.from_user if message.reply_to_message else None

        if target is None:
            await message.reply(
                "Малювати можуть: " + (", ".join(map(str, allowed)) or "ніхто")
            )
            return

        if target.id in allowed:
            allowed.remove(target.id)
            verdict = f"{target.full_name} більше не малює"
        else:
            allowed.append(target.id)
            verdict = f"{target.full_name} тепер малює"

        await config.set(
            db, "image_whitelist", images.render_whitelist(allowed), chat_id=message.chat.id
        )
        await message.reply(verdict)

    @router.message(Command("unban"))
    async def lift_ban(message: Message, db) -> None:
        target = message.reply_to_message.from_user if message.reply_to_message else None
        if target is None:
            bans = await store.active_bans(db, message.chat.id, _now())
            await message.reply(
                "Заблоковані: "
                + (", ".join(f"{who} до {until[11:16]}" for who, until, _ in bans) or "ніхто")
            )
            return
        lifted = await store.unban_user(db, message.chat.id, target.id)
        await message.reply(
            f"{target.full_name} розблокований" if lifted else "він і не був заблокований"
        )

    return router
