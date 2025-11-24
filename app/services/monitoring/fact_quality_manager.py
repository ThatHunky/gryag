"""
Fact quality manager for deduplication, conflict resolution, and validation.

Phase 2 implementation.

Handles:
- Semantic deduplication using embeddings
- Conflict detection and resolution
- Confidence decay over time
- Fact validation and quality scoring
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class FactComparison:
    """Result of comparing two facts."""

    fact1_id: int | None
    fact2_id: int | None
    similarity: float  # 0.0 to 1.0
    are_duplicates: bool
    are_conflicting: bool
    resolution_method: str | None = None


class FactQualityManager:
    """
    Manages fact quality through deduplication and conflict resolution.

    Phase 2: Full implementation with:
    - Semantic deduplication using embeddings
    - Conflict detection and resolution
    - Time-based confidence decay
    - Quality scoring and validation
    """

    # Similarity thresholds
    DUPLICATE_THRESHOLD = 0.85  # Above this = duplicate
    SIMILAR_THRESHOLD = 0.75  # Above this = related but not duplicate
    CONFLICT_THRESHOLD = 0.70  # Similar but contradictory

    # Confidence decay parameters (exponential decay)
    DECAY_HALF_LIFE_DAYS = 90  # Confidence halves every 90 days
    MIN_CONFIDENCE = 0.1  # Never decay below this

    def __init__(self, gemini_client: Any = None, db_connection: Any = None):
        """
        Initialize fact quality manager.

        Args:
            gemini_client: GeminiClient for generating embeddings
            db_connection: Database connection for fact_quality_metrics
        """
        self.gemini_client = gemini_client
        self.db_connection = db_connection

        # Rate limiting for embeddings (max 60/min for Gemini free tier)
        self._embedding_semaphore = asyncio.Semaphore(5)
        self._last_embedding_time = 0.0
        self._min_embedding_interval = 1.0  # 1 second between requests

        self._stats = {
            "facts_processed": 0,
            "duplicates_found": 0,
            "conflicts_resolved": 0,
            "facts_decayed": 0,
            "embeddings_generated": 0,
        }

        LOGGER.info("FactQualityManager initialized (Phase 2)")

    async def process_facts(
        self,
        facts: list[dict[str, Any]],
        user_id: int,
        chat_id: int,
        existing_facts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process facts for quality improvement.

        Pipeline:
        1. Validate facts
        2. Deduplicate against existing facts
        3. Resolve conflicts
        4. Apply confidence decay to old facts

        Args:
            facts: List of newly extracted facts
            user_id: User ID for the facts
            chat_id: Chat ID for the facts
            existing_facts: Existing facts for this user (optional)

        Returns:
            Processed, deduplicated, conflict-free facts
        """
        if not facts:
            return []

        self._stats["facts_processed"] += len(facts)

        # Step 1: Validate facts
        validated_facts = self._validate_facts(facts)

        if not validated_facts:
            return []

        # Step 2: Deduplicate if we have existing facts
        if existing_facts:
            validated_facts = await self.deduplicate_facts(
                validated_facts, existing_facts, user_id, chat_id
            )

        # Step 3: Resolve internal conflicts (within new facts)
        validated_facts = await self.resolve_conflicts(validated_facts)

        # Step 4: Apply confidence decay to facts (updates in place)
        if existing_facts:
            for fact in existing_facts:
                self._apply_decay_to_fact(fact)

        return validated_facts

    def _validate_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Validate facts have required fields and reasonable values.

        Required fields:
        - fact_type
        - fact_key
        - fact_value
        - confidence (0.0 to 1.0)
        """
        validated = []

        for fact in facts:
            # Check required fields
            if not all(k in fact for k in ["fact_type", "fact_key", "fact_value"]):
                LOGGER.warning(f"Fact missing required fields: {fact}")
                continue

            # Validate confidence
            confidence = fact.get("confidence", 1.0)
            if (
                not isinstance(confidence, (int, float))
                or confidence < 0
                or confidence > 1
            ):
                LOGGER.warning(f"Invalid confidence {confidence}, setting to 0.7")
                fact["confidence"] = 0.7

            # Validate fact_type
            valid_types = {
                "personal",
                "preference",
                "trait",
                "relationship",
                "skill",
                "opinion",
            }
            if fact["fact_type"] not in valid_types:
                LOGGER.warning(
                    f"Invalid fact_type {fact['fact_type']}, setting to 'personal'"
                )
                fact["fact_type"] = "personal"

            # Ensure fact_value is a string
            if not isinstance(fact["fact_value"], str):
                fact["fact_value"] = str(fact["fact_value"])

            # Skip empty values
            if not fact["fact_value"].strip():
                continue

            validated.append(fact)

        return validated

    async def deduplicate_facts(
        self,
        new_facts: list[dict[str, Any]],
        existing_facts: list[dict[str, Any]],
        user_id: int,
        chat_id: int,
    ) -> list[dict[str, Any]]:
        """
        Deduplicate facts using semantic similarity.

        Strategy:
        1. Generate embeddings for new facts (if not present)
        2. Compare each new fact with existing facts
        3. If similarity > DUPLICATE_THRESHOLD, merge with existing
        4. If similarity > SIMILAR_THRESHOLD, update existing
        5. Otherwise, keep as new fact

        Args:
            new_facts: Newly extracted facts
            existing_facts: Existing facts for this user
            user_id: User ID
            chat_id: Chat ID

        Returns:
            Deduplicated list of facts
        """
        if not new_facts or not existing_facts:
            return new_facts

        if not self.gemini_client:
            # No embedding support, use simple key matching
            return self._simple_deduplication(new_facts, existing_facts)

        deduplicated = []

        for new_fact in new_facts:
            # Find best matching existing fact
            best_match = await self._find_best_match(new_fact, existing_facts)

            if best_match is None:
                # No similar existing fact, keep as new
                deduplicated.append(new_fact)
                continue

            comparison, existing_fact = best_match

            if comparison.are_duplicates:
                # Duplicate found - merge with existing
                self._stats["duplicates_found"] += 1
                LOGGER.info(
                    f"Duplicate fact found (similarity={comparison.similarity:.2f})",
                    extra={
                        "new": new_fact["fact_key"],
                        "existing_id": existing_fact.get("id"),
                        "user_id": user_id,
                    },
                )

                # Update existing fact with new information
                self._merge_facts(existing_fact, new_fact)

                # Log to fact_quality_metrics if we have DB
                await self._log_duplicate(
                    user_id=user_id,
                    chat_id=chat_id,
                    new_fact=new_fact,
                    existing_fact=existing_fact,
                    similarity=comparison.similarity,
                )

                # Don't add to deduplicated (merged with existing)
                continue

            elif comparison.similarity > self.SIMILAR_THRESHOLD:
                # Similar but not duplicate - might be an update
                LOGGER.info(
                    f"Similar fact found (similarity={comparison.similarity:.2f})",
                    extra={
                        "new": new_fact["fact_key"],
                        "existing": existing_fact.get("id"),
                    },
                )

                # Check if it's an update (same key, different value)
                if new_fact["fact_key"] == existing_fact["fact_key"]:
                    if new_fact["fact_value"] != existing_fact["fact_value"]:
                        # Update: replace old value with new
                        LOGGER.info(f"Updating fact: {new_fact['fact_key']}")
                        self._merge_facts(existing_fact, new_fact, prefer_new=True)
                    # Don't add to deduplicated
                    continue

            # Not a duplicate or similar enough, keep as new
            deduplicated.append(new_fact)

        LOGGER.info(
            f"Deduplication: {len(new_facts)} new -> {len(deduplicated)} after dedup",
            extra={"duplicates_found": self._stats["duplicates_found"]},
        )

        return deduplicated

    def _simple_deduplication(
        self, new_facts: list[dict[str, Any]], existing_facts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Simple deduplication without embeddings (key-based).

        Fallback when embeddings not available.
        """
        existing_keys = {f["fact_key"]: f for f in existing_facts}
        deduplicated = []

        for new_fact in new_facts:
            key = new_fact["fact_key"]

            if key in existing_keys:
                existing_fact = existing_keys[key]

                # Check if value is different (update)
                if new_fact["fact_value"] != existing_fact["fact_value"]:
                    LOGGER.info(f"Updating fact via simple dedup: {key}")
                    self._merge_facts(existing_fact, new_fact, prefer_new=True)

                self._stats["duplicates_found"] += 1
            else:
                deduplicated.append(new_fact)

        return deduplicated

    async def _find_best_match(
        self, new_fact: dict[str, Any], existing_facts: list[dict[str, Any]]
    ) -> tuple[FactComparison, dict[str, Any]] | None:
        """
        Find the best matching existing fact for a new fact.

        Returns:
            (comparison, existing_fact) or None if no good match
        """
        # Generate embedding for new fact if not present
        if "embedding" not in new_fact:
            new_fact["embedding"] = await self._get_embedding(new_fact)

        if not new_fact["embedding"]:
            return None

        best_similarity = 0.0
        best_match = None

        for existing_fact in existing_facts:
            # Only compare same fact_type
            if existing_fact["fact_type"] != new_fact["fact_type"]:
                continue

            # Generate embedding for existing fact if needed
            if "embedding" not in existing_fact:
                existing_fact["embedding"] = await self._get_embedding(existing_fact)

            if not existing_fact["embedding"]:
                continue

            # Calculate cosine similarity
            similarity = self._cosine_similarity(
                new_fact["embedding"], existing_fact["embedding"]
            )

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = existing_fact

        if best_match is None or best_similarity < self.SIMILAR_THRESHOLD:
            return None

        # Create comparison result
        comparison = FactComparison(
            fact1_id=new_fact.get("id"),
            fact2_id=best_match.get("id"),
            similarity=best_similarity,
            are_duplicates=best_similarity >= self.DUPLICATE_THRESHOLD,
            are_conflicting=(
                best_similarity >= self.CONFLICT_THRESHOLD
                and best_similarity < self.DUPLICATE_THRESHOLD
                and new_fact["fact_key"] == best_match["fact_key"]
                and new_fact["fact_value"] != best_match["fact_value"]
            ),
        )

        return (comparison, best_match)

    async def _get_embedding(self, fact: dict[str, Any]) -> list[float] | None:
        """
        Get embedding for a fact.

        Creates text representation: "{fact_key}: {fact_value}"
        """
        if not self.gemini_client:
            return None

        text = f"{fact['fact_key']}: {fact['fact_value']}"

        # Rate limiting
        async with self._embedding_semaphore:
            now = time.time()
            time_since_last = now - self._last_embedding_time

            if time_since_last < self._min_embedding_interval:
                await asyncio.sleep(self._min_embedding_interval - time_since_last)

            try:
                embedding = await self.gemini_client.embed_text(text)
                self._last_embedding_time = time.time()
                self._stats["embeddings_generated"] += 1
                return embedding
            except Exception as e:
                LOGGER.error(f"Failed to generate embedding: {e}")
                return None

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def _merge_facts(
        self,
        existing_fact: dict[str, Any],
        new_fact: dict[str, Any],
        prefer_new: bool = False,
    ) -> None:
        """
        Merge new fact into existing fact (in-place update).

        Args:
            existing_fact: Fact to update
            new_fact: New information
            prefer_new: If True, prefer new_fact values; otherwise boost confidence
        """
        if prefer_new:
            # Update value with new information
            existing_fact["fact_value"] = new_fact["fact_value"]
            existing_fact["confidence"] = min(
                1.0, new_fact.get("confidence", 0.7) + 0.1
            )
            existing_fact["updated_at"] = int(time.time())
            existing_fact["last_mentioned"] = int(time.time())
        else:
            # Boost confidence (fact mentioned again)
            existing_fact["confidence"] = min(
                1.0, existing_fact.get("confidence", 0.7) + 0.05
            )
            existing_fact["last_mentioned"] = int(time.time())

        # Update evidence if provided
        if "evidence_text" in new_fact:
            existing_fact["evidence_text"] = new_fact["evidence_text"]

        if "source_message_id" in new_fact:
            existing_fact["source_message_id"] = new_fact["source_message_id"]

    async def _log_duplicate(
        self,
        user_id: int,
        chat_id: int,
        new_fact: dict[str, Any],
        existing_fact: dict[str, Any],
        similarity: float,
    ) -> None:
        """Log duplicate to fact_quality_metrics table."""
        if not self.db_connection:
            return

        try:
            # Insert into fact_quality_metrics table
            # We use the context_store (passed as db_connection) to execute the query
            if hasattr(self.db_connection, "execute"):
                # It's likely a ContextStore or similar wrapper
                # We need to check if it exposes a way to execute raw queries or if we need to use get_db_connection
                # Based on ContextStore implementation, it has _database_url but no direct execute method exposed publicly
                # However, FactQualityManager init says: db_connection=context_store

                # Let's try to use the db_utils directly if we have the URL, or use the store's connection context
                # The ContextStore has _database_url.

                db_url = getattr(self.db_connection, "_database_url", None)
                if db_url:
                    from app.infrastructure.db_utils import get_db_connection

                    async with get_db_connection(db_url) as conn:
                        await conn.execute(
                            """
                            INSERT INTO fact_quality_metrics
                            (user_id, chat_id, metric_type, fact_key, similarity_score, 
                             details, created_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            user_id,
                            chat_id,
                            "duplicate_detected",
                            new_fact["fact_key"],
                            similarity,
                            json.dumps({
                                "new_value": new_fact["fact_value"],
                                "existing_id": existing_fact.get("id"),
                                "existing_value": existing_fact.get("fact_value")
                            }),
                            int(time.time())
                        )
        except Exception as e:
            LOGGER.error(f"Failed to log duplicate: {e}")

    async def resolve_conflicts(
        self, facts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Resolve conflicting facts.

        Strategy:
        1. Group facts by fact_key
        2. If multiple facts with same key have different values, conflict detected
        3. Resolve by prioritizing:
           - Higher confidence
           - More recent (last_mentioned or created_at)
           - Longer/more detailed value

        Args:
            facts: List of facts (may contain conflicts)

        Returns:
            List with conflicts resolved
        """
        if len(facts) <= 1:
            return facts

        # Group by (fact_type, fact_key)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for fact in facts:
            key = (fact["fact_type"], fact["fact_key"])
            groups.setdefault(key, []).append(fact)

        resolved = []

        for key, group_facts in groups.items():
            if len(group_facts) == 1:
                resolved.append(group_facts[0])
                continue

            # Check if values are different (conflict)
            values = {f["fact_value"] for f in group_facts}

            if len(values) == 1:
                # Same value, just merge (boost confidence)
                best = group_facts[0]
                best["confidence"] = min(1.0, best.get("confidence", 0.7) + 0.1)
                resolved.append(best)
                continue

            # Conflict detected
            self._stats["conflicts_resolved"] += 1
            LOGGER.warning(
                f"Conflict detected for {key[1]}: {len(values)} different values",
                extra={"values": list(values)[:3]},  # Log first 3
            )

            # Resolve by scoring
            best_fact = self._score_and_select_fact(group_facts)
            best_fact["confidence"] = max(
                0.5, best_fact.get("confidence", 0.7) - 0.1
            )  # Reduce confidence due to conflict

            resolved.append(best_fact)

        return resolved

    def _score_and_select_fact(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Score facts and select the best one.

        Scoring criteria:
        - Confidence: 40%
        - Recency: 30%
        - Detail (length): 20%
        - Source quality: 10%
        """
        best_fact = None
        best_score = -1.0

        now = int(time.time())

        for fact in facts:
            # Confidence score (0-1)
            conf_score = fact.get("confidence", 0.7)

            # Recency score (0-1)
            last_mentioned = fact.get("last_mentioned", fact.get("created_at", now))
            age_seconds = now - last_mentioned
            age_days = age_seconds / 86400
            recency_score = math.exp(-age_days / 30)  # Decay with 30-day half-life

            # Detail score (0-1)
            value_length = len(fact.get("fact_value", ""))
            detail_score = min(1.0, value_length / 100)  # Normalize to 100 chars

            # Source quality score (0-1)
            has_evidence = 1.0 if fact.get("evidence_text") else 0.5

            # Weighted sum
            total_score = (
                conf_score * 0.4
                + recency_score * 0.3
                + detail_score * 0.2
                + has_evidence * 0.1
            )

            if total_score > best_score:
                best_score = total_score
                best_fact = fact

        return best_fact or facts[0]

    def apply_confidence_decay(self, fact: dict[str, Any], days_old: int) -> float:
        """
        Apply time-based confidence decay.

        Uses exponential decay: confidence * exp(-days / half_life)

        Args:
            fact: Fact to decay
            days_old: Age in days

        Returns:
            New confidence value
        """
        original_confidence = fact.get("confidence", 1.0)

        # Exponential decay
        decay_factor = math.exp(-days_old / self.DECAY_HALF_LIFE_DAYS)
        new_confidence = original_confidence * decay_factor

        # Never go below minimum
        new_confidence = max(self.MIN_CONFIDENCE, new_confidence)

        return new_confidence

    def _apply_decay_to_fact(self, fact: dict[str, Any]) -> None:
        """Apply confidence decay to a fact (in-place)."""
        created_at = fact.get("created_at", int(time.time()))
        now = int(time.time())
        age_seconds = now - created_at
        days_old = age_seconds / 86400

        if days_old > 1:  # Only decay if older than 1 day
            new_confidence = self.apply_confidence_decay(fact, int(days_old))

            if new_confidence != fact.get("confidence", 1.0):
                fact["confidence"] = new_confidence
                self._stats["facts_decayed"] += 1

    def get_stats(self) -> dict[str, int]:
        """Get processing statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        for key in self._stats:
            self._stats[key] = 0
