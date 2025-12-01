"""Background jobs for generating chat summaries with staggered processing."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

from app.config import Settings
from app.repositories.chat_summary_repository import ChatSummaryRepository
from app.services.gemini import GeminiClient
from app.services.instruction.summary_generator import SummaryGenerator

LOGGER = logging.getLogger(__name__)


class SummaryJobs:
    """Background jobs for generating chat summaries with staggered processing."""

    def __init__(
        self,
        settings: Settings,
        gemini_client: GeminiClient,
        summary_repository: ChatSummaryRepository,
        context_store: Any | None = None,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        """
        Initialize summary jobs.

        Args:
            settings: Application settings
            gemini_client: Gemini API client
            summary_repository: Summary repository
            context_store: Optional context store
            scheduler: Optional scheduler (creates new if None)
        """
        self.settings = settings
        self.gemini_client = gemini_client
        self.summary_repository = summary_repository
        self.context_store = context_store
        self.scheduler = scheduler or AsyncIOScheduler(timezone=ZoneInfo("Europe/Kiev"))
        self.generator = SummaryGenerator(
            settings=settings,
            gemini_client=gemini_client,
            summary_repository=summary_repository,
            context_store=context_store,
        )
        self._running = False

    def start(self) -> None:
        """Start the summary generation scheduler with staggered processing."""
        if not self.settings.enable_chat_summary_jobs:
            LOGGER.info("Summary generation jobs disabled")
            return

        if self._running:
            LOGGER.warning("Summary jobs already running")
            return

        try:
            # Schedule periodic batch processing (staggered across time slots)
            # Runs every N hours and processes a batch of chats each time
            interval_hours = self.settings.summary_jobs_interval_hours
            trigger = IntervalTrigger(hours=interval_hours, timezone="Europe/Kiev")

            self.scheduler.add_job(
                self._process_summary_batch,
                trigger=trigger,
                id="process_summary_batch",
                name="Process chat summary batch (staggered)",
                replace_existing=True,
            )

            if not self.scheduler.running:
                self.scheduler.start()

            self._running = True

            LOGGER.info(
                f"Summary generation jobs started (runs every {interval_hours} hours, "
                f"{self.settings.summary_jobs_chats_per_batch} chats per batch, "
                f"{self.settings.summary_jobs_stagger_slots} stagger slots)"
            )

        except Exception as e:
            LOGGER.error(f"Failed to start summary jobs: {e}", exc_info=True)
            raise

    async def stop(self) -> None:
        """Stop the summary generation scheduler."""
        if not self._running:
            return

        try:
            self.scheduler.shutdown(wait=True)
            self._running = False
            LOGGER.info("Summary generation jobs stopped")
        except Exception as e:
            LOGGER.error(f"Error stopping summary jobs: {e}", exc_info=True)

    async def _get_active_chat_ids(
        self, min_messages: int = 10, lookback_days: int = 60
    ) -> list[int]:
        """Get list of active chat IDs that have messages.

        Args:
            min_messages: Minimum number of messages to consider chat active
            lookback_days: How many days back to look for activity

        Returns:
            List of active chat IDs
        """
        from app.infrastructure.db_utils import get_db_connection

        cutoff_ts = int(
            (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()
        )

        query = """
            SELECT chat_id, COUNT(*) as message_count
            FROM messages
            WHERE ts >= $1
            GROUP BY chat_id
            HAVING COUNT(*) >= $2
            ORDER BY MAX(ts) DESC
        """

        async with get_db_connection(self.settings.database_url) as conn:
            rows = await conn.fetch(query, cutoff_ts, min_messages)

        return [row["chat_id"] for row in rows]

    def _get_time_slot_for_chat(self, chat_id: int) -> int:
        """Get the time slot index for a chat ID using hash-based distribution.

        Args:
            chat_id: Chat ID

        Returns:
            Time slot index (0 to stagger_slots-1)
        """
        # Use hash of chat_id to consistently assign to a time slot
        hash_obj = hashlib.md5(str(chat_id).encode())
        hash_int = int(hash_obj.hexdigest(), 16)
        return hash_int % self.settings.summary_jobs_stagger_slots

    def _get_current_time_slot(self) -> int:
        """Get the current time slot based on hour of day.

        Returns:
            Current time slot index (0 to stagger_slots-1)
        """
        now = datetime.now(timezone.utc)
        # Map hour of day to time slot
        hour = now.hour
        slots_per_hour = self.settings.summary_jobs_stagger_slots / 24.0
        return int(hour * slots_per_hour) % self.settings.summary_jobs_stagger_slots

    async def _should_process_chat(
        self, chat_id: int, summary_type: str
    ) -> tuple[bool, str]:
        """Check if a chat should be processed for summary generation.

        Args:
            chat_id: Chat ID
            summary_type: '30days' or '7days'

        Returns:
            Tuple of (should_process, reason)
        """
        # Check if chat is in the current time slot
        chat_slot = self._get_time_slot_for_chat(chat_id)
        current_slot = self._get_current_time_slot()

        if chat_slot != current_slot:
            return False, f"chat in slot {chat_slot}, current slot {current_slot}"

        # Check cooldown period
        latest_summary = await self.summary_repository.get_latest_summary(
            chat_id, summary_type
        )

        if latest_summary:
            cooldown_days = (
                self.settings.summary_30day_cooldown_days
                if summary_type == "30days"
                else self.settings.summary_7day_cooldown_days
            )
            cooldown_seconds = cooldown_days * 24 * 60 * 60
            time_since_generation = int(datetime.now(timezone.utc).timestamp()) - latest_summary["generated_at"]

            if time_since_generation < cooldown_seconds:
                days_remaining = (cooldown_seconds - time_since_generation) / (24 * 60 * 60)
                return False, f"cooldown active ({days_remaining:.1f} days remaining)"

        return True, "ready"

    async def _process_summary_batch(self) -> None:
        """Process a batch of chats for summary generation (staggered)."""
        LOGGER.info("Starting summary batch processing job")

        try:
            # Get active chats
            active_chats = await self._get_active_chat_ids()
            if not active_chats:
                LOGGER.info("No active chats found for summary generation")
                return

            LOGGER.info(f"Found {len(active_chats)} active chats")

            # Filter by allowed chat IDs if configured
            allowed_chat_ids = self.settings.summary_allowed_chat_ids_list
            if allowed_chat_ids:
                active_chats = [chat_id for chat_id in active_chats if chat_id in allowed_chat_ids]
                LOGGER.info(
                    f"Filtered to {len(active_chats)} chats in allowed list "
                    f"(from {len(allowed_chat_ids)} allowed chat IDs)"
                )
                if not active_chats:
                    LOGGER.info("No active chats match the allowed chat IDs list")
                    return

            # Filter chats that should be processed in current time slot
            current_slot = self._get_current_time_slot()
            eligible_chats = [
                chat_id
                for chat_id in active_chats
                if self._get_time_slot_for_chat(chat_id) == current_slot
            ]

            LOGGER.info(
                f"Time slot {current_slot}: {len(eligible_chats)} chats eligible for processing"
            )

            # Process summaries for eligible chats (both 30-day and 7-day)
            processed_30day = 0
            processed_7day = 0
            skipped_30day = 0
            skipped_7day = 0
            errors_30day = 0
            errors_7day = 0

            batch_size = self.settings.summary_jobs_chats_per_batch
            chats_to_process = eligible_chats[:batch_size]

            for chat_id in chats_to_process:
                # Process 30-day summary
                should_process, reason = await self._should_process_chat(
                    chat_id, "30days"
                )
                if should_process:
                    try:
                        await self._generate_30day_summary_for_chat(chat_id)
                        processed_30day += 1
                    except Exception as e:
                        LOGGER.error(
                            f"Error generating 30-day summary for chat {chat_id}: {e}",
                            exc_info=True,
                        )
                        errors_30day += 1
                else:
                    skipped_30day += 1
                    LOGGER.debug(
                        f"Skipping 30-day summary for chat {chat_id}: {reason}"
                    )

                # Process 7-day summary
                should_process, reason = await self._should_process_chat(chat_id, "7days")
                if should_process:
                    try:
                        await self._generate_7day_summary_for_chat(chat_id)
                        processed_7day += 1
                    except Exception as e:
                        LOGGER.error(
                            f"Error generating 7-day summary for chat {chat_id}: {e}",
                            exc_info=True,
                        )
                        errors_7day += 1
                else:
                    skipped_7day += 1
                    LOGGER.debug(
                        f"Skipping 7-day summary for chat {chat_id}: {reason}"
                    )

                # Small delay between chats to avoid overload
                await asyncio.sleep(1)

            LOGGER.info(
                f"Summary batch processing completed: "
                f"30-day: {processed_30day} processed, {skipped_30day} skipped, {errors_30day} errors; "
                f"7-day: {processed_7day} processed, {skipped_7day} skipped, {errors_7day} errors"
            )

        except Exception as e:
            LOGGER.error(f"Error in summary batch processing job: {e}", exc_info=True)

    async def _generate_30day_summary_for_chat(self, chat_id: int) -> None:
        """Generate 30-day summary for a specific chat.

        Args:
            chat_id: Chat ID
        """
        now = datetime.now(timezone.utc)
        period_end = now - timedelta(days=7)  # 7 days ago
        period_start = period_end - timedelta(days=30)  # 30 days before that

        period_start_ts = int(period_start.timestamp())
        period_end_ts = int(period_end.timestamp())

        LOGGER.info(
            f"Generating 30-day summary for chat {chat_id} "
            f"(period: {period_start_ts} to {period_end_ts})"
        )

        success = await self.generator.generate_30day_summary(chat_id=chat_id)

        if success:
            LOGGER.info(f"Successfully generated 30-day summary for chat {chat_id}")
        else:
            LOGGER.warning(f"Failed to generate 30-day summary for chat {chat_id}")

    async def _generate_7day_summary_for_chat(self, chat_id: int) -> None:
        """Generate 7-day summary for a specific chat.

        Args:
            chat_id: Chat ID
        """
        now = datetime.now(timezone.utc)
        period_end = now
        period_start = now - timedelta(days=7)

        period_start_ts = int(period_start.timestamp())
        period_end_ts = int(period_end.timestamp())

        LOGGER.info(
            f"Generating 7-day summary for chat {chat_id} "
            f"(period: {period_start_ts} to {period_end_ts})"
        )

        success = await self.generator.generate_7day_summary(chat_id=chat_id)

        if success:
            LOGGER.info(f"Successfully generated 7-day summary for chat {chat_id}")
        else:
            LOGGER.warning(f"Failed to generate 7-day summary for chat {chat_id}")

    async def generate_summary_for_chat(
        self, chat_id: int, summary_type: str = "both"
    ) -> bool:
        """
        Manually trigger summary generation for a specific chat.

        Args:
            chat_id: Chat ID
            summary_type: '30days', '7days', or 'both'

        Returns:
            True if successful
        """
        success = True

        if summary_type in ("30days", "both"):
            try:
                await self._generate_30day_summary_for_chat(chat_id)
            except Exception as e:
                LOGGER.error(f"Failed to generate 30-day summary: {e}", exc_info=True)
                success = False

        if summary_type in ("7days", "both"):
            try:
                await self._generate_7day_summary_for_chat(chat_id)
            except Exception as e:
                LOGGER.error(f"Failed to generate 7-day summary: {e}", exc_info=True)
                success = False

        return success
