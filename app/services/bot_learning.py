"""Bot self-learning engine - extracts learning from interactions.

Analyzes user reactions, feedback patterns, and conversation outcomes
to automatically generate bot facts and insights.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.services.bot_profile import BotProfileStore

LOGGER = logging.getLogger(__name__)


# Patterns for detecting user feedback
POSITIVE_PATTERNS = [
    r"\b(thanks?|thank you|thx|дяка|дякую)\b",
    r"\b(good|great|awesome|perfect|excellent|helpful|корисно)\b",
    r"\b(exactly|саме так|правильно|точно)\b",
    r"👍|❤️|🙏|💯|✅",
]

NEGATIVE_PATTERNS = [
    r"\b(wrong|incorrect|error|неправильно|помилка)\b",
    r"\b(confus|незрозуміло|не розумію)\b",
    r"\b(bad|terrible|awful|погано|жахливо)\b",
    r"👎|😡|😤|❌",
]

CORRECTION_PATTERNS = [
    r"\b(actually|насправді|to be honest|власне)\b",
    r"\b(no[,!]|ні[,!]|not|не так)\b",
    r"\b(you'?re wrong|ти не правий|помиляєшся)\b",
    r"\b(that'?s not|це не так|неправда)\b",
]

PRAISE_PATTERNS = [
    r"\b(brilliant|genius|розумний|молодець)\b",
    r"\b(love it|люблю|супер|класно)\b",
    r"🔥|⭐|🌟|💪",
]


class BotLearningEngine:
    """Extracts self-learning from user interactions."""

    def __init__(
        self,
        bot_profile: BotProfileStore,
        gemini_client: Any | None = None,
        enable_gemini_insights: bool = True,
    ):
        self.bot_profile = bot_profile
        self._gemini = gemini_client
        self._enable_gemini_insights = enable_gemini_insights

    def detect_user_sentiment(self, text: str) -> tuple[str, float]:
        """
        Detect sentiment from user message.

        Returns (sentiment_label, confidence_score).
        """
        text_lower = text.lower()

        # Check for explicit patterns
        has_praise = any(re.search(p, text, re.IGNORECASE) for p in PRAISE_PATTERNS)
        has_positive = any(re.search(p, text, re.IGNORECASE) for p in POSITIVE_PATTERNS)
        has_negative = any(re.search(p, text, re.IGNORECASE) for p in NEGATIVE_PATTERNS)
        has_correction = any(
            re.search(p, text, re.IGNORECASE) for p in CORRECTION_PATTERNS
        )

        if has_praise:
            return ("praised", 0.9)
        elif has_correction:
            return ("corrected", 0.8)
        elif has_negative:
            return ("negative", 0.7)
        elif has_positive:
            return ("positive", 0.7)
        else:
            return ("neutral", 0.5)

    def calculate_sentiment_score(self, sentiment: str) -> float:
        """Map sentiment to numeric score (-1.0 to 1.0)."""
        sentiment_scores = {
            "praised": 1.0,
            "positive": 0.7,
            "neutral": 0.0,
            "negative": -0.7,
            "corrected": -0.5,
            "ignored": -0.3,
        }
        return sentiment_scores.get(sentiment, 0.0)

    async def learn_from_user_reaction(
        self,
        user_message: str,
        bot_previous_response: str | None,
        chat_id: int,
        reaction_delay_seconds: int | None = None,
        context_tags: list[str] | None = None,
    ) -> None:
        """
        Analyze user message as reaction to bot's previous response.

        Extracts patterns about what works/doesn't work.
        """
        sentiment, confidence = self.detect_user_sentiment(user_message)
        sentiment_score = self.calculate_sentiment_score(sentiment)

        # Learn communication style patterns
        if sentiment in ("praised", "positive") and bot_previous_response:
            # Extract what worked
            response_length = len(bot_previous_response)
            response_type = self._classify_response_type(bot_previous_response)

            await self.bot_profile.add_fact(
                category="communication_style",
                key=f"effective_{response_type}_response",
                value=f"Response type '{response_type}' received {sentiment} feedback",
                confidence=confidence * 0.8,  # Slightly conservative
                source_type="reaction_analysis",
                chat_id=chat_id,
                context_tags=context_tags or [],
            )

            # Learn about response length preferences
            length_category = (
                "short"
                if response_length < 100
                else "medium" if response_length < 300 else "long"
            )
            await self.bot_profile.add_fact(
                category="communication_style",
                key=f"preferred_length",
                value=length_category,
                confidence=confidence * 0.6,
                source_type="reaction_analysis",
                chat_id=chat_id,
                context_tags=context_tags or [],
            )

        elif sentiment == "corrected" and bot_previous_response:
            # Learn from corrections
            await self.bot_profile.add_fact(
                category="mistake_pattern",
                key="requires_correction",
                value=f"User corrected response: {bot_previous_response[:100]}...",
                confidence=confidence,
                source_type="user_feedback",
                chat_id=chat_id,
                context_tags=context_tags or [],
                decay_rate=0.1,  # Mistakes should fade over time
            )

            # Extract topic/domain if possible
            topic = self._extract_topic(user_message)
            if topic:
                await self.bot_profile.add_fact(
                    category="knowledge_domain",
                    key=f"knowledge_gap_{topic}",
                    value=f"Struggled with topic: {topic}",
                    confidence=0.7,
                    source_type="error_pattern",
                    chat_id=chat_id,
                    context_tags=context_tags or [],
                )

        # Learn temporal patterns
        if reaction_delay_seconds is not None:
            delay_category = (
                "immediate"
                if reaction_delay_seconds < 10
                else (
                    "quick"
                    if reaction_delay_seconds < 60
                    else "delayed" if reaction_delay_seconds < 300 else "slow"
                )
            )

            if sentiment in ("praised", "positive") and delay_category in (
                "immediate",
                "quick",
            ):
                await self.bot_profile.add_fact(
                    category="temporal_pattern",
                    key="quick_engagement_indicator",
                    value=f"{delay_category} positive reaction",
                    confidence=0.6,
                    source_type="reaction_analysis",
                    chat_id=chat_id,
                    context_tags=context_tags or [],
                )

    async def learn_from_tool_usage(
        self,
        tool_name: str,
        tool_result: str | None,
        user_reaction: str | None,
        chat_id: int,
        success: bool = True,
        context_tags: list[str] | None = None,
    ) -> None:
        """Learn patterns about tool effectiveness."""
        if success and user_reaction:
            sentiment, confidence = self.detect_user_sentiment(user_reaction)

            if sentiment in ("praised", "positive"):
                await self.bot_profile.add_fact(
                    category="tool_effectiveness",
                    key=f"tool_{tool_name}_success",
                    value=f"Tool {tool_name} received {sentiment} feedback",
                    confidence=confidence * 0.8,
                    source_type="success_metric",
                    chat_id=chat_id,
                    context_tags=context_tags or [],
                )
            elif sentiment in ("negative", "corrected"):
                await self.bot_profile.add_fact(
                    category="tool_effectiveness",
                    key=f"tool_{tool_name}_failure",
                    value=f"Tool {tool_name} received {sentiment} feedback",
                    confidence=confidence * 0.7,
                    source_type="error_pattern",
                    chat_id=chat_id,
                    context_tags=context_tags or [],
                    decay_rate=0.05,
                )

    async def learn_from_episode(
        self,
        episode_id: int,
        episode_summary: str,
        importance: float,
        emotional_valence: str,
        chat_id: int,
    ) -> None:
        """
        Learn from completed conversation episodes.

        This integrates with episodic memory to extract higher-level patterns.
        """
        # Learn about conversation types
        if importance >= 0.8:
            await self.bot_profile.add_fact(
                category="user_interaction",
                key="high_value_episode_pattern",
                value=f"Participated in {emotional_valence} high-importance episode",
                confidence=importance,
                source_type="episode_learning",
                chat_id=chat_id,
                context_tags=[emotional_valence, "high_importance"],
            )

        # Learn emotional patterns
        if emotional_valence in ("positive", "mixed"):
            await self.bot_profile.add_fact(
                category="user_interaction",
                key=f"{emotional_valence}_conversation_success",
                value=f"Successfully navigated {emotional_valence} conversation",
                confidence=0.7,
                source_type="episode_learning",
                chat_id=chat_id,
                context_tags=[emotional_valence],
            )

    async def learn_from_performance_metrics(
        self,
        response_time_ms: int,
        token_count: int,
        outcome: str,
        chat_id: int,
        context_tags: list[str] | None = None,
    ) -> None:
        """Learn from performance metrics (response time, token usage)."""
        # Record metrics
        await self.bot_profile.record_performance_metric(
            metric_type="response_time",
            metric_value=float(response_time_ms),
            chat_id=chat_id,
            context_tags=context_tags,
        )

        await self.bot_profile.record_performance_metric(
            metric_type="token_usage",
            metric_value=float(token_count),
            chat_id=chat_id,
            context_tags=context_tags,
        )

        # Learn patterns if extreme values
        if response_time_ms < 1000 and outcome in ("praised", "positive"):
            await self.bot_profile.add_fact(
                category="performance_metric",
                key="fast_response_success",
                value="Fast responses (<1s) correlate with positive feedback",
                confidence=0.6,
                source_type="success_metric",
                chat_id=chat_id,
                context_tags=context_tags or [],
            )

        if response_time_ms > 10000 and outcome in ("negative", "ignored"):
            await self.bot_profile.add_fact(
                category="performance_metric",
                key="slow_response_problem",
                value="Slow responses (>10s) correlate with negative outcomes",
                confidence=0.7,
                source_type="error_pattern",
                chat_id=chat_id,
                context_tags=context_tags or [],
                decay_rate=0.05,  # Should improve over time
            )

    async def generate_gemini_insights(
        self, chat_id: int | None = None, days: int = 7
    ) -> list[dict[str, Any]]:
        """
        Use Gemini to generate high-level insights from accumulated data.

        This is the "self-reflection" capability.
        """
        if not self._gemini or not self._enable_gemini_insights:
            LOGGER.info("Gemini insights disabled or no client available")
            return []

        # Get effectiveness summary
        summary = await self.bot_profile.get_effectiveness_summary(
            chat_id=chat_id, days=days
        )

        # Get recent facts
        facts = await self.bot_profile.get_facts(
            chat_id=chat_id, min_confidence=0.6, limit=30
        )

        # Build context for Gemini
        facts_text = "\n".join(
            f"- [{f['fact_category']}] {f['fact_key']}: {f['fact_value']} "
            f"(confidence: {f['confidence']:.2f}, evidence: {f['evidence_count']})"
            for f in facts
        )

        prompt = f"""Analyze your own performance and learning patterns as a bot.

## Your Statistics (last {days} days)
- Total interactions: {summary['total_interactions']}
- Positive: {summary['positive_interactions']}
- Negative: {summary['negative_interactions']}
- Effectiveness score: {summary['effectiveness_score']:.2%}
- Recent effectiveness: {summary['recent_effectiveness']:.2%}
- Avg response time: {summary['avg_response_time_ms']:.0f}ms
- Avg sentiment: {summary['avg_sentiment']:.2f}

## Facts You've Learned About Yourself
{facts_text}

## Task
Generate 3-5 actionable insights about:
1. What communication patterns work best
2. Knowledge gaps or areas of struggle
3. Temporal patterns (time of day, response speed)
4. Tool usage effectiveness
5. Opportunities for improvement

Return JSON:
{{
  "insights": [
    {{
      "type": "effectiveness_trend|communication_pattern|knowledge_gap|temporal_insight|improvement_suggestion",
      "text": "Brief insight description",
      "confidence": 0.0-1.0,
      "actionable": true|false,
      "supporting_facts": ["fact_key1", "fact_key2"]
    }}
  ]
}}
"""

        try:
            response = await self._gemini.generate(
                system_prompt="You are analyzing your own bot performance data. Be honest and objective.",
                history=[],
                user_parts=[{"text": prompt}],
            )

            # Parse JSON response (generate() returns string directly)
            response_text = response.strip()
            # Extract JSON from markdown code blocks if present
            if "```json" in response_text:
                json_match = re.search(
                    r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL
                )
                if json_match:
                    response_text = json_match.group(1)
            elif "```" in response_text:
                json_match = re.search(
                    r"```\s*(\{.*?\})\s*```", response_text, re.DOTALL
                )
                if json_match:
                    response_text = json_match.group(1)

            data = json.loads(response_text)
            insights_data = data.get("insights", [])

            # Store insights
            stored_insights = []
            for insight in insights_data:
                insight_id = await self.bot_profile.add_insight(
                    insight_type=insight.get("type", "improvement_suggestion"),
                    insight_text=insight["text"],
                    supporting_data={
                        "supporting_facts": insight.get("supporting_facts", []),
                        "summary": summary,
                    },
                    confidence=insight.get("confidence", 0.5),
                    actionable=insight.get("actionable", False),
                    chat_id=chat_id,
                )
                stored_insights.append({"id": insight_id, **insight})

            LOGGER.info(f"Generated {len(stored_insights)} Gemini insights")
            return stored_insights

        except Exception as e:
            LOGGER.error(f"Failed to generate Gemini insights: {e}", exc_info=True)
            return []

    def _classify_response_type(self, response: str) -> str:
        """Classify response into categories."""
        response_lower = response.lower()

        if any(word in response_lower for word in ["?", "clarify", "уточни"]):
            return "clarification"
        elif any(
            word in response_lower for word in ["search", "weather", "calculator"]
        ):
            return "tool_usage"
        elif len(response) < 50:
            return "brief"
        elif len(response) > 500:
            return "detailed"
        else:
            return "conversational"

    def _extract_topic(self, text: str) -> str | None:
        """Extract topic/domain from text (simplified)."""
        text_lower = text.lower()

        topic_keywords = {
            "weather": ["weather", "temperature", "погода", "температура"],
            "currency": ["currency", "exchange", "валюта", "курс"],
            "calculation": ["calculate", "math", "порахуй", "математика"],
            "search": ["search", "find", "пошук", "знайди"],
            "programming": ["code", "program", "код", "програма"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return topic

        return None

    def get_context_tags(
        self, hour_of_day: int | None = None, is_weekend: bool | None = None
    ) -> list[str]:
        """Generate context tags for fact storage."""
        tags = []

        if hour_of_day is not None:
            if 6 <= hour_of_day < 12:
                tags.append("morning")
            elif 12 <= hour_of_day < 18:
                tags.append("afternoon")
            elif 18 <= hour_of_day < 22:
                tags.append("evening")
            else:
                tags.append("night")

        if is_weekend is not None:
            tags.append("weekend" if is_weekend else "weekday")

        return tags
