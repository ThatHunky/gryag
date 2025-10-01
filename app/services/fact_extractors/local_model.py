"""Local model-based fact extraction using Phi-3-mini."""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import FactExtractor
from .model_manager import ModelManager

logger = logging.getLogger(__name__)

# Prompt template for fact extraction
FACT_EXTRACTION_PROMPT = """<|system|>
You are a fact extraction assistant. Your task is to extract factual information about a user from their message.

Extract facts in these categories:
- personal: location, age, name, profession
- preference: likes, dislikes, interests
- skill: languages (spoken), programming_language, expertise
- trait: personality traits, characteristics
- opinion: views, beliefs

Return ONLY a JSON array of facts, no other text.

Format:
[
  {
    "fact_type": "personal|preference|skill|trait|opinion",
    "fact_key": "standardized_key",
    "fact_value": "the fact content",
    "confidence": 0.7-1.0
  }
]

If no facts found, return: []
<|end|>
<|user|>
Message: "{message}"
<|end|>
<|assistant|>
"""


class LocalModelFactExtractor(FactExtractor):
    """Extract facts using a local LLM (Phi-3-mini)."""

    def __init__(self, model_manager: ModelManager):
        """
        Initialize local model extractor.

        Args:
            model_manager: ModelManager instance with loaded model
        """
        self.model_manager = model_manager

    @property
    def is_available(self) -> bool:
        """Check if model is available and initialized."""
        return self.model_manager.is_initialized

    async def extract_facts(
        self,
        message: str,
        user_id: int,
        username: str | None = None,
        context: list[dict[str, Any]] | None = None,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Extract facts using local model.

        Args:
            message: User's message text
            user_id: Telegram user ID
            username: User's username
            context: Recent conversation history
            min_confidence: Minimum confidence threshold

        Returns:
            List of fact dicts
        """
        if not self.is_available:
            logger.warning("Local model not available for fact extraction")
            return []

        # Truncate very long messages
        if len(message) > 500:
            message = message[:500] + "..."

        # Build prompt
        prompt = FACT_EXTRACTION_PROMPT.format(message=message)

        try:
            # Generate with low temperature for deterministic output
            response = await self.model_manager.generate(
                prompt=prompt,
                max_tokens=512,
                temperature=0.3,
                top_p=0.9,
                stop=["<|end|>", "<|user|>"],
            )

            if not response:
                logger.warning("Local model returned empty response")
                return []

            # Parse JSON response
            facts = self._parse_response(response, min_confidence)

            # Add evidence text (original message snippet)
            for fact in facts:
                if "evidence_text" not in fact:
                    fact["evidence_text"] = message[:100]

            logger.info(
                f"Local model extracted {len(facts)} facts",
                extra={"user_id": user_id, "fact_count": len(facts)},
            )

            return facts

        except Exception as e:
            logger.error(
                f"Local model extraction failed: {e}",
                extra={"user_id": user_id, "error": str(e)},
                exc_info=True,
            )
            return []

    def _parse_response(
        self, response: str, min_confidence: float
    ) -> list[dict[str, Any]]:
        """
        Parse model JSON response.

        Args:
            response: Raw model output
            min_confidence: Minimum confidence threshold

        Returns:
            List of fact dicts
        """
        try:
            # Try to extract JSON array from response
            # Sometimes models wrap JSON in markdown or extra text
            response = response.strip()

            # Remove markdown code blocks if present
            if response.startswith("```"):
                # Find the actual JSON content
                lines = response.split("\n")
                json_lines = []
                in_code = False
                for line in lines:
                    if line.startswith("```"):
                        in_code = not in_code
                        continue
                    if in_code or (not line.startswith("```")):
                        json_lines.append(line)
                response = "\n".join(json_lines).strip()

            # Try to find JSON array
            start = response.find("[")
            end = response.rfind("]") + 1
            if start != -1 and end > start:
                response = response[start:end]

            facts = json.loads(response)

            if not isinstance(facts, list):
                logger.warning(f"Model returned non-list: {type(facts)}")
                return []

            # Validate and filter facts
            valid_facts = []
            for fact in facts:
                if not isinstance(fact, dict):
                    continue

                # Required fields
                if not all(
                    key in fact
                    for key in ["fact_type", "fact_key", "fact_value", "confidence"]
                ):
                    continue

                # Validate fact_type
                if fact["fact_type"] not in [
                    "personal",
                    "preference",
                    "skill",
                    "trait",
                    "opinion",
                ]:
                    continue

                # Validate confidence
                try:
                    confidence = float(fact["confidence"])
                    if confidence < min_confidence or confidence > 1.0:
                        continue
                    fact["confidence"] = confidence
                except (ValueError, TypeError):
                    continue

                # Ensure strings
                fact["fact_key"] = str(fact["fact_key"])
                fact["fact_value"] = str(fact["fact_value"])

                valid_facts.append(fact)

            return valid_facts

        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to parse model JSON: {e}",
                extra={"response": response[:200], "error": str(e)},
            )
            return []
        except Exception as e:
            logger.error(
                f"Error parsing model response: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )
            return []
