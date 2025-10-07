"""Chat filter middleware for whitelist/blacklist functionality."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings

logger = logging.getLogger(__name__)


class ChatFilterMiddleware(BaseMiddleware):
    """Filter messages based on chat whitelist/blacklist configuration.

    Modes:
    - 'global': Bot responds in all chats (default)
    - 'whitelist': Bot only responds in chats specified in ALLOWED_CHAT_IDS
    - 'blacklist': Bot responds everywhere except chats in BLOCKED_CHAT_IDS

    Private chats with admins always allowed regardless of mode.
    """

    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings
        logger.info(
            f"ChatFilterMiddleware initialized: mode={settings.bot_behavior_mode}, "
            f"allowed_chats={settings.allowed_chat_ids_list}, "
            f"blocked_chats={settings.blocked_chat_ids_list}"
        )

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """Filter messages based on chat configuration."""
        chat_id = event.chat.id
        user_id = event.from_user.id if event.from_user else None

        # Always allow private chats with admins
        if chat_id > 0 and user_id in self._settings.admin_user_ids_list:
            return await handler(event, data)

        mode = self._settings.bot_behavior_mode

        # Global mode: allow all chats
        if mode == "global":
            return await handler(event, data)

        # Whitelist mode: only allow specified chats
        if mode == "whitelist":
            if chat_id not in self._settings.allowed_chat_ids_list:
                logger.debug(f"Blocked message from chat {chat_id} (not in whitelist)")
                # Silently ignore - don't send error messages to avoid spam
                return None

        # Blacklist mode: block specified chats
        elif mode == "blacklist":
            if chat_id in self._settings.blocked_chat_ids_list:
                logger.debug(f"Blocked message from chat {chat_id} (in blacklist)")
                # Silently ignore
                return None

        # Pass through if not filtered
        return await handler(event, data)
