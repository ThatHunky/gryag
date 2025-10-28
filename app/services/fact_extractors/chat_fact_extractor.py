"""Chat fact extractor.

Extracts group-level facts from conversations using pattern matching,
statistical analysis, and LLM-based extraction.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from aiogram.types import Message

from app.repositories.chat_profile import ChatFact

LOGGER = logging.getLogger(__name__)


class ChatFactExtractor:
    """Extracts chat-level facts from group conversations."""

    def __init__(
        self,
        gemini_client: Any = None,
        enable_patterns: bool = True,
        enable_statistical: bool = True,
        enable_llm: bool = True,
        min_confidence: float = 0.6,
    ):
        """Initialize chat fact extractor.

        Args:
            gemini_client: Optional Gemini client for LLM extraction
            enable_patterns: Enable pattern-based extraction
            enable_statistical: Enable statistical extraction
            enable_llm: Enable LLM-based extraction
            min_confidence: Minimum confidence threshold
        """
        self.gemini_client = gemini_client
        self.enable_patterns = enable_patterns
        self.enable_statistical = enable_statistical
        self.enable_llm = enable_llm
        self.min_confidence = min_confidence

    async def extract_chat_facts(
        self,
        messages: List[Message],
        chat_id: int,
    ) -> List[ChatFact]:
        """Extract facts about the chat/group from conversation.

        Signals for chat-level facts:
        1. Plural pronouns: "we", "us", "our"
        2. Group decisions: "let's", "we should"
        3. Traditions: "always", "every [time period]"
        4. Norms: "usually", "typically", "here we"
        5. Statistical patterns: emoji usage, message length, formality

        Args:
            messages: List of messages to analyze
            chat_id: Chat ID

        Returns:
            List of ChatFact objects
        """
        all_facts: List[ChatFact] = []

        # Method 1: Pattern-based extraction (fast, 70% coverage)
        if self.enable_patterns:
            try:
                pattern_facts = await self._extract_via_patterns(messages, chat_id)
                all_facts.extend(pattern_facts)
                LOGGER.debug(
                    f"Pattern extraction: {len(pattern_facts)} facts",
                    extra={"chat_id": chat_id},
                )
            except Exception as e:
                LOGGER.error(f"Pattern extraction failed: {e}", exc_info=True)

        # Method 2: Statistical analysis (group behavior)
        if self.enable_statistical:
            try:
                statistical_facts = await self._extract_statistical_facts(
                    messages, chat_id
                )
                all_facts.extend(statistical_facts)
                LOGGER.debug(
                    f"Statistical extraction: {len(statistical_facts)} facts",
                    extra={"chat_id": chat_id},
                )
            except Exception as e:
                LOGGER.error(f"Statistical extraction failed: {e}", exc_info=True)

        # Method 3: LLM-based (for complex cases)
        if self.enable_llm and self.gemini_client:
            try:
                llm_facts = await self._extract_via_llm(messages, chat_id)
                all_facts.extend(llm_facts)
                LOGGER.debug(
                    f"LLM extraction: {len(llm_facts)} facts",
                    extra={"chat_id": chat_id},
                )
            except Exception as e:
                LOGGER.error(f"LLM extraction failed: {e}", exc_info=True)

        # Deduplicate and filter
        deduplicated_facts = await self._deduplicate_chat_facts(all_facts, chat_id)

        LOGGER.info(
            f"Extracted {len(deduplicated_facts)} chat facts (from {len(all_facts)} candidates)",
            extra={"chat_id": chat_id},
        )

        return deduplicated_facts

    async def _extract_via_patterns(
        self, messages: List[Message], chat_id: int
    ) -> List[ChatFact]:
        """Pattern-based extraction for common chat facts."""
        facts = []

        for msg in messages:
            if not msg.text:
                continue

            text = msg.text.lower()

            # Preference patterns
            if re.search(
                r"\b(we|us|our|ми|нас|наш)\b.*(like|love|prefer|enjoy|подобається|любимо)",
                text,
            ):
                preference = self._extract_preference(text)
                if preference:
                    facts.append(
                        ChatFact(
                            fact_id=None,
                            chat_id=chat_id,
                            fact_category="preference",
                            fact_key=preference["key"],
                            fact_value=preference["value"],
                            fact_description=preference["description"],
                            confidence=0.75,
                            evidence_text=msg.text[:200],
                        )
                    )

            # Tradition patterns
            if re.search(
                r"\b(every|always|щоразу|завжди)\b.*(week|month|friday|monday|тиждень|місяць|п'ятниц|понеділ)",
                text,
            ):
                tradition = self._extract_tradition(text)
                if tradition:
                    facts.append(
                        ChatFact(
                            fact_id=None,
                            chat_id=chat_id,
                            fact_category="tradition",
                            fact_key="recurring_event",
                            fact_value=tradition["value"],
                            fact_description=tradition["description"],
                            confidence=0.8,
                            evidence_text=msg.text[:200],
                        )
                    )

            # Rule patterns
            if re.search(
                r"\b(no|don't|don't|forbidden|rule|заборонено|правило|не можна)\b", text
            ):
                rule = self._extract_rule(text)
                if rule:
                    facts.append(
                        ChatFact(
                            fact_id=None,
                            chat_id=chat_id,
                            fact_category="rule",
                            fact_key="chat_rule",
                            fact_value=rule["value"],
                            fact_description=rule["description"],
                            confidence=0.85,
                            evidence_text=msg.text[:200],
                        )
                    )

            # Shared knowledge patterns
            if re.search(
                r"\b(we (discussed|talked about|decided)|ми (обговорювали|говорили про|вирішили))\b",
                text,
            ):
                topic = self._extract_topic(text)
                if topic:
                    facts.append(
                        ChatFact(
                            fact_id=None,
                            chat_id=chat_id,
                            fact_category="shared_knowledge",
                            fact_key="past_discussion",
                            fact_value=topic,
                            fact_description=f"Discussed: {topic}",
                            confidence=0.7,
                            evidence_text=msg.text[:200],
                        )
                    )

        return facts

    def _extract_preference(self, text: str) -> Optional[Dict[str, str]]:
        """Extract preference from text."""
        # Simple keyword extraction
        if "humor" in text or "гумор" in text:
            return {
                "key": "humor_style",
                "value": "dark" if "dark" in text or "чорн" in text else "general",
                "description": "Group humor preference",
            }
        if "language" in text or "мова" in text:
            if "ukrainian" in text or "українськ" in text:
                return {
                    "key": "language_preference",
                    "value": "ukrainian",
                    "description": "Prefers Ukrainian language",
                }
        return None

    def _extract_tradition(self, text: str) -> Optional[Dict[str, str]]:
        """Extract tradition from text."""
        # Look for day patterns
        if "friday" in text or "п'ятниц" in text:
            return {
                "value": "friday_event",
                "description": "Friday tradition/event",
            }
        if "monday" in text or "понеділ" in text:
            return {
                "value": "monday_event",
                "description": "Monday tradition/event",
            }
        return None

    def _extract_rule(self, text: str) -> Optional[Dict[str, str]]:
        """Extract rule from text."""
        # Look for forbidden topics
        if "politic" in text or "політик" in text:
            return {
                "value": "no_politics",
                "description": "No politics rule",
            }
        if "spam" in text or "спам" in text:
            return {
                "value": "no_spam",
                "description": "No spam rule",
            }
        return None

    def _extract_topic(self, text: str) -> Optional[str]:
        """Extract discussed topic from text."""
        # Simple extraction - look for quoted text or keywords after verbs
        match = re.search(r"discussed?\s+[\"']([^\"']+)[\"']", text, re.IGNORECASE)
        if match:
            return match.group(1)

        match = re.search(r"talked about\s+(\w+)", text, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    async def _extract_statistical_facts(
        self, messages: List[Message], chat_id: int
    ) -> List[ChatFact]:
        """Extract facts from message patterns and statistics."""
        facts = []

        if not messages:
            return facts

        # Analyze emoji usage
        emoji_count = sum(
            len(re.findall(r"[\U0001F300-\U0001F9FF]", m.text or "")) for m in messages
        )

        if emoji_count / max(len(messages), 1) > 2:
            facts.append(
                ChatFact(
                    fact_id=None,
                    chat_id=chat_id,
                    fact_category="norm",
                    fact_key="emoji_usage",
                    fact_value="high",
                    fact_description="Chat uses many emoji reactions",
                    confidence=0.8,
                )
            )

        # Analyze message length
        text_messages = [m for m in messages if m.text]
        if text_messages:
            avg_length = sum(len(m.text) for m in text_messages) / len(text_messages)

            if avg_length > 200:
                facts.append(
                    ChatFact(
                        fact_id=None,
                        chat_id=chat_id,
                        fact_category="norm",
                        fact_key="message_style",
                        fact_value="detailed_messages",
                        fact_description="Chat prefers longer, detailed messages",
                        confidence=0.75,
                    )
                )
            elif avg_length < 50:
                facts.append(
                    ChatFact(
                        fact_id=None,
                        chat_id=chat_id,
                        fact_category="norm",
                        fact_key="message_style",
                        fact_value="short_messages",
                        fact_description="Chat prefers short, concise messages",
                        confidence=0.75,
                    )
                )

        # Analyze formality (simple heuristic)
        formal_count = sum(1 for m in text_messages if self._is_formal(m.text))

        if formal_count / max(len(text_messages), 1) > 0.7:
            facts.append(
                ChatFact(
                    fact_id=None,
                    chat_id=chat_id,
                    fact_category="culture",
                    fact_key="communication_style",
                    fact_value="formal",
                    fact_description="Chat maintains formal communication",
                    confidence=0.8,
                )
            )

        return facts

    def _is_formal(self, text: str) -> bool:
        """Simple heuristic for formal text."""
        if not text:
            return False

        # No exclamation marks, proper capitalization
        has_caps = text[0].isupper() if text else False
        few_exclamations = text.count("!") <= 1
        has_periods = "." in text

        return has_caps and few_exclamations and has_periods

    async def _extract_via_llm(
        self, messages: List[Message], chat_id: int
    ) -> List[ChatFact]:
        """LLM-based extraction for complex chat dynamics."""
        if not self.gemini_client:
            return []

        # Build conversation summary (last 10 messages)
        conversation_lines = []
        for msg in messages[-10:]:
            if msg.text and msg.from_user:
                user_name = msg.from_user.first_name or f"User{msg.from_user.id}"
                conversation_lines.append(f"{user_name}: {msg.text}")

        if not conversation_lines:
            return []

        conversation = "\n".join(conversation_lines)

        prompt = f"""Analyze this group chat conversation and identify GROUP-LEVEL facts.

Conversation:
{conversation}

Extract facts about the GROUP (not individuals), such as:
- Preferences: What does this group like/dislike?
- Traditions: Any recurring activities or patterns?
- Rules: Explicit or implicit group rules?
- Norms: How does the group communicate?
- Topics: What does the group discuss often?
- Culture: What's the group's vibe/personality?

Output JSON array of facts:
[
  {{
    "category": "preference|tradition|rule|norm|topic|culture",
    "fact_key": "short_key",
    "fact_value": "concise_value",
    "fact_description": "Human-readable description",
    "confidence": 0.6-1.0
  }}
]

Focus on GROUP facts only (e.g., "we prefer", "the chat likes", "everyone does").
Ignore individual facts (e.g., "John likes", "Alice said").
Only include facts with confidence >= 0.6.
Return empty array if no group-level facts detected.
"""

        try:
            response_data = await self.gemini_client.generate(
                system_prompt="You are an expert at analyzing group chat dynamics. Output valid JSON only.",
                history=[],
                user_parts=[{"text": prompt}],
            )

            response = response_data.get("text", "")
            if not response:
                return []

            # Parse JSON response
            import json

            # Try to extract JSON from response
            response = response.strip()
            if not response.startswith("["):
                # Try to find JSON array in response
                match = re.search(r"\[.*\]", response, re.DOTALL)
                if match:
                    response = match.group(0)
                else:
                    LOGGER.warning("No JSON array found in LLM response")
                    return []

            facts_data = json.loads(response)

            facts = []
            for f in facts_data:
                # Validate required fields
                if not all(k in f for k in ["category", "fact_key", "fact_value"]):
                    continue

                # Validate confidence
                confidence = f.get("confidence", 0.7)
                if confidence < self.min_confidence:
                    continue

                facts.append(
                    ChatFact(
                        fact_id=None,
                        chat_id=chat_id,
                        fact_category=f["category"],
                        fact_key=f["fact_key"],
                        fact_value=f["fact_value"],
                        fact_description=f.get("fact_description"),
                        confidence=confidence,
                        evidence_text=f.get("evidence"),
                    )
                )

            return facts

        except json.JSONDecodeError as e:
            LOGGER.error(f"Failed to parse LLM JSON response: {e}")
            LOGGER.debug(f"Response was: {response[:500]}")
            return []
        except Exception as e:
            LOGGER.error(f"LLM chat fact extraction failed: {e}", exc_info=True)
            return []

    async def _deduplicate_chat_facts(
        self, facts: List[ChatFact], chat_id: int
    ) -> List[ChatFact]:
        """Deduplicate chat facts by key and similarity.

        Args:
            facts: List of facts to deduplicate
            chat_id: Chat ID

        Returns:
            Deduplicated list of facts
        """
        if not facts:
            return []

        # Group by key
        by_key: Dict[str, List[ChatFact]] = {}
        for fact in facts:
            key = f"{fact.fact_category}:{fact.fact_key}"
            by_key.setdefault(key, []).append(fact)

        # For each key, keep highest confidence
        deduplicated = []
        for key, key_facts in by_key.items():
            # Sort by confidence
            key_facts.sort(key=lambda f: f.confidence, reverse=True)

            # Keep best fact, merge evidence
            best_fact = key_facts[0]

            # If multiple facts, boost confidence slightly
            if len(key_facts) > 1:
                best_fact.confidence = min(1.0, best_fact.confidence * 1.1)
                best_fact.evidence_count = len(key_facts)

            deduplicated.append(best_fact)

        return deduplicated
