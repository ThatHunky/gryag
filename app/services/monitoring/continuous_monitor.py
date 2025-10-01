"""
Continuous monitoring orchestrator.

Main coordinator for the intelligent continuous learning system.
Integrates all components: classification, windowing, fact extraction, and proactive responses.

Phase 1: Log classifications, track windows, queue events (no behavior changes)
Phase 3+: Actually process events and enable continuous learning
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.monitoring.message_classifier import MessageClassifier, MessageValue
from app.services.monitoring.conversation_analyzer import (
    ConversationAnalyzer,
    ConversationWindow,
)
from app.services.monitoring.fact_quality_manager import FactQualityManager
from app.services.monitoring.proactive_trigger import ProactiveTrigger
from app.services.monitoring.event_system import EventQueue, Event, EventPriority
from app.services.user_profile import UserProfileStore
from app.services.fact_extractors import FactExtractor

LOGGER = logging.getLogger(__name__)


class ContinuousMonitor:
    """
    Main orchestrator for continuous learning system.

    Coordinates:
    - Message classification and filtering
    - Conversation window tracking
    - Async event processing
    - Fact extraction from windows
    - Proactive response decisions

    Phase 1: Infrastructure only, logging, no behavior changes
    Phase 3+: Full processing enabled
    """

    def __init__(
        self,
        settings: Settings,
        context_store: ContextStore,
        gemini_client: GeminiClient,
        user_profile_store: UserProfileStore,
        fact_extractor: FactExtractor,
        enable_monitoring: bool = True,
        enable_filtering: bool = False,  # Phase 1: False, Phase 3: True
        enable_async_processing: bool = False,  # Phase 1: False, Phase 3: True
    ):
        """
        Initialize continuous monitor.

        Args:
            settings: Bot settings
            context_store: Message context store
            gemini_client: Gemini API client
            user_profile_store: User profile store
            fact_extractor: Fact extraction service
            enable_monitoring: Master switch for monitoring
            enable_filtering: Enable message filtering (Phase 3)
            enable_async_processing: Enable async event processing (Phase 3)
        """
        self.settings = settings
        self.context_store = context_store
        self.gemini_client = gemini_client
        self.user_profile_store = user_profile_store
        self.fact_extractor = fact_extractor

        self.enable_monitoring = enable_monitoring
        self.enable_filtering = enable_filtering
        self.enable_async_processing = enable_async_processing

        # Initialize components
        self.classifier = MessageClassifier(enable_filtering=enable_filtering)

        self.analyzer = ConversationAnalyzer(
            max_window_size=8,  # Adjusted from chat analysis
            window_timeout_seconds=180,  # 3 minutes
        )

        self.fact_quality_manager = FactQualityManager(
            gemini_client=gemini_client,
            db_connection=context_store,  # For fact_quality_metrics
        )

        self.proactive_trigger = ProactiveTrigger(
            confidence_threshold=0.75,
            cooldown_seconds=300,
        )

        self.event_queue = EventQueue(
            num_workers=3,
            max_queue_size=1000,
            enable_circuit_breaker=True,
        )

        # Register event handlers
        self.event_queue.register_handler(
            "conversation_window_closed", self._handle_window_closed_event
        )

        self._bot_user_id: int | None = None

        self._stats = {
            "messages_monitored": 0,
            "windows_processed": 0,
            "facts_extracted": 0,
            "proactive_responses": 0,
        }

        LOGGER.info(
            "ContinuousMonitor initialized",
            extra={
                "enable_monitoring": enable_monitoring,
                "enable_filtering": enable_filtering,
                "enable_async_processing": enable_async_processing,
            },
        )

    def set_bot_user_id(self, bot_user_id: int) -> None:
        """Set bot's user ID for filtering bot messages."""
        self._bot_user_id = bot_user_id
        LOGGER.info(f"Bot user ID set to {bot_user_id}")

    async def start(self) -> None:
        """Start async processing."""
        if self.enable_async_processing:
            await self.event_queue.start()
            LOGGER.info("Continuous monitoring async processing started")
        else:
            LOGGER.info("Continuous monitoring initialized (async processing disabled)")

    async def stop(self) -> None:
        """Stop async processing gracefully."""
        if self.enable_async_processing:
            # Close all active windows before stopping
            closed_windows = self.analyzer.force_close_all()
            LOGGER.info(f"Force closed {len(closed_windows)} active windows")

            # Process closed windows if needed
            for window in closed_windows:
                await self._process_window(window)

            await self.event_queue.stop()
            LOGGER.info("Continuous monitoring stopped")

    async def process_message(
        self, message: Message, is_addressed: bool = False
    ) -> dict[str, Any]:
        """
        Process a message through the monitoring pipeline.

        Phase 1: Classify, track window, log (no behavior changes)
        Phase 3+: Actually process and extract facts

        Args:
            message: Telegram message to process
            is_addressed: Whether message is addressed to bot

        Returns:
            Processing result with stats
        """
        if not self.enable_monitoring:
            return {"monitored": False}

        # Skip bot's own messages
        if message.from_user and message.from_user.id == self._bot_user_id:
            return {"monitored": False, "reason": "bot_message"}

        self._stats["messages_monitored"] += 1

        # Step 1: Classify message
        classification = self.classifier.classify(message, is_addressed)

        LOGGER.debug(
            f"Message classified as {classification.value.value}",
            extra={
                "chat_id": message.chat.id,
                "user_id": message.from_user.id if message.from_user else None,
                "value": classification.value.value,
                "reason": classification.reason,
            },
        )

        # Step 2: Decide if we should process
        should_process = self.classifier.should_process(classification)

        if not should_process:
            LOGGER.debug("Message filtered out, skipping processing")
            return {
                "monitored": True,
                "classification": classification.value.value,
                "processed": False,
                "reason": "filtered",
            }

        # Step 3: Add to conversation window
        closed_window = self.analyzer.add_message(message, classification)

        # Step 4: If a window closed, process it
        if closed_window:
            LOGGER.info(
                f"Conversation window closed: {closed_window.closure_reason}",
                extra=closed_window.get_context_summary(),
            )

            if self.enable_async_processing:
                # Queue for async processing
                priority = (
                    EventPriority.HIGH
                    if closed_window.has_high_value
                    else EventPriority.MEDIUM
                )
                await self.event_queue.enqueue(
                    "conversation_window_closed",
                    {
                        "window": closed_window,
                    },
                    priority=priority,
                )
            else:
                # Phase 1: Just log, don't process
                LOGGER.info(
                    "Window would be processed (async processing disabled)",
                    extra=closed_window.get_context_summary(),
                )

        return {
            "monitored": True,
            "classification": classification.value.value,
            "processed": True,
            "window_closed": closed_window is not None,
        }

    async def _handle_window_closed_event(self, event: Event) -> None:
        """Handle a conversation window closed event."""
        window: ConversationWindow = event.data["window"]
        await self._process_window(window)

    async def _process_window(self, window: ConversationWindow) -> None:
        """
        Process a closed conversation window.

        Extracts facts and checks for proactive response opportunities.
        """
        self._stats["windows_processed"] += 1

        try:
            # Check if bot should proactively respond
            if self._bot_user_id:
                should_respond, reason, confidence = (
                    await self.proactive_trigger.should_respond(
                        window, self._bot_user_id
                    )
                )

                if should_respond:
                    LOGGER.info(
                        f"Proactive response triggered: {reason}",
                        extra={
                            "chat_id": window.chat_id,
                            "confidence": confidence,
                        },
                    )
                    self._stats["proactive_responses"] += 1
                    # TODO: Actually send proactive response (Phase 4)

            # Extract facts from window
            # For Phase 1, we just log the intent
            LOGGER.info(
                "Would extract facts from window (not implemented yet)",
                extra={
                    "chat_id": window.chat_id,
                    "message_count": len(window.messages),
                },
            )

            # TODO: Phase 3 - Actually extract facts
            # facts = await self._extract_facts_from_window(window)
            # await self._store_facts(facts)

        except Exception as e:
            LOGGER.error(
                "Error processing conversation window",
                exc_info=e,
                extra={"chat_id": window.chat_id},
            )

    async def _extract_facts_from_window(
        self, window: ConversationWindow
    ) -> list[dict[str, Any]]:
        """
        Extract facts from a conversation window.

        Phase 3 implementation.
        """
        # TODO: Implement in Phase 3
        return []

    async def _store_facts(self, facts: list[dict[str, Any]]) -> None:
        """
        Store extracted facts with quality processing.

        Phase 3 implementation.
        """
        # TODO: Implement in Phase 3
        pass

    def get_stats(self) -> dict[str, Any]:
        """Get monitoring statistics."""
        return {
            **self._stats,
            "classifier_stats": self.classifier.get_stats(),
            "analyzer_stats": self.analyzer.get_stats(),
            "queue_stats": (
                self.event_queue.get_stats() if self.enable_async_processing else {}
            ),
            "system_healthy": self.is_healthy(),
        }

    def is_healthy(self) -> bool:
        """Check if monitoring system is healthy."""
        if not self.enable_monitoring:
            return True

        if self.enable_async_processing:
            return self.event_queue.is_healthy()

        return True
