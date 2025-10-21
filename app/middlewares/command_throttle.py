"""
Command throttling middleware - prevents command spam.

Limits all bot commands to 1 per 5 minutes per user.
Admins bypass this restriction.

Usage:
    dispatcher.message.middleware(CommandThrottleMiddleware(settings, rate_limiter))
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings
from app.services.feature_rate_limiter import FeatureRateLimiter

logger = logging.getLogger(__name__)


class CommandThrottleMiddleware(BaseMiddleware):
    """
    Throttle bot commands to prevent spam.

    Limits: Configurable cooldown per command (default: 5 minutes)
    Admins: Bypass all limits
    Disabled: If ENABLE_COMMAND_THROTTLING=false
    """

    def __init__(self, settings: Settings, rate_limiter: FeatureRateLimiter) -> None:
        """
        Initialize command throttle middleware.

        Args:
            settings: Bot settings (for admin list and cooldown config)
            rate_limiter: Feature rate limiter instance
        """
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.cooldown_seconds = settings.command_cooldown_seconds
        self.enabled = settings.enable_command_throttling
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """
        Check if user can execute a command.

        Args:
            handler: Next handler in chain
            event: Incoming message
            data: Middleware data

        Returns:
            Handler result or None if throttled
        """
        # Skip if throttling is disabled
        if not self.enabled:
            return await handler(event, data)

        # Only throttle commands (messages starting with /)
        if not event.text or not event.text.startswith("/"):
            return await handler(event, data)

        # Skip if no user (shouldn't happen)
        if not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id

        # Admins bypass throttling
        if user_id in self.settings.admin_user_ids_list:
            return await handler(event, data)

        # Check cooldown
        allowed, retry_after, should_show_error = await self.rate_limiter.check_cooldown(
            user_id=user_id,
            feature="bot_commands",
            cooldown_seconds=self.cooldown_seconds,
        )

        if not allowed:
            # Only send error message if we haven't sent one recently (10 min cooldown)
            if should_show_error:
                # User is throttled
                minutes = retry_after // 60
                seconds = retry_after % 60

                if minutes > 0:
                    time_msg = f"{minutes} хв {seconds} сек"
                else:
                    time_msg = f"{seconds} сек"

                cooldown_minutes = self.cooldown_seconds // 60
                throttle_msg = (
                    f"⏱ <b>Зачекай трохи!</b>\n\n"
                    f"Команди можна використовувати <b>раз на {cooldown_minutes} хвилин</b>.\n"
                    f"Наступна команда через: <code>{time_msg}</code>"
                )

                await event.reply(throttle_msg, parse_mode="HTML")
                logger.info(
                    f"Command throttled for user {user_id}, retry after {retry_after}s (error shown)",
                    extra={
                        "user_id": user_id,
                        "command": event.text.split()[0] if event.text else "",
                        "retry_after": retry_after,
                    },
                )
            else:
                # Silently block (error already shown recently)
                logger.debug(
                    f"Command throttled for user {user_id}, retry after {retry_after}s (error suppressed)",
                    extra={
                        "user_id": user_id,
                        "command": event.text.split()[0] if event.text else "",
                        "retry_after": retry_after,
                    },
                )
            return None  # Stop processing

        # Allow command
        return await handler(event, data)
