from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.redis_types import RedisLike
from app.services.rate_limiter import RateLimiter
from app.utils.persona_helpers import get_response

router = Router()

LOGGER = logging.getLogger(__name__)


def get_admin_commands(prefix: str = "gryag") -> list[BotCommand]:
    """Generate admin commands with dynamic prefix."""
    return [
        BotCommand(
            command=f"{prefix}ban",
            description="🔒 Забанити користувача (тільки адміни, у відповідь або ID)",
        ),
        BotCommand(
            command=f"{prefix}unban",
            description="🔒 Розбанити користувача (тільки адміни, у відповідь або ID)",
        ),
        BotCommand(
            command=f"{prefix}reset",
            description="🔒 Скинути ліміти повідомлень у чаті (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}chatinfo",
            description="🔒 Показати ID чату для конфігурації (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}donate",
            description="🔒 Надіслати повідомлення з реквізитами для донату (тільки адміни)",
        ),
    ]


# Keep for backwards compatibility (used in main.py)
ADMIN_COMMANDS = get_admin_commands()

# Default responses removed - rely solely on PersonaLoader and persona instructions
# If PersonaLoader is not available, these will be empty strings
ADMIN_ONLY = ""
BAN_SUCCESS = ""
UNBAN_SUCCESS = ""
ALREADY_BANNED = ""
NOT_BANNED = ""
MISSING_TARGET = ""
RESET_DONE = ""


# Import get_response from shared utility (replaces local _get_response)
_get_response = get_response  # Alias for backward compatibility


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(
        message.from_user and message.from_user.id in settings.admin_user_ids_list
    )


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


@router.message(Command(commands=["gryagban", "ban"]))
async def ban_user_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    persona_loader: Any | None = None,
) -> None:
    # Support both legacy "gryagban" and dynamic "{prefix}ban"
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    target = _extract_target(message)
    if not target:
        await message.reply(
            _get_response("missing_target", persona_loader, MISSING_TARGET)
        )
        return

    target_id, target_label = target
    chat_id = message.chat.id

    if await store.is_banned(chat_id, target_id):
        await message.reply(
            _get_response("already_banned", persona_loader, ALREADY_BANNED)
        )
        return

    await store.ban_user(chat_id, target_id)
    await message.reply(
        _get_response("ban_success", persona_loader, BAN_SUCCESS, user=target_label)
    )


@router.message(Command(commands=["gryagunban", "unban"]))
async def unban_user_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    persona_loader: Any | None = None,
) -> None:
    # Support both legacy "gryagunban" and dynamic "{prefix}unban"
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    target = _extract_target(message)
    if not target:
        await message.reply(
            _get_response("missing_target", persona_loader, MISSING_TARGET)
        )
        return

    target_id, target_label = target
    chat_id = message.chat.id

    if not await store.is_banned(chat_id, target_id):
        await message.reply(_get_response("not_banned", persona_loader, NOT_BANNED))
        return

    await store.unban_user(chat_id, target_id)
    await message.reply(
        _get_response("unban_success", persona_loader, UNBAN_SUCCESS, user=target_label)
    )


@router.message(Command(commands=["gryagreset", "reset"]))
async def reset_quotas_command(
    message: Message,
    settings: Settings,
    store: ContextStore,
    rate_limiter: RateLimiter | None = None,
    redis_client: RedisLike | None = None,
    persona_loader: Any | None = None,
    image_gen_service: Any | None = None,
) -> None:
    # Support both legacy "gryagreset" and dynamic "{prefix}reset"
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    chat_id = message.chat.id

    # Check if this is a reply to a specific user (for per-user reset)
    target_user_id = None
    target_user_name = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_user_name = (
            message.reply_to_message.from_user.full_name
            or message.reply_to_message.from_user.username
            or str(target_user_id)
        )

    # Reset rate limiter (SQLite-backed)
    rate_limit_reset_msg = ""
    if rate_limiter is not None:
        if target_user_id is not None:
            # Per-user reset
            deleted = await rate_limiter.reset_user(target_user_id)
            LOGGER.info(
                f"Reset {deleted} rate limit record(s) for user {target_user_id}"
            )
            if deleted > 0:
                rate_limit_reset_msg = f"✓ Скинув ліміти для {target_user_name}\n"
        else:
            # Chat-wide reset
            deleted = await rate_limiter.reset_chat(chat_id)
            LOGGER.info(f"Reset {deleted} rate limit record(s) for chat {chat_id}")
            if deleted > 0:
                rate_limit_reset_msg = f"✓ Скинув ліміти повідомлень для чату ({deleted} записів)\n"

    # Reset image generation quotas (if service available)
    image_quota_reset_msg = ""
    if image_gen_service is not None:
        try:
            if target_user_id is not None:
                # Per-user image quota reset
                was_reset = await image_gen_service.reset_user_quota(
                    target_user_id, chat_id
                )
                LOGGER.info(
                    f"Reset image quota for user {target_user_id} in chat {chat_id}"
                )
                if was_reset:
                    image_quota_reset_msg = (
                        f"✓ Скинув ліміт генерації зображень для {target_user_name}\n"
                    )
            else:
                # Chat-wide image quota reset
                deleted = await image_gen_service.reset_chat_quotas(chat_id)
                LOGGER.info(
                    f"Reset image quotas for {deleted} user(s) in chat {chat_id}"
                )
                # Show message even if no records existed (quota was already empty)
                if deleted > 0:
                    image_quota_reset_msg = (
                        f"✓ Скинув ліміти зображень для чату ({deleted} користувачів)\n"
                    )
                else:
                    image_quota_reset_msg = (
                        "✓ Ліміти зображень скинуті для чату (нема активних квот)\n"
                    )
        except Exception as e:
            LOGGER.warning(f"Failed to reset image quotas: {e}", exc_info=True)

    # Also clear Redis quotas if available (legacy cleanup with hardcoded namespace)
    redis_reset_msg = ""
    if redis_client is not None:
        pattern = f"gryag:quota:{chat_id}:*"
        cursor = 0
        try:
            deleted_keys = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    await redis_client.delete(*keys)
                    deleted_keys += len(keys)
                if cursor == 0:
                    break
            if deleted_keys > 0:
                redis_reset_msg = f"✓ Очистив Redis кеш ({deleted_keys} записів)\n"
        except Exception as e:
            LOGGER.warning(
                f"Failed to clear Redis quotas for chat {chat_id}: {e}",
                exc_info=True,
            )

    # Build final response
    if target_user_id is not None:
        response = (
            f"<b>Скинув ліміти для {target_user_name}</b>:\n"
            f"{rate_limit_reset_msg}{image_quota_reset_msg}"
            if (rate_limit_reset_msg or image_quota_reset_msg)
            else f"Нема чого скидати для {target_user_name}"
        )
    else:
        response = (
            f"<b>Обнулив ліміти</b>:\n"
            f"{rate_limit_reset_msg}{image_quota_reset_msg}{redis_reset_msg}"
            if (rate_limit_reset_msg or image_quota_reset_msg or redis_reset_msg)
            else _get_response("reset_done", persona_loader, RESET_DONE)
        )

    await message.reply(response, parse_mode="HTML")


@router.message(Command(commands=["gryagchatinfo", "chatinfo"]))
async def chatinfo_command(
    message: Message,
    settings: Settings,
    persona_loader: Any | None = None,
) -> None:
    """Show chat ID and type for configuration purposes (admin only).

    This helps admins discover chat IDs to configure whitelist/blacklist.
    """
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    chat = message.chat
    chat_type = chat.type
    chat_id = chat.id

    # Build response with chat information
    response = f"📊 <b>Інформація про чат</b>\n\n"
    response += f"🆔 Chat ID: <code>{chat_id}</code>\n"
    response += f"📱 Тип: {chat_type}\n"

    if chat.title:
        response += f"📝 Назва: {chat.title}\n"

    if chat.username:
        response += f"🔗 Username: @{chat.username}\n"

    # Add configuration hints
    response += f"\n💡 <b>Використання:</b>\n"

    if chat_id < 0:  # Group/supergroup
        response += f"Для whitelist режиму:\n"
        response += f"<code>ALLOWED_CHAT_IDS={chat_id}</code>\n\n"
        response += f"Для blacklist режиму:\n"
        response += f"<code>BLOCKED_CHAT_IDS={chat_id}</code>\n\n"
        response += f"Кілька чатів через кому:\n"
        response += f"<code>ALLOWED_CHAT_IDS={chat_id},-100456,...</code>"
    else:  # Private chat
        response += f"Це приватний чат (ID > 0).\n"
        response += f"Приватні чати з адмінами завжди дозволені."

    # Show current configuration
    response += f"\n\n⚙️ <b>Поточна конфігурація:</b>\n"
    response += f"Режим: <code>{settings.bot_behavior_mode}</code>\n"

    if settings.allowed_chat_ids_list:
        response += f"Whitelist: <code>{settings.allowed_chat_ids_list}</code>\n"

    if settings.blocked_chat_ids_list:
        response += f"Blacklist: <code>{settings.blocked_chat_ids_list}</code>\n"

    # Check if current chat is allowed
    if settings.bot_behavior_mode == "whitelist":
        if chat_id in settings.allowed_chat_ids_list or chat_id > 0:
            response += f"\n✅ Цей чат <b>дозволений</b>"
        else:
            response += f"\n❌ Цей чат <b>НЕ в whitelist</b>"
    elif settings.bot_behavior_mode == "blacklist":
        if chat_id in settings.blocked_chat_ids_list:
            response += f"\n❌ Цей чат <b>заблокований</b>"
        else:
            response += f"\n✅ Цей чат <b>дозволений</b>"
    else:  # global
        response += f"\n✅ Всі чати дозволені (global режим)"

    await message.reply(response)


@router.message(Command(commands=["gryagdonate", "donate"]))
async def donate_command(
    message: Message,
    settings: Settings,
    donation_scheduler: Any | None = None,
    persona_loader: Any | None = None,
) -> None:
    """Send donation message to current chat (admin only).

    This allows admins to manually trigger the donation reminder
    in the current chat without waiting for the scheduled time.
    """
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    chat_id = message.chat.id

    if donation_scheduler is None:
        error_msg = (
            "❌ Donation scheduler not initialized. Please check bot logs and ensure the donation service started correctly."
        )
        await message.reply(error_msg)
        LOGGER.error("Donation scheduler is None in donate_command")
        return

    # Send donation message immediately
    try:
        success = await donation_scheduler.send_now(chat_id)

        if success:
            await message.reply(
                "✅ Donation message sent successfully!\n\n"
                "щоб гряг продовжував функціонувати треба оплачувати його комуналку (API)\n\n"
                "підтримати проєкт:\n\n"
                "🔗Посилання на банку\nhttps://send.monobank.ua/jar/77iG8mGBsH\n\n"
                "💳Номер картки банки\n4874 1000 2180 1892"
            )
            LOGGER.info(
                f"Admin {message.from_user.id} triggered donation message in chat {chat_id}"
            )
        else:
            await message.reply(
                "❌ Failed to send donation message.\n\n"
                "Possible reasons:\n"
                "- Bot doesn't have permission to send messages in this chat\n"
                "- Chat ID is in the ignored list\n"
                "- Telegram API error\n\n"
                "Check bot logs for more details."
            )
            LOGGER.error(f"Failed to send donation message in chat {chat_id}")
    except Exception as e:
        error_details = str(e)
        await message.reply(
            f"❌ Error sending donation message:\n{error_details}\n\n"
            "Check bot logs for more details."
        )
        LOGGER.error(
            f"Exception while sending donation message in chat {chat_id}: {e}",
            exc_info=True,
        )
