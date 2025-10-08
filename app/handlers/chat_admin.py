"""Admin commands for chat profile management."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from app.config import Settings
from app.repositories.chat_profile import ChatProfileRepository

router = Router()
logger = logging.getLogger(__name__)


def get_chat_commands(prefix: str = "gryag") -> list[BotCommand]:
    """Generate chat profile commands with dynamic prefix."""
    return [
        BotCommand(
            command=f"{prefix}chatfacts",
            description="Показати факти про цей чат/групу",
        ),
        BotCommand(
            command=f"{prefix}chatreset",
            description="🔒 Видалити всі факти про чат (тільки адміни, потребує підтвердження)",
        ),
    ]


# Keep for backwards compatibility (used in main.py)
CHAT_COMMANDS = get_chat_commands()


# Store confirmation requests for /gryagchatreset
_reset_confirmations: dict[str, tuple[int, float]] = (
    {}
)  # key: f"{chat_id}:{admin_id}", value: (chat_id, timestamp)


def _is_admin(user_id: int, settings: Settings) -> bool:
    """Check if user is an admin."""
    return user_id in settings.admin_user_ids_list


def _format_category(category: str) -> str:
    """Format fact category with emoji."""
    emojis = {
        "language": "🗣️",
        "culture": "🎭",
        "norms": "📜",
        "preferences": "⭐",
        "traditions": "🎉",
        "rules": "⚖️",
        "style": "🎨",
        "topics": "💬",
    }
    return f"{emojis.get(category, '📌')} {category.title()}"


@router.message(Command("gryagchatfacts", "chatfacts"))
async def chatfacts_command(
    message: Message,
    settings: Settings,
    chat_profile_store: ChatProfileRepository | None = None,
) -> None:
    """
    Show chat-level facts about the current group.

    Usage:
        /gryagchatfacts - Show top chat facts grouped by category
    """
    if not message.from_user:
        return

    if not chat_profile_store:
        await message.reply("❌ Chat memory is not enabled.")
        return

    chat_id = message.chat.id

    try:
        # Get chat profile
        profile = await chat_profile_store.get_or_create_profile(
            chat_id=chat_id,
            chat_type=message.chat.type,
            chat_title=message.chat.title,
        )

        # Get all active facts
        all_facts = await chat_profile_store.get_all_facts(
            chat_id=chat_id,
            include_inactive=False,
        )

        if not all_facts:
            await message.reply(
                "📭 Ще немає фактів про цей чат.\n\n"
                "Я почну запам'ятовувати групові звички, традиції та норми "
                "після кількох розмов."
            )
            return

        # Group facts by category
        facts_by_category: dict[str, list[Any]] = {}
        for fact in all_facts:
            category = fact.fact_category
            if category not in facts_by_category:
                facts_by_category[category] = []
            facts_by_category[category].append(fact)

        # Sort categories by fact count
        sorted_categories = sorted(
            facts_by_category.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )

        # Build response
        lines = [
            f"📊 <b>Факти про чат: {message.chat.title or 'цей чат'}</b>\n",
            f"Всього фактів: {len(all_facts)}\n",
        ]

        for category, facts in sorted_categories[:6]:  # Show top 6 categories
            lines.append(f"\n{_format_category(category)}")

            # Sort facts by confidence and show top 5 per category
            sorted_facts = sorted(
                facts,
                key=lambda f: f.confidence,
                reverse=True,
            )

            for fact in sorted_facts[:5]:
                confidence_bar = "●" * int(fact.confidence * 5)
                confidence_pct = int(fact.confidence * 100)

                # Format fact value
                if fact.fact_description:
                    fact_text = fact.fact_description
                else:
                    fact_text = f"{fact.fact_key}: {fact.fact_value}"

                lines.append(
                    f"  • {fact_text}\n"
                    f"    {confidence_bar} {confidence_pct}% "
                    f"(підтверджень: {fact.evidence_count})"
                )

        # Add summary if available
        if profile.culture_summary:
            lines.append(f"\n💡 <b>Культура чату:</b>\n{profile.culture_summary}")

        # Add footer
        lines.append(
            f"\n<i>Останнє оновлення: {_format_timestamp(profile.updated_at)}</i>"
        )

        response = "\n".join(lines)

        # Truncate if too long
        if len(response) > 4000:
            response = response[:3900] + "\n\n<i>... (обрізано)</i>"

        await message.reply(response)

        logger.info(
            f"Displayed {len(all_facts)} chat facts",
            extra={
                "chat_id": chat_id,
                "user_id": message.from_user.id,
                "categories": len(facts_by_category),
            },
        )

    except Exception as e:
        logger.error(f"Failed to retrieve chat facts: {e}", exc_info=True)
        await message.reply("❌ Помилка при отриманні фактів про чат.")


@router.message(Command("gryagchatreset", "chatreset"))
async def chatreset_command(
    message: Message,
    settings: Settings,
    chat_profile_store: ChatProfileRepository | None = None,
) -> None:
    """
    Delete all chat-level facts (admin only, requires confirmation).

    Usage:
        /gryagchatreset - Request confirmation
        /gryagchatreset confirm - Execute deletion
    """
    if not message.from_user:
        return

    if not chat_profile_store:
        await message.reply("❌ Chat memory is not enabled.")
        return

    # Check admin permissions
    if not _is_admin(message.from_user.id, settings):
        await message.reply("🔒 Ця команда доступна тільки адмінам.")
        return

    chat_id = message.chat.id
    admin_id = message.from_user.id
    confirm_key = f"{chat_id}:{admin_id}"

    # Check if this is a confirmation
    text = message.text or ""
    is_confirm = "confirm" in text.lower()

    if not is_confirm:
        # Request confirmation
        import time

        _reset_confirmations[confirm_key] = (chat_id, time.time())

        # Get current fact count
        facts = await chat_profile_store.get_all_facts(
            chat_id=chat_id,
            include_inactive=False,
        )

        await message.reply(
            f"⚠️ <b>Підтвердження видалення</b>\n\n"
            f"Це видалить <b>{len(facts)} фактів</b> про цей чат.\n\n"
            f"Для підтвердження відправте:\n"
            f"<code>/gryagchatreset confirm</code>\n\n"
            f"<i>Запит діє 60 секунд</i>"
        )
        return

    # Verify confirmation
    if confirm_key not in _reset_confirmations:
        await message.reply(
            "❌ Немає активного запиту на видалення.\n"
            "Спершу відправте /gryagchatreset"
        )
        return

    stored_chat_id, timestamp = _reset_confirmations[confirm_key]
    import time

    if time.time() - timestamp > 60:
        del _reset_confirmations[confirm_key]
        await message.reply("❌ Час на підтвердження минув (60 секунд).")
        return

    if stored_chat_id != chat_id:
        await message.reply("❌ Неправильний чат для підтвердження.")
        return

    # Execute deletion
    try:
        # Delete all chat facts
        deleted_count = await chat_profile_store.delete_all_facts(chat_id=chat_id)

        # Clear confirmation
        del _reset_confirmations[confirm_key]

        await message.reply(
            f"✅ Видалено {deleted_count} фактів про чат.\n\n"
            f"Пам'ять чату очищена. Я почну запам'ятовувати заново."
        )

        logger.info(
            f"Reset chat facts: {deleted_count} deleted",
            extra={
                "chat_id": chat_id,
                "admin_id": admin_id,
            },
        )

    except Exception as e:
        logger.error(f"Failed to reset chat facts: {e}", exc_info=True)
        await message.reply("❌ Помилка при видаленні фактів.")


def _format_timestamp(ts: int | None) -> str:
    """Format Unix timestamp to readable string."""
    if not ts:
        return "невідомо"

    from datetime import datetime

    try:
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "невідомо"
