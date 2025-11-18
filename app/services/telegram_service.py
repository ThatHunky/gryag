"""
This service handles interactions with the Telegram API, such as moderation actions.
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from app.config import Settings
from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)


class TelegramService:
    """A service for handling Telegram API interactions."""

    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

    async def kick_user(self, user_id: int, chat_id: int) -> str:
        """Kicks a user from the chat."""
        try:
            await self.bot.kick_chat_member(chat_id=chat_id, user_id=user_id)
            logger.info("Kicked user %d from chat %d", user_id, chat_id)
            return f"User {user_id} has been kicked from the chat."
        except Exception as e:
            logger.error("Failed to kick user %d from chat %d: %s", user_id, chat_id, e)
            return f"Failed to kick user {user_id} from the chat."

    async def mute_user(
        self, user_id: int, chat_id: int, duration_minutes: int | None = None
    ) -> str:
        """Temporarily mutes a user in the chat."""
        if duration_minutes is None:
            duration_minutes = self.settings.DEFAULT_MUTE_DURATION_MINUTES

        try:
            until_date = datetime.now() + timedelta(minutes=duration_minutes)
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
            logger.info(
                "Muted user %d in chat %d for %d minutes",
                user_id,
                chat_id,
                duration_minutes,
            )
            return f"User {user_id} has been muted for {duration_minutes} minutes."
        except Exception as e:
            logger.error("Failed to mute user %d in chat %d: %s", user_id, chat_id, e)
            return f"Failed to mute user {user_id}."

    async def unmute_user(self, user_id: int, chat_id: int) -> str:
        """Unmutes a user in the chat, restoring all permissions."""
        try:
            # Restore all chat permissions
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True,
                ),
            )
            logger.info("Unmuted user %d in chat %d", user_id, chat_id)
            return f"User {user_id} has been unmuted."
        except Exception as e:
            logger.error("Failed to unmute user %d in chat %d: %s", user_id, chat_id, e)
            return f"Failed to unmute user {user_id}."

    async def find_user(self, query: str, chat_id: int) -> dict:
        """
        Find a user in the database by username or display name.

        Args:
            query: Username, display name, or first name to search for
            chat_id: The chat ID to search within

        Returns:
            Dictionary with user_id, username, and display_name if found,
            or error message if not found or multiple matches
        """
        if not query or not isinstance(query, str):
            return {"error": "Invalid search query"}

        # Normalize query: remove @ prefix if present
        query = query.lstrip("@").strip().lower()

        if not query:
            return {"error": "Search query cannot be empty"}

        try:
            async with get_db_connection(self.settings.db_path) as db:
                # Search in user_profiles table by username or display_name
                # Select only 3 columns to normalize with message search
                cursor = await db.execute(
                    """
                    SELECT user_id, username, display_name
                    FROM user_profiles
                    WHERE chat_id = ? AND (
                        LOWER(username) = ? OR
                        LOWER(display_name) LIKE ? OR
                        LOWER(first_name) LIKE ? OR
                        LOWER(last_name) LIKE ?
                    )
                    LIMIT 10
                """,
                    (chat_id, query, f"%{query}%", f"%{query}%", f"%{query}%"),
                )

                results = await cursor.fetchall()

                if not results:
                    # Search in messages table as fallback for recent message senders
                    cursor = await db.execute(
                        """
                        SELECT DISTINCT external_user_id, sender_username, sender_name
                        FROM messages
                        WHERE chat_id = ? AND (
                            LOWER(sender_username) = ? OR
                            LOWER(sender_name) LIKE ?
                        )
                        ORDER BY ts DESC
                        LIMIT 10
                    """,
                        (chat_id, query, f"%{query}%"),
                    )

                    message_results = await cursor.fetchall()

                    if not message_results:
                        return {
                            "error": f"No user found matching '{query}' in this chat"
                        }

                    # Normalize message results: convert external_user_id (TEXT) to int
                    normalized = []
                    for r in message_results:
                        if r[0]:  # external_user_id is not null
                            try:
                                user_id = int(r[0])
                                normalized.append((user_id, r[1], r[2]))
                            except (ValueError, TypeError):
                                logger.warning(
                                    f"Could not convert external_user_id '{r[0]}' to int"
                                )

                    results = normalized

                if not results:
                    return {"error": f"No user found matching '{query}' in this chat"}

                # Deduplicate by user_id in case of multiple matches from same user
                seen = set()
                unique_results = []
                for user_id, username, display_name in results:
                    if user_id not in seen:
                        seen.add(user_id)
                        unique_results.append((user_id, username, display_name))

                results = unique_results

                if len(results) == 1:
                    user_id, username, display_name = results[0]

                    # Validate against system user
                    if user_id == 777000:
                        return {
                            "error": "Cannot moderate Telegram Service system account"
                        }

                    return {
                        "user_id": user_id,
                        "username": username or "N/A",
                        "display_name": display_name or "N/A",
                    }
                else:
                    # Multiple matches - return list for user to disambiguate
                    matches = [
                        {
                            "user_id": r[0],
                            "username": r[1] or "N/A",
                            "display_name": r[2] or "N/A",
                        }
                        for r in results
                    ]
                    return {
                        "error": f"Found {len(matches)} users matching '{query}'. Please be more specific.",
                        "matches": matches,
                    }
        except Exception as e:
            logger.error(
                f"Failed to find user '{query}' in chat {chat_id}: {e}", exc_info=True
            )
            return {"error": f"Failed to search for user: {str(e)}"}
