"""Admin commands for user profile management."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, BotCommandScopeChat, Message

from app.config import Settings
from app.services.user_profile import UserProfileStore
from app.services import telemetry

router = Router()
logger = logging.getLogger(__name__)

# Command descriptions for bot menu
PROFILE_COMMANDS = [
    BotCommand(
        command="gryagprofile",
        description="Показати профіль користувача (свій або у відповідь)",
    ),
    BotCommand(
        command="gryagfacts",
        description="Список фактів про користувача (свої або у відповідь)",
    ),
    BotCommand(
        command="gryagremovefact",
        description="🔒 Видалити конкретний факт за ID (тільки адміни)",
    ),
    BotCommand(
        command="gryagforget",
        description="🔒 Видалити всі факти про користувача (тільки адміни, потребує підтвердження)",
    ),
    BotCommand(
        command="gryagexport",
        description="🔒 Експортувати профіль у JSON (тільки адміни)",
    ),
]


async def setup_profile_commands(bot: Bot, chat_id: int) -> None:
    """
    Set up profile management commands in bot menu for a specific chat.

    Args:
        bot: Bot instance
        chat_id: Chat ID to set commands for
    """
    try:
        await bot.set_my_commands(
            commands=PROFILE_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id)
        )
        logger.info(f"Profile commands registered for chat {chat_id}")
    except Exception as e:
        logger.warning(f"Failed to set profile commands for chat {chat_id}: {e}")


# Store confirmation requests for /gryagforget
_forget_confirmations: dict[str, tuple[int, int, float]] = (
    {}
)  # key: f"{chat_id}:{admin_id}", value: (user_id, chat_id, timestamp)


def _is_admin(user_id: int, settings: Settings) -> bool:
    """Check if user is an admin."""
    return user_id in settings.admin_user_ids_list


def _format_fact_type(fact_type: str) -> str:
    """Format fact type with emoji."""
    emojis = {
        "personal": "👤",
        "preference": "❤️",
        "skill": "🎓",
        "trait": "✨",
        "opinion": "💭",
    }
    return f"{emojis.get(fact_type, '📌')} {fact_type}"


def _format_timestamp(timestamp: str | None) -> str:
    """Format ISO timestamp to readable format."""
    if not timestamp:
        return "невідомо"
    try:
        dt = datetime.fromisoformat(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return "невідомо"


async def _resolve_target_user(
    message: Message,
    profile_store: UserProfileStore,
) -> tuple[int, int, str | None] | None:
    """
    Resolve target user from reply or self.

    Returns:
        Tuple of (user_id, chat_id, display_name) or None if not found
    """
    chat_id = message.chat.id

    # Check if replying to someone
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        return (
            target_user.id,
            chat_id,
            target_user.full_name or target_user.username,
        )

    # Otherwise, show self
    if message.from_user:
        return (
            message.from_user.id,
            chat_id,
            message.from_user.full_name or message.from_user.username,
        )

    return None


@router.message(Command("gryagprofile"))
async def cmd_profile(
    message: Message,
    profile_store: UserProfileStore,
    settings: Settings,
) -> None:
    """
    Show user profile summary.

    Usage:
        /gryagprofile - Show your own profile
        /gryagprofile (reply) - Show profile of replied user
    """
    if not message.from_user:
        return

    # Resolve target user
    target = await _resolve_target_user(message, profile_store)
    if not target:
        await message.reply("❌ Не можу визначити користувача.")
        return

    user_id, chat_id, display_name = target

    # Check permissions (admins can view anyone, users can only view self)
    if (
        not _is_admin(message.from_user.id, settings)
        and user_id != message.from_user.id
    ):
        await message.reply("❌ Ти можеш дивитись тільки свій профіль.")
        return

    # Get profile
    profile = await profile_store.get_profile(user_id, chat_id)
    if not profile:
        await message.reply(f"📭 Профіль для {display_name} не знайдено.")
        return

    # Get fact count
    fact_count = await profile_store.get_fact_count(user_id, chat_id)

    # Build response
    response = f"👤 <b>Профіль: {display_name}</b>\n\n"
    response += f"🆔 User ID: <code>{user_id}</code>\n"
    response += f"💬 Chat ID: <code>{chat_id}</code>\n"

    if profile.get("username"):
        response += f"📝 Username: @{profile['username']}\n"

    response += f"\n📊 <b>Статистика:</b>\n"
    response += f"• Взаємодій: {profile.get('interaction_count', 0)}\n"
    response += f"• Фактів: {fact_count}\n"
    response += (
        f"• Остання дія: {_format_timestamp(profile.get('last_interaction_at'))}\n"
    )
    response += f"• Створено: {_format_timestamp(profile.get('created_at'))}\n"
    response += f"• Версія профілю: {profile.get('profile_version', 1)}\n"

    if profile.get("summary"):
        response += f"\n📝 <b>Підсумок:</b>\n{profile['summary'][:200]}"
        if len(profile["summary"]) > 200:
            response += "..."

    await message.reply(response, parse_mode="HTML")
    telemetry.increment_counter("profile_admin.profile_viewed")


@router.message(Command("gryagfacts"))
async def cmd_facts(
    message: Message,
    profile_store: UserProfileStore,
    settings: Settings,
) -> None:
    """
    List facts for a user.

    Usage:
        /gryagfacts - Show your own facts
        /gryagfacts (reply) - Show facts of replied user
        /gryagfacts personal - Filter by fact type
    """
    if not message.from_user:
        return

    # Parse arguments
    args = message.text.split()[1:] if message.text else []
    fact_type_filter = (
        args[0]
        if args and args[0] in ["personal", "preference", "skill", "trait", "opinion"]
        else None
    )

    # Resolve target user
    target = await _resolve_target_user(message, profile_store)
    if not target:
        await message.reply("❌ Не можу визначити користувача.")
        return

    user_id, chat_id, display_name = target

    # Check permissions
    if (
        not _is_admin(message.from_user.id, settings)
        and user_id != message.from_user.id
    ):
        await message.reply("❌ Ти можеш дивитись тільки свої факти.")
        return

    # Get facts
    facts = await profile_store.get_facts(
        user_id=user_id,
        chat_id=chat_id,
        fact_type=fact_type_filter,
        limit=20,  # Paginate at 20
    )

    if not facts:
        filter_msg = f" типу '{fact_type_filter}'" if fact_type_filter else ""
        await message.reply(f"📭 Фактів{filter_msg} для {display_name} не знайдено.")
        return

    # Build response
    header = f"📚 <b>Факти: {display_name}</b>"
    if fact_type_filter:
        header += f" ({_format_fact_type(fact_type_filter)})"
    header += f"\n<i>Показано {len(facts)} з {await profile_store.get_fact_count(user_id, chat_id)}</i>\n\n"

    lines = [header]
    for fact in facts:
        fact_id = fact.get("id", "?")
        fact_type = fact.get("fact_type", "unknown")
        fact_key = fact.get("fact_key", "")
        fact_value = fact.get("fact_value", "")
        confidence = fact.get("confidence", 0.0)
        evidence = fact.get("evidence_text", "")

        line = f"{_format_fact_type(fact_type)} <code>[{fact_id}]</code> <b>{fact_key}</b>: {fact_value}\n"
        line += f"   ├ Впевненість: {confidence:.0%}\n"

        if evidence and len(evidence) > 50:
            line += f"   └ «{evidence[:50]}...»\n"
        elif evidence:
            line += f"   └ «{evidence}»\n"

        lines.append(line)

    response = "\n".join(lines)

    # Telegram message limit is 4096 chars
    if len(response) > 4000:
        response = response[:4000] + "\n\n<i>... обрізано, забагато фактів</i>"

    await message.reply(response, parse_mode="HTML")
    telemetry.increment_counter(
        "profile_admin.facts_viewed", filtered=str(bool(fact_type_filter))
    )


@router.message(Command("gryagremovefact"))
async def cmd_remove_fact(
    message: Message,
    profile_store: UserProfileStore,
    settings: Settings,
) -> None:
    """
    Remove a specific fact by ID (admin only).

    Usage:
        /gryagremovefact <fact_id>
    """
    if not message.from_user:
        return

    # Check admin
    if not _is_admin(message.from_user.id, settings):
        await message.reply("❌ Тільки адміни можуть видаляти факти.")
        return

    # Parse fact ID
    args = message.text.split()[1:] if message.text else []
    if not args:
        await message.reply("❌ Вкажи ID факту: /gryagremovefact <fact_id>")
        return

    try:
        fact_id = int(args[0])
    except ValueError:
        await message.reply("❌ ID факту має бути числом.")
        return

    # Delete fact
    success = await profile_store.delete_fact(fact_id)

    if success:
        await message.reply(f"✅ Факт #{fact_id} видалено.")
        telemetry.increment_counter("profile_admin.fact_removed")
        logger.info(
            f"Admin {message.from_user.id} removed fact #{fact_id}",
            extra={"admin_id": message.from_user.id, "fact_id": fact_id},
        )
    else:
        await message.reply(f"❌ Факт #{fact_id} не знайдено.")


@router.message(Command("gryagforget"))
async def cmd_forget(
    message: Message,
    profile_store: UserProfileStore,
    settings: Settings,
) -> None:
    """
    Clear all facts for a user (admin only).
    Requires confirmation within 30 seconds.

    Usage:
        /gryagforget (reply) - Clear facts for replied user
        /gryagforget - Repeat within 30s to confirm
    """
    if not message.from_user or not message.chat:
        return

    # Check admin
    if not _is_admin(message.from_user.id, settings):
        await message.reply("❌ Тільки адміни можуть забувати користувачів.")
        return

    chat_id = message.chat.id
    admin_id = message.from_user.id
    confirm_key = f"{chat_id}:{admin_id}"

    # Check if this is a confirmation
    if confirm_key in _forget_confirmations:
        user_id, chat_id_stored, timestamp = _forget_confirmations[confirm_key]

        # Check if within 30 seconds
        if (datetime.now().timestamp() - timestamp) > 30:
            del _forget_confirmations[confirm_key]
            await message.reply("⏱ Час підтвердження вийшов. Спробуй знову.")
            return

        # Perform deletion
        count = await profile_store.clear_user_facts(user_id, chat_id_stored)
        del _forget_confirmations[confirm_key]

        await message.reply(f"🗑 Забув {count} фактів про користувача {user_id}.")
        telemetry.increment_counter(
            "profile_admin.user_forgotten", fact_count=str(count)
        )
        logger.info(
            f"Admin {admin_id} cleared {count} facts for user {user_id}",
            extra={"admin_id": admin_id, "user_id": user_id, "fact_count": count},
        )
        return

    # First invocation - require reply
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply(
            "❌ Відповідай на повідомлення користувача, якого треба забути."
        )
        return

    target_user_id = message.reply_to_message.from_user.id
    display_name = (
        message.reply_to_message.from_user.full_name
        or message.reply_to_message.from_user.username
        or f"ID {target_user_id}"
    )

    # Get fact count
    fact_count = await profile_store.get_fact_count(target_user_id, chat_id)

    # Store confirmation request
    _forget_confirmations[confirm_key] = (
        target_user_id,
        chat_id,
        datetime.now().timestamp(),
    )

    await message.reply(
        f"⚠️ <b>ПІДТВЕРДЖЕННЯ</b>\n\n"
        f"Збираєшся видалити <b>{fact_count}</b> фактів про <b>{display_name}</b>.\n\n"
        f"Відправ /gryagforget ще раз протягом 30 секунд для підтвердження.",
        parse_mode="HTML",
    )


@router.message(Command("gryagexport"))
async def cmd_export(
    message: Message,
    profile_store: UserProfileStore,
    settings: Settings,
) -> None:
    """
    Export user profile as JSON (admin only).

    Usage:
        /gryagexport (reply) - Export profile of replied user
    """
    if not message.from_user:
        return

    # Check admin
    if not _is_admin(message.from_user.id, settings):
        await message.reply("❌ Тільки адміни можуть експортувати профілі.")
        return

    # Require reply
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("❌ Відповідай на повідомлення користувача для експорту.")
        return

    target_user_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    display_name = (
        message.reply_to_message.from_user.full_name or f"ID {target_user_id}"
    )

    # Get profile
    profile = await profile_store.get_profile(target_user_id, chat_id)
    if not profile:
        await message.reply(f"❌ Профіль для {display_name} не знайдено.")
        return

    # Get facts
    facts = await profile_store.get_facts(
        user_id=target_user_id,
        chat_id=chat_id,
        limit=1000,  # Get all facts
    )

    # Get relationships
    relationships = await profile_store.get_relationships(target_user_id, chat_id)

    # Build export
    export_data = {
        "profile": profile,
        "facts": facts,
        "relationships": relationships,
        "export_timestamp": datetime.now().isoformat(),
        "exported_by": message.from_user.id,
    }

    # Format as pretty JSON
    json_data = json.dumps(export_data, indent=2, ensure_ascii=False)

    # Send as text (Telegram will show it nicely)
    if len(json_data) < 4000:
        await message.reply(
            f"📦 <b>Експорт профілю: {display_name}</b>\n\n" f"<pre>{json_data}</pre>",
            parse_mode="HTML",
        )
    else:
        # Too long, send summary
        await message.reply(
            f"📦 <b>Експорт профілю: {display_name}</b>\n\n"
            f"• Фактів: {len(facts)}\n"
            f"• Відношень: {len(relationships)}\n\n"
            f"<i>Профіль занадто великий для відображення. "
            f"Зверніться до логів або БД для повного експорту.</i>",
            parse_mode="HTML",
        )

    telemetry.increment_counter("profile_admin.profile_exported")
    logger.info(
        f"Admin {message.from_user.id} exported profile for user {target_user_id}",
        extra={
            "admin_id": message.from_user.id,
            "user_id": target_user_id,
            "fact_count": len(facts),
        },
    )
