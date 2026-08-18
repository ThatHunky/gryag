"""The phase-1 admin surface: switch the model, read what it costs.

These two exist in phase 1 rather than with the rest of the menu because quality is judged
live (see spec §10.2). A live comparison is only real if swapping the model is a button
press, and only measurable if every call was recorded.
"""

from __future__ import annotations

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from gryag import config, images, llm

MODEL_CHOICES = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite")


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


async def spend_report(db: aiosqlite.Connection, chat_id: int | None = None) -> str:
    where, params = "", []
    if chat_id is not None:
        where, params = "WHERE chat_id = ?", [chat_id]
    async with db.execute(
        f"""
        SELECT model,
               COUNT(*),
               SUM(cost_usd),
               AVG(prompt_tok),
               AVG(visible_tok),
               AVG(thought_tok),
               AVG(latency_ms),
               SUM(cached_tok) * 1.0 / NULLIF(SUM(prompt_tok), 0),
               SUM(searched)
        FROM usage {where}
        GROUP BY model
        """,
        params,
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "Витрат поки нічого немає."

    lines = ["Витрати:"]
    total = 0.0
    for model, calls, cost, prompt, visible, thoughts, latency, cache, searched in rows:
        total += cost or 0.0
        lines.append(
            f"{model}\n"
            f"  викликів: {calls}, разом ${cost:.4f}\n"
            f"  промпт {prompt:.0f}, видимих {visible:.0f}, думання {thoughts:.0f}\n"
            f"  латентність {latency:.0f} мс, кеш {100 * (cache or 0):.1f}%\n"
            f"  пошуків {searched or 0} з {llm.SEARCH_FREE_PER_MONTH} безкоштовних"
        )
    lines.append(f"Разом: ${total:.4f}")
    return "\n".join(lines)


def _menu(current_model: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("• " if model == current_model else "") + model,
                callback_data=f"model:{model}",
            )
        ]
        for model in MODEL_CHOICES
    ]
    rows.append(
        [
            InlineKeyboardButton(text="думання: 0", callback_data="think:0"),
            InlineKeyboardButton(text="думання: авто", callback_data="think:-1"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="увімкнути чат", callback_data="chat:on"),
            InlineKeyboardButton(text="вимкнути", callback_data="chat:off"),
        ]
    )
    rows.append([InlineKeyboardButton(text="витрати", callback_data="panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_router(admin_ids: tuple[int, ...]) -> Router:
    router = Router(name="admin")
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))

    @router.message(Command("gryag"))
    async def open_menu(message: Message, db) -> None:
        current = await config.get(db, "speak_model", message.chat.id)
        await message.answer(f"Модель: {current}", reply_markup=_menu(current))

    @router.message(Command("nb"))
    async def toggle_whitelist(message: Message, db) -> None:
        """Reply to somebody with /nb to let them draw, or /nb alone to see the list.

        Never registered with setMyCommands, so it does not appear in anyone's menu.
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
        """Reply to somebody with /unban to let them talk to gryag again."""
        from datetime import datetime, timezone

        from gryag import store

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        target = message.reply_to_message.from_user if message.reply_to_message else None
        if target is None:
            bans = await store.active_bans(db, message.chat.id, now)
            await message.reply(
                "Заблоковані: "
                + (", ".join(f"{who} до {until[11:16]}" for who, until, _ in bans) or "ніхто")
            )
            return
        lifted = await store.unban_user(db, message.chat.id, target.id)
        await message.reply(
            f"{target.full_name} розблокований" if lifted else "він і не був заблокований"
        )

    @router.callback_query(F.data.startswith("model:"))
    async def switch_model(query: CallbackQuery, db) -> None:
        model = query.data.split(":", 1)[1]
        await config.set(db, "speak_model", model, chat_id=query.message.chat.id)
        await query.message.edit_text(f"Модель: {model}", reply_markup=_menu(model))
        await query.answer("готово")

    @router.callback_query(F.data.startswith("think:"))
    async def switch_thinking(query: CallbackQuery, db) -> None:
        budget = query.data.split(":", 1)[1]
        await config.set(db, "thinking_budget", budget, chat_id=query.message.chat.id)
        await query.answer(f"думання: {budget}")

    @router.callback_query(F.data == "chat:on")
    async def turn_on(query: CallbackQuery, db) -> None:
        await enable_chat(db, query.message.chat.id, query.message.chat.title or "")
        await query.answer("чат увімкнено")

    @router.callback_query(F.data == "chat:off")
    async def turn_off(query: CallbackQuery, db) -> None:
        await disable_chat(db, query.message.chat.id)
        await query.answer("чат вимкнено")

    @router.callback_query(F.data == "panel")
    async def show_panel(query: CallbackQuery, db) -> None:
        await query.message.answer(await spend_report(db, query.message.chat.id))
        await query.answer()

    return router
