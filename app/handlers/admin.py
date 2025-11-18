from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from app.config import Settings
from app.infrastructure.db_utils import get_db_connection
from app.infrastructure.query_converter import convert_query_to_postgres
from app.services.context_store import ContextStore
from app.services.donation_scheduler import DONATION_MESSAGE
from app.services.rate_limiter import RateLimiter
from app.services.redis_types import RedisLike
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
    ]


# Keep for backwards compatibility (used in main.py)
ADMIN_COMMANDS = get_admin_commands()

# Default responses - fallback when PersonaLoader is unavailable
# These should match response templates but provide safe fallbacks
ADMIN_ONLY = "Тільки адміни можуть це робити."
BAN_SUCCESS = "Забанено користувача {user}."
UNBAN_SUCCESS = "Розбанено користувача {user}."
ALREADY_BANNED = "Користувач вже забанений."
NOT_BANNED = "Користувач не забанений."
MISSING_TARGET = "Вкажи користувача для цієї дії."
RESET_DONE = "Квоти скинуто."


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
                rate_limit_reset_msg = (
                    f"✓ Скинув ліміти повідомлень для чату ({deleted} записів)\n"
                )

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
    response = "📊 <b>Інформація про чат</b>\n\n"
    response += f"🆔 Chat ID: <code>{chat_id}</code>\n"
    response += f"📱 Тип: {chat_type}\n"

    if chat.title:
        response += f"📝 Назва: {chat.title}\n"

    if chat.username:
        response += f"🔗 Username: @{chat.username}\n"

    # Add configuration hints
    response += "\n💡 <b>Використання:</b>\n"

    if chat_id < 0:  # Group/supergroup
        response += "Для whitelist режиму:\n"
        response += f"<code>ALLOWED_CHAT_IDS={chat_id}</code>\n\n"
        response += "Для blacklist режиму:\n"
        response += f"<code>BLOCKED_CHAT_IDS={chat_id}</code>\n\n"
        response += "Кілька чатів через кому:\n"
        response += f"<code>ALLOWED_CHAT_IDS={chat_id},-100456,...</code>"
    else:  # Private chat
        response += "Це приватний чат (ID > 0).\n"
        response += "Приватні чати з адмінами завжди дозволені."

    # Show current configuration
    response += "\n\n⚙️ <b>Поточна конфігурація:</b>\n"
    response += f"Режим: <code>{settings.bot_behavior_mode}</code>\n"

    if settings.allowed_chat_ids_list:
        response += f"Whitelist: <code>{settings.allowed_chat_ids_list}</code>\n"

    if settings.blocked_chat_ids_list:
        response += f"Blacklist: <code>{settings.blocked_chat_ids_list}</code>\n"

    # Check if current chat is allowed
    if settings.bot_behavior_mode == "whitelist":
        if chat_id in settings.allowed_chat_ids_list or chat_id > 0:
            response += "\n✅ Цей чат <b>дозволений</b>"
        else:
            response += "\n❌ Цей чат <b>НЕ в whitelist</b>"
    elif settings.bot_behavior_mode == "blacklist":
        if chat_id in settings.blocked_chat_ids_list:
            response += "\n❌ Цей чат <b>заблокований</b>"
        else:
            response += "\n✅ Цей чат <b>дозволений</b>"
    else:  # global
        response += "\n✅ Всі чати дозволені (global режим)"

    await message.reply(response)


@router.message(Command(commands=["broadcastdonate"]))
async def broadcast_donate_command(
    message: Message,
    bot: Bot,
    settings: Settings,
    bot_id: int | None = None,
) -> None:
    """Hidden command to broadcast donation message to all private chats (user_id 392817811 only).

    This command is not registered in Telegram's command menu and is only accessible
    by typing the command directly. It broadcasts the donation message to all private chats.
    Requires confirmation before proceeding.
    """
    # Check if user is authorized (hardcoded user_id check)
    if not message.from_user or message.from_user.id != 392817811:
        # Log authorization failure for debugging (but don't reveal command exists to user)
        LOGGER.debug(
            f"Unauthorized broadcastdonate attempt from user {message.from_user.id if message.from_user else 'unknown'}"
        )
        return

    # Check if this is a confirmation
    command_text = (message.text or "").strip().lower()
    is_confirmation = False

    # Improved confirmation text matching: check for exact patterns
    # Matches: "/broadcastdonate confirm", "/broadcastdonate yes", "/broadcastdonate confirm something"
    if command_text.startswith("/broadcastdonate"):
        parts = command_text.split()
        if len(parts) >= 2 and parts[1] in ["confirm", "yes"]:
            is_confirmation = True

    # Check if message is a reply to a confirmation message from the bot
    if message.reply_to_message and message.reply_to_message.from_user:
        # Verify it's a reply to THIS bot's message (not just any bot)
        reply_user = message.reply_to_message.from_user
        if reply_user.is_bot and bot_id is not None and reply_user.id == bot_id:
            # Also verify the reply is to a confirmation message by checking text content
            reply_to_text = (message.reply_to_message.text or "").lower()
            if (
                "підтвердження трансляції" in reply_to_text
                or "подтверждение трансляции" in reply_to_text
            ):
                reply_text = (message.text or "").strip().lower()
                if reply_text in ["yes", "так", "y", "т"]:
                    is_confirmation = True

    # If not confirmed, show confirmation prompt (without querying database yet)
    if not is_confirmation:
        confirmation_msg = (
            "⚠️ <b>Підтвердження трансляції</b>\n\n"
            "Ви збираєтеся надіслати повідомлення про донат до всіх приватних чатів.\n\n"
            "Для підтвердження надішліть:\n"
            "• <code>/broadcastdonate confirm</code> або\n"
            "• <code>/broadcastdonate yes</code> або\n"
            "• Надішліть <code>yes</code> або <code>так</code> у відповідь на це повідомлення.\n\n"
            "Для скасування просто проігноруйте це повідомлення."
        )
        await message.reply(confirmation_msg, parse_mode="HTML")
        return

    # Confirmation received - now query database and proceed with broadcast
    try:
        # Query all distinct private chat IDs (chat_id > 0)
        query, params = convert_query_to_postgres(
            "SELECT DISTINCT chat_id FROM messages WHERE chat_id > 0 ORDER BY chat_id",
            (),
        )

        private_chat_ids: list[int] = []
        async with get_db_connection(settings.database_url) as conn:
            rows = await conn.fetch(query, *params)
            private_chat_ids = [row["chat_id"] for row in rows]

        total_chats = len(private_chat_ids)
        if total_chats == 0:
            await message.reply("❌ Не знайдено жодного приватного чату в базі даних.")
            return

        await message.reply(
            "🔄 Починаю трансляцію повідомлення про донат до всіх приватних чатів..."
        )

        LOGGER.info(
            f"User {message.from_user.id} starting broadcast to {total_chats} private chats"
        )

        # Send messages to each private chat with rate limiting
        success_count = 0
        failed_count = 0
        failed_chats: list[int] = []

        for chat_id in private_chat_ids:
            try:
                await bot.send_message(chat_id, DONATION_MESSAGE)
                success_count += 1
                # Rate limiting: wait 0.2 seconds between sends to avoid Telegram rate limits
                if success_count < total_chats:  # Don't wait after the last message
                    await asyncio.sleep(0.2)
                # Log progress every 10 chats
                if success_count % 10 == 0:
                    LOGGER.debug(
                        f"Broadcast progress: {success_count}/{total_chats} sent successfully"
                    )
            except TelegramBadRequest as e:
                # Common reasons: bot blocked, chat not found, etc.
                failed_count += 1
                failed_chats.append(chat_id)
                LOGGER.debug(f"Failed to send donation message to chat {chat_id}: {e}")
                # Still wait to maintain rate limiting even on failures
                if (success_count + failed_count) < total_chats:
                    await asyncio.sleep(0.2)
            except Exception as e:
                # Other unexpected errors
                failed_count += 1
                failed_chats.append(chat_id)
                LOGGER.warning(
                    f"Unexpected error sending to chat {chat_id}: {e}",
                    exc_info=True,
                )
                # Still wait to maintain rate limiting even on failures
                if (success_count + failed_count) < total_chats:
                    await asyncio.sleep(0.2)

        # Send summary to admin
        summary = (
            f"✅ Трансляцію завершено!\n\n"
            f"📊 Статистика:\n"
            f"• Всього чатів: {total_chats}\n"
            f"• Відправлено успішно: {success_count}\n"
            f"• Помилок: {failed_count}"
        )

        if failed_count > 0 and failed_count <= 10:
            # Show failed chat IDs if there are few failures
            summary += "\n\n❌ Не вдалося відправити до чатів:\n"
            summary += ", ".join(str(cid) for cid in failed_chats[:10])
        elif failed_count > 10:
            summary += f"\n\n❌ Не вдалося відправити до {failed_count} чатів (список занадто великий)"

        await message.reply(summary)
        LOGGER.info(
            f"Broadcast completed: {success_count} successful, {failed_count} failed "
            f"out of {total_chats} total private chats"
        )

    except Exception as e:
        error_msg = f"❌ Помилка під час трансляції: {str(e)}"
        await message.reply(error_msg)
        LOGGER.error(
            f"Exception during broadcast donation command: {e}",
            exc_info=True,
        )
