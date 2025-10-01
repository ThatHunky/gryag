"""
Proactive response trigger system.

Phase 4 implementation - currently a stub.

Will handle:
- Intent classification (questions, debates, factual discussions)
- User preference learning (who likes proactive responses)
- Response timing and cooldowns
- Natural engagement without being annoying
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.monitoring.conversation_analyzer import ConversationWindow

LOGGER = logging.getLogger(__name__)


class ProactiveTrigger:
    """
    Decides when bot should proactively respond to conversations.

    Phase 1: Stub implementation
    Phase 4: Full implementation with intent classification and user preferences
    """

    def __init__(
        self,
        confidence_threshold: float = 0.75,
        cooldown_seconds: int = 300,  # 5 minutes
    ):
        """
        Initialize proactive trigger.

        Args:
            confidence_threshold: Minimum confidence to trigger response
            cooldown_seconds: Minimum seconds between proactive responses
        """
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds

        # Track last proactive response time per chat
        self._last_response: dict[int, float] = {}

        LOGGER.info(
            "ProactiveTrigger initialized (stub)",
            extra={
                "confidence_threshold": confidence_threshold,
                "cooldown_seconds": cooldown_seconds,
            },
        )

    async def should_respond(
        self, window: ConversationWindow, bot_user_id: int
    ) -> tuple[bool, str, float]:
        """
        Decide if bot should proactively respond to this conversation.

        Phase 1: Always returns False (disabled)
        Phase 4: Intelligent decision based on intent and user preferences

        Args:
            window: Conversation window to analyze
            bot_user_id: Bot's user ID (to check if already participating)

        Returns:
            (should_respond, reason, confidence)
        """
        # Phase 1: Disabled
        return False, "Proactive responses disabled in Phase 1", 0.0

    async def classify_intent(self, window: ConversationWindow) -> dict[str, Any]:
        """
        Classify the intent of the conversation.

        Phase 4 implementation.

        Returns:
            Intent classification with confidence
        """
        # Stub
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "requires_bot": False,
        }

    async def get_user_preferences(self, user_id: int, chat_id: int) -> dict[str, Any]:
        """
        Get user's preferences for proactive responses.

        Phase 4 implementation.

        Returns:
            User preferences
        """
        # Stub
        return {
            "likes_proactive": True,
            "ignore_topics": [],
            "positive_reactions": 0,
            "negative_reactions": 0,
        }

    def record_response_reaction(
        self, user_id: int, chat_id: int, positive: bool
    ) -> None:
        """
        Record user's reaction to a proactive response.

        Phase 4 implementation.
        """
        # Stub
        pass
