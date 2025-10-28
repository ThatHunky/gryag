"""Processing lock middleware to prevent multiple simultaneous message processing per user.

This middleware ensures that only one message per user is processed at a time.
When a user sends multiple messages while the bot is still processing the first one,
subsequent messages are dropped to prevent queue buildup and outdated responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings
from app.services.redis_types import RedisLike
from app.services import telemetry

LOGGER = logging.getLogger(__name__)


class ProcessingLockMiddleware(BaseMiddleware):
    """Middleware that provides processing lock functionality to handlers.

    This middleware DOES NOT check locks directly. Instead, it provides helper
    functions (_processing_lock_check and _processing_lock_set) that handlers
    can use AFTER determining if a message should be processed.

    This ensures the lock only applies to bot-addressed messages, not all user messages.

    Features:
    - Per-user locks: (chat_id, user_id) key ensures users don't block each other
    - Redis support: Uses Redis for distributed deployments, falls back to in-memory
    - Handler-controlled: Lock is checked/acquired by handler after bot-addressed check
    - Safety TTL: 5-minute timeout prevents permanent locks if something crashes
    - Telemetry: Handlers track dropped messages for monitoring
    """

    def __init__(
        self,
        settings: Settings,
        redis_client: RedisLike | None = None,
    ) -> None:
        """Initialize the processing lock middleware.

        Args:
            settings: Application settings
            redis_client: Optional Redis client for distributed locks
        """
        self._settings = settings
        self._redis = redis_client
        self._use_redis = (
            redis_client is not None
            and settings.use_redis
            and getattr(settings, "processing_lock_use_redis", True)
        )

        # In-memory fallback for single-instance deployments
        self._processing: dict[tuple[int, int], bool] = {}
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

        LOGGER.info(
            "ProcessingLockMiddleware initialized (redis=%s, enabled=%s)",
            self._use_redis,
            getattr(settings, "enable_processing_lock", True),
        )

    async def __call__(
        self,
        handler: Callable,
        event: Any,  # TelegramObject (Message, CallbackQuery, etc.)
        data: dict[str, Any],
    ) -> Any:
        """Process the middleware logic.

        Args:
            handler: Next handler in the chain
            event: Incoming message
            data: Handler data dict

        Returns:
            Handler result or None if message was dropped
        """
        # Only process Message events
        if not isinstance(event, Message):
            return await handler(event, data)

        # Skip if feature is disabled
        if not getattr(self._settings, "enable_processing_lock", True):
            return await handler(event, data)

        # Skip messages without from_user (shouldn't happen, but be defensive)
        if not event.from_user:
            return await handler(event, data)

        # Instead of checking the lock here, provide helper functions to the handler
        # The handler will check AFTER determining if message is addressed to bot
        data["_processing_lock_check"] = self._check_processing
        data["_processing_lock_set"] = self._set_processing

        # Pass through to handler (lock check happens in handler after bot-addressed check)
        return await handler(event, data)

    async def _check_processing(self, key: tuple[int, int]) -> bool:
        """Check if a user is currently being processed.

        Args:
            key: (chat_id, user_id) tuple

        Returns:
            True if processing, False otherwise
        """
        if self._use_redis and self._redis is not None:
            # Redis key: "processing:chat:{chat_id}:user:{user_id}"
            redis_key = f"processing:chat:{key[0]}:user:{key[1]}"
            try:
                result = await self._redis.exists(redis_key)  # type: ignore[attr-defined]
                return bool(result)
            except Exception as e:
                LOGGER.warning(
                    "Redis check failed for key %s, falling back to in-memory: %s",
                    redis_key,
                    e,
                )
                # Fallback to in-memory on Redis error
                return self._processing.get(key, False)
        else:
            # In-memory lookup
            return self._processing.get(key, False)

    async def _set_processing(self, key: tuple[int, int], value: bool) -> None:
        """Set the processing state for a user.

        Args:
            key: (chat_id, user_id) tuple
            value: True to mark as processing, False to release
        """
        if self._use_redis and self._redis is not None:
            # Redis key: "processing:chat:{chat_id}:user:{user_id}"
            redis_key = f"processing:chat:{key[0]}:user:{key[1]}"
            ttl_seconds = getattr(self._settings, "processing_lock_ttl_seconds", 300)

            try:
                if value:
                    # Set key with TTL (safety timeout)
                    await self._redis.setex(redis_key, ttl_seconds, "1")  # type: ignore[attr-defined]
                else:
                    # Delete key to release lock
                    await self._redis.delete(redis_key)  # type: ignore[attr-defined]
            except Exception as e:
                LOGGER.warning(
                    "Redis set failed for key %s, falling back to in-memory: %s",
                    redis_key,
                    e,
                )
                # Fallback to in-memory on Redis error
                self._processing[key] = value
        else:
            # In-memory update
            self._processing[key] = value

            # Clean up in-memory dict when releasing (prevent memory leak)
            if not value and key in self._processing:
                del self._processing[key]
