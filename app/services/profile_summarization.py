"""Profile summarization service for background processing.

This service periodically generates summaries of user profiles by analyzing
accumulated facts and interactions. Optimized for i5-6500 hardware constraints:
- Processes 1 profile at a time to limit memory usage (6-8GB peak)
- Conservative batch size (30 turns default)
- Runs at low-traffic hours (3 AM default)
- Max 50 profiles/day to avoid CPU overload
- Expected latency: 150-300ms per summarization on 4 threads
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.telemetry import telemetry

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.gemini import GeminiClient
    from app.services.user_profile import UserProfileStore
    from app.services.user_profile_adapter import UserProfileStoreAdapter

    ProfileStoreType = UserProfileStore | UserProfileStoreAdapter
else:
    ProfileStoreType = Any

logger = logging.getLogger(__name__)


class ProfileSummarizer:
    """Background service for generating profile summaries."""

    def __init__(
        self,
        settings: Settings,
        profile_store: ProfileStoreType,
        gemini_client: GeminiClient,
    ) -> None:
        """Initialize profile summarizer.

        Args:
            settings: Application settings with summarization config
            profile_store: User profile storage service
            gemini_client: Gemini API client for generating summaries
        """
        self.settings = settings
        self.profile_store = profile_store
        self.gemini_client = gemini_client
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._daily_count = 0
        self._last_reset_date: datetime | None = None

    async def start(self) -> None:
        """Start the background summarization scheduler."""
        if not self.settings.enable_profile_summarization:
            logger.info("Profile summarization disabled in config")
            return

        if self._running:
            logger.warning("Profile summarizer already running")
            return

        # Schedule daily summarization at configured hour
        trigger = CronTrigger(
            hour=self.settings.profile_summarization_hour,
            minute=0,
            second=0,
        )

        self.scheduler.add_job(
            self._summarize_profiles,
            trigger=trigger,
            id="profile_summarization",
            name="Summarize user profiles",
            replace_existing=True,
        )

        self.scheduler.start()
        self._running = True

        logger.info(
            "Profile summarization scheduler started (runs at %02d:00)",
            self.settings.profile_summarization_hour,
        )

    async def stop(self) -> None:
        """Stop the background summarization scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Profile summarization scheduler stopped")

    async def _summarize_profiles(self) -> None:
        """Main summarization task - processes profiles needing updates."""
        # Reset daily counter if it's a new day
        now = datetime.now()
        if self._last_reset_date is None or self._last_reset_date.date() != now.date():
            self._daily_count = 0
            self._last_reset_date = now

        # Check if we've hit the daily limit
        if self._daily_count >= self.settings.max_profiles_per_day:
            logger.info(
                f"Daily profile summarization limit reached ({self._daily_count}/{self.settings.max_profiles_per_day})",
            )
            return

        logger.info("Starting profile summarization task")
        start_time = asyncio.get_event_loop().time()

        try:
            # Get profiles that need summarization
            profiles = await self.profile_store.get_profiles_needing_summarization(
                limit=self.settings.max_profiles_per_day - self._daily_count
            )

            if not profiles:
                logger.info("No profiles need summarization")
                return

            logger.info(f"Found {len(profiles)} profiles needing summarization")

            # Process each profile sequentially to limit memory usage
            success_count = 0
            fail_count = 0

            for user_id in profiles:
                try:
                    await self._summarize_profile(user_id)
                    success_count += 1
                    self._daily_count += 1
                    telemetry.increment_counter("summaries_generated")

                    # Small delay between profiles to avoid CPU spikes
                    await asyncio.sleep(0.5)

                except Exception as exc:
                    logger.error(
                        f"Failed to summarize profile for user {user_id}: {exc}",
                        exc_info=True,
                    )
                    fail_count += 1
                    telemetry.increment_counter("summaries_failed")

            elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            telemetry.set_gauge("summarization_time_ms", elapsed_ms)

            logger.info(
                f"Profile summarization complete: {success_count} success, {fail_count} failed, {elapsed_ms}ms elapsed",
            )

        except Exception as exc:
            logger.error(
                f"Profile summarization task failed: {exc}",
                exc_info=True,
            )
            telemetry.increment_counter("summaries_failed")

    async def _summarize_profile(self, user_id: int) -> None:
        """Generate summary for a single user profile.

        Args:
            user_id: Telegram user ID to summarize

        Raises:
            Exception: If summarization fails
        """
        profile_start = asyncio.get_event_loop().time()

        # Get profile data with limited batch size (i5-6500 optimization)
        profile = await self.profile_store.get_profile(
            user_id=user_id,
            limit=self.settings.profile_summarization_batch_size,
        )

        if not profile:
            logger.warning(f"No profile data found for user {user_id}")
            return

        # Build summarization prompt
        facts_by_type = {
            "personal": [],
            "preferences": [],
            "relationships": [],
        }

        for fact in profile.get("facts", []):
            fact_type = fact.get("fact_type", "personal")
            facts_by_type[fact_type].append(fact)

        # Skip if no facts to summarize
        total_facts = sum(len(facts) for facts in facts_by_type.values())
        if total_facts == 0:
            logger.info(f"User {user_id} has no facts to summarize")
            return

        # Generate summary using Gemini
        prompt = self._build_summary_prompt(facts_by_type, profile)
        system_instruction = "You are a concise profile summarizer. Generate a brief, factual summary of the user based on their facts. Keep it under 200 words."

        try:
            response = await self.gemini_client.generate(
                system_prompt=system_instruction,
                history=None,
                user_parts=[{"text": prompt}],
            )

            summary = response.get("text", "")
            if not summary:
                raise ValueError("Empty summary generated")

            # Store summary in database
            await self.profile_store.update_summary(user_id, summary)

            elapsed_ms = int((asyncio.get_event_loop().time() - profile_start) * 1000)
            logger.info(
                f"Summarized profile for user {user_id}: {total_facts} facts, {elapsed_ms}ms"
            )

        except Exception as exc:
            logger.error(
                f"Failed to generate summary for user {user_id}: {exc}",
                exc_info=True,
            )
            raise

    def _build_summary_prompt(
        self, facts_by_type: dict[str, list[dict]], profile: dict
    ) -> str:
        """Build prompt for profile summarization.

        Args:
            facts_by_type: Facts grouped by type
            profile: Full profile data with metadata

        Returns:
            Prompt string for Gemini
        """
        lines = [
            "Summarize this user's profile based on their facts:",
            "",
        ]

        # Personal facts
        if facts_by_type["personal"]:
            lines.append("PERSONAL:")
            for fact in facts_by_type["personal"]:
                confidence = fact.get("confidence", 0.0)
                content = fact.get("content", "")
                lines.append(f"- {content} (confidence: {confidence:.2f})")
            lines.append("")

        # Preferences
        if facts_by_type["preferences"]:
            lines.append("PREFERENCES:")
            for fact in facts_by_type["preferences"]:
                confidence = fact.get("confidence", 0.0)
                content = fact.get("content", "")
                lines.append(f"- {content} (confidence: {confidence:.2f})")
            lines.append("")

        # Relationships
        if facts_by_type["relationships"]:
            lines.append("RELATIONSHIPS:")
            for fact in facts_by_type["relationships"]:
                confidence = fact.get("confidence", 0.0)
                content = fact.get("content", "")
                lines.append(f"- {content} (confidence: {confidence:.2f})")
            lines.append("")

        lines.extend(
            [
                "Generate a concise summary that:",
                "1. Highlights key personal traits and preferences",
                "2. Notes important relationships and social context",
                "3. Uses natural language (not bullet points)",
                "4. Stays under 200 words",
                "5. Writes in Ukrainian if the user primarily uses Ukrainian",
            ]
        )

        return "\n".join(lines)

    async def summarize_now(self, user_id: int) -> str | None:
        """Manually trigger summarization for a specific user (for testing).

        Args:
            user_id: Telegram user ID to summarize

        Returns:
            Generated summary text, or None if failed
        """
        try:
            await self._summarize_profile(user_id)
            profile = await self.profile_store.get_profile(user_id)
            return profile.get("summary") if profile else None
        except Exception as exc:
            logger.error(
                f"Manual summarization failed for user {user_id}: {exc}",
                exc_info=True,
            )
            return None
