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
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.infrastructure.db_utils import get_db_connection
from app.services.redis_types import RedisLike

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
        redis_client: RedisLike | None = None,
    ):
        self.database_url = str(db_path)  # Accept database_url string
        self.settings = settings
        self.gemini = gemini_client
        self.redis: RedisLike | None = redis_client

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
        timeout_seconds: float = 10.0,
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
            timeout_seconds: Maximum seconds to wait for search (default 10s)

        Returns:
            List of SearchResults ranked by final_score
        """
        if not self.settings.enable_hybrid_search:
            # Fallback to semantic only
            return await self._semantic_search_only(
                query, chat_id, thread_id, limit, time_range_days
            )

        # Check Redis cache if enabled
        if self.settings.enable_result_caching and self.redis is not None:
            cache_key = self._build_cache_key(
                query=query,
                chat_id=chat_id,
                thread_id=thread_id,
                user_id=user_id,
                limit=limit,
                time_range_days=time_range_days,
            )
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    try:
                        payload = json.loads(cached)
                        return [SearchResult(**item) for item in payload]
                    except Exception:
                        # Corrupt cache entry; ignore
                        pass
            except Exception:
                # Redis errors should not break search
                pass

        try:
            # Execute searches in parallel with timeout protection
            tasks = []

            # Semantic search
            tasks.append(
                self._semantic_search(
                    query, chat_id, thread_id, limit * 3, time_range_days
                )
            )

            # Keyword search (if enabled)
            if self.settings.enable_keyword_search:
                tasks.append(
                    self._keyword_search(
                        query, chat_id, thread_id, limit * 3, time_range_days
                    )
                )

            results_list = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=timeout_seconds
            )
        except TimeoutError:
            LOGGER.warning(
                f"Hybrid search timeout ({timeout_seconds}s) for chat {chat_id}, using semantic-only fallback",
                extra={"chat_id": chat_id, "query": query[:100]},
            )
            # Fallback to semantic only
            return await self._semantic_search_only(
                query, chat_id, thread_id, limit, time_range_days
            )

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

        results = boosted[:limit]

        # Store in Redis cache
        if self.settings.enable_result_caching and self.redis is not None:
            cache_key = self._build_cache_key(
                query=query,
                chat_id=chat_id,
                thread_id=thread_id,
                user_id=user_id,
                limit=limit,
                time_range_days=time_range_days,
            )
            try:
                serialized = json.dumps(
                    [r.__dict__ for r in results], ensure_ascii=False
                )
                await self.redis.set(
                    cache_key, serialized, ex=self.settings.cache_ttl_seconds
                )
            except Exception:
                # Ignore cache set failures
                pass

        return results

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

            # Convert ? to $1, $2, etc.
            param_count = 0
            query_pg = ""
            for char in query_sql:
                if char == "?":
                    param_count += 1
                    query_pg += f"${param_count}"
                else:
                    query_pg += char

            async with get_db_connection(self.database_url) as conn:
                rows = await conn.fetch(query_pg, *params)

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

            ts_terms = []
            for kw in keywords:
                sanitized = re.sub(r"[^a-z0-9]+", "", kw.lower())
                if not sanitized:
                    continue
                ts_terms.append(f"{sanitized}:*")

            if not ts_terms:
                return []

            ts_query = " | ".join(ts_terms)

            where_clauses = [
                "m.text_search_vector @@ to_tsquery('english', $1)",
                "m.chat_id = $2",
            ]
            params: list[Any] = [ts_query, chat_id]
            param_idx = 3

            if thread_id is None:
                where_clauses.append("m.thread_id IS NULL")
            else:
                where_clauses.append(f"m.thread_id = ${param_idx}")
                params.append(thread_id)
                param_idx += 1

            if time_range_days:
                cutoff = int(time.time()) - (time_range_days * 86400)
                where_clauses.append(f"m.ts >= ${param_idx}")
                params.append(cutoff)
                param_idx += 1

            # Build LIMIT clause with proper parameter placeholder
            limit_placeholder = f"${param_idx}"
            params.append(limit)

            query_sql = f"""
                SELECT
                    m.id,
                    m.chat_id,
                    m.thread_id,
                    m.user_id,
                    m.role,
                    m.text,
                    m.media,
                    m.ts,
                    ts_rank_cd(m.text_search_vector, to_tsquery('english', $1)) AS rank
                FROM messages m
                WHERE {' AND '.join(where_clauses)}
                ORDER BY rank DESC
                LIMIT {limit_placeholder}
            """

            async with get_db_connection(self.database_url) as conn:
                rows = await conn.fetch(query_sql, *params)

            # Build results
            results = []
            for row in rows:
                keyword_score = float(row["rank"]) if row["rank"] is not None else 0.0

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
            async with get_db_connection(self.database_url) as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_id, COUNT(*) AS msg_count
                    FROM messages
                    WHERE chat_id = $1 AND user_id IS NOT NULL
                    GROUP BY user_id
                    """,
                    chat_id,
                )

            if not rows:
                return {}

            # Calculate weights based on message counts
            max_count = max(row["msg_count"] for row in rows)
            if max_count == 0:
                return {}

            weights: dict[int, float] = {}
            for row in rows:
                uid = row["user_id"]
                count = row["msg_count"]
                # Linear scaling from 1.0 to 2.0 based on activity
                weight = 1.0 + (count / max_count)
                weights[int(uid)] = weight

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
        from app.utils.text_processing import cosine_similarity

        return cosine_similarity(a, b)

    def _extract_keywords(self, query: str) -> list[str]:
        """
        Extract keywords from query for FTS5 search.

        Removes stop words, normalizes whitespace.
        """
        from app.utils.text_processing import extract_keywords

        return extract_keywords(query)

    def _build_cache_key(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        user_id: int | None,
        limit: int,
        time_range_days: int | None,
    ) -> str:
        # Normalize components for key stability
        q = re.sub(r"\s+", " ", query.strip().lower())[:200]
        parts = [
            "hybrid_search",
            f"c:{chat_id}",
            f"t:{thread_id or 'none'}",
            f"u:{user_id or 'none'}",
            f"l:{limit}",
            f"d:{time_range_days or 'none'}",
            f"q:{q}",
        ]
        return "|".join(parts)
