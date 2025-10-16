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
from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine

router = Router()
logger = logging.getLogger(__name__)


def get_profile_commands(prefix: str = "gryag") -> list[BotCommand]:
    """Generate profile commands with dynamic prefix."""
    return [
        BotCommand(
            command=f"{prefix}profile",
            description="Показати профіль користувача (свій або у відповідь)",
        ),
        BotCommand(
            command=f"{prefix}facts",
            description="Список фактів про користувача (свої або у відповідь)",
        ),
        BotCommand(
            command=f"{prefix}removefact",
            description="🔒 Видалити конкретний факт за ID (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}forget",
            description="🔒 Видалити всі факти про користувача (тільки адміни, потребує підтвердження)",
        ),
        BotCommand(
            command=f"{prefix}export",
            description="🔒 Експортувати профіль у JSON (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}users",
            description="🔒 Перелік користувачів у чаті (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}self",
            description="🔒 Показати self-learning профіль бота (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}insights",
            description="🔒 Показати insights про бота (тільки адміни)",
        ),
    ]


# Keep for backwards compatibility (used in main.py)
PROFILE_COMMANDS = get_profile_commands()


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


def _format_timestamp(timestamp: Any) -> str:
    """Format timestamp-like value to readable format."""
    if timestamp in (None, "", 0):
        return "невідомо"

    try:
        if isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(int(timestamp))
        elif isinstance(timestamp, str):
            if timestamp.isdigit():
                dt = datetime.fromtimestamp(int(timestamp))
            else:
                dt = datetime.fromisoformat(timestamp)
        else:
            return "невідомо"
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return "невідомо"


def _parse_users_command_args(text: str | None) -> tuple[bool, int]:
    """Parse optional arguments for /gryagusers command."""
    include_inactive = True
    limit = 20

    if not text:
        return include_inactive, limit

    parts = text.split()[1:]
    for token in parts:
        lower = token.lower()
        if lower in {"active", "members", "current"}:
            include_inactive = False
        elif token.isdigit():
            limit = max(1, min(int(token), 100))

    return include_inactive, limit


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


@router.message(Command(commands=["gryagusers", "users"]))
async def list_chat_users_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
) -> None:
    """List known users for the current chat."""
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    include_inactive, limit = _parse_users_command_args(message.text)
    chat_id = message.chat.id

    users = await profile_store.list_chat_users(
        chat_id=chat_id, limit=limit, include_inactive=include_inactive
    )

    if not users:
        await message.reply("📭 Немає збережених користувачів для цього чату.")
        return

    status_icons = {
        "member": "✅",
        "administrator": "🛡️",
        "creator": "👑",
        "left": "🚪",
        "kicked": "🚫",
        "banned": "⛔",
        "restricted": "⚠️",
    }

    lines: list[str] = []
    for idx, user in enumerate(users, start=1):
        user_id = user["user_id"]
        display_name = user.get("display_name") or "—"
        username = user.get("username")
        username_text = f"@{username.lstrip('@')}" if username else "—"
        status = user.get("membership_status", "unknown")
        status_icon = status_icons.get(status, "❔")
        last_seen = _format_timestamp(user.get("last_seen"))
        interactions = user.get("interaction_count", 0)

        lines.append(
            f"{idx}. <b>{display_name}</b> ({username_text})\n"
            f"   ID: <code>{user_id}</code> • Статус: {status_icon} {status}\n"
            f"   Остання активність: {last_seen} • Взаємодій: {interactions}"
        )

    header = "📇 <b>Учасники чату</b>\n"
    header += (
        "Показую лише активних користувачів.\n"
        if not include_inactive
        else "Показую активних та архівованих користувачів.\n"
    )
    header += f"Разом: {len(users)} (ліміт {limit})\n\n"

    await message.reply(header + "\n".join(lines), parse_mode="HTML")


@router.message(Command(commands=["gryagprofile", "profile"]))
async def get_user_profile_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
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


@router.message(Command(commands=["gryagfacts", "facts"]))
async def get_user_facts_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
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


@router.message(Command(commands=["gryagremovefact", "removefact"]))
async def remove_fact_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
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


@router.message(Command(commands=["gryagforget", "forget"]))
async def forget_user_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
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


@router.message(Command(commands=["gryagexport", "export"]))
async def export_profile_command(
    message: Message, settings: Settings, profile_store: UserProfileStore
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


@router.message(Command(commands=["gryagself", "self"]))
async def cmd_bot_self_profile(
    message: Message,
    settings: Settings,
    bot_profile: BotProfileStore | None,
) -> None:
    """View bot's self-learning profile (admin only)."""
    if not _is_admin(message.from_user.id, settings):
        await message.reply("🔒 Ця команда доступна тільки адмінам.")
        return

    if not bot_profile:
        await message.reply(
            "🤖 Bot self-learning вимкнено (ENABLE_BOT_SELF_LEARNING=false)."
        )
        return

    chat_id = message.chat.id

    # Get effectiveness summary
    summary = await bot_profile.get_effectiveness_summary(chat_id=chat_id, days=7)

    # Get top facts by category
    categories = [
        "communication_style",
        "knowledge_domain",
        "tool_effectiveness",
        "user_interaction",
        "mistake_pattern",
    ]

    response = "🤖 <b>Bot Self-Learning Profile</b>\n\n"
    response += f"📊 <b>Effectiveness (last 7 days)</b>\n"
    response += f"• Overall score: {summary['effectiveness_score']:.1%}\n"
    response += f"• Recent score: {summary['recent_effectiveness']:.1%}\n"
    response += f"• Total interactions: {summary['total_interactions']}\n"
    response += f"• Positive: {summary['positive_interactions']} ({summary['positive_interactions']/max(summary['total_interactions'],1):.1%})\n"
    response += f"• Negative: {summary['negative_interactions']} ({summary['negative_interactions']/max(summary['total_interactions'],1):.1%})\n\n"

    response += f"⚡ <b>Performance</b>\n"
    response += f"• Avg response time: {summary['avg_response_time_ms']:.0f}ms\n"
    response += f"• Avg tokens: {summary['avg_token_count']:.0f}\n"
    response += f"• Avg sentiment: {summary['avg_sentiment']:.2f}\n\n"

    # Show top 3 facts per category
    for category in categories:
        facts = await bot_profile.get_facts(
            category=category,
            chat_id=chat_id,
            min_confidence=0.5,
            limit=3,
        )

        if facts:
            emoji_map = {
                "communication_style": "💬",
                "knowledge_domain": "📚",
                "tool_effectiveness": "🛠",
                "user_interaction": "👥",
                "mistake_pattern": "⚠️",
            }
            emoji = emoji_map.get(category, "📌")
            response += f"{emoji} <b>{category.replace('_', ' ').title()}</b>\n"

            for fact in facts:
                confidence = fact.get("effective_confidence", fact["confidence"])
                response += (
                    f"• {fact['fact_key'][:50]}: {fact['fact_value'][:80]}...\n"
                    f"  └ confidence: {confidence:.2f}, evidence: {fact['evidence_count']}\n"
                )

            response += "\n"

    # Truncate if too long
    if len(response) > 4000:
        response = response[:3950] + "\n\n<i>... (truncated)</i>"

    await message.reply(response, parse_mode="HTML")
    telemetry.increment_counter("profile_admin.bot_self_viewed")
    logger.info(
        f"Admin {message.from_user.id} viewed bot self-profile for chat {chat_id}"
    )


@router.message(Command(commands=["gryaginsights", "insights"]))
async def cmd_generate_insights(
    message: Message,
    settings: Settings,
    bot_profile: BotProfileStore | None,
    bot_learning: BotLearningEngine | None,
) -> None:
    """Generate Gemini-powered insights about bot's learning (admin only)."""
    if not _is_admin(message.from_user.id, settings):
        await message.reply("🔒 Ця команда доступна тільки адмінам.")
        return

    if not bot_profile or not bot_learning:
        await message.reply(
            "🤖 Bot self-learning вимкнено (ENABLE_BOT_SELF_LEARNING=false)."
        )
        return

    chat_id = message.chat.id

    # Send initial message
    status_msg = await message.reply(
        "🧠 Генерую інсайти через Gemini... (це займе ~10-30 секунд)"
    )

    try:
        # Generate insights
        insights = await bot_learning.generate_gemini_insights(chat_id=chat_id, days=7)

        if not insights:
            await status_msg.edit_text(
                "ℹ️ Не вдалося згенерувати інсайти (недостатньо даних або помилка API)."
            )
            return

        response = "🧠 <b>Bot Self-Reflection Insights</b>\n\n"
        response += f"<i>Generated from {await bot_profile.get_effectiveness_summary(chat_id, 7)}</i>\n\n"

        for idx, insight in enumerate(insights, 1):
            emoji_map = {
                "effectiveness_trend": "📈",
                "communication_pattern": "💬",
                "knowledge_gap": "📚",
                "temporal_insight": "⏰",
                "improvement_suggestion": "💡",
            }
            emoji = emoji_map.get(insight.get("type", ""), "📌")

            response += f"{emoji} <b>Insight {idx}</b>\n"
            response += f"{insight['text']}\n"
            response += f"• Confidence: {insight.get('confidence', 0.5):.2f}\n"
            response += f"• Actionable: {'✅ Yes' if insight.get('actionable') else '❌ No'}\n\n"

        # Truncate if too long
        if len(response) > 4000:
            response = response[:3950] + "\n\n<i>... (truncated)</i>"

        await status_msg.edit_text(response, parse_mode="HTML")
        telemetry.increment_counter("profile_admin.insights_generated")
        logger.info(
            f"Admin {message.from_user.id} generated {len(insights)} insights for chat {chat_id}"
        )

    except Exception as e:
        logger.error(f"Failed to generate insights: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Помилка при генерації інсайтів: {str(e)}")
