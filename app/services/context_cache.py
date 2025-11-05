"""
Redis-backed context caching for conversation history.

Provides high-performance caching for recent messages to reduce database load.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.redis_types import RedisLike

logger = logging.getLogger(__name__)


class ContextCache:
    """Redis-backed cache for conversation context."""

    def __init__(
        self,
        redis_client: RedisLike | None,
        ttl_seconds: int = 60,
    ) -> None:
        """
        Initialize context cache.

        Args:
            redis_client: Redis client instance (None if Redis unavailable)
            ttl_seconds: Time-to-live for cached entries (default: 60 seconds)
        """
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _get_key(self, chat_id: int, thread_id: int | None) -> str:
        """Generate Redis key for context cache."""
        if thread_id is None:
            return f"context:chat:{chat_id}:thread:null"
        return f"context:chat:{chat_id}:thread:{thread_id}"

    async def get(
        self,
        chat_id: int,
        thread_id: int | None,
        max_turns: int,
    ) -> list[dict[str, Any]] | None:
        """
        Get cached context from Redis.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (None for main thread)
            max_turns: Maximum number of turns requested

        Returns:
            Cached context list if found and valid, None otherwise
        """
        if self._redis is None:
            return None

        try:
            key = self._get_key(chat_id, thread_id)
            cached_data = await self._redis.get(key)

            if cached_data is None:
                return None

            # Parse cached data
            if isinstance(cached_data, bytes):
                cached_data = cached_data.decode("utf-8")

            data = json.loads(cached_data)

            # Validate cached data has enough turns
            if isinstance(data, list) and len(data) >= max_turns:
                return data

            return None

        except Exception as exc:
            logger.warning(f"Redis context cache get failed: {exc}")
            return None

    async def set(
        self,
        chat_id: int,
        thread_id: int | None,
        context: list[dict[str, Any]],
    ) -> None:
        """
        Cache context in Redis.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (None for main thread)
            context: Context list to cache
        """
        if self._redis is None:
            return

        try:
            key = self._get_key(chat_id, thread_id)
            data = json.dumps(context)
            await self._redis.set(key, data, ex=self._ttl)

        except Exception as exc:
            logger.warning(f"Redis context cache set failed: {exc}")

    async def invalidate(
        self,
        chat_id: int,
        thread_id: int | None = None,
    ) -> None:
        """
        Invalidate cached context for a chat/thread.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (None to invalidate all threads in chat)
        """
        if self._redis is None:
            return

        try:
            if thread_id is None:
                # Invalidate all threads for this chat
                pattern = f"context:chat:{chat_id}:thread:*"
                cursor = 0

                while True:
                    cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
            else:
                # Invalidate specific thread
                key = self._get_key(chat_id, thread_id)
                await self._redis.delete(key)

        except Exception as exc:
            logger.warning(f"Redis context cache invalidate failed: {exc}")

