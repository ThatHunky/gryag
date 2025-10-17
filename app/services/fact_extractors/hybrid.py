"""Hybrid fact extraction orchestrator using multiple strategies."""

from __future__ import annotations

import logging
from typing import Any

from .base import FactExtractor
from .normalizers import get_dedup_key
from .rule_based import RuleBasedFactExtractor

logger = logging.getLogger(__name__)


class HybridFactExtractor(FactExtractor):
    """
    Orchestrates fact extraction using a two-tier strategy:
    1. Rule-based (instant, high precision)
    2. Gemini fallback (optional, for complex cases)
    """

    def __init__(
        self,
        rule_based: RuleBasedFactExtractor,
        gemini_extractor: Any | None = None,
        enable_gemini_fallback: bool = True,
    ):
        """
        Initialize hybrid extractor.

        Args:
            rule_based: Rule-based pattern matcher (always used)
            gemini_extractor: Gemini extractor (optional fallback)
            enable_gemini_fallback: Whether to use Gemini as fallback (default: True)
        """
        self.rule_based = rule_based
        self.gemini_extractor = gemini_extractor
        self.enable_gemini_fallback = enable_gemini_fallback

    async def extract_facts(
        self,
        message: str,
        user_id: int,
        username: str | None = None,
        context: list[dict[str, Any]] | None = None,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Extract facts using hybrid strategy.

        Args:
            message: User's message text
            user_id: Telegram user ID
            username: User's username
            context: Recent conversation history
            min_confidence: Minimum confidence threshold

        Returns:
            List of fact dicts
        """
        import time

        from app.services.telemetry import telemetry

        start_time = time.time()
        all_facts: list[dict[str, Any]] = []
        extraction_method = "rule_based"  # Default to rule-based

        # Tier 1: Rule-based extraction (always run, instant)
        try:
            rule_facts = await self.rule_based.extract_facts(
                message=message,
                user_id=user_id,
                username=username,
                context=context,
                min_confidence=min_confidence,
            )
            all_facts.extend(rule_facts)
            logger.debug(
                f"Rule-based found {len(rule_facts)} facts",
                extra={"user_id": user_id, "rule_fact_count": len(rule_facts)},
            )
        except Exception as e:
            logger.error(
                f"Rule-based extraction failed: {e}",
                extra={"user_id": user_id, "error": str(e)},
            )

        # If rule-based found sufficient facts, we're done
        if len(all_facts) >= 3:
            logger.info(
                f"Rule-based extraction sufficient: {len(all_facts)} facts",
                extra={"user_id": user_id, "tier": "rule_based"},
            )
            elapsed_ms = int((time.time() - start_time) * 1000)
            telemetry.set_gauge("fact_extraction_latency_ms", elapsed_ms)
            telemetry.increment_counter(
                "fact_extraction_method_used", method=extraction_method
            )
            telemetry.increment_counter("facts_extracted_count", count=len(all_facts))
            return self._deduplicate_facts(all_facts)

        # Tier 2: Gemini fallback (only if enabled and rule-based found few facts)
        if (
            self.enable_gemini_fallback
            and self.gemini_extractor
            and len(all_facts) < 2  # Very few facts found
            and len(message) > 30  # Substantial message
        ):
            try:
                logger.info(
                    "Falling back to Gemini extraction",
                    extra={"user_id": user_id, "tier": "gemini_fallback"},
                )
                gemini_facts = await self.gemini_extractor.extract_user_facts(
                    message=message,
                    user_id=user_id,
                    username=username,
                    context=context,
                    min_confidence=min_confidence,
                )
                all_facts.extend(gemini_facts)
                extraction_method = "gemini_fallback"
                logger.debug(
                    f"Gemini found {len(gemini_facts)} facts",
                    extra={"user_id": user_id, "gemini_fact_count": len(gemini_facts)},
                )
            except Exception as e:
                logger.error(
                    f"Gemini fallback extraction failed: {e}",
                    extra={"user_id": user_id, "error": str(e)},
                )

        # Deduplicate and return
        final_facts = self._deduplicate_facts(all_facts)

        elapsed_ms = int((time.time() - start_time) * 1000)
        telemetry.set_gauge("fact_extraction_latency_ms", elapsed_ms)
        telemetry.increment_counter(
            "fact_extraction_method_used", method=extraction_method
        )
        telemetry.increment_counter("facts_extracted_count", count=len(final_facts))

        logger.info(
            f"Hybrid extraction complete: {len(final_facts)} unique facts in {elapsed_ms}ms",
            extra={
                "user_id": user_id,
                "total_facts": len(all_facts),
                "unique_facts": len(final_facts),
                "extraction_method": extraction_method,
                "latency_ms": elapsed_ms,
            },
        )

        return final_facts

    def _deduplicate_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Remove duplicate facts, keeping highest confidence.

        Uses normalized values for better semantic deduplication.

        Args:
            facts: List of fact dicts

        Returns:
            Deduplicated list
        """
        if not facts:
            return []

        # Group by normalized dedup key
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}

        for fact in facts:
            # Use normalized dedup key
            key = get_dedup_key(fact)

            # Keep fact with highest confidence
            if key not in seen or fact.get("confidence", 0) > seen[key].get(
                "confidence", 0
            ):
                seen[key] = fact

        return list(seen.values())


# Convenience function to create hybrid extractor
async def create_hybrid_extractor(
    enable_gemini_fallback: bool = True,
    gemini_client: Any | None = None,
) -> HybridFactExtractor:
    """
    Create and initialize a HybridFactExtractor.

    Args:
        enable_gemini_fallback: Whether to enable Gemini as fallback (default: True)
        gemini_client: Gemini client instance (for fallback)

    Returns:
        Configured HybridFactExtractor using rule-based + optional Gemini fallback
    """
    # Always create rule-based extractor
    rule_based = RuleBasedFactExtractor()

    # Create Gemini extractor if needed
    gemini_extractor = None
    if enable_gemini_fallback and gemini_client:
        # Import legacy extractor
        from app.services.user_profile import FactExtractor as LegacyFactExtractor

        gemini_extractor = LegacyFactExtractor(gemini_client)
        logger.info("Gemini fallback enabled for fact extraction")

    return HybridFactExtractor(
        rule_based=rule_based,
        gemini_extractor=gemini_extractor,
        enable_gemini_fallback=enable_gemini_fallback,
    )
