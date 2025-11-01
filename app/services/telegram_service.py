"""
This service handles interactions with the Telegram API, such as moderation actions.
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from app.config import Settings

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
