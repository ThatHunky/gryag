"""
Adaptive throttling based on user behavior and reputation.

This module analyzes user request patterns and automatically adjusts
rate limits based on behavior:
- Good users (natural request spacing) get +50% limits
- Spammy users (burst requests, rapid-fire) get -30% limits
- Reputation updates daily based on last 7 days of activity

Usage:
    adaptive = AdaptiveThrottleManager(db_path)
    await adaptive.init()

    # Get multiplier for user (0.7-1.5 range)
    multiplier = await adaptive.get_throttle_multiplier(user_id=12345)

    # adjusted_limit = base_limit * multiplier
    # Example: 10 requests/hour * 1.5 = 15 requests/hour (good user)
    #          10 requests/hour * 0.7 = 7 requests/hour (spammy user)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.infrastructure.db_utils import get_db_connection
from app.services import telemetry


class AdaptiveThrottleManager:
    """
    Manages adaptive throttling based on user behavior patterns.

    Analyzes request history to detect:
    - Burst requests (many requests in short time)
    - Natural spacing (requests spread out evenly)
    - Throttle abuse (hitting limits repeatedly)
    - Time of day patterns

    Reputation scoring (0.0 = worst, 1.0 = best):
    - 0.9-1.0: Excellent (natural usage, no bursts)
    - 0.7-0.9: Good (occasional bursts, mostly natural)
    - 0.5-0.7: Moderate (some spam behavior)
    - 0.3-0.5: Poor (frequent bursts, hitting limits)
    - 0.0-0.3: Bad (constant spam, abuse)
    """

    # Reputation thresholds for multiplier calculation
    EXCELLENT_THRESHOLD = 0.9  # +50% limits
    GOOD_THRESHOLD = 0.7  # +25% limits
    MODERATE_THRESHOLD = 0.5  # No change
    POOR_THRESHOLD = 0.3  # -15% limits
    # Below 0.3: -30% limits

    # Analysis parameters
    BURST_WINDOW_SECONDS = 60  # Requests within 60s considered a burst
    BURST_THRESHOLD = 5  # 5+ requests in 60s = burst
    ANALYSIS_DAYS = 7  # Analyze last 7 days
    UPDATE_INTERVAL_HOURS = 24  # Update reputation daily

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize the adaptive throttle manager.

        Args:
            db_path: Path to SQLite database
        """
        self._db_path = Path(db_path)
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Ensure database is reachable."""
        async with get_db_connection(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()

    async def get_throttle_multiplier(self, user_id: int) -> float:
        """
        Get current throttle multiplier for a user.

        Returns:
            Float between 0.7 (spammy) and 1.5 (excellent)
            1.0 = default (no adjustment)
        """
        current_ts = int(time.time())

        async with get_db_connection(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT throttle_multiplier, last_reputation_update, spam_score
                FROM user_throttle_metrics
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()

            if not row:
                # New user, default reputation
                return 1.0

            multiplier, last_update, spam_score = row

            # Check if reputation needs update
            update_interval = self.UPDATE_INTERVAL_HOURS * 3600
            if current_ts - last_update > update_interval:
                # Update reputation in background (don't await)
                asyncio.create_task(self.update_user_reputation(user_id))

            return multiplier

    async def update_user_reputation(self, user_id: int) -> dict:
        """
        Analyze user behavior and update reputation score.

        Returns:
            Dict with updated metrics
        """
        current_ts = int(time.time())
        analysis_start = current_ts - (self.ANALYSIS_DAYS * 86400)

        async with self._lock:
            async with get_db_connection(self._db_path) as db:
                # Get request history for analysis
                cursor = await db.execute(
                    """
                    SELECT requested_at, was_throttled
                    FROM user_request_history
                    WHERE user_id = ? AND requested_at > ?
                    ORDER BY requested_at ASC
                    """,
                    (user_id, analysis_start),
                )
                history = await cursor.fetchall()

                if not history:
                    # No data, keep default
                    return {
                        "user_id": user_id,
                        "multiplier": 1.0,
                        "spam_score": 0.0,
                        "reputation": "unknown",
                    }

                # Analyze behavior patterns
                total_requests = len(history)
                throttled_count = sum(1 for _, throttled in history if throttled)
                timestamps = [ts for ts, _ in history]

                # Calculate metrics
                burst_count = self._count_bursts(timestamps)
                avg_spacing = self._calculate_avg_spacing(timestamps)
                throttle_rate = (
                    throttled_count / total_requests if total_requests > 0 else 0
                )

                # Calculate spam score (0.0 = good, 1.0 = bad)
                # Factors:
                # 1. Burst frequency (0-0.4)
                # 2. Throttle rate (0-0.4)
                # 3. Request spacing (0-0.2)

                burst_score = min(burst_count / 10.0, 0.4)  # 10+ bursts = max penalty
                throttle_score = min(throttle_rate, 0.4)  # 100% throttled = max penalty

                # Ideal spacing: 60-120 seconds between requests
                # Too fast (<30s) or too slow (>300s) both penalize slightly
                if avg_spacing < 30:
                    spacing_score = 0.2
                elif avg_spacing > 300:
                    spacing_score = 0.1
                elif 60 <= avg_spacing <= 120:
                    spacing_score = 0.0  # Ideal
                else:
                    spacing_score = 0.05

                spam_score = min(burst_score + throttle_score + spacing_score, 1.0)
                reputation_score = 1.0 - spam_score

                # Calculate throttle multiplier based on reputation
                multiplier = self._calculate_multiplier(reputation_score)

                # Store updated metrics
                await db.execute(
                    """
                    INSERT OR REPLACE INTO user_throttle_metrics
                    (user_id, throttle_multiplier, spam_score, total_requests,
                     throttled_requests, burst_requests, avg_request_spacing_seconds,
                     last_reputation_update, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        multiplier,
                        spam_score,
                        total_requests,
                        throttled_count,
                        burst_count,
                        avg_spacing,
                        current_ts,
                        current_ts,
                        current_ts,
                    ),
                )
                await db.commit()

        reputation_label = self._get_reputation_label(reputation_score)

        telemetry.increment_counter(
            "adaptive_throttle.reputation_updated",
            user_id=user_id,
            reputation=reputation_label,
            multiplier=f"{multiplier:.2f}",
        )

        return {
            "user_id": user_id,
            "multiplier": multiplier,
            "spam_score": spam_score,
            "reputation": reputation_label,
            "total_requests": total_requests,
            "throttled_requests": throttled_count,
            "burst_count": burst_count,
            "avg_spacing": avg_spacing,
        }

    def _count_bursts(self, timestamps: list[int]) -> int:
        """Count number of burst patterns (5+ requests within 60 seconds)."""
        if len(timestamps) < self.BURST_THRESHOLD:
            return 0

        bursts = 0
        for i in range(len(timestamps)):
            window_end = timestamps[i] + self.BURST_WINDOW_SECONDS
            # Count requests in this 60s window
            count = sum(1 for ts in timestamps[i:] if ts <= window_end)
            if count >= self.BURST_THRESHOLD:
                bursts += 1

        return bursts

    def _calculate_avg_spacing(self, timestamps: list[int]) -> float:
        """Calculate average time between consecutive requests."""
        if len(timestamps) < 2:
            return 0.0

        spacings = [
            timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)
        ]
        return sum(spacings) / len(spacings)

    def _calculate_multiplier(self, reputation_score: float) -> float:
        """
        Calculate throttle multiplier from reputation score.

        Excellent (0.9-1.0): 1.5x limits (+50%)
        Good (0.7-0.9): 1.25x limits (+25%)
        Moderate (0.5-0.7): 1.0x limits (no change)
        Poor (0.3-0.5): 0.85x limits (-15%)
        Bad (0.0-0.3): 0.7x limits (-30%)
        """
        if reputation_score >= self.EXCELLENT_THRESHOLD:
            return 1.5
        elif reputation_score >= self.GOOD_THRESHOLD:
            return 1.25
        elif reputation_score >= self.MODERATE_THRESHOLD:
            return 1.0
        elif reputation_score >= self.POOR_THRESHOLD:
            return 0.85
        else:
            return 0.7

    def _get_reputation_label(self, reputation_score: float) -> str:
        """Get human-readable reputation label."""
        if reputation_score >= self.EXCELLENT_THRESHOLD:
            return "excellent"
        elif reputation_score >= self.GOOD_THRESHOLD:
            return "good"
        elif reputation_score >= self.MODERATE_THRESHOLD:
            return "moderate"
        elif reputation_score >= self.POOR_THRESHOLD:
            return "poor"
        else:
            return "bad"

    async def get_reputation_summary(self, user_id: int) -> dict:
        """
        Get detailed reputation summary for a user.

        Returns:
            Dict with all reputation metrics
        """
        async with get_db_connection(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT throttle_multiplier, spam_score, total_requests,
                       throttled_requests, burst_requests, avg_request_spacing_seconds,
                       last_reputation_update
                FROM user_throttle_metrics
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()

            if not row:
                return {
                    "user_id": user_id,
                    "reputation": "unknown",
                    "multiplier": 1.0,
                    "message": "No request history found",
                }

            (
                multiplier,
                spam_score,
                total_requests,
                throttled_requests,
                burst_requests,
                avg_spacing,
                last_update,
            ) = row

            reputation_score = 1.0 - spam_score
            reputation_label = self._get_reputation_label(reputation_score)

            return {
                "user_id": user_id,
                "reputation": reputation_label,
                "reputation_score": reputation_score,
                "spam_score": spam_score,
                "multiplier": multiplier,
                "total_requests": total_requests,
                "throttled_requests": throttled_requests,
                "throttle_rate": (
                    throttled_requests / total_requests if total_requests > 0 else 0
                ),
                "burst_count": burst_requests,
                "avg_spacing_seconds": avg_spacing,
                "last_update": last_update,
                "update_age_hours": (int(time.time()) - last_update) / 3600,
            }

    async def reset_user_reputation(self, user_id: int) -> None:
        """Reset user reputation to default (admin command)."""
        current_ts = int(time.time())

        async with self._lock:
            async with get_db_connection(self._db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO user_throttle_metrics
                    (user_id, throttle_multiplier, spam_score, total_requests,
                     throttled_requests, burst_requests, avg_request_spacing_seconds,
                     last_reputation_update, created_at, updated_at)
                    VALUES (?, 1.0, 0.0, 0, 0, 0, 0.0, ?, ?, ?)
                    """,
                    (user_id, current_ts, current_ts, current_ts),
                )
                await db.commit()

        telemetry.increment_counter(
            "adaptive_throttle.reputation_reset",
            user_id=user_id,
        )
