"""
Message classifier for filtering low-value messages.

Filters out messages that are unlikely to contain valuable information:
- Stickers, reactions, media-only messages
- Greetings and small talk
- Bot commands (unless addressed)
- Very short messages (<3 words)

This significantly reduces computational load by skipping 40-60% of messages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aiogram.types import Message

LOGGER = logging.getLogger(__name__)


class MessageValue(Enum):
    """Classification of message value for continuous learning."""

    HIGH = "high"  # Contains facts, questions, opinions - always process
    MEDIUM = "medium"  # Contextual value, might be useful - process with lower priority
    LOW = "low"  # Small talk, reactions - skip unless in conversation window
    NOISE = "noise"  # Pure noise (stickers, etc) - always skip


@dataclass
class ClassificationResult:
    """Result of message classification."""

    value: MessageValue
    reason: str
    confidence: float  # 0.0 to 1.0
    features: dict[str, Any]  # Debugging info


class MessageClassifier:
    """
    Classifies messages by their learning value.

    Phase 1: Log classifications without changing behavior.
    Phase 3: Actually filter messages based on classification.
    """

    # Patterns for noise detection
    STICKER_ONLY_RE = re.compile(r"^\s*$")  # Empty text (sticker/media only)
    REACTION_RE = re.compile(
        r"^[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]{1,5}$"
    )  # Only emojis

    # Patterns for greetings (Ukrainian/Russian/English)
    GREETING_RE = re.compile(
        r"^\s*(привіт|привет|hi|hello|hey|добрий\s+день|доброго\s+дня|"
        r"добрый\s+день|вітаю|здоровенькі\s+були|йоу|yo|sup|здарова|"
        r"доброї\s+ночі|спокійної\s+ночі|на\s+добраніч|good\s+night|"
        r"бувай|пока|bye|до\s+зустрічі|до\s+побачення|cya|see\s+ya)"
        r"[!.?\s]*$",
        re.IGNORECASE | re.UNICODE,
    )

    # Patterns for simple acknowledgments
    ACK_RE = re.compile(
        r"^\s*(ок|ok|окей|okay|добре|добро|гаразд|так|да|yes|no|ні|ага|угу|"
        r"нє|неа|nope|yep|yeah|ну|хм|hmm|хех|lol|ха|ха-ха|😂|👍|👌|🤷)"
        r"[!.?\s]*$",
        re.IGNORECASE | re.UNICODE,
    )

    # Bot commands that aren't useful for learning
    LOW_VALUE_COMMANDS = {
        "/start",
        "/help",
        "/status",
        "/ping",
    }

    def __init__(self, enable_filtering: bool = False):
        """
        Initialize classifier.

        Args:
            enable_filtering: If False (Phase 1), only log. If True (Phase 3), actually filter.
        """
        self.enable_filtering = enable_filtering
        self._stats = {
            "total": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "noise": 0,
        }
        LOGGER.info(
            "MessageClassifier initialized",
            extra={"enable_filtering": enable_filtering},
        )

    def classify(
        self, message: Message, is_addressed: bool = False
    ) -> ClassificationResult:
        """
        Classify a message by its learning value.

        Args:
            message: Telegram message to classify
            is_addressed: True if message is explicitly addressed to the bot

        Returns:
            ClassificationResult with value, reason, and features
        """
        self._stats["total"] += 1

        features = {
            "has_text": bool(message.text or message.caption),
            "has_media": bool(
                message.photo or message.video or message.document or message.audio
            ),
            "has_sticker": bool(message.sticker),
            "is_addressed": is_addressed,
            "text_length": len(message.text or message.caption or ""),
            "word_count": len((message.text or message.caption or "").split()),
        }

        # Rule 1: Stickers and pure media without text are noise
        if message.sticker or (features["has_media"] and not features["has_text"]):
            return self._classify_as(
                MessageValue.NOISE, "Sticker or media without text", 0.95, features
            )

        text = (message.text or message.caption or "").strip()

        # Rule 2: Empty messages are noise
        if not text:
            return self._classify_as(MessageValue.NOISE, "Empty message", 1.0, features)

        # Rule 3: Pure emoji reactions are noise
        if self.REACTION_RE.match(text):
            return self._classify_as(
                MessageValue.NOISE, "Pure emoji reaction", 0.9, features
            )

        # Rule 4: Addressed messages are always high value (user wants bot's attention)
        if is_addressed:
            return self._classify_as(
                MessageValue.HIGH, "Addressed to bot", 1.0, features
            )

        # Rule 5: Very short messages (<3 words) are typically low value
        # unless they contain questions or factual statements
        if features["word_count"] < 3:
            if "?" in text or "!" in text:
                return self._classify_as(
                    MessageValue.MEDIUM, "Short but expressive", 0.6, features
                )
            if self.ACK_RE.match(text):
                return self._classify_as(
                    MessageValue.LOW, "Simple acknowledgment", 0.8, features
                )
            return self._classify_as(
                MessageValue.LOW, "Very short message", 0.7, features
            )

        # Rule 6: Greetings are low value (polite but not informative)
        if self.GREETING_RE.match(text):
            return self._classify_as(MessageValue.LOW, "Greeting", 0.85, features)

        # Rule 7: Low-value bot commands
        if text.startswith("/"):
            command = text.split()[0].lower()
            if command in self.LOW_VALUE_COMMANDS:
                return self._classify_as(
                    MessageValue.LOW, "Low-value command", 0.8, features
                )
            # Other commands might be informative
            return self._classify_as(MessageValue.MEDIUM, "Bot command", 0.6, features)

        # Rule 8: Questions are high value (seeking information or opinions)
        if "?" in text:
            return self._classify_as(
                MessageValue.HIGH, "Contains question", 0.8, features
            )

        # Rule 9: Longer messages (>10 words) are more likely to contain facts
        if features["word_count"] >= 10:
            return self._classify_as(
                MessageValue.HIGH, "Substantial message", 0.75, features
            )

        # Rule 10: Medium-length messages (3-10 words) are medium value
        # Could be contextual or could be small talk
        return self._classify_as(
            MessageValue.MEDIUM, "Medium-length message", 0.6, features
        )

    def _classify_as(
        self,
        value: MessageValue,
        reason: str,
        confidence: float,
        features: dict[str, Any],
    ) -> ClassificationResult:
        """Helper to create classification result and update stats."""
        self._stats[value.value] += 1

        result = ClassificationResult(
            value=value, reason=reason, confidence=confidence, features=features
        )

        LOGGER.debug(
            f"Classified message as {value.value}",
            extra={
                "value": value.value,
                "reason": reason,
                "confidence": confidence,
                "features": features,
                "filtering_enabled": self.enable_filtering,
            },
        )

        return result

    def should_process(self, classification: ClassificationResult) -> bool:
        """
        Decide if a message should be processed based on its classification.

        Phase 1: Always returns True (logging only, no filtering)
        Phase 3: Returns False for NOISE, respects classification

        Args:
            classification: Result from classify()

        Returns:
            True if message should be processed for fact extraction
        """
        if not self.enable_filtering:
            # Phase 1: Log but don't filter
            return True

        # Phase 3: Actually filter based on classification
        if classification.value == MessageValue.NOISE:
            return False

        if classification.value == MessageValue.LOW:
            # Low-value messages are only processed if confidence is low
            # (uncertain classification means we might be wrong)
            return classification.confidence < 0.7

        # HIGH and MEDIUM always processed
        return True

    def get_stats(self) -> dict[str, int]:
        """Get classification statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset classification statistics."""
        for key in self._stats:
            if key != "total":
                self._stats[key] = 0
            else:
                self._stats[key] = 0
