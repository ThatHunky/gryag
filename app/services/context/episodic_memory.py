"""
Episodic memory for storing and retrieving significant conversation events.

Manages memorable conversation episodes, events, and milestones.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.infrastructure.db_utils import get_db_connection

LOGGER = logging.getLogger(__name__)


@dataclass
class Episode:
    """A memorable conversation episode."""

    id: int
    chat_id: int
    thread_id: int | None
    topic: str
    summary: str
    importance: float
    emotional_valence: str
    message_ids: list[int]
    participant_ids: list[int]
    tags: list[str]
    created_at: int
    last_accessed: int | None = None
    access_count: int = 0


@dataclass
class ConversationWindow:
    """A window of related messages for analysis."""

    chat_id: int
    thread_id: int | None
    messages: list[dict[str, Any]]
    start_time: int
    end_time: int
    participant_ids: set[int]
    message_count: int
    extracted_facts: list[dict[str, Any]]
    question_count: int


class EpisodicMemoryStore:
    """
    Stores and retrieves memorable conversation episodes.

    Episodes are significant conversation events that should be
    remembered long-term, such as:
    - Important information sharing
    - Emotional conversations
    - Milestones and events
    - Long coherent discussions on a topic
    """

    def __init__(
        self,
        db_path: Path | str,
        settings: Settings,
        gemini_client: Any,
    ):
        self.database_url = str(db_path)  # Accept database_url string
        self.settings = settings
        self.gemini = gemini_client
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init(self) -> None:
        """Initialize (schema is applied by ContextStore)."""
        async with self._init_lock:
            if self._initialized:
                return
            self._initialized = True

    async def create_episode(
        self,
        chat_id: int,
        thread_id: int | None,
        user_ids: list[int],
        topic: str,
        summary: str,
        messages: list[int],
        importance: float,
        emotional_valence: str = "neutral",
        tags: list[str] | None = None,
    ) -> int:
        """
        Create a new episode from conversation window.

        Returns episode ID.
        """
        await self.init()

        if not messages or not user_ids:
            LOGGER.warning("Cannot create episode without messages or participants")
            return 0

        ts = int(time.time())
        tags = tags or []

        # Generate embedding for summary
        summary_embedding = None
        try:
            embedding = await self.gemini.embed_text(summary)
            if embedding:
                summary_embedding = json.dumps(embedding)
        except Exception as e:
            LOGGER.warning(f"Failed to generate episode embedding: {e}")

        query = """
            INSERT INTO episodes
            (chat_id, thread_id, topic, summary, summary_embedding, importance,
             emotional_valence, message_ids, participant_ids, tags, created_at, access_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 0)
            RETURNING id
        """
        params = (
            chat_id,
            thread_id,
            topic,
            summary,
            summary_embedding,
            importance,
            emotional_valence,
            json.dumps(messages),
            json.dumps(user_ids),
            json.dumps(tags),
            ts,
        )
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(query, *params)
            episode_id = row["id"] if row else 0

        LOGGER.info(
            f"Created episode {episode_id} in chat {chat_id}: {topic}",
            extra={
                "episode_id": episode_id,
                "chat_id": chat_id,
                "importance": importance,
            },
        )

        return episode_id

    async def retrieve_relevant_episodes(
        self,
        chat_id: int,
        user_id: int,
        query: str,
        limit: int = 5,
        min_importance: float | None = None,
    ) -> list[Episode]:
        """
        Retrieve episodes relevant to query.

        Uses:
        - Semantic search on summary
        - Tag matching
        - Participant matching
        - Importance threshold
        """
        await self.init()

        min_importance = min_importance or self.settings.episode_min_importance

        # Generate query embedding
        query_embedding = None
        try:
            query_embedding = await self.gemini.embed_text(query)
        except Exception as e:
            LOGGER.warning(f"Failed to generate query embedding: {e}")

        # Fetch candidate episodes
        # PostgreSQL: participant_ids is TEXT (JSON), need to cast to jsonb for array operations
        query = """
            SELECT * FROM episodes
            WHERE chat_id = $1
              AND importance >= $2
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(CAST(participant_ids AS jsonb)) je
                  WHERE je::bigint = $3
              )
            ORDER BY created_at DESC
            LIMIT $4
        """
        params = (chat_id, min_importance, user_id, limit * 3)
        async with get_db_connection(self.database_url) as conn:
            rows = await conn.fetch(query, *params)

        if not rows:
            return []

        # Score and rank episodes
        scored = []
        query_keywords = set(self._extract_keywords(query))

        for row in rows:
            score = 0.0

            # Semantic similarity
            if query_embedding and row["summary_embedding"]:
                try:
                    summary_embedding = json.loads(row["summary_embedding"])
                    similarity = self._cosine_similarity(
                        query_embedding, summary_embedding
                    )
                    score += similarity * 0.6
                except (json.JSONDecodeError, TypeError):
                    pass

            # Tag overlap
            tags = set(json.loads(row["tags"] or "[]"))
            tag_overlap = len(tags & query_keywords) / max(len(query_keywords), 1)
            score += tag_overlap * 0.3

            # Importance
            score += row["importance"] * 0.1

            scored.append((score, row))

        # Sort and convert
        scored.sort(reverse=True, key=lambda x: x[0])

        episodes = []
        episode_ids_to_track = []
        for _, row in scored[:limit]:
            episode_ids_to_track.append(row["id"])

            episodes.append(
                Episode(
                    id=row["id"],
                    chat_id=row["chat_id"],
                    thread_id=row["thread_id"],
                    topic=row["topic"],
                    summary=row["summary"],
                    importance=row["importance"],
                    emotional_valence=row["emotional_valence"],
                    message_ids=json.loads(row["message_ids"]),
                    participant_ids=json.loads(row["participant_ids"]),
                    tags=json.loads(row["tags"] or "[]"),
                    created_at=row["created_at"],
                    last_accessed=row["last_accessed"],
                    access_count=row["access_count"],
                )
            )

        # Batch update access tracking for all episodes
        if episode_ids_to_track:
            await self._record_access_batch(episode_ids_to_track)

        return episodes

    async def detect_episode_boundaries(
        self, window: ConversationWindow
    ) -> tuple[bool, float, str]:
        """
        Detect if conversation window should become an episode.

        Returns:
            (should_create, importance_score, emotional_valence)
        """
        if not self.settings.enable_episodic_memory:
            return False, 0.0, "neutral"

        if window.message_count < self.settings.episode_min_messages:
            return False, 0.0, "neutral"

        importance = 0.0

        # Has significant facts?
        if len(window.extracted_facts) >= 3:
            importance += 0.3

        # High engagement (many messages)?
        if window.message_count >= 10:
            importance += 0.2

        # Multiple questions (indicates active discussion)?
        if window.question_count >= 3:
            importance += 0.2

        # Long duration (sustained conversation)?
        duration_minutes = (window.end_time - window.start_time) / 60
        if duration_minutes >= 5:
            importance += 0.15

        # Multiple participants?
        if len(window.participant_ids) >= 2:
            importance += 0.15

        # Determine emotional valence (simplified)
        emotional_valence = await self._detect_emotion(window)

        # High emotion is important
        if emotional_valence in ("positive", "negative", "mixed"):
            importance += 0.2

        # Decide
        should_create = importance >= self.settings.episode_min_importance

        return should_create, min(importance, 1.0), emotional_valence

    async def _detect_emotion(self, window: ConversationWindow) -> str:
        """
        Detect emotional valence of conversation window.

        Returns: positive, negative, neutral, or mixed
        """
        # Simple heuristic-based detection
        # Could be enhanced with Gemini analysis

        positive_indicators = ["!", "😊", "😄", "thanks", "great", "awesome", "love"]
        negative_indicators = ["?!", ":(", "😢", "sad", "angry", "hate", "terrible"]

        positive_count = 0
        negative_count = 0

        for msg in window.messages:
            text = msg.get("text", "").lower()
            positive_count += sum(1 for ind in positive_indicators if ind in text)
            negative_count += sum(1 for ind in negative_indicators if ind in text)

        if positive_count > negative_count * 2:
            return "positive"
        elif negative_count > positive_count * 2:
            return "negative"
        elif positive_count > 0 and negative_count > 0:
            return "mixed"
        else:
            return "neutral"

    async def _record_access(self, episode_id: int) -> None:
        """Record that an episode was accessed."""
        await self._record_access_batch([episode_id])

    async def _record_access_batch(self, episode_ids: list[int]) -> None:
        """Batch record that multiple episodes were accessed."""
        if not episode_ids:
            return

        ts = int(time.time())

        async with get_db_connection(self.database_url) as conn:
            # Batch update episodes
            placeholders = ",".join(f"${i+1}" for i in range(len(episode_ids)))
            query = f"""
                UPDATE episodes
                SET last_accessed = ${len(episode_ids) + 1},
                    access_count = access_count + 1
                WHERE id IN ({placeholders})
            """
            params = list(episode_ids) + [ts]
            await conn.execute(query, *params)

            # Batch insert access logs
            access_records = [(ep_id, ts, "retrieval") for ep_id in episode_ids]
            query = """
                INSERT INTO episode_accesses (episode_id, accessed_at, access_type)
                VALUES ($1, $2, $3)
            """
            # Execute in chunks to avoid parameter limits
            chunk_size = 100
            for i in range(0, len(access_records), chunk_size):
                chunk = access_records[i : i + chunk_size]
                await conn.executemany(query, chunk)

    async def get_episode(self, episode_id: int) -> Episode | None:
        """Get a specific episode by ID."""
        await self.init()

        query = "SELECT * FROM episodes WHERE id = $1"
        params = (episode_id,)
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(query, *params)

        if not row:
            return None

        await self._record_access_batch([episode_id])

        return Episode(
            id=row["id"],
            chat_id=row["chat_id"],
            thread_id=row["thread_id"],
            topic=row["topic"],
            summary=row["summary"],
            importance=row["importance"],
            emotional_valence=row["emotional_valence"],
            message_ids=json.loads(row["message_ids"]),
            participant_ids=json.loads(row["participant_ids"]),
            tags=json.loads(row["tags"] or "[]"),
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
        )

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity."""
        from app.utils.text_processing import cosine_similarity

        return cosine_similarity(a, b)

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract keywords from text."""
        from app.utils.text_processing import extract_keywords

        return extract_keywords(text)
