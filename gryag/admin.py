"""The admin surface: inline menu, spend panel, whitelist and bans.

Everything the admin can change lives in the `config` table and is read at decision time,
so nothing here needs a restart. That is the whole reason config is in the database rather
than the environment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from gryag import cleanup, config, images, menu, store
from gryag.handlers import _spawn
from gryag.screens import (
    _now,
    _persona_size_hint,
    chat_is_enabled,
    root_markup,
    root_text,
    screen_markup,
    screen_text,
    spend_report,
)

log = logging.getLogger(__name__)

MODEL_CHOICES = tuple(
    c.value for c in menu.SECTIONS["model"][1][0].choices
)


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


async def _rerun_and_report(on_digest, db, chat) -> None:
    """Regenerate one chat's summaries and say so when it lands.

    Spawned rather than awaited inside the callback: a multi-chunk day takes tens of
    seconds, and holding the callback open that long makes Telegram redeliver it — which
    used to start a second concurrent digest on the same connection.
    """
    try:
        await on_digest(db, chat.id)
    except Exception:
        log.exception("rerunning the digest for %s failed", chat.id)
        cleanup.sweep_message(await chat.send_message("самарі не вийшло, дивись логи"))
        return
    cleanup.sweep_message(await chat.send_message("самарі перераховане"))


async def _lore_and_report(on_lore, db, chat) -> None:
    """Rewrite one chat's lore and say how it went.

    Spawned rather than awaited inside the callback: a rewrite takes tens of seconds, and
    a callback held open that long is redelivered by Telegram.
    """
    try:
        wrote = await on_lore(db, chat.id)
    except Exception:
        log.exception("rewriting the lore for %s failed", chat.id)
        cleanup.sweep_message(await chat.send_message("лор не вийшов, дивись логи"))
        return
    cleanup.sweep_message(
        await chat.send_message("лор переписаний" if wrote else "лор не переписався, дивись логи")
    )


def build_router(
    admin_ids: tuple[int, ...], on_reload=None, on_digest=None, on_lore=None, persona=None
) -> Router:
    router = Router(name="admin")
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))
    if persona is not None:
        _persona_size_hint["chars"] = len(persona["text"])

    async def show(target, db, screen_key: str, section: str | None, edit: bool) -> None:
        chat_id = target.chat.id
        if screen_key == "root":
            text = await root_text(db, chat_id)
            markup = await root_markup(db, chat_id)
        else:
            screen = menu.screen(screen_key)
            section = section or (screen.tabs[0] if screen.tabs else "")
            text = await screen_text(db, chat_id, screen)
            markup = await screen_markup(db, chat_id, screen, section)
        if not edit or not hasattr(target, "edit_text"):
            # A menu older than 48 hours arrives as InaccessibleMessage, which has no
            # edit_text. Answer fresh rather than raising into the callback.
            cleanup.sweep_message(await target.answer(text, reply_markup=markup), cleanup.MENU_TTL)
            return
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            # Tapping the screen you are already in produces identical content, and
            # Telegram treats an edit that changes nothing as an error.
            if "message is not modified" not in str(exc):
                raise
        # Pushed back on every navigation, so a menu in use never vanishes mid-tap.
        cleanup.sweep_message(target, cleanup.MENU_TTL)

    @router.message(Command("gryag"))
    async def open_menu(message: Message, db) -> None:
        await show(message, db, "root", None, edit=False)
        cleanup.sweep_message(message, cleanup.MENU_TTL)

    @router.callback_query(F.data.startswith("nav:"))
    async def navigate(query: CallbackQuery, db) -> None:
        await show(query.message, db, query.data.split(":", 1)[1], None, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("sec:"))
    async def switch_tab(query: CallbackQuery, db) -> None:
        _, screen_key, section = query.data.split(":", 2)
        await show(query.message, db, screen_key, section, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("set:"))
    async def cycle_setting(query: CallbackQuery, db) -> None:
        _, section, key = query.data.split(":", 2)
        setting = next(s for s in menu.SECTIONS[section][1] if s.key == key)
        current = await config.get(db, key, query.message.chat.id)
        value = menu.cycle(setting, current)
        await config.set(db, key, value, chat_id=query.message.chat.id)
        screen_key = next(s.key for s in menu.SCREENS if section in s.tabs)
        await show(query.message, db, screen_key, section, edit=True)
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
        await show(query.message, db, "root", None, edit=True)
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
        await show(query.message, db, "root", None, edit=True)

    @router.callback_query(F.data.startswith("spend:"))
    async def show_spend(query: CallbackQuery, db) -> None:
        period = query.data.split(":", 1)[1]
        report = await spend_report(db, query.message.chat.id, period)
        markup = await screen_markup(db, query.message.chat.id, menu.screen("spend"), "")
        try:
            await query.message.edit_text(report, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
        await query.answer()

    @router.callback_query(F.data == "pidor:roll")
    async def roll_now(query: CallbackQuery, db) -> None:
        # Imported here rather than at module level: pidor reaches back into screens for
        # chat_is_enabled, and a module-level import each way is a cycle.
        from gryag import pidor

        now = datetime.now(timezone.utc)
        result = await pidor.roll(db, query.message.chat.id, now)
        if result is None:
            await query.answer("нема з кого вибирати")
            return
        await query.answer("розіграно" if result[1] else "на сьогодні вже є")
        await pidor.announce(
            query.bot, db, query.message.chat.id, result[0], result[1], now
        )

    @router.callback_query(F.data == "pidor:top")
    async def show_top(query: CallbackQuery, db) -> None:
        from gryag import pidor

        cleanup.sweep_message(
            await query.message.answer(
                await pidor.leaderboard_text(db, query.message.chat.id, datetime.now(timezone.utc))
            ),
            cleanup.REPORT_TTL,
        )
        await query.answer()

    @router.callback_query(F.data == "board:now")
    async def show_board(query: CallbackQuery, db) -> None:
        from gryag import pidrahuika

        text = await pidrahuika.digest_text(db, "daily", datetime.now(timezone.utc))
        cleanup.sweep_message(
            await query.message.answer(text or "табло не відповідає"), cleanup.REPORT_TTL
        )
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
        # Not awaited: a multi-chunk day takes tens of seconds, and holding the callback
        # open that long makes Telegram redeliver it — which used to start a second
        # concurrent digest on the same connection.
        chat = query.message.chat
        _spawn(_rerun_and_report(on_digest, db, chat))

    @router.callback_query(F.data == "lore")
    async def rewrite_lore(query: CallbackQuery, db) -> None:
        if on_lore is None:
            await query.answer("недоступно")
            return
        await query.answer("переписую, це надовго")
        _spawn(_lore_and_report(on_lore, db, query.message.chat))

    @router.message(Command("nb"))
    async def toggle_whitelist(message: Message, db) -> None:
        """Reply to somebody with /nb to let them draw, or /nb alone to see the list.

        Never registered with setMyCommands, so it appears in nobody's menu.
        """
        raw = await config.get(db, "image_whitelist", message.chat.id)
        allowed = images.parse_whitelist(raw)
        target = message.reply_to_message.from_user if message.reply_to_message else None

        if target is None:
            cleanup.sweep_message(
                await message.reply("Малювати можуть: " + (", ".join(map(str, allowed)) or "ніхто"))
            )
            cleanup.sweep_message(message)
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
        cleanup.sweep_message(await message.reply(verdict))
        cleanup.sweep_message(message)

    @router.message(Command("unban"))
    async def lift_ban(message: Message, db) -> None:
        target = message.reply_to_message.from_user if message.reply_to_message else None
        if target is None:
            bans = await store.active_bans(db, message.chat.id, _now())
            cleanup.sweep_message(
                await message.reply(
                    "Заблоковані: "
                    + (", ".join(f"{who} до {until[11:16]}" for who, until, _ in bans) or "ніхто")
                )
            )
            cleanup.sweep_message(message)
            return
        lifted = await store.unban_user(db, message.chat.id, target.id)
        cleanup.sweep_message(
            await message.reply(
                f"{target.full_name} розблокований" if lifted else "він і не був заблокований"
            )
        )
        cleanup.sweep_message(message)

    return router
