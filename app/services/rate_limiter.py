from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Tuple

import aiosqlite

from app.services import telemetry


class RateLimiter:
    """Simple per-user rate limiter backed by SQLite."""

    WINDOW_SECONDS = 3600

    def __init__(self, db_path: str | Path, per_user_per_hour: int) -> None:
        self._db_path = Path(db_path)
        self._limit = per_user_per_hour
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Ensure database is reachable."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()

    async def check_and_increment(
        self, user_id: int, now: int | None = None
    ) -> Tuple[bool, int, int]:
        """
        Check if the user is within the allowed rate and increment on success.

        Args:
            user_id: Telegram user ID to rate limit.
            now: Optional override for current timestamp (seconds).

        Returns:
            Tuple of (allowed, remaining_quota, retry_after_seconds)
        """
        if self._limit <= 0:
            # Unlimited
            return True, -1, 0

        current_ts = int(now or time.time())
        window_start = current_ts - (current_ts % self.WINDOW_SECONDS)
        reset_at = window_start + self.WINDOW_SECONDS
        retry_after = max(reset_at - current_ts, 0)

        async with self._lock:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "DELETE FROM rate_limits WHERE window_start < ?",
                    (window_start - self.WINDOW_SECONDS,),
                )

                cursor = await db.execute(
                    """
                    SELECT request_count
                    FROM rate_limits
                    WHERE user_id = ? AND window_start = ?
                    """,
                    (user_id, window_start),
                )
                row = await cursor.fetchone()

                if row and row[0] >= self._limit:
                    telemetry.increment_counter(
                        "rate_limiter.blocked",
                        user_id=user_id,
                    )
                    return False, 0, retry_after

                if row:
                    await db.execute(
                        """
                        UPDATE rate_limits
                        SET request_count = request_count + 1, last_seen = ?
                        WHERE user_id = ? AND window_start = ?
                        """,
                        (current_ts, user_id, window_start),
                    )
                    new_count = row[0] + 1
                else:
                    await db.execute(
                        """
                        INSERT INTO rate_limits (user_id, window_start, request_count, last_seen)
                        VALUES (?, ?, 1, ?)
                        """,
                        (user_id, window_start, current_ts),
                    )
                    new_count = 1

                await db.commit()

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
        async with self._lock:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute("DELETE FROM rate_limits")
                await db.commit()
                deleted = cursor.rowcount or 0

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
        async with self._lock:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM rate_limits WHERE user_id = ?",
                    (user_id,),
                )
                await db.commit()
                deleted = cursor.rowcount or 0

        telemetry.increment_counter(
            "rate_limiter.reset_user",
            user_id=user_id,
            deleted=deleted,
        )
        return deleted
