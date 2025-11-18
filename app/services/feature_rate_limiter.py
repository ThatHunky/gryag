"""
Feature-specific rate limiting and cooldown management.

This module provides comprehensive throttling for individual features:
- Per-feature hourly/daily limits (weather, currency, images, polls, memory)
- Per-request cooldowns (prevents rapid-fire requests)
- Admin bypass support
- Integration with adaptive throttling system

Usage:
    limiter = FeatureRateLimiter(db_path, admin_ids)
    await limiter.init()

    # Check rate limit
    allowed, retry_after = await limiter.check_rate_limit(
        user_id=12345,
        feature="weather",
        limit_per_hour=10
    )

    # Check cooldown
    allowed, retry_after = await limiter.check_cooldown(
        user_id=12345,
        feature="image_generation",
        cooldown_seconds=60
    )
"""

from __future__ import annotations

import asyncio
import time

from app.infrastructure.db_utils import get_db_connection
from app.services import telemetry
from app.services.redis_rate_limiter import RedisFeatureRateLimiter
from app.services.redis_types import RedisLike


class FeatureRateLimiter:
    """
    Feature-specific rate limiting with cooldown support.

    Provides two types of throttling:
    1. Rate limiting: Maximum requests per time window (hour/day)
    2. Cooldowns: Minimum time between consecutive requests
    """

    WINDOW_SECONDS = 3600  # 1 hour

    # Feature-specific limits (requests per hour)
    DEFAULT_LIMITS = {
        "weather": 10,
        "currency": 20,
        "web_search": 5,
        "polls": 5,  # per day (special case)
        "remember_memory": 30,
        "recall_memories": 30,
        "forget_memory": 10,
        "forget_all_memories": 5,
        "image_generation": 3,  # per day (special case)
        "edit_image": 3,  # per day (special case)
    }

    # Feature-specific cooldowns (seconds between requests)
    DEFAULT_COOLDOWNS = {
        "image_generation": 60,  # 1 minute between images
        "edit_image": 60,  # 1 minute between edits
        "weather": 30,  # 30 seconds between weather checks
        "currency": 15,  # 15 seconds between currency checks
        "web_search": 60,  # 1 minute between searches
        "polls": 300,  # 5 minutes between poll creations
    }

    def __init__(
        self,
        database_url: str,
        admin_user_ids: list[int] | None = None,
        redis_client: RedisLike | None = None,
    ) -> None:
        """
        Initialize the feature rate limiter.

        Args:
            database_url: PostgreSQL connection string
            admin_user_ids: List of admin user IDs (bypass all limits)
            redis_client: Optional Redis client for high-performance rate limiting
        """
        self._database_url = database_url
        self._admin_ids = set(admin_user_ids or [])
        self._lock = asyncio.Lock()
        self._redis_limiter = (
            RedisFeatureRateLimiter(redis_client, self.WINDOW_SECONDS)
            if redis_client is not None
            else None
        )

        # Track when we last sent throttle error message to each user
        # Format: {user_id: {feature: last_error_ts}}
        self._last_error_message: dict[int, dict[str, int]] = {}
        self._error_message_cooldown = 600  # 10 minutes

    async def init(self) -> None:
        """Ensure database is reachable."""
        async with get_db_connection(self._database_url) as conn:
            await conn.execute("SELECT 1")

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin (bypasses all limits)."""
        return user_id in self._admin_ids

    def should_send_error_message(self, user_id: int, feature: str) -> bool:
        """
        Check if we should send throttle error message to user.

        Only sends error messages once per 10 minutes to avoid spam.

        Args:
            user_id: User ID
            feature: Feature name (e.g., "weather", "bot_commands")

        Returns:
            True if we should send error message, False to suppress
        """
        current_ts = int(time.time())

        # Get last error time for this user+feature
        if user_id not in self._last_error_message:
            self._last_error_message[user_id] = {}

        last_error_ts = self._last_error_message[user_id].get(feature, 0)

        # Check if cooldown has passed
        if current_ts - last_error_ts >= self._error_message_cooldown:
            # Update last error time
            self._last_error_message[user_id][feature] = current_ts
            return True

        # Still in cooldown, suppress error message
        return False

    async def check_rate_limit(
        self,
        user_id: int,
        feature: str,
        limit_per_hour: int | None = None,
        window_seconds: int | None = None,
    ) -> tuple[bool, int, bool]:
        """
        Check if user is within rate limit for a feature.

        Args:
            user_id: Telegram user ID
            feature: Feature name (e.g., "weather", "currency")
            limit_per_hour: Max requests per hour (uses default if None)
            window_seconds: Time window in seconds (default: 3600)

        Returns:
            Tuple of (allowed, retry_after_seconds, should_show_error)
        """
        # Admins bypass all limits
        if self.is_admin(user_id):
            return True, 0, False

        # Get limit for this feature
        if limit_per_hour is None:
            limit_per_hour = self.DEFAULT_LIMITS.get(feature, 10)

        if limit_per_hour <= 0:
            return True, 0, False  # Unlimited

        window_seconds = window_seconds or self.WINDOW_SECONDS
        current_ts = int(time.time())
        window_start = current_ts - (current_ts % window_seconds)
        reset_at = window_start + window_seconds
        retry_after = max(reset_at - current_ts, 0)

        # Try Redis first if available
        if self._redis_limiter is not None:
            result = await self._redis_limiter.check_and_increment(
                user_id, feature, limit_per_hour, window_seconds, current_ts
            )
            if result is not None:
                # Redis succeeded
                allowed, redis_retry_after = result
                if not allowed:
                    # Check if we should show error message (once per 10 min)
                    should_show_error = self.should_send_error_message(user_id, feature)

                    telemetry.increment_counter(
                        "feature_rate_limiter.blocked",
                        user_id=user_id,
                        feature=feature,
                        error_shown=str(should_show_error),
                    )
                    # Still record throttled request in PostgreSQL for analytics
                    async with get_db_connection(self._database_url) as conn:
                        query = """
                            INSERT INTO user_request_history
                            (user_id, feature_name, requested_at, was_throttled, created_at)
                            VALUES ($1, $2, $3, 1, $4)
                        """
                        params = (user_id, feature, current_ts, current_ts)
                        await conn.execute(query, *params)
                    return False, redis_retry_after, should_show_error

                # Allowed - record successful request and return
                async with get_db_connection(self._database_url) as conn:
                    query = """
                        INSERT INTO user_request_history
                        (user_id, feature_name, requested_at, was_throttled, created_at)
                        VALUES ($1, $2, $3, 0, $4)
                    """
                    params = (user_id, feature, current_ts, current_ts)
                    await conn.execute(query, *params)

                telemetry.increment_counter(
                    "feature_rate_limiter.allowed",
                    user_id=user_id,
                    feature=feature,
                )
                return True, redis_retry_after, False

        # Fallback to PostgreSQL
        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                # Clean up old records
                query = "DELETE FROM feature_rate_limits WHERE window_start < $1"
                params = (window_start - window_seconds,)
                await conn.execute(query, *params)

                # Check current count
                query = """
                    SELECT request_count
                    FROM feature_rate_limits
                    WHERE user_id = $1 AND feature_name = $2 AND window_start = $3
                """
                params = (user_id, feature, window_start)
                row = await conn.fetchrow(query, *params)

                if row and row["request_count"] >= limit_per_hour:
                    # Check if we should show error message (once per 10 min)
                    should_show_error = self.should_send_error_message(user_id, feature)

                    telemetry.increment_counter(
                        "feature_rate_limiter.blocked",
                        user_id=user_id,
                        feature=feature,
                        error_shown=str(should_show_error),
                    )
                    # Record throttled request
                    query = """
                        INSERT INTO user_request_history
                        (user_id, feature_name, requested_at, was_throttled, created_at)
                        VALUES ($1, $2, $3, 1, $4)
                    """
                    params = (user_id, feature, current_ts, current_ts)
                    await conn.execute(query, *params)
                    return False, retry_after, should_show_error

                # Increment count
                if row:
                    query = """
                        UPDATE feature_rate_limits
                        SET request_count = request_count + 1, last_request = $1
                        WHERE user_id = $2 AND feature_name = $3 AND window_start = $4
                    """
                    params = (current_ts, user_id, feature, window_start)
                    await conn.execute(query, *params)
                else:
                    query = """
                        INSERT INTO feature_rate_limits
                        (user_id, feature_name, window_start, request_count, last_request)
                        VALUES ($1, $2, $3, 1, $4)
                    """
                    params = (user_id, feature, window_start, current_ts)
                    await conn.execute(query, *params)

                # Record successful request
                query = """
                    INSERT INTO user_request_history
                    (user_id, feature_name, requested_at, was_throttled, created_at)
                    VALUES ($1, $2, $3, 0, $4)
                """
                params = (user_id, feature, current_ts, current_ts)
                await conn.execute(query, *params)

        telemetry.increment_counter(
            "feature_rate_limiter.allowed",
            user_id=user_id,
            feature=feature,
        )
        return True, 0, False

    async def check_cooldown(
        self,
        user_id: int,
        feature: str,
        cooldown_seconds: int | None = None,
    ) -> tuple[bool, int, bool]:
        """
        Check if user has waited long enough since last request (cooldown).

        Args:
            user_id: Telegram user ID
            feature: Feature name
            cooldown_seconds: Minimum seconds between requests (uses default if None)

        Returns:
            Tuple of (allowed, retry_after_seconds, should_show_error)
        """
        # Admins bypass cooldowns
        if self.is_admin(user_id):
            return True, 0, False

        # Get cooldown for this feature
        if cooldown_seconds is None:
            cooldown_seconds = self.DEFAULT_COOLDOWNS.get(feature, 0)

        if cooldown_seconds <= 0:
            return True, 0, False  # No cooldown

        current_ts = int(time.time())

        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                query = """
                    SELECT last_used, cooldown_seconds
                    FROM feature_cooldowns
                    WHERE user_id = $1 AND feature_name = $2
                """
                params = (user_id, feature)
                row = await conn.fetchrow(query, *params)

                if row:
                    last_used = row["last_used"]
                    stored_cooldown = row["cooldown_seconds"]
                    time_since_last = current_ts - last_used
                    retry_after = max(stored_cooldown - time_since_last, 0)

                    if time_since_last < stored_cooldown:
                        # Check if we should show error message (once per 10 min)
                        should_show_error = self.should_send_error_message(
                            user_id, feature
                        )

                        telemetry.increment_counter(
                            "feature_rate_limiter.cooldown_blocked",
                            user_id=user_id,
                            feature=feature,
                            error_shown=str(should_show_error),
                        )
                        return False, retry_after, should_show_error

                # Update or insert cooldown record
                query = """
                    INSERT INTO feature_cooldowns
                    (user_id, feature_name, last_used, cooldown_seconds)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, feature_name) DO UPDATE SET
                        last_used = $3, cooldown_seconds = $4
                """
                params = (user_id, feature, current_ts, cooldown_seconds)
                await conn.execute(query, *params)

        telemetry.increment_counter(
            "feature_rate_limiter.cooldown_allowed",
            user_id=user_id,
            feature=feature,
        )
        return True, 0, False

    async def get_user_status(self, user_id: int) -> dict:
        """
        Get comprehensive throttle status for a user.

        Returns:
            Dict with current limits, cooldowns, and request history
        """
        current_ts = int(time.time())
        window_start = current_ts - (current_ts % self.WINDOW_SECONDS)

        async with get_db_connection(self._database_url) as conn:
            # Get current rate limits
            query = """
                SELECT feature_name, request_count, last_request
                FROM feature_rate_limits
                WHERE user_id = $1 AND window_start = $2
            """
            params = (user_id, window_start)
            rows = await conn.fetch(query, *params)
            rate_limits = {
                row["feature_name"]: {
                    "count": row["request_count"],
                    "last_request": row["last_request"],
                }
                for row in rows
            }

            # Get active cooldowns
            query = """
                SELECT feature_name, last_used, cooldown_seconds
                FROM feature_cooldowns
                WHERE user_id = $1
            """
            params = (user_id,)
            rows = await conn.fetch(query, *params)
            cooldowns = {
                row["feature_name"]: {
                    "last_used": row["last_used"],
                    "cooldown_seconds": row["cooldown_seconds"],
                    "remaining": max(
                        row["cooldown_seconds"] - (current_ts - row["last_used"]), 0
                    ),
                }
                for row in rows
            }

            # Get request history (last hour)
            query = """
                SELECT feature_name, COUNT(*) as total,
                       SUM(CASE WHEN was_throttled = 1 THEN 1 ELSE 0 END) as throttled
                FROM user_request_history
                WHERE user_id = $1 AND requested_at > $2
                GROUP BY feature_name
            """
            params = (user_id, current_ts - 3600)
            rows = await conn.fetch(query, *params)
            history = {
                row["feature_name"]: {
                    "total": row["total"],
                    "throttled": row["throttled"],
                }
                for row in rows
            }

        return {
            "user_id": user_id,
            "is_admin": self.is_admin(user_id),
            "rate_limits": rate_limits,
            "cooldowns": cooldowns,
            "history": history,
            "timestamp": current_ts,
        }

    async def reset_user_limits(self, user_id: int, feature: str | None = None) -> int:
        """
        Reset rate limits for a user (admin command).

        Args:
            user_id: User to reset
            feature: Specific feature to reset (or all if None)

        Returns:
            Number of records deleted
        """
        deleted = 0

        # Reset in Redis if available
        if self._redis_limiter is not None:
            redis_deleted = await self._redis_limiter.reset_user(user_id, feature)
            deleted += redis_deleted

        # Also reset in PostgreSQL
        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                if feature:
                    query = "DELETE FROM feature_rate_limits WHERE user_id = $1 AND feature_name = $2"
                    params = (user_id, feature)
                else:
                    query = "DELETE FROM feature_rate_limits WHERE user_id = $1"
                    params = (user_id,)
                result = await conn.execute(query, *params)
                pg_deleted = (
                    int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                )
                deleted += pg_deleted

        telemetry.increment_counter(
            "feature_rate_limiter.reset",
            user_id=user_id,
            feature=feature or "all",
            deleted=deleted,
        )
        return deleted

    async def cleanup_old_records(self) -> int:
        """
        Clean up old rate limit and cooldown records.

        Returns:
            Number of records deleted
        """
        current_ts = int(time.time())
        cutoff = current_ts - (2 * self.WINDOW_SECONDS)  # Keep last 2 hours

        async with self._lock:
            async with get_db_connection(self._database_url) as conn:
                query = "DELETE FROM feature_rate_limits WHERE window_start < $1"
                params = (cutoff,)
                result = await conn.execute(query, *params)
                deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0

        return deleted
