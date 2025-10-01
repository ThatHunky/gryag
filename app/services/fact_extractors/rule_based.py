"""Rule-based fact extraction using regex patterns."""

from __future__ import annotations

import logging
from typing import Any

from .base import FactExtractor
from .patterns import english, ukrainian

logger = logging.getLogger(__name__)


class RuleBasedFactExtractor(FactExtractor):
    """Extract facts using predefined regex patterns."""

    def __init__(self):
        """Initialize pattern matchers."""
        # Compile all patterns
        self.uk_location = ukrainian.compile_patterns(ukrainian.LOCATION_PATTERNS)
        self.uk_like = ukrainian.compile_patterns(ukrainian.LIKE_PATTERNS)
        self.uk_dislike = ukrainian.compile_patterns(ukrainian.DISLIKE_PATTERNS)
        self.uk_language = ukrainian.compile_patterns(ukrainian.LANGUAGE_PATTERNS)
        self.uk_profession = ukrainian.compile_patterns(ukrainian.PROFESSION_PATTERNS)
        self.uk_prog_lang = ukrainian.compile_patterns(ukrainian.PROG_LANG_PATTERNS)

        self.en_location = english.compile_patterns(english.LOCATION_PATTERNS)
        self.en_like = english.compile_patterns(english.LIKE_PATTERNS)
        self.en_dislike = english.compile_patterns(english.DISLIKE_PATTERNS)
        self.en_language = english.compile_patterns(english.LANGUAGE_PATTERNS)
        self.en_profession = english.compile_patterns(english.PROFESSION_PATTERNS)
        self.en_prog_lang = english.compile_patterns(english.PROG_LANG_PATTERNS)
        self.en_age = english.compile_patterns(english.AGE_PATTERNS)

    async def extract_facts(
        self,
        message: str,
        user_id: int,
        username: str | None = None,
        context: list[dict[str, Any]] | None = None,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Extract facts using regex patterns.

        Args:
            message: User's message text
            user_id: Telegram user ID
            username: User's username
            context: Recent conversation history (not used in rule-based)
            min_confidence: Minimum confidence threshold

        Returns:
            List of fact dicts
        """
        facts = []
        msg_lower = message.lower()

        # Extract location
        location = self._extract_location(message, msg_lower)
        if location:
            facts.append(location)

        # Extract preferences (likes)
        likes = self._extract_likes(message, msg_lower)
        facts.extend(likes)

        # Extract preferences (dislikes)
        dislikes = self._extract_dislikes(message, msg_lower)
        facts.extend(dislikes)

        # Extract languages
        languages = self._extract_languages(message, msg_lower)
        facts.extend(languages)

        # Extract profession
        profession = self._extract_profession(message, msg_lower)
        if profession:
            facts.append(profession)

        # Extract programming languages
        prog_langs = self._extract_prog_languages(message, msg_lower)
        facts.extend(prog_langs)

        # Extract age (English only)
        age = self._extract_age(message)
        if age:
            facts.append(age)

        # Filter by confidence threshold
        facts = [f for f in facts if f["confidence"] >= min_confidence]

        logger.info(
            f"Rule-based extraction found {len(facts)} facts from message",
            extra={"user_id": user_id, "fact_count": len(facts)},
        )

        return facts

    def _extract_location(self, message: str, msg_lower: str) -> dict[str, Any] | None:
        """Extract location information."""
        # Try Ukrainian patterns
        for pattern in self.uk_location:
            match = pattern.search(message)
            if match:
                location = match.group(1).strip()
                # Check if it's a known Ukrainian city
                if location.lower() in ukrainian.UKRAINIAN_CITIES:
                    return {
                        "fact_type": "personal",
                        "fact_key": "location",
                        "fact_value": location,
                        "confidence": 0.95,
                        "evidence_text": match.group(0),
                    }
                # Generic location match
                return {
                    "fact_type": "personal",
                    "fact_key": "location",
                    "fact_value": location,
                    "confidence": 0.85,
                    "evidence_text": match.group(0),
                }

        # Try English patterns
        for pattern in self.en_location:
            match = pattern.search(message)
            if match:
                location = match.group(1).strip()
                return {
                    "fact_type": "personal",
                    "fact_key": "location",
                    "fact_value": location,
                    "confidence": 0.9,
                    "evidence_text": match.group(0),
                }

        return None

    def _extract_likes(self, message: str, msg_lower: str) -> list[dict[str, Any]]:
        """Extract things the user likes."""
        likes = []

        # Ukrainian patterns
        for pattern in self.uk_like:
            match = pattern.search(message)
            if match:
                thing = match.group(1).strip()
                if len(thing) > 2 and len(thing) < 100:  # Sanity check
                    likes.append(
                        {
                            "fact_type": "preference",
                            "fact_key": "likes",
                            "fact_value": thing,
                            "confidence": 0.9,
                            "evidence_text": match.group(0),
                        }
                    )

        # English patterns
        for pattern in self.en_like:
            match = pattern.search(message)
            if match:
                thing = match.group(1).strip()
                if len(thing) > 2 and len(thing) < 100:
                    likes.append(
                        {
                            "fact_type": "preference",
                            "fact_key": "likes",
                            "fact_value": thing,
                            "confidence": 0.9,
                            "evidence_text": match.group(0),
                        }
                    )

        return likes

    def _extract_dislikes(self, message: str, msg_lower: str) -> list[dict[str, Any]]:
        """Extract things the user dislikes."""
        dislikes = []

        # Ukrainian patterns
        for pattern in self.uk_dislike:
            match = pattern.search(message)
            if match:
                thing = match.group(1).strip()
                if len(thing) > 2 and len(thing) < 100:
                    dislikes.append(
                        {
                            "fact_type": "preference",
                            "fact_key": "dislikes",
                            "fact_value": thing,
                            "confidence": 0.9,
                            "evidence_text": match.group(0),
                        }
                    )

        # English patterns
        for pattern in self.en_dislike:
            match = pattern.search(message)
            if match:
                thing = match.group(1).strip()
                if len(thing) > 2 and len(thing) < 100:
                    dislikes.append(
                        {
                            "fact_type": "preference",
                            "fact_key": "dislikes",
                            "fact_value": thing,
                            "confidence": 0.9,
                            "evidence_text": match.group(0),
                        }
                    )

        return dislikes

    def _extract_languages(self, message: str, msg_lower: str) -> list[dict[str, Any]]:
        """Extract spoken languages."""
        languages = []

        # Ukrainian patterns
        for pattern in self.uk_language:
            match = pattern.search(message)
            if match:
                lang_text = match.group(1).strip().lower()
                # Check against known languages
                for lang in ukrainian.SPOKEN_LANGUAGES:
                    if lang in lang_text:
                        languages.append(
                            {
                                "fact_type": "skill",
                                "fact_key": "language",
                                "fact_value": lang,
                                "confidence": 0.95,
                                "evidence_text": match.group(0),
                            }
                        )
                        break

        # English patterns
        for pattern in self.en_language:
            match = pattern.search(message)
            if match:
                lang_text = match.group(1).strip().lower()
                for lang in english.SPOKEN_LANGUAGES:
                    if lang in lang_text:
                        languages.append(
                            {
                                "fact_type": "skill",
                                "fact_key": "language",
                                "fact_value": lang,
                                "confidence": 0.95,
                                "evidence_text": match.group(0),
                            }
                        )
                        break

        return languages

    def _extract_profession(
        self, message: str, msg_lower: str
    ) -> dict[str, Any] | None:
        """Extract profession/occupation."""
        # Ukrainian patterns
        for pattern in self.uk_profession:
            match = pattern.search(message)
            if match:
                profession = match.group(1).strip()
                if len(profession) > 2 and len(profession) < 50:
                    return {
                        "fact_type": "personal",
                        "fact_key": "profession",
                        "fact_value": profession,
                        "confidence": 0.85,
                        "evidence_text": match.group(0),
                    }

        # English patterns
        for pattern in self.en_profession:
            match = pattern.search(message)
            if match:
                profession = match.group(1).strip()
                if len(profession) > 2 and len(profession) < 50:
                    return {
                        "fact_type": "personal",
                        "fact_key": "profession",
                        "fact_value": profession,
                        "confidence": 0.85,
                        "evidence_text": match.group(0),
                    }

        return None

    def _extract_prog_languages(
        self, message: str, msg_lower: str
    ) -> list[dict[str, Any]]:
        """Extract programming languages."""
        prog_langs = []

        # Ukrainian patterns
        for pattern in self.uk_prog_lang:
            match = pattern.search(message)
            if match:
                lang_text = match.group(1).strip().lower()
                # Check against known programming languages
                for lang in ukrainian.PROGRAMMING_LANGUAGES:
                    if lang in lang_text:
                        prog_langs.append(
                            {
                                "fact_type": "skill",
                                "fact_key": "programming_language",
                                "fact_value": lang,
                                "confidence": 0.95,
                                "evidence_text": match.group(0),
                            }
                        )
                        break

        # English patterns
        for pattern in self.en_prog_lang:
            match = pattern.search(message)
            if match:
                lang_text = match.group(1).strip().lower()
                for lang in english.PROGRAMMING_LANGUAGES:
                    if lang in lang_text:
                        prog_langs.append(
                            {
                                "fact_type": "skill",
                                "fact_key": "programming_language",
                                "fact_value": lang,
                                "confidence": 0.95,
                                "evidence_text": match.group(0),
                            }
                        )
                        break

        return prog_langs

    def _extract_age(self, message: str) -> dict[str, Any] | None:
        """Extract age (English only)."""
        for pattern in self.en_age:
            match = pattern.search(message)
            if match:
                age = match.group(1)
                age_int = int(age)
                # Sanity check: reasonable age range
                if 10 <= age_int <= 100:
                    return {
                        "fact_type": "personal",
                        "fact_key": "age",
                        "fact_value": age,
                        "confidence": 1.0,
                        "evidence_text": match.group(0),
                    }

        return None
