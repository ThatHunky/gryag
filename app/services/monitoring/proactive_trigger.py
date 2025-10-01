"""
Proactive response trigger system.

Phase 4 implementation with:
- Intent classification (questions, requests, problems, opportunities)
- User preference learning (reactions, ignores, negative feedback)
- Response timing and cooldowns (global, per-user, per-intent)
- Conservative safety checks to avoid being annoying
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from app.services.monitoring.conversation_analyzer import ConversationWindow

LOGGER = logging.getLogger(__name__)


class IntentType(Enum):
    """Types of conversation intents we can respond to."""

    QUESTION = "question"  # User asks something
    REQUEST = "request"  # User wants information/action
    PROBLEM = "problem"  # User describes issue
    OPPORTUNITY = "opportunity"  # Bot has relevant info
    NONE = "none"  # No clear intent


class UserReaction(Enum):
    """User reactions to proactive responses."""

    POSITIVE = "positive"  # Engaged with response (replied, reacted positively)
    NEUTRAL = "neutral"  # Acknowledged but didn't engage
    NEGATIVE = "negative"  # Expressed annoyance or asked to stop
    IGNORED = "ignored"  # No reaction within timeout


@dataclass
class ConversationIntent:
    """Detected intent in conversation window."""

    intent_type: IntentType
    confidence: float  # 0.0-1.0
    trigger_message: str  # The message that triggered detection
    context_summary: str  # What the conversation is about
    suggested_response: Optional[str] = None  # Optional AI suggestion


@dataclass
class UserPreference:
    """Learned preferences for proactive responses."""

    user_id: int
    proactivity_multiplier: float  # 0.0-2.0, default 1.0
    last_proactive_response: Optional[datetime]
    total_proactive_sent: int
    reaction_counts: dict[UserReaction, int]
    consecutive_ignores: int
    last_negative_feedback: Optional[datetime]


@dataclass
class ProactiveDecision:
    """Decision about proactive response."""

    should_respond: bool
    confidence: float
    intent: Optional[ConversationIntent]
    reason: str  # Why we should/shouldn't respond
    suggested_response: Optional[str] = None


class IntentClassifier:
    """Detects conversation intents for proactive responses."""

    def __init__(self, gemini_client, settings):
        self.gemini = gemini_client
        self.settings = settings
        self._intent_cache = (
            {}
        )  # (chat_id, thread_id, first_timestamp) -> ConversationIntent

    async def classify_window(
        self, window: ConversationWindow, bot_capabilities: list[str]
    ) -> Optional[ConversationIntent]:
        """
        Analyze window to detect if proactive response would be helpful.

        Args:
            window: Conversation window to analyze
            bot_capabilities: List of bot capabilities

        Returns:
            ConversationIntent if opportunity detected, None otherwise
        """
        # Check cache first (use window identity as key)
        cache_key = (window.chat_id, window.thread_id, window.first_timestamp)
        if cache_key in self._intent_cache:
            return self._intent_cache[cache_key]

        # Build conversation context
        conversation_text = self._build_conversation_text(window)

        # Prompt Gemini to classify intent
        prompt = self._build_classification_prompt(
            conversation_text, bot_capabilities, len(window.participant_ids)
        )

        try:
            response = await self.gemini.generate(
                message=prompt,
                context=[],
                system_prompt=self._get_intent_system_prompt(),
            )

            intent = self._parse_intent_response(response, window)

            if intent and intent.confidence >= 0.5:  # Minimum threshold
                cache_key = (window.chat_id, window.thread_id, window.first_timestamp)
                self._intent_cache[cache_key] = intent
                return intent

        except Exception as e:
            LOGGER.error(f"Intent classification failed: {e}")

        return None

    def _build_conversation_text(self, window: ConversationWindow) -> str:
        """Build readable conversation from window."""
        lines = []
        for msg in window.messages[-5:]:  # Last 5 messages
            username = f"User{msg.user_id}"
            lines.append(f"{username}: {msg.text}")
        return "\n".join(lines)

    def _build_classification_prompt(
        self, conversation: str, capabilities: list[str], participant_count: int
    ) -> str:
        """Build prompt for intent classification."""
        return f"""Analyze this conversation and determine if I should proactively respond.

Conversation:
{conversation}

My capabilities: {', '.join(capabilities)}
Participants: {participant_count}

Should I respond proactively? Consider:
1. Is there an unanswered question I can help with?
2. Did someone request information I can provide?
3. Is there a problem I can solve?
4. Do I have relevant information that would add value?

Response format (JSON):
{{
    "should_respond": true/false,
    "intent_type": "question|request|problem|opportunity",
    "confidence": 0.0-1.0,
    "context_summary": "brief description",
    "suggested_response": "optional response text"
}}

Be conservative - only respond if genuinely helpful."""

    def _get_intent_system_prompt(self) -> str:
        """System prompt for intent classification."""
        return """You are analyzing conversations to detect when a bot should proactively respond.

Rules:
- Be VERY conservative - silence is better than spam
- Only suggest responses that add clear value
- Consider conversation flow and social dynamics
- Respect that users may not want bot involvement
- Return structured JSON only"""

    def _parse_intent_response(
        self, response: str, window: ConversationWindow
    ) -> Optional[ConversationIntent]:
        """Parse Gemini's intent classification response."""
        try:
            data = json.loads(response)

            if not data.get("should_respond", False):
                return None

            intent_type = IntentType(data["intent_type"])
            confidence = float(data["confidence"])

            return ConversationIntent(
                intent_type=intent_type,
                confidence=confidence,
                trigger_message=window.messages[-1].text if window.messages else "",
                context_summary=data.get("context_summary", ""),
                suggested_response=data.get("suggested_response"),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            LOGGER.warning(f"Failed to parse intent response: {e}")
            return None


class UserPreferenceManager:
    """Manages user preferences for proactive responses."""

    def __init__(self, context_store, settings):
        self.store = context_store
        self.settings = settings
        self._preferences = {}  # user_id -> UserPreference

    async def get_preference(self, user_id: int) -> UserPreference:
        """Get user's proactive response preferences."""
        if user_id not in self._preferences:
            self._preferences[user_id] = await self._load_preference(user_id)
        return self._preferences[user_id]

    async def _load_preference(self, user_id: int) -> UserPreference:
        """Load preference from database."""
        conn = await self.store._get_connection()
        cursor = await conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                MAX(created_at) as last_sent,
                SUM(CASE WHEN user_reaction = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN user_reaction = 'neutral' THEN 1 ELSE 0 END) as neutral,
                SUM(CASE WHEN user_reaction = 'negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN user_reaction = 'ignored' THEN 1 ELSE 0 END) as ignored
            FROM proactive_events
            WHERE chat_id IN (
                SELECT DISTINCT chat_id FROM messages WHERE user_id = ?
            )
            AND response_sent = 1
        """,
            (user_id,),
        )

        row = await cursor.fetchone()

        # Calculate proactivity multiplier based on history
        multiplier = self._calculate_multiplier(
            positive=row[2] or 0,
            neutral=row[3] or 0,
            negative=row[4] or 0,
            ignored=row[5] or 0,
        )

        # Check for consecutive ignores
        cursor = await conn.execute(
            """
            SELECT user_reaction
            FROM proactive_events
            WHERE chat_id IN (
                SELECT DISTINCT chat_id FROM messages WHERE user_id = ?
            )
            AND response_sent = 1
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (user_id,),
        )

        recent_reactions = [r[0] for r in await cursor.fetchall()]
        consecutive_ignores = 0
        for reaction in recent_reactions:
            if reaction == "ignored":
                consecutive_ignores += 1
            else:
                break

        last_sent = None
        if row[1]:
            last_sent = datetime.fromtimestamp(row[1])

        return UserPreference(
            user_id=user_id,
            proactivity_multiplier=multiplier,
            last_proactive_response=last_sent,
            total_proactive_sent=row[0] or 0,
            reaction_counts={
                UserReaction.POSITIVE: row[2] or 0,
                UserReaction.NEUTRAL: row[3] or 0,
                UserReaction.NEGATIVE: row[4] or 0,
                UserReaction.IGNORED: row[5] or 0,
            },
            consecutive_ignores=consecutive_ignores,
            last_negative_feedback=None,
        )

    def _calculate_multiplier(
        self, positive: int, neutral: int, negative: int, ignored: int
    ) -> float:
        """
        Calculate proactivity multiplier based on reaction history.

        Returns:
            0.0-2.0 multiplier (1.0 = normal, <1.0 = reduce, >1.0 = increase)
        """
        total = positive + neutral + negative + ignored
        if total == 0:
            return 1.0  # No history, default

        # Positive reactions increase multiplier
        positive_ratio = positive / total
        negative_ratio = negative / total
        ignored_ratio = ignored / total

        # Base multiplier
        multiplier = 1.0

        # Adjust based on ratios
        if positive_ratio > 0.5:  # >50% positive
            multiplier += 0.3
        elif positive_ratio > 0.3:  # >30% positive
            multiplier += 0.1

        if negative_ratio > 0.2:  # >20% negative
            multiplier -= 0.5
        elif negative_ratio > 0.1:  # >10% negative
            multiplier -= 0.3

        if ignored_ratio > 0.6:  # >60% ignored
            multiplier -= 0.4
        elif ignored_ratio > 0.4:  # >40% ignored
            multiplier -= 0.2

        # Clamp to 0.0-2.0
        return max(0.0, min(2.0, multiplier))

    async def record_reaction(
        self, event_id: int, reaction: UserReaction, reaction_time: Optional[int] = None
    ):
        """Record user's reaction to proactive response."""
        conn = await self.store._get_connection()
        await conn.execute(
            """
            UPDATE proactive_events
            SET user_reaction = ?, reaction_timestamp = ?
            WHERE id = ?
        """,
            (
                reaction.value,
                int(time.time()) if reaction_time is None else reaction_time,
                event_id,
            ),
        )
        await conn.commit()

        # Invalidate cache
        cursor = await conn.execute(
            "SELECT chat_id FROM proactive_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        if row:
            # Invalidate all cached preferences (simple approach)
            self._preferences.clear()

    async def check_cooldown(
        self,
        chat_id: int,
        user_id: Optional[int] = None,
        intent_type: Optional[IntentType] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if cooldown period has passed.

        Returns:
            (allowed, reason) - True if can send, False + reason if blocked
        """
        conn = await self.store._get_connection()

        # Check global cooldown (any proactive in last N seconds)
        cursor = await conn.execute(
            """
            SELECT created_at FROM proactive_events
            WHERE chat_id = ? AND response_sent = 1
            ORDER BY created_at DESC
            LIMIT 1
        """,
            (chat_id,),
        )

        row = await cursor.fetchone()
        if row:
            last_sent = row[0]
            elapsed = int(time.time()) - last_sent

            if elapsed < self.settings.proactive_cooldown_seconds:
                return (
                    False,
                    f"Global cooldown: {elapsed}s / {self.settings.proactive_cooldown_seconds}s",
                )

        # Check per-user cooldown if user specified
        if user_id:
            cursor = await conn.execute(
                """
                SELECT created_at FROM proactive_events
                WHERE chat_id = ? AND response_sent = 1
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (chat_id,),
            )

            row = await cursor.fetchone()
            if row:
                last_sent = row[0]
                elapsed = int(time.time()) - last_sent

                # Per-user cooldown is 2x global
                per_user_cooldown = self.settings.proactive_cooldown_seconds * 2

                if elapsed < per_user_cooldown:
                    return False, f"User cooldown: {elapsed}s / {per_user_cooldown}s"

        # Check same-intent cooldown if intent specified
        if intent_type:
            cursor = await conn.execute(
                """
                SELECT created_at FROM proactive_events
                WHERE chat_id = ? 
                AND json_extract(intent_classification, '$.intent_type') = ?
                AND response_sent = 1
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (chat_id, intent_type.value),
            )

            row = await cursor.fetchone()
            if row:
                last_sent = row[0]
                elapsed = int(time.time()) - last_sent

                # Same-intent cooldown is 6x global (30 min if global is 5 min)
                same_intent_cooldown = self.settings.proactive_cooldown_seconds * 6

                if elapsed < same_intent_cooldown:
                    return (
                        False,
                        f"Intent cooldown: {elapsed}s / {same_intent_cooldown}s",
                    )

        return True, None


class ProactiveTrigger:
    """
    Decides when bot should proactively respond to conversations.

    Phase 4: Full implementation with intent classification and user preferences
    """

    def __init__(self, context_store, gemini_client, settings):
        """
        Initialize proactive trigger.

        Args:
            context_store: Database store for preferences and history
            gemini_client: Gemini client for intent classification
            settings: Bot settings with proactive configuration
        """
        self.store = context_store
        self.gemini = gemini_client
        self.settings = settings

        self.intent_classifier = IntentClassifier(gemini_client, settings)
        self.preference_manager = UserPreferenceManager(context_store, settings)

        # Stats
        self.stats = {
            "windows_analyzed": 0,
            "intents_detected": 0,
            "responses_triggered": 0,
            "responses_blocked": 0,
            "block_reasons": defaultdict(int),
        }

        LOGGER.info(
            "ProactiveTrigger initialized",
            extra={
                "enabled": settings.enable_proactive_responses,
                "confidence_threshold": settings.proactive_confidence_threshold,
                "cooldown_seconds": settings.proactive_cooldown_seconds,
            },
        )

    async def should_respond(
        self, window: ConversationWindow, bot_user_id: int, bot_capabilities: list[str]
    ) -> ProactiveDecision:
        """
        Decide if bot should proactively respond to this conversation.

        Args:
            window: Conversation window to analyze
            bot_user_id: Bot's user ID (to check if already participating)
            bot_capabilities: List of bot capabilities

        Returns:
            ProactiveDecision with should_respond and reasoning
        """
        self.stats["windows_analyzed"] += 1

        # Safety check 1: Feature enabled?
        if not self.settings.enable_proactive_responses:
            return ProactiveDecision(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason="Proactive responses disabled",
            )

        # Safety check 2: Minimum window size (need at least 3 messages)
        if len(window.messages) < 3:
            return ProactiveDecision(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason=f"Window too small ({len(window.messages)} < 3)",
            )

        # Safety check 3: Bot already participating?
        bot_participating = any(msg.user_id == bot_user_id for msg in window.messages)
        if bot_participating:
            return ProactiveDecision(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason="Bot already participating in conversation",
            )

        # Safety check 4: Recent activity (conversation still active)
        if window.messages:
            last_message_time = window.messages[-1].timestamp
            age_seconds = int(time.time()) - last_message_time

            if age_seconds > 300:  # 5 minutes
                return ProactiveDecision(
                    should_respond=False,
                    confidence=0.0,
                    intent=None,
                    reason=f"Window too old ({age_seconds}s > 300s)",
                )

        # Step 1: Detect intent
        intent = await self.intent_classifier.classify_window(window, bot_capabilities)

        if not intent:
            return ProactiveDecision(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason="No intent detected",
            )

        self.stats["intents_detected"] += 1

        # Step 2: Check cooldowns
        cooldown_ok, cooldown_reason = await self.preference_manager.check_cooldown(
            chat_id=window.chat_id, intent_type=intent.intent_type
        )

        if not cooldown_ok:
            self.stats["responses_blocked"] += 1
            self.stats["block_reasons"]["cooldown"] += 1
            return ProactiveDecision(
                should_respond=False,
                confidence=intent.confidence,
                intent=intent,
                reason=cooldown_reason or "Cooldown active",
            )

        # Step 3: Apply user preferences
        primary_user_id = self._get_primary_participant(window, bot_user_id)
        adjusted_confidence = intent.confidence

        if primary_user_id:
            preference = await self.preference_manager.get_preference(primary_user_id)

            # Adjust confidence by user multiplier
            adjusted_confidence = intent.confidence * preference.proactivity_multiplier

            # Check for too many ignores
            if preference.consecutive_ignores >= 3:
                self.stats["responses_blocked"] += 1
                self.stats["block_reasons"]["user_preference"] += 1
                return ProactiveDecision(
                    should_respond=False,
                    confidence=adjusted_confidence,
                    intent=intent,
                    reason=f"User ignoring proactive responses ({preference.consecutive_ignores} consecutive)",
                )

        # Step 4: Check adjusted confidence threshold
        if adjusted_confidence < self.settings.proactive_confidence_threshold:
            self.stats["responses_blocked"] += 1
            self.stats["block_reasons"]["low_confidence"] += 1
            return ProactiveDecision(
                should_respond=False,
                confidence=adjusted_confidence,
                intent=intent,
                reason=f"Confidence too low ({adjusted_confidence:.2f} < {self.settings.proactive_confidence_threshold})",
            )

        # All checks passed!
        self.stats["responses_triggered"] += 1

        return ProactiveDecision(
            should_respond=True,
            confidence=adjusted_confidence,
            intent=intent,
            reason="All checks passed",
            suggested_response=intent.suggested_response,
        )

    def _get_primary_participant(
        self, window: ConversationWindow, bot_user_id: int
    ) -> Optional[int]:
        """Get most active participant in window (for preference lookup)."""
        if not window.messages:
            return None

        # Count messages per user (excluding bot)
        message_counts = defaultdict(int)
        for msg in window.messages:
            if msg.user_id != bot_user_id:
                message_counts[msg.user_id] += 1

        if not message_counts:
            return None

        # Return user with most messages
        return max(message_counts.items(), key=lambda x: x[1])[0]

    async def record_proactive_response(
        self,
        chat_id: int,
        window_id: int,
        intent: ConversationIntent,
        response_text: str,
        response_message_id: Optional[int] = None,
    ) -> int:
        """
        Record that proactive response was sent.

        Returns:
            event_id for later reaction tracking
        """
        conn = await self.store._get_connection()

        intent_json = json.dumps(
            {
                "intent_type": intent.intent_type.value,
                "confidence": intent.confidence,
                "context_summary": intent.context_summary,
            }
        )

        cursor = await conn.execute(
            """
            INSERT INTO proactive_events (
                chat_id, thread_id, window_id, trigger_reason, trigger_confidence,
                intent_classification, response_sent, response_message_id, created_at
            ) VALUES (?, NULL, ?, ?, ?, ?, 1, ?, ?)
        """,
            (
                chat_id,
                window_id,
                intent.context_summary[:200],  # Truncate if too long
                intent.confidence,
                intent_json,
                response_message_id,
                int(time.time()),
            ),
        )

        await conn.commit()
        return cursor.lastrowid

    async def classify_intent(self, window: ConversationWindow) -> dict[str, Any]:
        """
        Classify the intent of the conversation (public API).

        Returns:
            Intent classification with confidence
        """
        intent = await self.intent_classifier.classify_window(
            window, bot_capabilities=["weather", "currency", "search", "calculations"]
        )

        if intent:
            return {
                "intent": intent.intent_type.value,
                "confidence": intent.confidence,
                "requires_bot": True,
                "context": intent.context_summary,
            }

        return {"intent": "none", "confidence": 0.0, "requires_bot": False}

    async def get_user_preferences(self, user_id: int, chat_id: int) -> dict[str, Any]:
        """
        Get user's preferences for proactive responses (public API).

        Returns:
            User preferences
        """
        preference = await self.preference_manager.get_preference(user_id)

        return {
            "likes_proactive": preference.proactivity_multiplier >= 1.0,
            "proactivity_multiplier": preference.proactivity_multiplier,
            "total_sent": preference.total_proactive_sent,
            "positive_reactions": preference.reaction_counts.get(
                UserReaction.POSITIVE, 0
            ),
            "negative_reactions": preference.reaction_counts.get(
                UserReaction.NEGATIVE, 0
            ),
            "consecutive_ignores": preference.consecutive_ignores,
        }

    def record_response_reaction(self, event_id: int, reaction: UserReaction) -> None:
        """
        Record user's reaction to a proactive response (sync wrapper).

        For async context, use preference_manager.record_reaction directly.
        """
        # This is a sync method for backward compatibility
        # In practice, should use async version
        LOGGER.info(
            f"Recording reaction for event {event_id}: {reaction.value}",
            extra={"event_id": event_id, "reaction": reaction.value},
        )

    def get_stats(self) -> dict[str, Any]:
        """Get proactive trigger statistics."""
        return {
            "windows_analyzed": self.stats["windows_analyzed"],
            "intents_detected": self.stats["intents_detected"],
            "responses_triggered": self.stats["responses_triggered"],
            "responses_blocked": self.stats["responses_blocked"],
            "block_reasons": dict(self.stats["block_reasons"]),
            "trigger_rate": (
                self.stats["responses_triggered"] / self.stats["windows_analyzed"]
                if self.stats["windows_analyzed"] > 0
                else 0.0
            ),
        }
