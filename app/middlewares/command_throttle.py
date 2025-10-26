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
from aiogram.types import Message, TelegramObject

from app.config import Settings
from app.services.feature_rate_limiter import FeatureRateLimiter

logger = logging.getLogger(__name__)


class CommandThrottleMiddleware(BaseMiddleware):
    """
    Throttle bot commands to prevent spam.

    Only throttles commands that are registered to this bot.
    Ignores commands meant for other bots or unknown commands.

    Limits: Configurable cooldown per command (default: 5 minutes)
    Admins: Bypass all limits
    Disabled: If ENABLE_COMMAND_THROTTLING=false
    """

    # All commands registered to gryag (without prefix)
    KNOWN_COMMANDS = {
        "gryag",  # USER_COMMANDS
        "gryagban",
        "gryagunban",
        "gryagreset",
        "gryagchatinfo",  # ADMIN_COMMANDS
        "gryagprofile",
        "gryagfacts",
        "gryagremovefact",
        "gryagforget",
        "gryagexport",
        "gryagusers",
        "gryagself",
        "gryaginsights",  # PROFILE_COMMANDS
        "gryagchatfacts",
        "gryagchatreset",  # CHAT_COMMANDS
        "gryagprompt",
        "gryagsetprompt",
        "gryagresetprompt",
        "gryagprompthistory",
        "gryagactivateprompt",  # PROMPT_COMMANDS
    }

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
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
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
        if not isinstance(event, Message):
            return await handler(event, data)

        message = event

        is_command = bool(message.text and message.text.startswith("/"))

        # Only process throttling logic for slash commands
        if not is_command:
            return await handler(message, data)

        # Skip if no user (shouldn't happen, but stay defensive)
        if not message.from_user:
            return await handler(message, data)

        # Ignore commands originating from any bot user (reply-to trickery included)
        if getattr(message.from_user, "is_bot", False):
            logger.debug(
                "Dropping command from bot user",
                extra={
                    "user_id": getattr(message.from_user, "id", None),
                    "username": getattr(message.from_user, "username", None),
                    "command": message.text.split()[0] if message.text else "",
                    "reply_to_bot": bool(
                        message.reply_to_message
                        and message.reply_to_message.from_user
                        and getattr(message.reply_to_message.from_user, "is_bot", False)
                    ),
                },
            )
            return None

        # Skip throttling logic entirely if feature disabled
        if not self.enabled:
            return await handler(message, data)

        # Extract command name (without @ mention if present)
        text = message.text or ""
        command_with_args = text.split()[0] if text else ""

        # Throttle all slash commands regardless of registration status.
        # This prevents spam from unknown or deprecated commands as well.
        # If a command explicitly targets another bot via @mention (handled below),
        # we'll skip throttling accordingly.

        # Check if command is addressed to a specific bot
        # Format: /command@bot_username
        bot_username = data.get("bot_username")
        if bot_username and "@" in command_with_args:
            # Extract the bot mention from the command
            command_parts = command_with_args.split("@", 1)
            if len(command_parts) == 2:
                mentioned_bot = command_parts[1]
                # If command is for a different bot, don't throttle
                if mentioned_bot.lower() != bot_username.lower():
                    logger.debug(
                        f"Command for different bot (@{mentioned_bot}), skipping throttle",
                        extra={
                            "user_id": message.from_user.id,
                            "command": command_with_args,
                            "mentioned_bot": mentioned_bot,
                            "our_bot": bot_username,
                        },
                    )
                    return await handler(message, data)

        user_id = message.from_user.id

        # Admins bypass throttling
        if user_id in self.settings.admin_user_ids_list:
            return await handler(message, data)

        # Check cooldown
        allowed, retry_after, should_show_error = (
            await self.rate_limiter.check_cooldown(
                user_id=user_id,
                feature="bot_commands",
                cooldown_seconds=self.cooldown_seconds,
            )
        )

        if not allowed:
            # Only send error message if we haven't sent one recently (10 min cooldown)
            if should_show_error:
                # User is throttled - show warning message
                minutes = retry_after // 60
                seconds = retry_after % 60

                cooldown_minutes = self.cooldown_seconds // 60
                throttle_msg = (
                    f"<b>Зачекай трохи!</b>\n\n"
                    f"Команди можна використовувати раз на <b>{cooldown_minutes} хвилин</b>. "
                    f"Наступна команда через: ⏱ <b>{minutes} хв {seconds} сек</b>"
                )

                await message.reply(throttle_msg, parse_mode="HTML")
                logger.info(
                    f"Command throttled for user {user_id}, retry after {retry_after}s (warning shown)",
                    extra={
                        "user_id": user_id,
                        "command": message.text.split()[0] if message.text else "",
                        "retry_after": retry_after,
                    },
                )
            else:
                # Silently block (warning already shown recently - user is spamming)
                logger.debug(
                    f"Command throttled for user {user_id}, retry after {retry_after}s (silently ignored)",
                    extra={
                        "user_id": user_id,
                        "command": message.text.split()[0] if message.text else "",
                        "retry_after": retry_after,
                    },
                )
            return None  # Stop processing

        # Allow command
        return await handler(message, data)
