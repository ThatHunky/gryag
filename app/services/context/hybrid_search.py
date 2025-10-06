"""
Hybrid search engine combining semantic, keyword, and temporal signals.

Provides multi-signal search that combines:
- Semantic similarity (embedding-based)
- Keyword relevance (FTS5-based)
- Temporal recency (exponential decay)
- Importance weighting (user interaction patterns)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from hybrid search with all scoring components."""

    message_id: int
    chat_id: int
    thread_id: int | None
    user_id: int | None
    role: str
    text: str
    timestamp: int
    is_addressed: bool

    # Scoring components
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    temporal_factor: float = 1.0
    importance_factor: float = 1.0
    type_boost: float = 1.0

    # Final score
    final_score: float = 0.0

    # Metadata
    metadata: dict[str, Any] | None = None
    matched_keywords: list[str] | None = None


class HybridSearchEngine:
    """
    Multi-signal search combining semantic, keyword, temporal, and importance signals.

    Implements the hybrid search strategy:
    1. Semantic similarity via embeddings
    2. Keyword matching via FTS5
    3. Temporal recency boosting
    4. Importance weighting
    5. Message type boosting (addressed vs unaddressed)
    """

    def __init__(
        self,
        db_path: Path | str,
        settings: Settings,
        gemini_client: Any,
    ):
        self.db_path = Path(db_path)
        self.settings = settings
        self.gemini = gemini_client

        # Weights for score combination
        self.semantic_weight = settings.semantic_weight
        self.keyword_weight = settings.keyword_weight
        self.temporal_weight = settings.temporal_weight

        # Cache for user interaction weights
        self._user_weight_cache: dict[tuple[int, int], dict[int, float]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamps: dict[tuple[int, int], float] = {}

    async def search(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        user_id: int | None = None,
        limit: int = 10,
        time_range_days: int | None = None,
    ) -> list[SearchResult]:
        """
        Hybrid search with multiple signals.

        Args:
            query: Search query text
            chat_id: Chat to search in
            thread_id: Thread to search in (optional)
            user_id: User making the query (for importance weighting)
            limit: Maximum results to return
            time_range_days: Limit search to recent N days (optional)

        Returns:
            List of SearchResults ranked by final_score
        """
        if not self.settings.enable_hybrid_search:
            # Fallback to semantic only
            return await self._semantic_search_only(
                query, chat_id, thread_id, limit, time_range_days
            )

        # Execute searches in parallel
        tasks = []

        # Semantic search
        tasks.append(
            self._semantic_search(query, chat_id, thread_id, limit * 3, time_range_days)
        )

        # Keyword search (if enabled)
        if self.settings.enable_keyword_search:
            tasks.append(
                self._keyword_search(
                    query, chat_id, thread_id, limit * 3, time_range_days
                )
            )

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        semantic_results = []
        keyword_results = []

        if isinstance(results_list[0], list):
            semantic_results = results_list[0]
        else:
            LOGGER.error(f"Semantic search failed: {results_list[0]}")

        if len(results_list) > 1:
            if isinstance(results_list[1], list):
                keyword_results = results_list[1]
            else:
                LOGGER.error(f"Keyword search failed: {results_list[1]}")

        # Merge results
        merged = self._merge_results(semantic_results, keyword_results)

        # Apply boosting
        if self.settings.enable_temporal_boosting and user_id:
            boosted = await self._apply_boosting(merged, user_id, chat_id)
        else:
            # Just calculate final scores without user-specific boosting
            for result in merged:
                result.final_score = self._calculate_base_score(result)
            boosted = merged

        # Sort by final score
        boosted.sort(key=lambda r: r.final_score, reverse=True)

        return boosted[:limit]

    async def _semantic_search(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        limit: int,
        time_range_days: int | None,
    ) -> list[SearchResult]:
        """Execute semantic search using embeddings."""
        try:
            # Generate query embedding
            query_embedding = await self.gemini.embed_text(query)

            if not query_embedding:
                return []

            # Build query
            if thread_id is None:
                where_clause = "WHERE m.chat_id = ? AND m.embedding IS NOT NULL"
                params: list[Any] = [chat_id]
            else:
                where_clause = "WHERE m.chat_id = ? AND m.thread_id = ? AND m.embedding IS NOT NULL"
                params = [chat_id, thread_id]

            # Add time range filter
            if time_range_days:
                cutoff = int(time.time()) - (time_range_days * 86400)
                where_clause += " AND m.ts >= ?"
                params.append(cutoff)

            query_sql = f"""
                SELECT m.id, m.chat_id, m.thread_id, m.user_id, m.role, 
                       m.text, m.media, m.embedding, m.ts
                FROM messages m
                {where_clause}
                ORDER BY m.id DESC
                LIMIT ?
            """
            params.append(min(limit, self.settings.max_search_candidates))

            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query_sql, params) as cursor:
                    rows = await cursor.fetchall()

            # Calculate similarities
            results = []
            for row in rows:
                embedding_json = row["embedding"]
                if not embedding_json:
                    continue

                try:
                    stored_embedding = json.loads(embedding_json)
                    if not isinstance(stored_embedding, list):
                        continue

                    similarity = self._cosine_similarity(
                        query_embedding, stored_embedding
                    )

                    if similarity <= 0:
                        continue

                    # Parse metadata
                    metadata = {}
                    is_addressed = False
                    if row["media"]:
                        try:
                            media_payload = json.loads(row["media"])
                            if isinstance(media_payload, dict):
                                metadata = media_payload.get("meta", {})
                                # Check if message was addressed to bot
                                is_addressed = metadata.get("addressed", False)
                        except json.JSONDecodeError:
                            pass

                    results.append(
                        SearchResult(
                            message_id=row["id"],
                            chat_id=row["chat_id"],
                            thread_id=row["thread_id"],
                            user_id=row["user_id"],
                            role=row["role"],
                            text=row["text"] or "",
                            timestamp=row["ts"],
                            is_addressed=is_addressed,
                            semantic_score=similarity,
                            metadata=metadata,
                        )
                    )

                except (json.JSONDecodeError, TypeError) as e:
                    LOGGER.debug(f"Failed to parse embedding: {e}")
                    continue

            return results

        except Exception as e:
            LOGGER.error(f"Semantic search failed: {e}", exc_info=True)
            return []

    async def _keyword_search(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        limit: int,
        time_range_days: int | None,
    ) -> list[SearchResult]:
        """Execute keyword search using FTS5."""
        try:
            # Extract keywords from query
            keywords = self._extract_keywords(query)
            if not keywords:
                return []

            # Build FTS5 query - quote each keyword to handle special chars
            fts_query = " OR ".join(f'"{kw}"' for kw in keywords)

            # Build SQL query
            if thread_id is None:
                where_clause = "AND m.chat_id = ?"
                params: list[Any] = [fts_query, chat_id]
            else:
                where_clause = "AND m.chat_id = ? AND m.thread_id = ?"
                params = [fts_query, chat_id, thread_id]

            # Add time range filter
            if time_range_days:
                cutoff = int(time.time()) - (time_range_days * 86400)
                where_clause += " AND m.ts >= ?"
                params.append(cutoff)

            query_sql = f"""
                SELECT m.id, m.chat_id, m.thread_id, m.user_id, m.role,
                       m.text, m.media, m.ts, 
                       rank as fts_rank
                FROM messages_fts fts
                JOIN messages m ON fts.rowid = m.id
                WHERE messages_fts MATCH ? {where_clause}
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)

            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query_sql, params) as cursor:
                    rows = await cursor.fetchall()

            # Build results
            results = []
            for row in rows:
                # FTS5 rank is negative (lower is better), normalize to 0-1
                # Typical ranks are -1.0 to -10.0
                fts_rank = abs(row["fts_rank"])
                keyword_score = 1.0 / (1.0 + fts_rank)  # Normalize to 0-1

                # Parse metadata
                metadata = {}
                is_addressed = False
                if row["media"]:
                    try:
                        media_payload = json.loads(row["media"])
                        if isinstance(media_payload, dict):
                            metadata = media_payload.get("meta", {})
                            is_addressed = metadata.get("addressed", False)
                    except json.JSONDecodeError:
                        pass

                # Find matched keywords
                text = row["text"] or ""
                text_lower = text.lower()
                matched = [kw for kw in keywords if kw.lower() in text_lower]

                results.append(
                    SearchResult(
                        message_id=row["id"],
                        chat_id=row["chat_id"],
                        thread_id=row["thread_id"],
                        user_id=row["user_id"],
                        role=row["role"],
                        text=text,
                        timestamp=row["ts"],
                        is_addressed=is_addressed,
                        keyword_score=keyword_score,
                        metadata=metadata,
                        matched_keywords=matched,
                    )
                )

            return results

        except Exception as e:
            LOGGER.error(f"Keyword search failed: {e}", exc_info=True)
            return []

    def _merge_results(
        self,
        semantic_results: list[SearchResult],
        keyword_results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        Merge semantic and keyword search results.

        If a message appears in both, combine their scores.
        """
        # Index by message_id
        by_id: dict[int, SearchResult] = {}

        for result in semantic_results:
            by_id[result.message_id] = result

        for result in keyword_results:
            if result.message_id in by_id:
                # Merge scores
                existing = by_id[result.message_id]
                existing.keyword_score = result.keyword_score
                if result.matched_keywords:
                    existing.matched_keywords = result.matched_keywords
            else:
                # Add new result
                by_id[result.message_id] = result

        return list(by_id.values())

    def _calculate_base_score(self, result: SearchResult) -> float:
        """Calculate base score from semantic and keyword components."""
        # Normalize weights
        total_weight = self.semantic_weight + self.keyword_weight
        if total_weight == 0:
            return 0.0

        semantic_w = self.semantic_weight / total_weight
        keyword_w = self.keyword_weight / total_weight

        score = result.semantic_score * semantic_w + result.keyword_score * keyword_w

        return score

    async def _apply_boosting(
        self,
        results: list[SearchResult],
        user_id: int,
        chat_id: int,
    ) -> list[SearchResult]:
        """
        Apply temporal, importance, and type boosting.

        - Temporal decay: score *= exp(-age_days / half_life)
        - Importance boost: score *= (1 + user_interaction_weight)
        - Type boost: addressed messages get 1.5x
        """
        now = time.time()
        half_life_days = self.settings.temporal_half_life_days

        # Get user interaction weights
        user_weights = await self._get_user_weights(chat_id)

        for result in results:
            # Base score
            base_score = self._calculate_base_score(result)

            # Temporal decay
            age_seconds = now - result.timestamp
            age_days = age_seconds / 86400
            temporal_factor = math.exp(-age_days / half_life_days)
            result.temporal_factor = temporal_factor

            # Importance boost
            sender_weight = user_weights.get(result.user_id or 0, 1.0)
            result.importance_factor = sender_weight

            # Type boost
            type_boost = 1.5 if result.is_addressed else 1.0
            result.type_boost = type_boost

            # Combined final score
            result.final_score = (
                base_score
                * (temporal_factor**self.temporal_weight)
                * sender_weight
                * type_boost
            )

        return results

    async def _get_user_weights(self, chat_id: int) -> dict[int, float]:
        """
        Get user interaction weights for a chat.

        Users with more interactions get higher weights (1.0 - 2.0).
        Cached for performance.
        """
        cache_key = (chat_id, 0)  # 0 as placeholder

        # Check cache
        now = time.time()
        if cache_key in self._user_weight_cache:
            if now - self._cache_timestamps.get(cache_key, 0) < self._cache_ttl:
                return self._user_weight_cache[cache_key]

        # Query database
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    """
                    SELECT user_id, COUNT(*) as msg_count
                    FROM messages
                    WHERE chat_id = ? AND user_id IS NOT NULL
                    GROUP BY user_id
                    """,
                    (chat_id,),
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                return {}

            # Calculate weights based on message counts
            max_count = max(row[1] for row in rows)
            if max_count == 0:
                return {}

            weights = {}
            for user_id, count in rows:
                # Linear scaling from 1.0 to 2.0 based on activity
                weight = 1.0 + (count / max_count)
                weights[user_id] = weight

            # Cache it
            self._user_weight_cache[cache_key] = weights
            self._cache_timestamps[cache_key] = now

            return weights

        except Exception as e:
            LOGGER.error(f"Failed to get user weights: {e}")
            return {}

    async def _semantic_search_only(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        limit: int,
        time_range_days: int | None,
    ) -> list[SearchResult]:
        """Fallback to semantic search only when hybrid is disabled."""
        results = await self._semantic_search(
            query, chat_id, thread_id, limit, time_range_days
        )

        # Set final scores
        for result in results:
            result.final_score = result.semantic_score

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:limit]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """
        Extract keywords from query for FTS5 search.

        Removes stop words, normalizes whitespace.
        """
        # Simple keyword extraction (can be enhanced)
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "should",
            "could",
            "may",
            "might",
            "can",
            "about",
            "that",
            "this",
            "these",
            "those",
        }

        # Split and clean
        words = query.lower().split()
        keywords = [
            w.strip(".,!?;:\"'()[]{}")
            for w in words
            if w.strip(".,!?;:\"'()[]{}") not in stop_words and len(w) > 2
        ]

        return keywords
