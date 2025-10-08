"""
Continuous monitoring orchestrator.

Main coordinator for the intelligent continuous learning system.
Integrates all components: classification, windowing, fact extraction, and proactive responses.

Phase 1: Log classifications, track windows, queue events (no behavior changes)
Phase 3+: Actually process events and enable continuous learning
Chat Public Memory (Oct 2025): Extract and store group-level facts
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

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
from app.services.fact_extractors.chat_fact_extractor import ChatFactExtractor
from app.repositories.chat_profile import ChatProfileRepository, ChatFact

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
        chat_profile_store: ChatProfileRepository | None = None,
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
            chat_profile_store: Chat profile store (for chat-level facts)
            enable_monitoring: Master switch for monitoring
            enable_filtering: Enable message filtering (Phase 3)
            enable_async_processing: Enable async event processing (Phase 3)
        """
        self.settings = settings
        self.context_store = context_store
        self.gemini_client = gemini_client
        self.user_profile_store = user_profile_store
        self.fact_extractor = fact_extractor
        self.chat_profile_store = chat_profile_store

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
            context_store=context_store,
            gemini_client=gemini_client,
            settings=settings,
        )

        # Chat fact extractor (for group-level facts)
        self.chat_fact_extractor = None
        if self.settings.enable_chat_memory and chat_profile_store:
            method = self.settings.chat_fact_extraction_method
            self.chat_fact_extractor = ChatFactExtractor(
                gemini_client=gemini_client,
                enable_patterns="pattern" in method or "hybrid" in method,
                enable_statistical="statistical" in method or "hybrid" in method,
                enable_llm="llm" in method or "hybrid" in method,
                min_confidence=self.settings.chat_fact_min_confidence,
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
        self._bot_instance = None  # For sending proactive responses

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

    def set_bot_instance(self, bot) -> None:
        """
        Set bot instance for sending proactive responses.

        Args:
            bot: Aiogram Bot instance
        """
        self._bot_instance = bot
        LOGGER.info("Bot instance attached to ContinuousMonitor")

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
            # Phase 4: Check if bot should proactively respond
            if (
                self._bot_user_id
                and self._bot_instance
                and self.settings.enable_proactive_responses
            ):
                decision = await self.proactive_trigger.should_respond(
                    window,
                    bot_user_id=self._bot_user_id,
                    bot_capabilities=["weather", "currency", "search", "calculations"],
                )

                if decision.should_respond:
                    LOGGER.info(
                        f"Proactive response triggered: {decision.reason}",
                        extra={
                            "chat_id": window.chat_id,
                            "confidence": decision.confidence,
                            "intent": (
                                decision.intent.intent_type.value
                                if decision.intent
                                else None
                            ),
                        },
                    )

                    # Send proactive response
                    await self._send_proactive_response(window, decision)
                    self._stats["proactive_responses"] += 1
                else:
                    LOGGER.debug(
                        f"Proactive response blocked: {decision.reason}",
                        extra={"chat_id": window.chat_id},
                    )

            # Extract facts from window (Phase 3)
            facts = await self._extract_facts_from_window(window)

            if facts:
                LOGGER.info(
                    f"Extracted {len(facts)} facts from window",
                    extra={
                        "chat_id": window.chat_id,
                        "message_count": len(window.messages),
                    },
                )

                # Store facts with quality processing (Phase 3)
                await self._store_facts(facts, window)

            else:
                LOGGER.debug(
                    "No facts extracted from window",
                    extra={"chat_id": window.chat_id},
                )

        except Exception as e:
            LOGGER.error(
                "Error processing conversation window",
                exc_info=e,
                extra={"chat_id": window.chat_id},
            )

    async def _send_proactive_response(
        self, window: ConversationWindow, decision
    ) -> None:
        """
        Send proactive response to conversation.

        Args:
            window: Conversation window
            decision: ProactiveDecision with intent and suggested response
        """
        if not self._bot_instance or not decision.intent:
            return

        try:
            # Generate response using Gemini
            conversation_text = "\n".join(
                f"User{msg.user_id}: {msg.text}" for msg in window.messages[-5:]
            )

            prompt = f"""Based on this conversation, provide a helpful proactive response:

{conversation_text}

Intent detected: {decision.intent.intent_type.value}
Context: {decision.intent.context_summary}

Your response should:
1. Be natural and conversational
2. Address the detected intent
3. Be brief (1-2 sentences)
4. Add value without being intrusive

Response:"""

            response_text = await self.gemini_client.generate(
                system_prompt="You are a helpful bot joining a conversation proactively. Be brief, natural, and valuable.",
                history=[],
                user_parts=[{"text": prompt}],
            )

            if not response_text:
                LOGGER.warning("Empty proactive response from Gemini")
                return

            # Send message to chat
            sent_message = await self._bot_instance.send_message(
                chat_id=window.chat_id,
                text=response_text,
                message_thread_id=window.thread_id,
            )

            # Record proactive response
            # Note: window doesn't have an id field, so we pass 0 for now
            # This should be updated when conversation_windows table is used
            await self.proactive_trigger.record_proactive_response(
                chat_id=window.chat_id,
                window_id=0,  # TODO: Use actual window_id when available
                intent=decision.intent,
                response_text=response_text,
                response_message_id=sent_message.message_id,
            )

            LOGGER.info(
                "Proactive response sent successfully",
                extra={
                    "chat_id": window.chat_id,
                    "message_id": sent_message.message_id,
                    "intent": decision.intent.intent_type.value,
                },
            )

        except Exception as e:
            LOGGER.error(
                "Failed to send proactive response",
                exc_info=e,
                extra={"chat_id": window.chat_id},
            )

    async def _extract_facts_from_window(
        self, window: ConversationWindow
    ) -> Tuple[List[dict[str, Any]], List[ChatFact]]:
        """
        Extract both user facts and chat facts from a conversation window.

        Phase 3 implementation: Uses fact extractor to analyze conversation context.
        Chat Public Memory (Oct 2025): Also extracts group-level facts.

        Args:
            window: Closed conversation window

        Returns:
            Tuple of (user_facts, chat_facts)
        """
        try:
            # Build conversation context from window messages
            messages_text = []
            participants = set()
            user_names = {}

            for msg_ctx in window.messages:
                participants.add(msg_ctx.user_id)

                # Build message representation
                if msg_ctx.text:
                    # Try to get username from first message for each user
                    if msg_ctx.user_id not in user_names:
                        user_names[msg_ctx.user_id] = f"User{msg_ctx.user_id}"

                    messages_text.append(
                        f"{user_names[msg_ctx.user_id]}: {msg_ctx.text}"
                    )

            if not messages_text:
                LOGGER.debug("No text content in window, skipping fact extraction")
                return ([], [])

            # Join into conversation
            conversation = "\n".join(messages_text)

            LOGGER.debug(
                f"Extracting facts from window with {len(messages_text)} messages",
                extra={
                    "chat_id": window.chat_id,
                    "participants": len(participants),
                },
            )

            # Extract user facts for each participant
            all_user_facts = []

            for user_id in participants:
                # Skip bot's own messages
                if user_id == self._bot_user_id:
                    continue

                try:
                    # Use existing fact extractor
                    # Pass full conversation as context
                    facts = await self.fact_extractor.extract_facts(
                        message=conversation,
                        user_id=user_id,
                        username=user_names.get(user_id),
                        context=[],  # Window IS the context
                        min_confidence=0.6,  # Lower threshold for window-based
                    )

                    # Add window metadata to each fact
                    for fact in facts:
                        fact["extracted_from_window"] = True
                        fact["window_message_count"] = len(window.messages)
                        fact["window_has_high_value"] = window.has_high_value

                    all_user_facts.extend(facts)

                    LOGGER.info(
                        f"Extracted {len(facts)} user facts from window for user {user_id}",
                        extra={"chat_id": window.chat_id, "user_id": user_id},
                    )

                except Exception as e:
                    LOGGER.error(
                        f"Failed to extract user facts for user {user_id}: {e}",
                        extra={"chat_id": window.chat_id, "user_id": user_id},
                    )

            # Extract chat facts (group-level)
            chat_facts = []
            if (
                self.settings.enable_chat_memory
                and self.settings.enable_chat_fact_extraction
                and self.chat_fact_extractor
                and hasattr(window, "raw_messages")
                and window.raw_messages
            ):
                try:
                    chat_facts = await self.chat_fact_extractor.extract_chat_facts(
                        messages=window.raw_messages,
                        chat_id=window.chat_id,
                    )

                    LOGGER.info(
                        f"Extracted {len(chat_facts)} chat-level facts from window",
                        extra={"chat_id": window.chat_id},
                    )

                except Exception as e:
                    LOGGER.error(
                        f"Failed to extract chat facts: {e}",
                        exc_info=True,
                        extra={"chat_id": window.chat_id},
                    )

            self._stats["facts_extracted"] += len(all_user_facts) + len(chat_facts)
            return (all_user_facts, chat_facts)

        except Exception as e:
            LOGGER.error(
                f"Error extracting facts from window: {e}",
                exc_info=True,
                extra={"chat_id": window.chat_id},
            )
            return ([], [])

    async def _store_facts(
        self,
        facts: Tuple[List[dict[str, Any]], List[ChatFact]],
        window: ConversationWindow,
    ) -> None:
        """
        Store extracted user facts and chat facts with quality processing.

        Phase 3 implementation: Apply deduplication, conflict resolution, and decay
        before storing facts.
        Chat Public Memory (Oct 2025): Also stores group-level facts.

        Args:
            facts: Tuple of (user_facts, chat_facts) from extraction
            window: Conversation window (for context)
        """
        user_facts, chat_facts = facts

        # Store user facts (existing logic)
        if user_facts:
            await self._store_user_facts(user_facts, window)

        # Store chat facts (new logic)
        if chat_facts and self.chat_profile_store:
            await self._store_chat_facts(chat_facts, window)

    async def _store_user_facts(
        self, facts: List[dict[str, Any]], window: ConversationWindow
    ) -> None:
        """
        Store user facts with quality processing.

        Args:
            facts: Extracted user facts from window
            window: Conversation window (for context)
        """
        if not facts:
            return

        try:
            # Group facts by user
            facts_by_user: dict[int, list[dict[str, Any]]] = {}

            for fact in facts:
                user_id = fact.get("user_id")
                if not user_id:
                    LOGGER.warning("Fact missing user_id, skipping")
                    continue

                facts_by_user.setdefault(user_id, []).append(fact)

            # Process and store facts for each user
            for user_id, user_facts in facts_by_user.items():
                try:
                    # Get existing facts for this user
                    existing_facts = await self.user_profile_store.get_facts(
                        user_id=user_id,
                        chat_id=window.chat_id,
                        limit=1000,  # Get recent facts for dedup
                    )

                    LOGGER.debug(
                        f"Processing {len(user_facts)} new facts against {len(existing_facts)} existing",
                        extra={"user_id": user_id},
                    )

                    # Apply quality processing (Phase 2 integration)
                    processed_facts = await self.fact_quality_manager.process_facts(
                        facts=user_facts,
                        user_id=user_id,
                        chat_id=window.chat_id,
                        existing_facts=existing_facts,
                    )

                    LOGGER.info(
                        f"Quality processing: {len(user_facts)} → {len(processed_facts)} facts",
                        extra={
                            "user_id": user_id,
                            "duplicates_removed": len(user_facts)
                            - len(processed_facts),
                        },
                    )

                    # Store processed facts
                    for fact in processed_facts:
                        try:
                            await self.user_profile_store.add_fact(
                                user_id=user_id,
                                chat_id=window.chat_id,
                                fact_type=fact.get("fact_type", "personal"),
                                fact_key=fact.get("fact_key", ""),
                                fact_value=fact.get("fact_value", ""),
                                confidence=fact.get("confidence", 0.7),
                                evidence_text=fact.get("evidence_text"),
                                source_message_id=fact.get("source_message_id"),
                            )

                        except Exception as e:
                            LOGGER.error(
                                f"Failed to store fact: {e}",
                                extra={
                                    "user_id": user_id,
                                    "fact_key": fact.get("fact_key"),
                                },
                            )

                    LOGGER.info(
                        f"Stored {len(processed_facts)} facts for user {user_id}",
                        extra={"chat_id": window.chat_id},
                    )

                except Exception as e:
                    LOGGER.error(
                        f"Failed to process facts for user {user_id}: {e}",
                        exc_info=True,
                        extra={"chat_id": window.chat_id},
                    )

        except Exception as e:
            LOGGER.error(
                f"Error storing facts: {e}",
                exc_info=True,
                extra={"chat_id": window.chat_id},
            )

    async def _store_chat_facts(
        self, chat_facts: list[ChatFact], window: ConversationWindow
    ) -> None:
        """
        Store chat-level facts via ChatProfileRepository.

        Args:
            chat_facts: List of extracted chat facts
            window: Conversation window containing source messages
        """
        if not self.chat_profile_store or not chat_facts:
            return

        try:
            LOGGER.info(
                f"Storing {len(chat_facts)} chat facts",
                extra={"chat_id": window.chat_id},
            )

            for fact in chat_facts:
                try:
                    await self.chat_profile_store.add_chat_fact(
                        chat_id=window.chat_id,
                        category=fact.fact_category,
                        fact_key=fact.fact_key,
                        fact_value=fact.fact_value,
                        fact_description=fact.fact_description,
                        confidence=fact.confidence,
                        evidence_text=fact.evidence_text,
                    )

                    LOGGER.debug(
                        f"Stored chat fact: {fact.fact_category}.{fact.fact_key}",
                        extra={
                            "chat_id": window.chat_id,
                            "confidence": fact.confidence,
                        },
                    )

                except Exception as e:
                    LOGGER.error(
                        f"Failed to store chat fact: {e}",
                        extra={
                            "chat_id": window.chat_id,
                            "fact_category": fact.fact_category,
                            "fact_key": fact.fact_key,
                        },
                    )

            LOGGER.info(
                f"Successfully stored {len(chat_facts)} chat facts",
                extra={"chat_id": window.chat_id},
            )

        except Exception as e:
            LOGGER.error(
                f"Error storing chat facts: {e}",
                exc_info=True,
                extra={"chat_id": window.chat_id},
            )

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
