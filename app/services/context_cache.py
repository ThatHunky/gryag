"""
Redis-backed context caching for conversation history.

Provides high-performance caching for recent messages to reduce database load.
Includes adaptive TTL, cache metrics, and LRU-style eviction.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from typing import Any

from app.services.redis_types import RedisLike

logger = logging.getLogger(__name__)


class ContextCache:
    """Redis-backed cache for conversation context with adaptive TTL and metrics."""

    def __init__(
        self,
        redis_client: RedisLike | None,
        ttl_seconds: int = 60,
        max_in_memory_size: int = 100,
    ) -> None:
        """
        Initialize context cache.

        Args:
            redis_client: Redis client instance (None if Redis unavailable)
            ttl_seconds: Base time-to-live for cached entries (default: 60 seconds)
            max_in_memory_size: Maximum number of entries in in-memory LRU cache (default: 100)
        """
        self._redis = redis_client
        self._base_ttl = ttl_seconds
        self._max_in_memory_size = max_in_memory_size

        # In-memory LRU cache for frequently accessed entries (acts as L1 cache)
        self._lru_cache: OrderedDict[
            tuple[int, int | None], tuple[list[dict[str, Any]], float]
        ] = OrderedDict()

        # Cache metrics
        self._hit_count = 0
        self._miss_count = 0
        self._last_access_times: dict[tuple[int, int | None], float] = {}

    def _get_key(self, chat_id: int, thread_id: int | None) -> str:
        """Generate Redis key for context cache."""
        if thread_id is None:
            return f"context:chat:{chat_id}:thread:null"
        return f"context:chat:{chat_id}:thread:{thread_id}"

    async def get(
        self,
        chat_id: int,
        thread_id: int | None,
        max_messages: int,
    ) -> list[dict[str, Any]] | None:
        """
        Get cached context from Redis with in-memory LRU fallback.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (None for main thread)
            max_messages: Maximum number of messages requested

        Returns:
            Cached context list if found and valid, None otherwise
        """
        cache_key = (chat_id, thread_id)
        now = time.time()

        # Check in-memory LRU cache first (L1)
        if cache_key in self._lru_cache:
            data, cache_time = self._lru_cache[cache_key]
            # Move to end (most recently used)
            self._lru_cache.move_to_end(cache_key)
            if isinstance(data, list) and len(data) >= max_messages:
                self._hit_count += 1
                self._last_access_times[cache_key] = now
                return data

        # Check Redis cache (L2)
        if self._redis is None:
            self._miss_count += 1
            return None

        try:
            key = self._get_key(chat_id, thread_id)
            cached_data = await self._redis.get(key)

            if cached_data is None:
                self._miss_count += 1
                return None

            # Parse cached data
            if isinstance(cached_data, bytes):
                cached_data = cached_data.decode("utf-8")

            data = json.loads(cached_data)

            # Validate cached data has enough messages
            if isinstance(data, list) and len(data) >= max_messages:
                # Store in LRU cache
                self._update_lru_cache(cache_key, data, now)
                self._hit_count += 1
                self._last_access_times[cache_key] = now
                return data

            self._miss_count += 1
            return None

        except Exception as exc:
            logger.warning(f"Redis context cache get failed: {exc}")
            self._miss_count += 1
            return None

    async def set(
        self,
        chat_id: int,
        thread_id: int | None,
        context: list[dict[str, Any]],
    ) -> None:
        """
        Cache context in Redis with adaptive TTL.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (None for main thread)
            context: Context list to cache
        """
        cache_key = (chat_id, thread_id)
        now = time.time()

        # Calculate adaptive TTL based on access frequency
        ttl = self._calculate_adaptive_ttl(cache_key)

        # Store in LRU cache
        self._update_lru_cache(cache_key, context, now)
        self._last_access_times[cache_key] = now

        # Store in Redis
        if self._redis is None:
            return

        try:
            key = self._get_key(chat_id, thread_id)
            data = json.dumps(context)
            await self._redis.set(key, data, ex=ttl)

        except Exception as exc:
            logger.warning(f"Redis context cache set failed: {exc}")

    def _update_lru_cache(
        self,
        cache_key: tuple[int, int | None],
        data: list[dict[str, Any]],
        now: float,
    ) -> None:
        """Update LRU cache with eviction if needed."""
        # Remove if exists to update position
        if cache_key in self._lru_cache:
            self._lru_cache.move_to_end(cache_key)
        else:
            # Evict oldest if at capacity
            if len(self._lru_cache) >= self._max_in_memory_size:
                self._lru_cache.popitem(last=False)  # Remove oldest

        # Add/update entry
        self._lru_cache[cache_key] = (data, now)

    def _calculate_adaptive_ttl(self, cache_key: tuple[int, int | None]) -> int:
        """
        Calculate adaptive TTL based on access frequency.

        Frequently accessed chats get longer TTL.
        """
        base_ttl = self._base_ttl

        # Check access frequency
        if cache_key in self._last_access_times:
            # Recently accessed - extend TTL
            return int(base_ttl * 1.5)  # 50% longer for active chats

        return base_ttl

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache performance statistics.

        Returns:
            Dictionary with hit/miss counts and hit rate
        """
        total = self._hit_count + self._miss_count
        hit_rate = (self._hit_count / total * 100) if total > 0 else 0.0

        return {
            "hits": self._hit_count,
            "misses": self._miss_count,
            "total": total,
            "hit_rate_percent": round(hit_rate, 2),
            "lru_cache_size": len(self._lru_cache),
            "max_lru_size": self._max_in_memory_size,
        }

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
                    cursor, keys = await self._redis.scan(
                        cursor, match=pattern, count=100
                    )
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
