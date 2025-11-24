"""Admin commands for user profile management."""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import Settings
from app.repositories.memory_repository import MemoryRepository
from app.services import telemetry
from app.services.bot_learning import BotLearningEngine
from app.services.bot_profile import BotProfileStore
from app.services.context_store import ContextStore
from app.services.user_profile import UserProfileStore
from app.utils.persona_helpers import get_response

router = Router()
logger = logging.getLogger(__name__)

# Default admin-only message - fallback when PersonaLoader is unavailable
ADMIN_ONLY = "Тільки адміни можуть це робити."


async def _check_banned(
    message: Message, store: ContextStore, settings: Settings
) -> bool:
    """
    Check if user is banned. Returns True if banned (handler should return early).
    Silently blocks banned users from commands - no response sent.
    """
    if not message.from_user:
        return True  # No user = block

    # Admins bypass ban checks
    if message.from_user.id in settings.admin_user_ids_list:
        return False

    chat_id = message.chat.id
    user_id = message.from_user.id

    if await store.is_banned(chat_id, user_id):
        logger.info(
            f"Blocked command from banned user: user_id={user_id}, chat_id={chat_id}, command={message.text}"
        )
        telemetry.increment_counter("profile_admin.banned_user_blocked")
        return True

    return False


def get_profile_commands(prefix: str = "gryag") -> list[BotCommand]:
    """Generate profile commands with dynamic prefix."""
    return [
        BotCommand(
            command=f"{prefix}profile",
            description="Показати профіль користувача (свій або у відповідь)",
        ),
        BotCommand(
            command=f"{prefix}facts",
            description="Список фактів (компактний формат, /facts 2 для сторінки 2)",
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
    message: Message,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
) -> None:
    """List known users for the current chat."""
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

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
    message: Message,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
) -> None:
    """
    Show user profile with facts grouped by type (compact format).

    Usage:
        /gryagprofile - Show your own profile
        /gryagprofile (reply) - Show profile of replied user
    """
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

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

    response += "\n📊 <b>Статистика:</b>\n"
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
    message: Message,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
    memory_repo: MemoryRepository | None = None,
) -> None:
    """
    List facts for a user (compact paginated format with inline buttons).

    Now shows BOTH:
    - Old user_facts (structured facts from profiling)
    - New user_memories (simple text memories from tool-based memory)

    Usage:
        /gryagfacts - Show your own facts (page 1, max 5 per page)
        /gryagfacts (reply) - Show facts of replied user
        /gryagfacts personal - Filter by fact type
        /gryagfacts --verbose - Show detailed format (old style)

    Pagination is handled via inline buttons (Previous/Next).
    """
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

    if not message.from_user:
        return

    # Parse arguments
    args = message.text.split()[1:] if message.text else []
    fact_type_filter = None
    verbose_mode = False
    page = 1

    for arg in args:
        if arg in ["personal", "preference", "skill", "trait", "opinion"]:
            fact_type_filter = arg
        elif arg in ["--verbose", "-v", "--detailed"]:
            verbose_mode = True
        elif arg.isdigit():
            page = max(1, int(arg))

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

    # Get facts from OLD system (user_facts table)
    old_facts_count = await profile_store.get_fact_count(user_id, chat_id)

    # Get memories from NEW system (user_memories table)
    memories = []
    memories_count = 0
    if memory_repo:
        try:
            # Get total count first (we can't easily get count without a separate query or fetching all)
            # For now, we'll fetch a reasonable limit to check count if needed, or just rely on pagination
            # But since we need total_count for pagination UI, we might need a count method in repo
            # For now, let's assume we can fetch all IDs to count, or just fetch all (since limit is small ~15)
            # The repo limits to 15 anyway, so fetching all is fine for count.
            all_memories = await memory_repo.get_memories_for_user(user_id, chat_id)
            memories_count = len(all_memories)
        except Exception as e:
            logger.error(f"Failed to get memories: {e}", exc_info=True)

    # Calculate total count (old facts + new memories)
    total_count = old_facts_count + memories_count

    if total_count == 0:
        filter_msg = f" типу '{fact_type_filter}'" if fact_type_filter else ""
        await message.reply(f"📭 Фактів{filter_msg} для {display_name} не знайдено.")
        return

    # Pagination settings
    FACTS_PER_PAGE = 5  # Reduced from 20 for better readability
    total_pages = (total_count + FACTS_PER_PAGE - 1) // FACTS_PER_PAGE
    page = min(page, total_pages)  # Clamp to valid range
    offset = (page - 1) * FACTS_PER_PAGE

    # Get facts for this page
    # We need to handle pagination across two sources: facts and memories.
    # This is tricky because we want them interleaved or at least presented consistently.
    # Strategy:
    # 1. Calculate how many items from "facts" and "memories" fit into the current page window.
    #    This is hard because we don't know the exact distribution without fetching all.
    # 2. SIMPLIFICATION: Since we have offset support now, we can fetch the relevant slice.
    #    But we have two distinct lists.
    #    Let's treat them as one concatenated list: [Facts... | Memories...]
    #    If offset < old_facts_count: we need some facts.
    #    If offset + limit > old_facts_count: we need some memories.

    facts_to_fetch = []
    memories_to_fetch = []

    # Calculate range for this page
    start_idx = offset
    end_idx = offset + FACTS_PER_PAGE

    # 1. Fetch Facts if the window overlaps with facts range [0, old_facts_count)
    if start_idx < old_facts_count:
        facts_limit = min(FACTS_PER_PAGE, old_facts_count - start_idx)
        facts_to_fetch = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            fact_type=fact_type_filter,
            limit=facts_limit,
            offset=start_idx
        )

    # 2. Fetch Memories if the window overlaps with memories range [old_facts_count, total_count)
    if end_idx > old_facts_count and memory_repo:
        # Calculate offset relative to memories list
        mem_offset = max(0, start_idx - old_facts_count)
        # Calculate limit for memories
        mem_limit = FACTS_PER_PAGE - len(facts_to_fetch)

        if mem_limit > 0:
            memories_to_fetch = await memory_repo.get_memories_for_user(
                user_id=user_id,
                chat_id=chat_id,
                limit=mem_limit,
                offset=mem_offset
            )

    all_facts = facts_to_fetch
    memories = memories_to_fetch

    # Combine old facts and new memories into a unified list
    # Format memories to look like facts for consistency
    all_items = []

    # Add old facts first
    for fact in all_facts:
        all_items.append(
            {
                "type": "fact",
                "id": fact.get("id", "?"),
                "fact_key": fact.get("fact_key", ""),
                "fact_value": fact.get("fact_value", ""),
                "confidence": fact.get("confidence", 0.0),
                "fact_type": fact.get("fact_type", "unknown"),
                "evidence_text": fact.get("evidence_text", ""),
            }
        )

    # Add new memories
    for memory in memories:
        all_items.append(
            {
                "type": "memory",
                "id": f"M{memory.id}",
                "text": memory.memory_text,
                "created_at": memory.created_at,
            }
        )

    # Paginate the combined list
    # items = all_items[offset : offset + FACTS_PER_PAGE] # No longer needed, we fetched exactly what we need
    items = all_items

    if not verbose_mode:
        # Compact format (DEFAULT, like ChatGPT Memories)
        # Header with pagination info
        # Escape display_name to prevent @mentions from creating clickable tags
        escaped_name = html.escape(display_name or "Користувач")
        header = f"📚 <b>Факти: {escaped_name}</b>"
        if fact_type_filter:
            header += f" ({fact_type_filter})"
        header += f"\n<i>Сторінка {page}/{total_pages} • Всього: {total_count}</i>\n\n"

        lines = [header]
        for item in items:
            if item["type"] == "fact":
                fact_id = item.get("id", "?")
                fact_key = item.get("fact_key", "")
                fact_value = item.get("fact_value", "")
                confidence = item.get("confidence", 0.0)

                # One-liner format: [ID] key: value (confidence%) - all in monospace to prevent mentions
                line = f"<code>[{fact_id}] {fact_key}: {fact_value} ({confidence:.0%})</code>"
                lines.append(line)
            elif item["type"] == "memory":
                # New memory format: [MID] 💭 memory text - in monospace to prevent mentions
                memory_id = item.get("id", "?")
                memory_text = item.get("text", "")
                line = f"<code>[{memory_id}] 💭 {memory_text}</code>"
                lines.append(line)

        response = "\n".join(lines)

        # Create inline keyboard for pagination
        keyboard = None
        if total_pages > 1:
            buttons = []
            if page > 1:
                # Previous button
                prev_callback = (
                    f"facts:{user_id}:{chat_id}:{page - 1}:{fact_type_filter or 'all'}"
                )
                buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня", callback_data=prev_callback
                    )
                )
            if page < total_pages:
                # Next button
                next_callback = (
                    f"facts:{user_id}:{chat_id}:{page + 1}:{fact_type_filter or 'all'}"
                )
                buttons.append(
                    InlineKeyboardButton(text="Наступна ▶️", callback_data=next_callback)
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    else:
        # Verbose format (OLD STYLE, only with --verbose flag)
        # Escape display_name to prevent @mentions from creating clickable tags
        escaped_name = html.escape(display_name or "Користувач")
        header = f"📚 <b>Факти: {escaped_name}</b> (детальний режим)"
        if fact_type_filter:
            header += f" ({_format_fact_type(fact_type_filter)})"
        header += f"\n<i>Сторінка {page}/{total_pages} • Всього: {total_count}</i>\n\n"

        lines = [header]
        for item in items:
            line = ""
            if item["type"] == "fact":
                fact_id = item.get("id", "?")
                fact_type = item.get("fact_type", "unknown")
                fact_key = item.get("fact_key", "")
                fact_value = item.get("fact_value", "")
                confidence = item.get("confidence", 0.0)
                evidence = item.get("evidence_text", "")

                line = f"{_format_fact_type(fact_type)} <code>[{fact_id}]</code> <b>{fact_key}</b>: {fact_value}\n"
                line += f"   ├ Впевненість: {confidence:.0%}\n"

                if evidence and len(evidence) > 50:
                    line += f"   └ «{evidence[:50]}...»\n"
                elif evidence:
                    line += f"   └ «{evidence}»\n"
            elif item["type"] == "memory":
                # Memory format in verbose mode
                memory_id = item.get("id", "?")
                memory_text = item.get("text", "")
                created_at = item.get("created_at", 0)

                # Format timestamp
                try:
                    from datetime import datetime

                    dt = datetime.fromtimestamp(created_at)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError, OSError) as e:
                    logger.warning(
                        f"Failed to format memory timestamp {created_at}: {e}"
                    )
                    time_str = "?"

                line = f"💭 <code>[{memory_id}]</code> {memory_text}\n"
                line += f"   └ Створено: {time_str}\n"

            if line:
                lines.append(line)

            lines.append(line)

        response = "\n".join(lines)

        # Create inline keyboard for pagination (verbose mode)
        keyboard = None
        if total_pages > 1:
            buttons = []
            if page > 1:
                prev_callback = f"facts:{user_id}:{chat_id}:{page - 1}:{fact_type_filter or 'all'}:v"
                buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня", callback_data=prev_callback
                    )
                )
            if page < total_pages:
                next_callback = f"facts:{user_id}:{chat_id}:{page + 1}:{fact_type_filter or 'all'}:v"
                buttons.append(
                    InlineKeyboardButton(text="Наступна ▶️", callback_data=next_callback)
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    # Telegram message limit is 4096 chars
    if len(response) > 4000:
        response = response[:4000] + "\n\n<i>... обрізано</i>"

    await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
    telemetry.increment_counter(
        "profile_admin.facts_viewed",
        filtered=str(bool(fact_type_filter)),
        verbose=str(verbose_mode),
        page=str(page),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("facts:"))
async def facts_pagination_callback(
    callback: CallbackQuery,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
) -> None:
    """
    Handle pagination button clicks for facts display.

    Callback data format: facts:user_id:chat_id:page:fact_type[:v]
    """
    if not callback.data or not callback.message:
        await callback.answer("❌ Помилка: неправильні дані")
        return

    # Parse callback data
    parts = callback.data.split(":")
    if len(parts) < 5:
        await callback.answer("❌ Помилка: неправильний формат даних")
        return

    target_user_id = int(parts[1])
    target_chat_id = int(parts[2])
    page = int(parts[3])
    fact_type_filter = parts[4] if parts[4] != "all" else None
    verbose_mode = len(parts) > 5 and parts[5] == "v"

    # Check permissions
    if not callback.from_user:
        await callback.answer("❌ Помилка: невідомий користувач")
        return

    if (
        not _is_admin(callback.from_user.id, settings)
        and target_user_id != callback.from_user.id
    ):
        await callback.answer("❌ Ти можеш дивитись тільки свої факти.")
        return

    # Get user display name
    profile = await profile_store.get_profile(target_user_id, target_chat_id)
    display_name = "Користувач"
    if profile:
        display_name = (
            profile.get("display_name")
            or profile.get("username")
            or f"User {target_user_id}"
        )

    # Get total count first for pagination
    total_count = await profile_store.get_fact_count(target_user_id, target_chat_id)

    if total_count == 0:
        await callback.answer("📭 Фактів не знайдено")
        return

    # Pagination settings
    FACTS_PER_PAGE = 5
    total_pages = (total_count + FACTS_PER_PAGE - 1) // FACTS_PER_PAGE
    page = min(page, total_pages)  # Clamp to valid range
    offset = (page - 1) * FACTS_PER_PAGE

    # Get facts for this page
    # Note: This callback currently only supports "facts" from profile_store, not memories
    # because the callback logic in get_user_facts_command didn't fully account for the unified view in the callback handler.
    # The original code only fetched from profile_store.
    # To fix this properly, we should replicate the unified logic or assume this is legacy.
    # Given the TODO was about offset support, let's update the profile_store call.

    # If we want to support memories here too, we'd need memory_repo access which isn't passed to this handler wrapper?
    # The handler signature has: profile_store: UserProfileStore, store: ContextStore.
    # It seems memory_repo is missing from the dependency injection for this callback in the original code?
    # Let's check the signature.
    # The original signature: async def facts_pagination_callback(..., profile_store: UserProfileStore, store: ContextStore) -> None:
    # It seems memory_repo is NOT injected.
    # For now, I will implement offset for profile_store facts.

    all_facts = await profile_store.get_facts(
        user_id=target_user_id,
        chat_id=target_chat_id,
        fact_type=fact_type_filter,
        limit=FACTS_PER_PAGE,
        offset=offset
    )
    facts = all_facts

    if not verbose_mode:
        # Compact format
        # Escape display_name to prevent @mentions from creating clickable tags
        escaped_name = html.escape(display_name)
        header = f"📚 <b>Факти: {escaped_name}</b>"
        if fact_type_filter:
            header += f" ({fact_type_filter})"
        header += f"\n<i>Сторінка {page}/{total_pages} • Всього: {total_count}</i>\n\n"

        lines = [header]
        for fact in facts:
            fact_id = fact.get("id", "?")
            fact_key = fact.get("fact_key", "")
            fact_value = fact.get("fact_value", "")
            confidence = fact.get("confidence", 0.0)

            # One-liner format: [ID] key: value (confidence%) - all in monospace to prevent mentions
            line = (
                f"<code>[{fact_id}] {fact_key}: {fact_value} ({confidence:.0%})</code>"
            )
            lines.append(line)

        response = "\n".join(lines)

        # Create inline keyboard
        keyboard = None
        if total_pages > 1:
            buttons = []
            if page > 1:
                prev_callback = f"facts:{target_user_id}:{target_chat_id}:{page - 1}:{fact_type_filter or 'all'}"
                buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня", callback_data=prev_callback
                    )
                )
            if page < total_pages:
                next_callback = f"facts:{target_user_id}:{target_chat_id}:{page + 1}:{fact_type_filter or 'all'}"
                buttons.append(
                    InlineKeyboardButton(text="Наступна ▶️", callback_data=next_callback)
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    else:
        # Verbose format
        # Escape display_name to prevent @mentions from creating clickable tags
        escaped_name = html.escape(display_name)
        header = f"📚 <b>Факти: {escaped_name}</b> (детальний режим)"
        if fact_type_filter:
            header += f" ({_format_fact_type(fact_type_filter)})"
        header += f"\n<i>Сторінка {page}/{total_pages} • Всього: {total_count}</i>\n\n"

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

        # Create inline keyboard
        keyboard = None
        if total_pages > 1:
            buttons = []
            if page > 1:
                prev_callback = f"facts:{target_user_id}:{target_chat_id}:{page - 1}:{fact_type_filter or 'all'}:v"
                buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня", callback_data=prev_callback
                    )
                )
            if page < total_pages:
                next_callback = f"facts:{target_user_id}:{target_chat_id}:{page + 1}:{fact_type_filter or 'all'}:v"
                buttons.append(
                    InlineKeyboardButton(text="Наступна ▶️", callback_data=next_callback)
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    # Telegram message limit is 4096 chars
    if len(response) > 4000:
        response = response[:4000] + "\n\n<i>... обрізано</i>"

    # Edit the message with new page
    try:
        # Type guard: check if message is accessible (not InaccessibleMessage)
        if isinstance(callback.message, InaccessibleMessage):
            await callback.answer("❌ Помилка: повідомлення недоступне")
            return

        await callback.message.edit_text(
            response, parse_mode="HTML", reply_markup=keyboard
        )
        await callback.answer(f"📄 Сторінка {page}/{total_pages}")
    except Exception as e:
        logger.error(f"Failed to edit facts message: {e}")
        await callback.answer("❌ Помилка при оновленні")

    telemetry.increment_counter(
        "profile_admin.facts_paginated",
        page=str(page),
    )


@router.message(Command(commands=["gryagremovefact", "removefact"]))
async def remove_fact_command(
    message: Message,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
    persona_loader: Any | None = None,
) -> None:
    """
    Remove a specific fact by ID (admin only).

    Usage:
        /gryagremovefact 123 - Remove fact with ID 123

    ⚠️ DEPRECATED: This command is deprecated. Use the `forget_memory` tool instead.
    The model can now handle memory deletion autonomously via function calling.
    This command will be removed in a future version.
    """
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

    if not message.from_user or not _is_admin(message.from_user.id, settings):
        # Removed hardcoded message - rely on persona instructions
        admin_msg = get_response("admin_only", persona_loader, ADMIN_ONLY)
        if admin_msg:
            await message.reply(admin_msg)
        return

    # Deprecation warning
    deprecation_msg = (
        "⚠️ <b>Ця команда застаріла</b>\n\n"
        "Команда <code>/gryagremovefact</code> застаріла. "
        "Використовуй інструмент <code>forget_memory</code> через модель бота. "
        "Просто попроси бота забути конкретну пам'ять, і він зробить це автоматично.\n\n"
        "Ця команда буде видалена в майбутній версії."
    )
    await message.reply(deprecation_msg, parse_mode="HTML")


@router.message(Command(commands=["gryagforget", "forget"]))
async def forget_user_command(
    message: Message,
    settings: Settings,
    profile_store: UserProfileStore,
    store: ContextStore,
    persona_loader: Any | None = None,
) -> None:
    """
    Forget all facts about a user (requires confirmation, admin only).

    Usage:
        /gryagforget (reply) - Forget all facts about replied user
        /gryagforget @username - Forget facts about @username
        /gryagforgetconfirm - Confirm deletion

    ⚠️ DEPRECATED: This command is deprecated. Use the `forget_all_memories` tool instead.
    The model can now handle memory deletion autonomously via function calling.
    This command will be removed in a future version.
    """
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

    if not message.from_user or not _is_admin(message.from_user.id, settings):
        # Removed hardcoded message - rely on persona instructions
        admin_msg = get_response("admin_only", persona_loader, ADMIN_ONLY)
        if admin_msg:
            await message.reply(admin_msg)
        return

    # Deprecation warning
    deprecation_msg = (
        "⚠️ <b>Ця команда застаріла</b>\n\n"
        "Команда <code>/gryagforget</code> застаріла. "
        "Використовуй інструмент <code>forget_all_memories</code> через модель бота. "
        "Просто попроси бота забути все про користувача, і він зробить це автоматично.\n\n"
        "Ця команда буде видалена в майбутній версії."
    )
    await message.reply(deprecation_msg, parse_mode="HTML")


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
    store: ContextStore,
) -> None:
    """View bot's self-learning profile (admin only)."""
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

    if not message.from_user:
        return

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
    response += "📊 <b>Effectiveness (last 7 days)</b>\n"
    response += f"• Overall score: {summary['effectiveness_score']:.1%}\n"
    response += f"• Recent score: {summary['recent_effectiveness']:.1%}\n"
    response += f"• Total interactions: {summary['total_interactions']}\n"
    response += f"• Positive: {summary['positive_interactions']} ({summary['positive_interactions']/max(summary['total_interactions'],1):.1%})\n"
    response += f"• Negative: {summary['negative_interactions']} ({summary['negative_interactions']/max(summary['total_interactions'],1):.1%})\n\n"

    response += "⚡ <b>Performance</b>\n"
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
    store: ContextStore,
) -> None:
    """Generate Gemini-powered insights about bot's learning (admin only)."""
    # Block banned users silently
    if await _check_banned(message, store, settings):
        return

    if not message.from_user:
        return

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
