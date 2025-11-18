"""
Episode Monitor for automatic episode creation.

Phase 4.2: Monitors conversation windows and automatically creates episodes
when boundaries are detected.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.services.context.episode_boundary_detector import (
    EpisodeBoundaryDetector,
    MessageSequence,
)
from app.services.context.episode_summarizer import EpisodeSummarizer
from app.services.context.episodic_memory import EpisodicMemoryStore

LOGGER = logging.getLogger(__name__)


@dataclass
class ConversationWindow:
    """A window of recent messages for boundary detection."""

    chat_id: int
    thread_id: int | None
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_activity: int = field(default_factory=lambda: int(time.time()))
    participant_ids: set[int] = field(default_factory=set)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to the window."""
        self.messages.append(message)
        self.last_activity = int(time.time())

        # Track participants
        if "user_id" in message:
            self.participant_ids.add(message["user_id"])
        elif "from_user" in message and message["from_user"]:
            self.participant_ids.add(message["from_user"])

    def is_expired(self, timeout: int) -> bool:
        """Check if window has been inactive for too long."""
        return (int(time.time()) - self.last_activity) > timeout

    def has_minimum_messages(self, min_messages: int) -> bool:
        """Check if window has enough messages for episode creation."""
        return len(self.messages) >= min_messages

    def to_message_sequence(self) -> MessageSequence:
        """Convert window to MessageSequence for boundary detection."""
        return MessageSequence(
            messages=self.messages,
            chat_id=self.chat_id,
            thread_id=self.thread_id,
            start_timestamp=self.messages[0]["timestamp"] if self.messages else 0,
            end_timestamp=self.messages[-1]["timestamp"] if self.messages else 0,
        )


class EpisodeMonitor:
    """
    Monitors active conversations and automatically creates episodes.

    Tracks conversation windows, detects boundaries, and creates episodes
    when boundaries are detected or windows expire.
    """

    def __init__(
        self,
        database_url: str,
        settings: Settings,
        gemini_client: Any,
        episodic_memory: EpisodicMemoryStore,
        boundary_detector: EpisodeBoundaryDetector,
        summarizer: EpisodeSummarizer | None = None,
    ):
        self.database_url = str(database_url)
        self.settings = settings
        self.gemini = gemini_client
        self.episodic_memory = episodic_memory
        self.boundary_detector = boundary_detector

        # Phase 4.2.1: Episode summarizer (optional, falls back to heuristics)
        self.summarizer = summarizer

        # Active conversation windows: (chat_id, thread_id) -> ConversationWindow
        self.windows: dict[tuple[int, int | None], ConversationWindow] = {}

        # Lock for thread-safe window access
        self._lock = asyncio.Lock()

        # Background task handle
        self._monitor_task: asyncio.Task | None = None
        self._running = False

        # Configuration
        self.window_timeout = getattr(
            settings, "episode_window_timeout", 1800
        )  # 30 minutes
        self.max_messages_per_window = getattr(
            settings, "episode_window_max_messages", 50
        )
        self.min_messages_for_episode = getattr(settings, "episode_min_messages", 5)
        self.check_interval = getattr(
            settings, "episode_monitor_interval", 300
        )  # 5 minutes

    async def start(self) -> None:
        """Start the background monitoring task."""
        if self._running:
            LOGGER.warning("Episode monitor already running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        LOGGER.info("Episode monitor started")

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        if not self._running:
            return

        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        LOGGER.info("Episode monitor stopped")

    async def track_message(
        self, chat_id: int, thread_id: int | None, message: dict[str, Any]
    ) -> None:
        """
        Track a message in the appropriate conversation window.

        Creates a new window if needed, or adds to existing window.
        """
        if not self.settings.auto_create_episodes:
            return

        async with self._lock:
            key = (chat_id, thread_id)

            # Get or create window
            if key not in self.windows:
                self.windows[key] = ConversationWindow(
                    chat_id=chat_id, thread_id=thread_id
                )
                LOGGER.debug(
                    f"Created new conversation window for chat {chat_id}, thread {thread_id}"
                )

            window = self.windows[key]

            # Add message to window
            window.add_message(message)

            # Check if window is full
            if len(window.messages) >= self.max_messages_per_window:
                LOGGER.info(
                    f"Window reached max size ({self.max_messages_per_window}), checking for boundary"
                )
                await self._check_window_boundary(key, window)

    async def _monitor_loop(self) -> None:
        """Background loop that periodically checks windows for boundaries."""
        LOGGER.info(f"Episode monitor loop started (interval: {self.check_interval}s)")

        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

                if not self._running:
                    break

                await self._check_all_windows()

            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.error(f"Error in episode monitor loop: {e}", exc_info=True)

        LOGGER.info("Episode monitor loop stopped")

    async def _check_all_windows(self) -> None:
        """Check all active windows for boundaries or expiration."""
        batch_delay_ms = getattr(self.settings, "episode_monitor_batch_delay_ms", 100)
        batch_delay = batch_delay_ms / 1000.0  # Convert to seconds

        async with self._lock:
            windows_to_check = list(self.windows.items())

        # Process windows sequentially with delays to reduce CPU spikes
        for idx, (key, window) in enumerate(windows_to_check):
            try:
                # Add delay between window checks (except first one)
                if idx > 0 and batch_delay > 0:
                    await asyncio.sleep(batch_delay)

                # Check if window expired
                if window.is_expired(self.window_timeout):
                    LOGGER.info(f"Window expired for chat {key[0]}, thread {key[1]}")
                    await self._create_episode_from_window(window, "timeout")

                    async with self._lock:
                        if key in self.windows:
                            del self.windows[key]
                    continue

                # Skip boundary detection for very small or very new windows
                # (reduces unnecessary API calls)
                window_age = int(time.time()) - window.last_activity
                if (
                    len(window.messages) < self.min_messages_for_episode
                    or window_age < 60  # Skip if window is less than 1 minute old
                ):
                    continue

                # Check for boundaries in active windows
                await self._check_window_boundary(key, window, auto_close=False)

            except Exception as e:
                LOGGER.error(
                    f"Error checking window {key}: {e}",
                    exc_info=True,
                )

    async def _check_window_boundary(
        self,
        key: tuple[int, int | None],
        window: ConversationWindow,
        auto_close: bool = True,
    ) -> None:
        """
        Check a specific window for episode boundaries.

        Args:
            key: Window key (chat_id, thread_id)
            window: Conversation window to check
            auto_close: Whether to close window and create episode if boundary found
        """
        # Need minimum messages to detect boundary
        if not window.has_minimum_messages(self.min_messages_for_episode):
            return

        try:
            # Detect boundaries
            sequence = window.to_message_sequence()
            signals = await self.boundary_detector.detect_boundaries(sequence)

            # Check if boundary should be created
            (
                should_create,
                score,
                contributing,
            ) = await self.boundary_detector.should_create_boundary(sequence, signals)

            if should_create:
                LOGGER.info(
                    f"Boundary detected in chat {key[0]}, thread {key[1]} "
                    f"(score: {score:.2f}, signals: {len(contributing)})"
                )

                if auto_close:
                    # Create episode and close window
                    await self._create_episode_from_window(window, "boundary")
                    del self.windows[key]
                else:
                    # Just log detection (will be handled later)
                    LOGGER.debug("Boundary detected but auto_close=False")

        except Exception as e:
            LOGGER.error(
                f"Error detecting boundary in window {key}: {e}", exc_info=True
            )

    async def _create_episode_from_window(
        self, window: ConversationWindow, reason: str
    ) -> int | None:
        """
        Create an episode from a conversation window.

        Args:
            window: Window to create episode from
            reason: Reason for creation ("boundary" or "timeout")

        Returns:
            Episode ID if created, None if failed
        """
        if not window.has_minimum_messages(self.min_messages_for_episode):
            LOGGER.debug(
                f"Skipping episode creation: only {len(window.messages)} messages "
                f"(minimum: {self.min_messages_for_episode})"
            )
            return None

        try:
            # Extract message IDs
            message_ids = [msg.get("id", 0) for msg in window.messages if msg.get("id")]

            if not message_ids:
                LOGGER.warning("No valid message IDs in window")
                return None

            # Extract participants
            participant_ids = list(window.participant_ids)

            if not participant_ids:
                LOGGER.warning("No participants in window")
                return None

            # CPU optimization: Use heuristics immediately (fast, no API calls)
            # Gemini summarization can be enabled but is optional and rate-limited
            topic = await self._generate_topic(window)
            summary = await self._generate_summary(window)
            emotional_valence = "neutral"
            tags = [reason]

            # Optionally try Gemini summarization in background (non-blocking)
            # Only if enabled and rate limit allows
            if self.summarizer and getattr(
                self.settings, "enable_episode_gemini_summarization", False
            ):
                # Try to get Gemini summary, but don't block if rate limited
                try:
                    result = await self.summarizer.summarize_episode(
                        window.messages, window.participant_ids
                    )
                    if result:
                        # Use Gemini results if available (they're better quality)
                        gemini_topic = result.get("topic")
                        gemini_summary = result.get("summary")
                        gemini_valence = result.get("emotional_valence", "neutral")
                        gemini_tags = result.get("tags", [])

                        if gemini_topic:
                            topic = gemini_topic
                        if gemini_summary:
                            summary = gemini_summary
                        if gemini_valence != "neutral":
                            emotional_valence = gemini_valence
                        if gemini_tags:
                            tags = [reason] + gemini_tags[:4]  # Limit tags

                        LOGGER.debug(
                            f"Enhanced episode with Gemini summary (topic: {topic[:50]})"
                        )
                except Exception as e:
                    # Silent fallback - heuristics already provided values
                    LOGGER.debug(
                        f"Gemini summarization skipped (rate limited or failed): {e}"
                    )

            # Calculate importance (basic heuristic for now)
            importance = self._calculate_importance(window)

            # Create episode
            episode_id = await self.episodic_memory.create_episode(
                chat_id=window.chat_id,
                thread_id=window.thread_id,
                user_ids=participant_ids,
                topic=topic,
                summary=summary,
                messages=message_ids,
                importance=importance,
                emotional_valence=emotional_valence,
                tags=tags,
            )

            LOGGER.info(
                f"Created episode {episode_id} from window "
                f"({len(message_ids)} messages, {len(participant_ids)} participants, "
                f"importance: {importance:.2f}, emotion: {emotional_valence}, "
                f"tags: {tags}, reason: {reason})"
            )

            return episode_id

        except Exception as e:
            LOGGER.error(f"Error creating episode from window: {e}", exc_info=True)
            return None

    async def _generate_topic(self, window: ConversationWindow) -> str:
        """
        Generate a topic for the episode.

        Uses fast heuristics by default. Gemini can be enabled optionally.
        """
        # Fast heuristic: use first message as topic seed (no API calls)
        if window.messages:
            first_text = window.messages[0].get("text", "")
            # Take first 50 chars as topic
            topic = first_text[:50].strip()
            if len(first_text) > 50:
                topic += "..."
            return topic or "Conversation"

        return "Conversation"

    async def _generate_summary(self, window: ConversationWindow) -> str:
        """
        Generate a summary for the episode.

        Uses fast heuristics by default. Gemini can be enabled optionally.
        """
        # Fast heuristic: simple message/participant count (no API calls)
        msg_count = len(window.messages)
        participant_count = len(window.participant_ids)

        return (
            f"Conversation with {participant_count} participant(s) "
            f"over {msg_count} message(s)"
        )

    def _calculate_importance(self, window: ConversationWindow) -> float:
        """
        Calculate importance score for episode.

        Uses heuristics based on message count, participants, and duration.
        """
        importance = 0.0

        # Base importance from message count
        msg_count = len(window.messages)
        if msg_count >= 20:
            importance += 0.4
        elif msg_count >= 10:
            importance += 0.3
        elif msg_count >= 5:
            importance += 0.2

        # Importance from participant count
        participant_count = len(window.participant_ids)
        if participant_count >= 3:
            importance += 0.3
        elif participant_count >= 2:
            importance += 0.2

        # Importance from duration
        if window.messages:
            duration = (
                window.messages[-1]["timestamp"] - window.messages[0]["timestamp"]
            )
            duration_minutes = duration / 60

            if duration_minutes >= 30:
                importance += 0.3
            elif duration_minutes >= 10:
                importance += 0.2
            elif duration_minutes >= 5:
                importance += 0.1

        return min(importance, 1.0)

    async def get_active_windows(self) -> list[ConversationWindow]:
        """Get list of all active conversation windows."""
        async with self._lock:
            return list(self.windows.values())

    async def get_window_count(self) -> int:
        """Get count of active windows."""
        async with self._lock:
            return len(self.windows)

    async def clear_window(self, chat_id: int, thread_id: int | None) -> bool:
        """
        Manually clear a conversation window without creating episode.

        Returns True if window was cleared, False if not found.
        """
        async with self._lock:
            key = (chat_id, thread_id)
            if key in self.windows:
                del self.windows[key]
                LOGGER.info(f"Cleared window for chat {chat_id}, thread {thread_id}")
                return True
            return False
