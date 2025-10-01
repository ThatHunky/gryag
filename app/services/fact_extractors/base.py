"""Base interface for fact extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FactExtractor(ABC):
    """Abstract base class for fact extraction implementations."""

    @abstractmethod
    async def extract_facts(
        self,
        message: str,
        user_id: int,
        username: str | None = None,
        context: list[dict[str, Any]] | None = None,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Extract facts from a user message.

        Args:
            message: User's message text
            user_id: Telegram user ID
            username: User's username
            context: Recent conversation history
            min_confidence: Minimum confidence threshold (0.0-1.0)

        Returns:
            List of fact dicts with structure:
            {
                'fact_type': 'personal|preference|trait|skill|opinion',
                'fact_key': 'standardized_key',
                'fact_value': 'the fact content',
                'confidence': 0.7-1.0,
                'evidence_text': 'supporting quote'
            }
        """
        pass
