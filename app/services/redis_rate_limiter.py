"""
Redis-backed rate limiting utilities.

Provides high-performance rate limiting using Redis atomic operations
with automatic fallback to PostgreSQL if Redis is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Tuple

from app.services.redis_types import RedisLike

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """Redis-backed rate limiter using atomic INCR operations."""

    WINDOW_SECONDS = 3600

    def __init__(
        self,
        redis_client: RedisLike | None,
        per_user_per_hour: int,
        window_seconds: int = 3600,
    ) -> None:
        """
        Initialize Redis rate limiter.

        Args:
            redis_client: Redis client instance (None if Redis unavailable)
            per_user_per_hour: Maximum requests per hour per user
            window_seconds: Time window in seconds (default: 3600 = 1 hour)
        """
        self._redis = redis_client
        self._limit = per_user_per_hour
        self._window_seconds = window_seconds

    def _get_key(self, user_id: int, window_start: int) -> str:
        """Generate Redis key for rate limit tracking."""
        return f"rate_limit:user:{user_id}:{window_start}"

    async def check_and_increment(
        self, user_id: int, now: int | None = None
    ) -> Tuple[bool, int, int] | None:
        """
        Check if the user is within the allowed rate and increment on success.

        Args:
            user_id: Telegram user ID to rate limit.
            now: Optional override for current timestamp (seconds).

        Returns:
            Tuple of (allowed, remaining_quota, retry_after_seconds) if Redis available,
            None if Redis unavailable (should fallback to PostgreSQL).
        """
        if self._redis is None:
            return None  # Signal to use PostgreSQL fallback

        if self._limit <= 0:
            # Unlimited
            return True, -1, 0

        try:
            current_ts = int(now or time.time())
            window_start = current_ts - (current_ts % self._window_seconds)
            reset_at = window_start + self._window_seconds
            retry_after = max(reset_at - current_ts, 0)

            key = self._get_key(user_id, window_start)

            # Use Redis pipeline for atomic operation
            # INCR returns the new count after increment
            count = await self._redis.incr(key)

            # Set expiration on first increment (when count == 1)
            if count == 1:
                await self._redis.expire(key, self._window_seconds)

            # Check if limit exceeded
            if count > self._limit:
                return False, 0, retry_after

            remaining = max(self._limit - count, 0)
            return True, remaining, retry_after

        except Exception as exc:
            logger.warning(f"Redis rate limit check failed: {exc}, falling back to PostgreSQL")
            return None  # Signal to use PostgreSQL fallback

    async def reset_user(self, user_id: int) -> int:
        """
        Reset rate limits for a specific user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of keys deleted (0 if Redis unavailable)
        """
        if self._redis is None:
            return 0

        try:
            # Pattern match to find all keys for this user
            pattern = f"rate_limit:user:{user_id}:*"
            cursor = 0
            deleted = 0

            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            return deleted
        except Exception as exc:
            logger.warning(f"Redis reset_user failed: {exc}")
            return 0

    async def reset_all(self) -> int:
        """
        Reset all rate limits.

        Returns:
            Number of keys deleted (0 if Redis unavailable)
        """
        if self._redis is None:
            return 0

        try:
            pattern = "rate_limit:user:*"
            cursor = 0
            deleted = 0

            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            return deleted
        except Exception as exc:
            logger.warning(f"Redis reset_all failed: {exc}")
            return 0


class RedisFeatureRateLimiter:
    """Redis-backed feature-specific rate limiter."""

    WINDOW_SECONDS = 3600

    def __init__(
        self,
        redis_client: RedisLike | None,
        window_seconds: int = 3600,
    ) -> None:
        """
        Initialize Redis feature rate limiter.

        Args:
            redis_client: Redis client instance (None if Redis unavailable)
            window_seconds: Time window in seconds (default: 3600 = 1 hour)
        """
        self._redis = redis_client
        self._window_seconds = window_seconds

    def _get_key(self, user_id: int, feature: str, window_start: int) -> str:
        """Generate Redis key for feature rate limit tracking."""
        return f"feature_rate_limit:user:{user_id}:{feature}:{window_start}"

    async def check_and_increment(
        self,
        user_id: int,
        feature: str,
        limit_per_hour: int,
        window_seconds: int | None = None,
        now: int | None = None,
    ) -> Tuple[bool, int] | None:
        """
        Check if user is within rate limit for a feature and increment.

        Args:
            user_id: Telegram user ID
            feature: Feature name (e.g., "weather", "currency")
            limit_per_hour: Max requests per hour
            window_seconds: Time window in seconds (uses default if None)
            now: Optional override for current timestamp

        Returns:
            Tuple of (allowed, retry_after_seconds) if Redis available,
            None if Redis unavailable (should fallback to PostgreSQL).
        """
        if self._redis is None:
            return None  # Signal to use PostgreSQL fallback

        if limit_per_hour <= 0:
            return True, 0

        try:
            window_sec = window_seconds or self._window_seconds
            current_ts = int(now or time.time())
            window_start = current_ts - (current_ts % window_sec)
            reset_at = window_start + window_sec
            retry_after = max(reset_at - current_ts, 0)

            key = self._get_key(user_id, feature, window_start)

            # Atomic increment
            count = await self._redis.incr(key)

            # Set expiration on first increment
            if count == 1:
                await self._redis.expire(key, window_sec)

            # Check if limit exceeded
            if count > limit_per_hour:
                return False, retry_after

            return True, retry_after

        except Exception as exc:
            logger.warning(
                f"Redis feature rate limit check failed: {exc}, falling back to PostgreSQL"
            )
            return None  # Signal to use PostgreSQL fallback

    async def reset_user(self, user_id: int, feature: str | None = None) -> int:
        """
        Reset rate limits for a user (optionally for a specific feature).

        Args:
            user_id: Telegram user ID
            feature: Feature name (None for all features)

        Returns:
            Number of keys deleted
        """
        if self._redis is None:
            return 0

        try:
            if feature:
                pattern = f"feature_rate_limit:user:{user_id}:{feature}:*"
            else:
                pattern = f"feature_rate_limit:user:{user_id}:*"

            cursor = 0
            deleted = 0

            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            return deleted
        except Exception as exc:
            logger.warning(f"Redis feature reset_user failed: {exc}")
            return 0

