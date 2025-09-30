from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.redis_types import RedisLike

router = Router()

ADMIN_ONLY = "Ця команда лише для своїх. І явно не для тебе."
BAN_SUCCESS = "Готово: користувача кувалдіровано."
UNBAN_SUCCESS = "Ок, розбанив. Нехай знову пиздить."
ALREADY_BANNED = "Та він і так у бані сидів."
NOT_BANNED = "Нема кого розбанювати — список чистий."
MISSING_TARGET = "Покажи, кого саме прибрати: зроби реплай або передай ID."
RESET_DONE = "Все, обнулив ліміти. Можна знову розганяти балачки."


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_user_ids)


def _extract_target(message: Message) -> tuple[int, str] | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user
        return user.id, user.full_name or user.username or str(user.id)
    if message.text:
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) == 2:
            candidate = parts[1].strip()
            if candidate.startswith("@"):
                # Without a lookup we can't resolve username to ID.
                return None
            try:
                return int(candidate), candidate
            except ValueError:
                return None
    return None


@router.message(Command("gryagban"))
async def ban_user_command(
    message: Message, settings: Settings, store: ContextStore
) -> None:
    if not _is_admin(message, settings):
        await message.reply(ADMIN_ONLY)
        return

    target = _extract_target(message)
    if not target:
        await message.reply(MISSING_TARGET)
        return

    target_id, target_label = target
    chat_id = message.chat.id

    if await store.is_banned(chat_id, target_id):
        await message.reply(ALREADY_BANNED)
        return

    await store.ban_user(chat_id, target_id)
    await message.reply(f"{BAN_SUCCESS} ({target_label})")


@router.message(Command("gryagunban"))
async def unban_user_command(
    message: Message, settings: Settings, store: ContextStore
) -> None:
    if not _is_admin(message, settings):
        await message.reply(ADMIN_ONLY)
        return

    target = _extract_target(message)
    if not target:
        await message.reply(MISSING_TARGET)
        return

    target_id, target_label = target
    chat_id = message.chat.id

    if not await store.is_banned(chat_id, target_id):
        await message.reply(NOT_BANNED)
        return

    await store.unban_user(chat_id, target_id)
    await message.reply(f"{UNBAN_SUCCESS} ({target_label})")


@router.message(Command("gryagreset"))
async def reset_quotas_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    redis_client: RedisLike | None = None,
) -> None:
    if not _is_admin(message, settings):
        await message.reply(ADMIN_ONLY)
        return

    chat_id = message.chat.id
    await store.reset_quotas(chat_id)

    if redis_client is not None:
        pattern = f"gryag:quota:{chat_id}:*"
        cursor = 0
        try:
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    await redis_client.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass

    await message.reply(RESET_DONE)
