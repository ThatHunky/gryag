"""
Episode Summarizer for intelligent episode metadata generation.

Phase 4.2.1: Uses Gemini to generate rich episode summaries, topics,
emotional valence, and tags from conversation windows.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from app.config import Settings
from app.services.gemini import GeminiClient

LOGGER = logging.getLogger(__name__)


class EpisodeSummarizer:
    """Generate intelligent episode metadata using Gemini with rate limiting."""

    def __init__(
        self,
        settings: Settings,
        gemini_client: GeminiClient,
    ):
        self.settings = settings
        self.gemini = gemini_client

        # Rate limiting: track timestamps of recent API calls
        self.rate_limit = getattr(settings, "episode_summarization_rate_limit", 1)
        self._rate_limit_window = 60.0  # 1 minute window
        self._recent_calls: deque[float] = deque()
        self._rate_limit_lock = asyncio.Lock()

    async def _check_rate_limit(self) -> bool:
        """
        Check if we can make a Gemini API call based on rate limit.

        Returns:
            True if call is allowed, False if rate limited
        """
        async with self._rate_limit_lock:
            now = time.time()
            # Remove calls outside the window
            while (
                self._recent_calls
                and (now - self._recent_calls[0]) > self._rate_limit_window
            ):
                self._recent_calls.popleft()

            # Check if we're at the limit
            if len(self._recent_calls) >= self.rate_limit:
                return False

            # Record this call
            self._recent_calls.append(now)
            return True

    async def _wait_for_rate_limit(self) -> None:
        """Wait until rate limit allows another call."""
        async with self._rate_limit_lock:
            if not self._recent_calls:
                return

            now = time.time()
            # Remove old calls
            while (
                self._recent_calls
                and (now - self._recent_calls[0]) > self._rate_limit_window
            ):
                self._recent_calls.popleft()

            # If still at limit, wait for oldest call to expire
            if len(self._recent_calls) >= self.rate_limit:
                oldest_call = self._recent_calls[0]
                wait_time = (
                    self._rate_limit_window - (now - oldest_call) + 0.1
                )  # Small buffer
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

    async def summarize_episode(
        self,
        messages: list[dict[str, Any]],
        participants: set[int],
    ) -> dict[str, Any]:
        """
        Generate comprehensive episode metadata from messages.

        Args:
            messages: List of message dicts with id, user_id, text, timestamp
            participants: Set of unique participant user IDs

        Returns:
            Dictionary with:
                - topic: Short topic title (max 100 chars)
                - summary: Concise summary (2-3 sentences)
                - emotional_valence: One of: positive, negative, neutral, mixed
                - tags: List of relevant tags/keywords
                - key_points: List of main discussion points
        """
        if not messages:
            return self._empty_summary()

        # Check if Gemini summarization is enabled
        if not getattr(self.settings, "enable_episode_gemini_summarization", False):
            # Use heuristics immediately (no API calls)
            return self._fallback_summary(messages, participants)

        # Check rate limit before making API call
        if not await self._check_rate_limit():
            LOGGER.debug(
                "Episode summarization rate limited, using fallback heuristics",
                extra={
                    "messages": len(messages),
                    "rate_limit": self.rate_limit,
                },
            )
            return self._fallback_summary(messages, participants)

        # Build conversation context for Gemini
        conversation_text = self._format_messages_for_analysis(messages)

        # Generate summary using Gemini
        prompt = self._build_summary_prompt(
            conversation_text=conversation_text,
            message_count=len(messages),
            participant_count=len(participants),
        )

        try:
            response_data = await self.gemini.generate(
                system_prompt=self._get_system_instruction(),
                history=[],
                user_parts=[{"text": prompt}],
            )

            response = self._extract_text(response_data)
            # Parse Gemini response
            summary_data = self._parse_summary_response(response)

            LOGGER.info(
                "Episode summary generated",
                extra={
                    "messages": len(messages),
                    "participants": len(participants),
                    "topic": summary_data.get("topic", "")[:50],
                    "valence": summary_data.get("emotional_valence"),
                    "tags": len(summary_data.get("tags", [])),
                },
            )

            return summary_data

        except Exception as e:
            LOGGER.error(
                "Failed to generate episode summary with Gemini",
                exc_info=e,
                extra={
                    "messages": len(messages),
                    "participants": len(participants),
                },
            )
            # Fallback to simple heuristic
            return self._fallback_summary(messages, participants)

    def _format_messages_for_analysis(self, messages: list[dict[str, Any]]) -> str:
        """Format messages into readable conversation text."""
        lines = []
        for msg in messages:
            user_id = msg.get("user_id", "unknown")
            text = msg.get("text", "").strip()
            if text:
                lines.append(f"User {user_id}: {text}")

        return "\n".join(lines)

    def _build_summary_prompt(
        self,
        conversation_text: str,
        message_count: int,
        participant_count: int,
    ) -> str:
        """Build prompt for Gemini to generate episode summary."""
        return f"""Analyze this conversation and provide a structured summary.

CONVERSATION ({message_count} messages, {participant_count} participants):
{conversation_text}

Provide your analysis in this exact format:

TOPIC: [A short, descriptive topic title (max 100 characters)]

SUMMARY: [A concise 2-3 sentence summary of the conversation]

EMOTIONAL_VALENCE: [One of: positive, negative, neutral, mixed]

TAGS: [Comma-separated relevant keywords or themes, max 5]

KEY_POINTS:
- [First main point discussed]
- [Second main point discussed]
- [Third main point discussed, if applicable]

Guidelines:
- Topic should be clear and informative
- Summary should capture the essence without unnecessary detail
- Emotional valence should reflect overall conversation mood
- Tags should be single words or short phrases
- Key points should be the most important discussion items
"""

    def _get_system_instruction(self) -> str:
        """Get system instruction for episode summarization."""
        return """You are an expert conversation analyst specializing in extracting meaningful insights from chat discussions.

Your task is to analyze conversations and provide structured summaries that help users quickly understand what was discussed, the main points, and the overall tone.

Be concise, accurate, and objective. Focus on the content and themes rather than individual message details."""

    @staticmethod
    def _extract_text(response_data: Any) -> str:
        """Normalize Gemini response payloads to plain text."""
        if isinstance(response_data, dict):
            text = response_data.get("text")
            if isinstance(text, str):
                return text
            # Some callers may still populate the top-level key
            if isinstance(response_data.get("content"), str):
                return str(response_data["content"])
        elif isinstance(response_data, str):
            return response_data
        return ""

    def _parse_summary_response(self, response: str) -> dict[str, Any]:
        """Parse Gemini's structured response into summary dict."""
        result = {
            "topic": "",
            "summary": "",
            "emotional_valence": "neutral",
            "tags": [],
            "key_points": [],
        }

        # Parse response sections
        current_section = None
        lines = response.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect section headers
            if line.startswith("TOPIC:"):
                result["topic"] = line[6:].strip()[:100]  # Max 100 chars
                current_section = None
            elif line.startswith("SUMMARY:"):
                result["summary"] = line[8:].strip()
                current_section = None
            elif line.startswith("EMOTIONAL_VALENCE:"):
                valence = line[18:].strip().lower()
                if valence in ["positive", "negative", "neutral", "mixed"]:
                    result["emotional_valence"] = valence
                current_section = None
            elif line.startswith("TAGS:"):
                tags_text = line[5:].strip()
                # Split by comma and clean up
                tags = [tag.strip() for tag in tags_text.split(",") if tag.strip()]
                result["tags"] = tags[:5]  # Max 5 tags
                current_section = None
            elif line.startswith("KEY_POINTS:"):
                current_section = "key_points"
            elif line.startswith("-") and current_section == "key_points":
                point = line[1:].strip()
                if point:
                    result["key_points"].append(point)

        # Validation
        if not result["topic"]:
            result["topic"] = "Conversation"
        if not result["summary"]:
            result["summary"] = "No summary available"

        return result

    def _empty_summary(self) -> dict[str, Any]:
        """Return empty summary when no messages."""
        return {
            "topic": "Empty conversation",
            "summary": "No messages in this episode",
            "emotional_valence": "neutral",
            "tags": [],
            "key_points": [],
        }

    def _fallback_summary(
        self,
        messages: list[dict[str, Any]],
        participants: set[int],
    ) -> dict[str, Any]:
        """Fallback to simple heuristic summary when Gemini fails."""
        # Extract topic from first message
        topic = "Conversation"
        if messages:
            first_text = messages[0].get("text", "")
            if first_text:
                topic = first_text[:50]
                if len(first_text) > 50:
                    topic += "..."

        # Simple summary template
        summary = (
            f"Conversation with {len(participants)} participant(s) "
            f"over {len(messages)} message(s)"
        )

        # Extract simple tags from message text
        tags = []
        all_text = " ".join(msg.get("text", "") for msg in messages)
        words = all_text.lower().split()
        # Get common meaningful words (simple heuristic)
        word_freq = {}
        for word in words:
            if len(word) > 3:  # Skip short words
                word_freq[word] = word_freq.get(word, 0) + 1

        # Top 3 most common words as tags
        if word_freq:
            sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
            tags = [word for word, _ in sorted_words[:3]]

        return {
            "topic": topic,
            "summary": summary,
            "emotional_valence": "neutral",
            "tags": tags,
            "key_points": [],
        }

    async def generate_topic_only(self, messages: list[dict[str, Any]]) -> str:
        """
        Generate just a topic title (fast version).

        Useful when you need just a quick topic without full analysis.
        """
        if not messages:
            return "Empty conversation"

        # Check if Gemini summarization is enabled
        if not getattr(self.settings, "enable_episode_gemini_summarization", False):
            # Use heuristic fallback
            first_text = messages[0].get("text", "Conversation")
            return first_text[:50] + ("..." if len(first_text) > 50 else "")

        # Check rate limit
        if not await self._check_rate_limit():
            # Fallback to first message
            first_text = messages[0].get("text", "Conversation")
            return first_text[:50] + ("..." if len(first_text) > 50 else "")

        conversation_text = self._format_messages_for_analysis(
            messages[:5]  # Use first 5 messages for topic
        )

        prompt = f"""Analyze this conversation snippet and provide ONLY a short topic title (max 100 characters).

CONVERSATION:
{conversation_text}

Respond with ONLY the topic title, nothing else."""

        try:
            response_data = await self.gemini.generate(
                system_prompt="You are a conversation topic analyzer. Provide only the topic title requested.",
                history=[],
                user_parts=[{"text": prompt}],
            )

            response = self._extract_text(response_data)
            topic = response.strip()[:100]
            if not topic:
                topic = messages[0].get("text", "Conversation")[:50]

            return topic

        except Exception as e:
            LOGGER.error("Failed to generate topic with Gemini", exc_info=e)
            # Fallback to first message
            return messages[0].get("text", "Conversation")[:50]

    async def detect_emotional_valence(self, messages: list[dict[str, Any]]) -> str:
        """
        Detect emotional valence of conversation (fast version).

        Returns: One of 'positive', 'negative', 'neutral', 'mixed'
        """
        if not messages:
            return "neutral"

        conversation_text = self._format_messages_for_analysis(messages)

        prompt = f"""Analyze the emotional tone of this conversation.

CONVERSATION:
{conversation_text}

Respond with ONLY ONE WORD from these options:
- positive (happy, excited, supportive)
- negative (angry, sad, frustrated)
- neutral (informational, factual)
- mixed (combination of emotions)

Respond with only the single word, nothing else."""

        try:
            response_data = await self.gemini.generate(
                system_prompt="You are an emotion analyzer. Respond with only one word: positive, negative, neutral, or mixed.",
                history=[],
                user_parts=[{"text": prompt}],
            )

            response = self._extract_text(response_data)
            valence = response.strip().lower()
            if valence not in ["positive", "negative", "neutral", "mixed"]:
                valence = "neutral"

            return valence

        except Exception as e:
            LOGGER.error("Failed to detect emotional valence", exc_info=e)
            return "neutral"
