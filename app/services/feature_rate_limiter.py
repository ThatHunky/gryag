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
from pathlib import Path
from typing import Tuple

import aiosqlite

from app.services import telemetry


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
        self, db_path: str | Path, admin_user_ids: list[int] | None = None
    ) -> None:
        """
        Initialize the feature rate limiter.

        Args:
            db_path: Path to SQLite database
            admin_user_ids: List of admin user IDs (bypass all limits)
        """
        self._db_path = Path(db_path)
        self._admin_ids = set(admin_user_ids or [])
        self._lock = asyncio.Lock()

        # Track when we last sent throttle error message to each user
        # Format: {user_id: {feature: last_error_ts}}
        self._last_error_message: dict[int, dict[str, int]] = {}
        self._error_message_cooldown = 600  # 10 minutes

    async def init(self) -> None:
        """Ensure database is reachable and create tables if needed."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()

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
    ) -> Tuple[bool, int, bool]:
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

        async with self._lock:
            async with aiosqlite.connect(self._db_path) as db:
                # Clean up old records
                await db.execute(
                    "DELETE FROM feature_rate_limits WHERE window_start < ?",
                    (window_start - window_seconds,),
                )

                # Check current count
                cursor = await db.execute(
                    """
                    SELECT request_count
                    FROM feature_rate_limits
                    WHERE user_id = ? AND feature_name = ? AND window_start = ?
                    """,
                    (user_id, feature, window_start),
                )
                row = await cursor.fetchone()

                if row and row[0] >= limit_per_hour:
                    # Check if we should show error message (once per 10 min)
                    should_show_error = self.should_send_error_message(user_id, feature)

                    telemetry.increment_counter(
                        "feature_rate_limiter.blocked",
                        user_id=user_id,
                        feature=feature,
                        error_shown=str(should_show_error),
                    )
                    # Record throttled request
                    await db.execute(
                        """
                        INSERT INTO user_request_history
                        (user_id, feature_name, requested_at, was_throttled, created_at)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (user_id, feature, current_ts, current_ts),
                    )
                    await db.commit()
                    return False, retry_after, should_show_error

                # Increment count
                if row:
                    await db.execute(
                        """
                        UPDATE feature_rate_limits
                        SET request_count = request_count + 1, last_request = ?
                        WHERE user_id = ? AND feature_name = ? AND window_start = ?
                        """,
                        (current_ts, user_id, feature, window_start),
                    )
                else:
                    await db.execute(
                        """
                        INSERT INTO feature_rate_limits
                        (user_id, feature_name, window_start, request_count, last_request)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (user_id, feature, window_start, current_ts),
                    )

                # Record successful request
                await db.execute(
                    """
                    INSERT INTO user_request_history
                    (user_id, feature_name, requested_at, was_throttled, created_at)
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    (user_id, feature, current_ts, current_ts),
                )

                await db.commit()

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
    ) -> Tuple[bool, int, bool]:
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
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    """
                    SELECT last_used, cooldown_seconds
                    FROM feature_cooldowns
                    WHERE user_id = ? AND feature_name = ?
                    """,
                    (user_id, feature),
                )
                row = await cursor.fetchone()

                if row:
                    last_used, stored_cooldown = row
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
                await db.execute(
                    """
                    INSERT OR REPLACE INTO feature_cooldowns
                    (user_id, feature_name, last_used, cooldown_seconds)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, feature, current_ts, cooldown_seconds),
                )
                await db.commit()

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

        async with aiosqlite.connect(self._db_path) as db:
            # Get current rate limits
            cursor = await db.execute(
                """
                SELECT feature_name, request_count, last_request
                FROM feature_rate_limits
                WHERE user_id = ? AND window_start = ?
                """,
                (user_id, window_start),
            )
            rate_limits = {
                row[0]: {"count": row[1], "last_request": row[2]}
                for row in await cursor.fetchall()
            }

            # Get active cooldowns
            cursor = await db.execute(
                """
                SELECT feature_name, last_used, cooldown_seconds
                FROM feature_cooldowns
                WHERE user_id = ?
                """,
                (user_id,),
            )
            cooldowns = {
                row[0]: {
                    "last_used": row[1],
                    "cooldown_seconds": row[2],
                    "remaining": max(row[2] - (current_ts - row[1]), 0),
                }
                for row in await cursor.fetchall()
            }

            # Get request history (last hour)
            cursor = await db.execute(
                """
                SELECT feature_name, COUNT(*) as total,
                       SUM(CASE WHEN was_throttled = 1 THEN 1 ELSE 0 END) as throttled
                FROM user_request_history
                WHERE user_id = ? AND requested_at > ?
                GROUP BY feature_name
                """,
                (user_id, current_ts - 3600),
            )
            history = {
                row[0]: {"total": row[1], "throttled": row[2]}
                for row in await cursor.fetchall()
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
        async with self._lock:
            async with aiosqlite.connect(self._db_path) as db:
                if feature:
                    cursor = await db.execute(
                        "DELETE FROM feature_rate_limits WHERE user_id = ? AND feature_name = ?",
                        (user_id, feature),
                    )
                else:
                    cursor = await db.execute(
                        "DELETE FROM feature_rate_limits WHERE user_id = ?",
                        (user_id,),
                    )

                await db.commit()
                deleted = cursor.rowcount or 0

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
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM feature_rate_limits WHERE window_start < ?",
                    (cutoff,),
                )
                await db.commit()
                deleted = cursor.rowcount or 0

        return deleted
