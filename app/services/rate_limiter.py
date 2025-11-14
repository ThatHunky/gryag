from __future__ import annotations

import asyncio
import time
from typing import Tuple

from app.infrastructure.db_utils import get_db_connection
from app.services import telemetry
from app.services.redis_rate_limiter import RedisRateLimiter
from app.services.redis_types import RedisLike


class RateLimiter:
    """Per-user rate limiter with Redis optimization and PostgreSQL fallback."""

    WINDOW_SECONDS = 3600

    def __init__(
        self,
        database_url: str,
        per_user_per_hour: int,
        redis_client: RedisLike | None = None,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            database_url: PostgreSQL connection string
            per_user_per_hour: Maximum requests per hour per user
            redis_client: Optional Redis client for high-performance rate limiting
        """
        self._database_url = database_url
        self._limit = per_user_per_hour
        self._lock = asyncio.Lock()
        self._redis_limiter = (
            RedisRateLimiter(redis_client, per_user_per_hour, self.WINDOW_SECONDS)
            if redis_client is not None
            else None
        )

        # Track when we last sent throttle error message to each user
        # Format: {user_id: last_error_ts}
        self._last_error_message: dict[int, int] = {}
        self._error_message_cooldown = 3600  # 1 hour

    async def init(self) -> None:
        """Ensure database is reachable."""
        async with get_db_connection(self._database_url) as conn:
            await conn.execute("SELECT 1")

    def should_send_error_message(self, user_id: int) -> bool:
        """
        Check if we should send throttle error message to user.

        Only sends error messages once per hour to avoid spam.

        Args:
            user_id: User ID

        Returns:
            True if we should send error message, False to suppress
        """
        current_ts = int(time.time())
        last_error_ts = self._last_error_message.get(user_id, 0)

        # Check if cooldown has passed
        if current_ts - last_error_ts >= self._error_message_cooldown:
            # Update last error time
            self._last_error_message[user_id] = current_ts
            return True

        # Still in cooldown, suppress error message
        return False

    async def check_and_increment(
        self, user_id: int, now: int | None = None
    ) -> Tuple[bool, int, int]:
        """
        Check if the user is within the allowed rate and increment on success.

        Uses Redis for high-performance rate limiting with PostgreSQL fallback.

        Args:
            user_id: Telegram user ID to rate limit.
            now: Optional override for current timestamp (seconds).

        Returns:
            Tuple of (allowed, remaining_quota, retry_after_seconds)
        """
        if self._limit <= 0:
            # Unlimited
            return True, -1, 0

        # Try Redis first if available
        if self._redis_limiter is not None:
            result = await self._redis_limiter.check_and_increment(user_id, now)
            if result is not None:
                # Redis succeeded
                allowed, remaining, retry_after = result
                if allowed:
                    telemetry.increment_counter(
                        "rate_limiter.allowed",
                        user_id=user_id,
                        remaining=remaining,
                    )
                else:
                    telemetry.increment_counter(
                        "rate_limiter.blocked",
                        user_id=user_id,
                    )
                return result

        # Fallback to PostgreSQL
        current_ts = int(now or time.time())
        window_start = current_ts - (current_ts % self.WINDOW_SECONDS)
        reset_at = window_start + self.WINDOW_SECONDS
        retry_after = max(reset_at - current_ts, 0)

        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                query = "DELETE FROM rate_limits WHERE window_start < $1"
                params = (window_start - self.WINDOW_SECONDS,)
                await conn.execute(query, *params)

                query = """
                    SELECT request_count
                    FROM rate_limits
                    WHERE user_id = $1 AND window_start = $2
                    """
                params = (user_id, window_start)
                row = await conn.fetchrow(query, *params)

                if row and row['request_count'] >= self._limit:
                    telemetry.increment_counter(
                        "rate_limiter.blocked",
                        user_id=user_id,
                    )
                    return False, 0, retry_after

                if row:
                    query = """
                        UPDATE rate_limits
                        SET request_count = request_count + 1, last_seen = $1
                        WHERE user_id = $2 AND window_start = $3
                    """
                    params = (current_ts, user_id, window_start)
                    await conn.execute(query, *params)
                    new_count = row['request_count'] + 1
                else:
                    query = """
                        INSERT INTO rate_limits (user_id, window_start, request_count, last_seen)
                        VALUES ($1, $2, 1, $3)
                    """
                    params = (user_id, window_start, current_ts)
                    await conn.execute(query, *params)
                    new_count = 1

        remaining = max(self._limit - new_count, 0)
        telemetry.increment_counter(
            "rate_limiter.allowed",
            user_id=user_id,
            remaining=remaining,
        )
        return True, remaining, retry_after

    async def reset_chat(self, chat_id: int) -> int:
        """
        Reset rate limits for all users in a chat.

        Args:
            chat_id: Chat ID (not used in current implementation, but kept for API compatibility)

        Returns:
            Number of rate limit records deleted
        """
        deleted = 0

        # Reset in Redis if available
        if self._redis_limiter is not None:
            redis_deleted = await self._redis_limiter.reset_all()
            deleted += redis_deleted

        # Also reset in PostgreSQL
        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                result = await conn.execute("DELETE FROM rate_limits")
                # Extract row count from result string like "DELETE 5"
                pg_deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                deleted += pg_deleted

        telemetry.increment_counter(
            "rate_limiter.reset",
            chat_id=chat_id,
            deleted=deleted,
        )
        return deleted

    async def reset_user(self, user_id: int) -> int:
        """
        Reset rate limits for a specific user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of rate limit records deleted
        """
        deleted = 0

        # Reset in Redis if available
        if self._redis_limiter is not None:
            redis_deleted = await self._redis_limiter.reset_user(user_id)
            deleted += redis_deleted

        # Also reset in PostgreSQL
        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                query = "DELETE FROM rate_limits WHERE user_id = $1"
                params = (user_id,)
                result = await conn.execute(query, *params)
                pg_deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                deleted += pg_deleted

        telemetry.increment_counter(
            "rate_limiter.reset_user",
            user_id=user_id,
            deleted=deleted,
        )
        return deleted
