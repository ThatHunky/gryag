"""Bot self-learning profile system - Phase 5.

The bot learns about itself over time:
- Tracks interaction outcomes and effectiveness
- Learns communication patterns that work/don't work
- Identifies knowledge gaps and strengths
- Adapts persona dynamically based on context
- Uses semantic similarity for fact deduplication (like user facts)
- Integrates with episodic memory for conversation-level learning
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

import aiosqlite

from app.infrastructure.db_utils import get_db_connection
from app.services import telemetry

LOGGER = logging.getLogger(__name__)


class BotProfileStore:
    """Manages bot's self-learning profile with enhanced features."""

    def __init__(
        self,
        db_path: str,
        bot_id: int,
        gemini_client: Any | None = None,
        enable_temporal_decay: bool = True,
        enable_semantic_dedup: bool = True,
    ):
        self._db_path = db_path
        self._bot_id = bot_id
        self._gemini = gemini_client
        self._enable_temporal_decay = enable_temporal_decay
        self._enable_semantic_dedup = enable_semantic_dedup
        self._initialized = False
        self._embed_semaphore = asyncio.Semaphore(4)  # Limit concurrent embeddings

    async def init(self) -> None:
        """Initialize bot profile (create if not exists)."""
        if self._initialized:
            return

        async with get_db_connection(self._db_path) as db:
            # Create global profile
            await db.execute(
                """
                INSERT OR IGNORE INTO bot_profiles (
                    bot_id, chat_id, created_at, updated_at
                )
                VALUES (?, NULL, ?, ?)
                """,
                (self._bot_id, int(time.time()), int(time.time())),
            )
            await db.commit()

        self._initialized = True
        LOGGER.info(f"BotProfileStore initialized for bot_id={self._bot_id}")

    async def _get_or_create_profile_id(self, chat_id: int | None = None) -> int:
        """Get profile ID for chat (or global if chat_id is None)."""
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._db_path) as db:
            # Try to get existing profile
            async with db.execute(
                "SELECT id FROM bot_profiles WHERE bot_id = ? AND chat_id IS ?",
                (self._bot_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]

            # Create new profile
            cursor = await db.execute(
                """
                INSERT INTO bot_profiles (
                    bot_id, chat_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (self._bot_id, chat_id, now, now),
            )
            await db.commit()
            return cursor.lastrowid

    async def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding for text using Gemini."""
        if not self._gemini or not self._enable_semantic_dedup:
            return None

        try:
            async with self._embed_semaphore:
                return await self._gemini.embed_text(text)
        except Exception as e:
            LOGGER.warning(f"Failed to get embedding for bot fact: {e}")
            return None

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    async def _find_similar_fact(
        self,
        profile_id: int,
        category: str,
        key: str,
        value: str,
        embedding: list[float] | None,
        similarity_threshold: float = 0.85,
    ) -> tuple[int | None, float]:
        """
        Find existing similar fact using semantic similarity.

        Returns (fact_id, similarity_score) or (None, 0.0) if no match.
        """
        if not embedding or not self._enable_semantic_dedup:
            # Fallback to exact key match
            async with get_db_connection(self._db_path) as db:
                async with db.execute(
                    """
                    SELECT id FROM bot_facts
                    WHERE profile_id = ? AND fact_category = ? AND fact_key = ?
                    AND is_active = 1
                    """,
                    (profile_id, category, key),
                ) as cursor:
                    row = await cursor.fetchone()
                    return (row[0], 1.0) if row else (None, 0.0)

        # Semantic search among existing facts of same category
        async with get_db_connection(self._db_path) as db:
            async with db.execute(
                """
                SELECT id, fact_key, fact_value, fact_embedding
                FROM bot_facts
                WHERE profile_id = ? AND fact_category = ? AND is_active = 1
                AND fact_embedding IS NOT NULL
                """,
                (profile_id, category),
            ) as cursor:
                rows = await cursor.fetchall()

        best_match = None
        best_similarity = 0.0

        for fact_id, _fact_key, _fact_value, fact_embedding_json in rows:
            try:
                fact_embedding = json.loads(fact_embedding_json)
                similarity = self._cosine_similarity(embedding, fact_embedding)

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = fact_id
            except (json.JSONDecodeError, TypeError):
                continue

        if best_similarity >= similarity_threshold:
            return (best_match, best_similarity)

        return (None, 0.0)

    async def add_fact(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
        source_type: str = "success_metric",
        chat_id: int | None = None,
        context_tags: list[str] | None = None,
        decay_rate: float = 0.0,
    ) -> int:
        """
        Add or update a fact about the bot with semantic deduplication.

        Args:
            category: Fact category (communication_style, knowledge_domain, etc.)
            key: Standardized fact key
            value: The actual fact
            confidence: Initial confidence (0.0-1.0)
            source_type: How this fact was learned
            chat_id: Specific chat or None for global
            context_tags: Tags for context-based retrieval
            decay_rate: Temporal decay rate (0.0 = no decay, higher = faster decay)

        Returns:
            Fact ID
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        now = int(time.time())

        # Get embedding for semantic deduplication
        embedding = await self._get_embedding(f"{key}: {value}")
        embedding_json = json.dumps(embedding) if embedding else None

        # Check for similar existing fact
        similar_fact_id, similarity = await self._find_similar_fact(
            profile_id, category, key, value, embedding
        )

        async with get_db_connection(self._db_path) as db:
            if similar_fact_id:
                # Reinforce existing fact
                async with db.execute(
                    """
                    SELECT evidence_count, confidence, fact_value
                    FROM bot_facts
                    WHERE id = ?
                    """,
                    (similar_fact_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        LOGGER.error(f"Similar fact {similar_fact_id} not found")
                        return similar_fact_id

                    old_count, old_confidence, old_value = row

                new_count = old_count + 1
                # Weighted average: favor more recent observations
                new_confidence = old_confidence * 0.7 + confidence * 0.3
                new_confidence = min(1.0, new_confidence)

                # Update value if new one is more confident
                final_value = value if confidence > old_confidence else old_value

                await db.execute(
                    """
                    UPDATE bot_facts
                    SET fact_value = ?, confidence = ?, evidence_count = ?,
                        last_reinforced = ?, updated_at = ?,
                        context_tags = ?, fact_embedding = ?
                    WHERE id = ?
                    """,
                    (
                        final_value,
                        new_confidence,
                        new_count,
                        now,
                        now,
                        json.dumps(context_tags or []),
                        embedding_json,
                        similar_fact_id,
                    ),
                )
                await db.commit()

                telemetry.increment_counter("bot_facts_reinforced")
                LOGGER.info(
                    f"Reinforced bot fact (similarity={similarity:.2f}): "
                    f"{key}={final_value} (confidence: {new_confidence:.2f}, "
                    f"evidence_count: {new_count})"
                )
                return similar_fact_id

            else:
                # Create new fact
                cursor = await db.execute(
                    """
                    INSERT INTO bot_facts (
                        profile_id, fact_category, fact_key, fact_value,
                        confidence, source_type, context_tags,
                        fact_embedding, decay_rate,
                        last_reinforced, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        category,
                        key,
                        value,
                        confidence,
                        source_type,
                        json.dumps(context_tags or []),
                        embedding_json,
                        decay_rate,
                        now,
                        now,
                        now,
                    ),
                )
                fact_id = cursor.lastrowid
                await db.commit()

                telemetry.increment_counter("bot_facts_learned")
                LOGGER.info(
                    f"Learned new bot fact: {key}={value} "
                    f"(confidence: {confidence:.2f}, category: {category})"
                )
                return fact_id

    async def get_facts(
        self,
        category: str | None = None,
        min_confidence: float = 0.5,
        chat_id: int | None = None,
        context_tags: list[str] | None = None,
        apply_temporal_decay: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Retrieve bot facts with optional temporal decay.

        Returns facts sorted by confidence (with decay applied if enabled).
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        now = int(time.time())

        query = """
        SELECT bf.*
        FROM bot_facts bf
        WHERE bf.profile_id = ? AND bf.is_active = 1
        """
        params: list[Any] = [profile_id]

        if category:
            query += " AND bf.fact_category = ?"
            params.append(category)

        if min_confidence > 0:
            query += " AND bf.confidence >= ?"
            params.append(min_confidence)

        async with get_db_connection(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                facts = [dict(row) for row in rows]

        # Apply temporal decay if enabled
        if apply_temporal_decay and self._enable_temporal_decay:
            for fact in facts:
                age_seconds = now - fact["updated_at"]
                age_days = age_seconds / 86400
                decay_rate = fact.get("decay_rate", 0.0)

                if decay_rate > 0:
                    # Exponential decay: confidence * exp(-decay_rate * age_days)
                    decay_factor = math.exp(-decay_rate * age_days)
                    fact["effective_confidence"] = fact["confidence"] * decay_factor
                else:
                    fact["effective_confidence"] = fact["confidence"]

            # Re-filter by min_confidence after decay
            facts = [f for f in facts if f["effective_confidence"] >= min_confidence]

            # Sort by effective confidence
            facts.sort(key=lambda f: f["effective_confidence"], reverse=True)
        else:
            # Sort by raw confidence
            facts.sort(
                key=lambda f: (f["confidence"], f["evidence_count"]),
                reverse=True,
            )

        # Filter by context tags if provided
        if context_tags:
            filtered = []
            for fact in facts:
                fact_tags = json.loads(fact.get("context_tags") or "[]")
                # Match if any tag overlaps
                if any(tag in fact_tags for tag in context_tags):
                    filtered.append(fact)
            facts = filtered

        return facts[:limit]

    async def record_interaction_outcome(
        self,
        outcome: str,
        chat_id: int,
        thread_id: int | None = None,
        message_id: int | None = None,
        interaction_type: str = "response",
        response_text: str | None = None,
        response_length: int | None = None,
        response_time_ms: int | None = None,
        token_count: int | None = None,
        tools_used: list[str] | None = None,
        user_reaction: str | None = None,
        reaction_delay_seconds: int | None = None,
        sentiment_score: float | None = None,
        context_snapshot: dict[str, Any] | None = None,
        episode_id: int | None = None,
    ) -> int:
        """
        Track interaction outcome for learning.

        Returns outcome ID.
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        now = int(time.time())

        async with get_db_connection(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO bot_interaction_outcomes (
                    profile_id, message_id, chat_id, thread_id,
                    interaction_type, outcome, sentiment_score,
                    context_snapshot, response_text, response_length,
                    response_time_ms, token_count, tools_used,
                    user_reaction, reaction_delay_seconds, episode_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    message_id,
                    chat_id,
                    thread_id,
                    interaction_type,
                    outcome,
                    sentiment_score,
                    json.dumps(context_snapshot or {}),
                    response_text,
                    response_length,
                    response_time_ms,
                    token_count,
                    json.dumps(tools_used or []),
                    user_reaction,
                    reaction_delay_seconds,
                    episode_id,
                    now,
                ),
            )
            outcome_id = cursor.lastrowid

            # Update profile stats
            await db.execute(
                """
                UPDATE bot_profiles
                SET total_interactions = total_interactions + 1,
                    positive_interactions = positive_interactions + CASE
                        WHEN ? IN ('positive', 'praised') THEN 1 ELSE 0 END,
                    negative_interactions = negative_interactions + CASE
                        WHEN ? IN ('negative', 'corrected', 'ignored') THEN 1 ELSE 0 END,
                    updated_at = ?
                WHERE id = ?
                """,
                (outcome, outcome, now, profile_id),
            )

            await db.commit()

        telemetry.increment_counter(f"bot_outcome_{outcome}")
        return outcome_id

    async def record_performance_metric(
        self,
        metric_type: str,
        metric_value: float,
        chat_id: int | None = None,
        context_tags: list[str] | None = None,
    ) -> None:
        """Record performance metric for analysis."""
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        now = int(time.time())

        async with get_db_connection(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO bot_performance_metrics (
                    profile_id, metric_type, metric_value,
                    context_tags, measured_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    metric_type,
                    metric_value,
                    json.dumps(context_tags or []),
                    now,
                ),
            )
            await db.commit()

    async def get_effectiveness_summary(
        self, chat_id: int | None = None, days: int = 7
    ) -> dict[str, Any]:
        """
        Generate summary of bot's learned effectiveness.

        Args:
            chat_id: Specific chat or None for global
            days: Look back period

        Returns:
            Summary dict with effectiveness metrics
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        cutoff_time = int(time.time()) - (days * 86400)

        async with get_db_connection(self._db_path) as db:
            # Get outcome distribution
            async with db.execute(
                """
                SELECT outcome, COUNT(*) as count
                FROM bot_interaction_outcomes
                WHERE profile_id = ? AND created_at >= ?
                GROUP BY outcome
                """,
                (profile_id, cutoff_time),
            ) as cursor:
                outcomes = {row[0]: row[1] for row in await cursor.fetchall()}

            # Get average response metrics
            async with db.execute(
                """
                SELECT
                    AVG(response_time_ms) as avg_response_time,
                    AVG(token_count) as avg_tokens,
                    AVG(sentiment_score) as avg_sentiment
                FROM bot_interaction_outcomes
                WHERE profile_id = ? AND created_at >= ?
                """,
                (profile_id, cutoff_time),
            ) as cursor:
                row = await cursor.fetchone()
                avg_response_time = row[0] or 0
                avg_tokens = row[1] or 0
                avg_sentiment = row[2] or 0

            # Get profile stats
            async with db.execute(
                """
                SELECT
                    total_interactions,
                    positive_interactions,
                    negative_interactions,
                    effectiveness_score
                FROM bot_profiles
                WHERE id = ?
                """,
                (profile_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    total, positive, negative, effectiveness = row
                else:
                    total, positive, negative, effectiveness = 0, 0, 0, 0.5

        # Calculate effectiveness score
        total_outcomes = sum(outcomes.values())
        if total_outcomes > 0:
            weights = {
                "praised": 1.0,
                "positive": 0.8,
                "neutral": 0.5,
                "negative": 0.2,
                "corrected": 0.1,
                "ignored": 0.0,
            }
            weighted_sum = sum(outcomes.get(k, 0) * v for k, v in weights.items())
            recent_effectiveness = weighted_sum / total_outcomes
        else:
            recent_effectiveness = 0.5

        return {
            "total_interactions": total,
            "positive_interactions": positive,
            "negative_interactions": negative,
            "effectiveness_score": effectiveness,
            "recent_effectiveness": recent_effectiveness,
            "recent_outcomes": outcomes,
            "avg_response_time_ms": avg_response_time,
            "avg_token_count": avg_tokens,
            "avg_sentiment": avg_sentiment,
            "period_days": days,
        }

    async def add_insight(
        self,
        insight_type: str,
        insight_text: str,
        supporting_data: dict[str, Any] | None = None,
        confidence: float = 0.5,
        actionable: bool = False,
        chat_id: int | None = None,
    ) -> int:
        """
        Add a self-reflection insight (typically generated by Gemini).

        Returns insight ID.
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)
        now = int(time.time())

        async with get_db_connection(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO bot_insights (
                    profile_id, insight_type, insight_text,
                    supporting_data, confidence, actionable, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    insight_type,
                    insight_text,
                    json.dumps(supporting_data or {}),
                    confidence,
                    1 if actionable else 0,
                    now,
                ),
            )
            insight_id = cursor.lastrowid
            await db.commit()

        LOGGER.info(f"Added bot insight: {insight_type} - {insight_text[:100]}")
        return insight_id

    async def get_recent_insights(
        self,
        chat_id: int | None = None,
        insight_type: str | None = None,
        actionable_only: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get recent self-reflection insights."""
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)

        query = """
        SELECT * FROM bot_insights
        WHERE profile_id = ?
        """
        params: list[Any] = [profile_id]

        if insight_type:
            query += " AND insight_type = ?"
            params.append(insight_type)

        if actionable_only:
            query += " AND actionable = 1"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with get_db_connection(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_effectiveness_score(self, chat_id: int | None = None) -> float:
        """
        Recalculate and update effectiveness score.

        Returns new effectiveness score.
        """
        await self.init()
        profile_id = await self._get_or_create_profile_id(chat_id)

        summary = await self.get_effectiveness_summary(chat_id, days=7)
        new_score = summary["recent_effectiveness"]

        async with get_db_connection(self._db_path) as db:
            await db.execute(
                """
                UPDATE bot_profiles
                SET effectiveness_score = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_score, int(time.time()), profile_id),
            )
            await db.commit()

        LOGGER.info(f"Updated bot effectiveness score: {new_score:.2f}")
        return new_score
