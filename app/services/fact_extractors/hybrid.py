"""Hybrid fact extraction orchestrator using multiple strategies."""

from __future__ import annotations

import logging
from typing import Any

from .base import FactExtractor
from .local_model import LocalModelFactExtractor
from .rule_based import RuleBasedFactExtractor

logger = logging.getLogger(__name__)


class HybridFactExtractor(FactExtractor):
    """
    Orchestrates fact extraction using a three-tier strategy:
    1. Rule-based (instant, high precision)
    2. Local model (100-500ms, good accuracy)
    3. Gemini fallback (optional, disabled by default)
    """

    def __init__(
        self,
        rule_based: RuleBasedFactExtractor,
        local_model: LocalModelFactExtractor | None = None,
        gemini_extractor: Any | None = None,
        enable_gemini_fallback: bool = False,
    ):
        """
        Initialize hybrid extractor.

        Args:
            rule_based: Rule-based pattern matcher (always used)
            local_model: Local LLM extractor (optional)
            gemini_extractor: Legacy Gemini extractor (optional fallback)
            enable_gemini_fallback: Whether to use Gemini as last resort
        """
        self.rule_based = rule_based
        self.local_model = local_model
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

        # Phase 3: Check resource pressure before using local model
        should_skip_local = False
        try:
            from app.services.resource_monitor import get_resource_monitor

            resource_monitor = get_resource_monitor()
            if resource_monitor.should_disable_local_model():
                logger.warning(
                    "Skipping local model due to memory pressure",
                    extra={"user_id": user_id},
                )
                should_skip_local = True
                telemetry.increment_counter("fact_extraction_skipped_memory_pressure")
        except ImportError:
            pass

        # Tier 2: Local model (if available, substantial message, and resources OK)
        if (
            not should_skip_local
            and self.local_model
            and self.local_model.is_available
            and len(message) > 20  # Skip very short messages
        ):
            try:
                local_facts = await self.local_model.extract_facts(
                    message=message,
                    user_id=user_id,
                    username=username,
                    context=context,
                    min_confidence=min_confidence,
                )
                all_facts.extend(local_facts)
                extraction_method = "hybrid"  # Used rule-based + local model
                logger.debug(
                    f"Local model found {len(local_facts)} facts",
                    extra={"user_id": user_id, "local_fact_count": len(local_facts)},
                )
            except Exception as e:
                logger.error(
                    f"Local model extraction failed: {e}",
                    extra={"user_id": user_id, "error": str(e)},
                )

        # Tier 3: Gemini fallback (only if enabled and other methods insufficient)
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

        Args:
            facts: List of fact dicts

        Returns:
            Deduplicated list
        """
        if not facts:
            return []

        # Group by (fact_type, fact_key, fact_value)
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}

        for fact in facts:
            key = (
                fact.get("fact_type", ""),
                fact.get("fact_key", ""),
                fact.get("fact_value", "").lower().strip(),
            )

            # Keep fact with highest confidence
            if key not in seen or fact.get("confidence", 0) > seen[key].get(
                "confidence", 0
            ):
                seen[key] = fact

        return list(seen.values())


# Convenience function to create hybrid extractor
async def create_hybrid_extractor(
    extraction_method: str = "hybrid",
    local_model_path: str | None = None,
    local_model_threads: int | None = None,
    enable_gemini_fallback: bool = False,
    gemini_client: Any | None = None,
    lazy_load_model: bool = True,  # Phase 3: Enable lazy loading by default
) -> HybridFactExtractor:
    """
    Create and initialize a HybridFactExtractor.

    Args:
        extraction_method: 'rule_based', 'local_model', 'hybrid', or 'gemini'
        local_model_path: Path to local model GGUF file
        local_model_threads: Number of threads for local model
        enable_gemini_fallback: Whether to enable Gemini as fallback
        gemini_client: Gemini client instance (for fallback)
        lazy_load_model: If True, delay model loading until first use (Phase 3)

    Returns:
        Configured HybridFactExtractor
    """
    from .model_manager import ModelManager

    # Always create rule-based extractor
    rule_based = RuleBasedFactExtractor()

    # Create local model extractor if needed
    local_model = None
    if extraction_method in ("local_model", "hybrid") and local_model_path:
        model_manager = ModelManager(
            model_path=local_model_path,
            n_ctx=2048,
            n_threads=local_model_threads,
            lazy_load=lazy_load_model,
        )

        # Phase 3: Only initialize if eager loading requested
        if not lazy_load_model:
            # Try to initialize model immediately
            success = await model_manager.initialize()
            if success:
                local_model = LocalModelFactExtractor(model_manager)
                logger.info("Local model initialized successfully (eager loading)")
            else:
                logger.warning(
                    "Failed to initialize local model, will use rule-based only"
                )
        else:
            # Lazy loading mode - model will be initialized on first use
            local_model = LocalModelFactExtractor(model_manager)
            logger.info(
                "Local model configured with lazy loading (will load on first use)"
            )

    # Create legacy Gemini extractor if needed
    gemini_extractor = None
    if enable_gemini_fallback and gemini_client:
        # Import legacy extractor
        from app.services.user_profile import FactExtractor as LegacyFactExtractor

        gemini_extractor = LegacyFactExtractor(gemini_client)
        logger.info("Gemini fallback enabled")

    return HybridFactExtractor(
        rule_based=rule_based,
        local_model=local_model,
        gemini_extractor=gemini_extractor,
        enable_gemini_fallback=enable_gemini_fallback,
    )
