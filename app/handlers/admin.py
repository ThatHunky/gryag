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

# Default responses (will be overridden by PersonaLoader if enabled)
ADMIN_ONLY = "Ця команда лише для своїх. І явно не для тебе."
BAN_SUCCESS = "Готово: користувача кувалдіровано."
UNBAN_SUCCESS = "Ок, розбанив. Нехай знову пиздить."
ALREADY_BANNED = "Та він і так у бані сидив."
NOT_BANNED = "Нема кого розбанювати — список чистий."
MISSING_TARGET = "Покажи, кого саме прибрати: зроби реплай або передай ID."
RESET_DONE = "Все, обнулив ліміти. Можна знову розганяти балачки."


def _get_response(
    key: str,
    persona_loader: Any | None,
    default: str,
    **kwargs: Any,
) -> str:
    """Get response from PersonaLoader if available, otherwise use default."""
    # If persona loader is available, inject bot-related variables (if present)
    if persona_loader is not None:
        try:
            persona = getattr(persona_loader, "persona", None)
            bot_name = getattr(persona, "name", None) if persona is not None else None
            bot_display = (
                getattr(persona, "display_name", None) if persona is not None else None
            )
            # Do not override variables explicitly provided by the caller
            if bot_name and "bot_name" not in kwargs:
                kwargs["bot_name"] = bot_name
            if bot_display and "bot_display_name" not in kwargs:
                kwargs["bot_display_name"] = bot_display
        except Exception:
            LOGGER.exception(
                "Failed to inject persona variables into response template"
            )

        return persona_loader.get_response(key, **kwargs)

    # No persona loader: try to format the default template with kwargs if provided
    if kwargs:
        try:
            return default.format(**kwargs)
        except KeyError:
            LOGGER.warning(
                "Missing variable while formatting default response for key=%s", key
            )
            # Fall through to return raw default
    return default


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
) -> None:
    # Support both legacy "gryagreset" and dynamic "{prefix}reset"
    if not _is_admin(message, settings):
        await message.reply(_get_response("admin_only", persona_loader, ADMIN_ONLY))
        return

    chat_id = message.chat.id

    # Reset rate limiter (SQLite-backed)
    if rate_limiter is not None:
        deleted = await rate_limiter.reset_chat(chat_id)
        LOGGER.info(f"Reset {deleted} rate limit record(s) for chat {chat_id}")

    # Also clear Redis quotas if available (legacy cleanup with hardcoded namespace)
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
        except Exception as e:
            LOGGER.warning(
                f"Failed to clear Redis quotas for chat {chat_id}: {e}",
                exc_info=True,
            )

    await message.reply(_get_response("reset_done", persona_loader, RESET_DONE))


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
        await message.reply("Donation scheduler is not initialized.")
        LOGGER.error("Donation scheduler is None in donate_command")
        return

    # Send donation message immediately
    success = await donation_scheduler.send_now(chat_id)

    if success:
        LOGGER.info(f"Admin {message.from_user.id} triggered donation message in chat {chat_id}")
    else:
        await message.reply("Failed to send donation message. Check logs for details.")
        LOGGER.error(f"Failed to send donation message in chat {chat_id}")
