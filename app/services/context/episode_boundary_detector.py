"""
Episode Boundary Detection for automatic episode creation.

Phase 4.1: Implements automatic detection of episode boundaries using:
- Semantic similarity between consecutive messages
- Time gap detection
- Topic marker detection
- Combined scoring to decide when to create episodes
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


from app.config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass
class BoundarySignal:
    """A signal indicating a possible episode boundary."""

    message_id: int
    timestamp: int
    signal_type: str  # semantic, temporal, topic_marker
    strength: float  # 0.0 to 1.0
    reason: str
    metadata: dict[str, Any] | None = None


@dataclass
class MessageSequence:
    """A sequence of messages for boundary analysis."""

    messages: list[dict[str, Any]]
    chat_id: int
    thread_id: int | None
    start_timestamp: int
    end_timestamp: int


class EpisodeBoundaryDetector:
    """
    Detects episode boundaries in conversation flow.

    Uses multiple signals to identify when a coherent episode ends
    and a new one begins, enabling automatic episode creation.
    """

    # Topic marker patterns (Ukrainian and English)
    TOPIC_MARKERS = [
        # Ukrainian
        r"\b(давайте поговорим|поговорим про|змін[іи]мо тему|нова тема|до речі|кстаті)\b",
        r"\b(а зараз|зараз про|перейдем до|далі)\b",
        r"\b(тепер про|тепер давайте|тепер до|окей, .*тепер)\b",
        # English
        r"\b(let'?s talk about|speaking of|by the way|anyway|on another note)\b",
        r"\b(changing (the )?subject|new topic|moving on|next topic)\b",
        r"\b(now (about|for)|so about|okay so)\b",
        # Questions that signal topic change
        r"^(а що|а як|а чому|а коли|що думаєш про|як щодо)",
        r"^(what about|how about|what do you think about|speaking of)",
    ]

    # Temporal thresholds
    DEFAULT_SHORT_GAP_SECONDS = 120  # 2 minutes
    DEFAULT_MEDIUM_GAP_SECONDS = 900  # 15 minutes
    DEFAULT_LONG_GAP_SECONDS = 3600  # 1 hour

    # Semantic thresholds
    DEFAULT_LOW_SIMILARITY = 0.3
    DEFAULT_MEDIUM_SIMILARITY = 0.5
    DEFAULT_HIGH_SIMILARITY = 0.7

    # Combined scoring weights
    SEMANTIC_WEIGHT = 0.4
    TEMPORAL_WEIGHT = 0.35
    TOPIC_MARKER_WEIGHT = 0.25

    def __init__(
        self,
        database_url: str,
        settings: Settings,
        gemini_client: Any,
    ):
        self.database_url = str(database_url)
        self.settings = settings
        self.gemini = gemini_client
        self._init_lock = asyncio.Lock()
        self._initialized = False

        # Compile regex patterns
        self._topic_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.TOPIC_MARKERS
        ]

        # Configurable thresholds
        self.short_gap = getattr(
            settings, "episode_short_gap_seconds", self.DEFAULT_SHORT_GAP_SECONDS
        )
        self.medium_gap = getattr(
            settings, "episode_medium_gap_seconds", self.DEFAULT_MEDIUM_GAP_SECONDS
        )
        self.long_gap = getattr(
            settings, "episode_long_gap_seconds", self.DEFAULT_LONG_GAP_SECONDS
        )

        self.low_similarity = getattr(
            settings,
            "episode_low_similarity_threshold",
            self.DEFAULT_LOW_SIMILARITY,
        )
        self.medium_similarity = getattr(
            settings,
            "episode_medium_similarity_threshold",
            self.DEFAULT_MEDIUM_SIMILARITY,
        )
        self.high_similarity = getattr(
            settings,
            "episode_high_similarity_threshold",
            self.DEFAULT_HIGH_SIMILARITY,
        )

        # Boundary detection threshold
        self.boundary_threshold = getattr(settings, "episode_boundary_threshold", 0.6)

    async def init(self) -> None:
        """Initialize detector (schema is applied by ContextStore)."""
        async with self._init_lock:
            if self._initialized:
                return
            self._initialized = True
            LOGGER.info("Episode boundary detector initialized")

    async def detect_boundaries(
        self, sequence: MessageSequence
    ) -> list[BoundarySignal]:
        """
        Detect all boundary signals in message sequence.

        Returns list of boundary signals, sorted by timestamp.
        """
        await self.init()

        if len(sequence.messages) < 2:
            return []

        signals = []

        # Analyze consecutive message pairs
        for i in range(len(sequence.messages) - 1):
            msg_a = sequence.messages[i]
            msg_b = sequence.messages[i + 1]

            # Temporal signal
            temporal = await self._detect_temporal_boundary(msg_a, msg_b)
            if temporal:
                signals.append(temporal)

            # Topic marker signal
            topic_marker = await self._detect_topic_marker(msg_b)
            if topic_marker:
                signals.append(topic_marker)

            # Semantic signal (expensive, run last)
            semantic = await self._detect_semantic_boundary(msg_a, msg_b)
            if semantic:
                signals.append(semantic)

        # Sort by timestamp
        signals.sort(key=lambda s: s.timestamp)

        return signals

    async def should_create_boundary(
        self, sequence: MessageSequence, signals: list[BoundarySignal]
    ) -> tuple[bool, float, list[BoundarySignal]]:
        """
        Determine if a boundary should be created based on signals.

        Returns:
            (should_create, combined_score, contributing_signals)
        """
        if not signals:
            return False, 0.0, []

        # Group signals by position (allow clustering within 60 seconds)
        clusters = self._cluster_signals(signals, time_window=60)

        # Score each cluster
        best_score = 0.0
        best_cluster = []

        for cluster in clusters:
            score = self._score_signal_cluster(cluster)
            if score > best_score:
                best_score = score
                best_cluster = cluster

        should_create = best_score >= self.boundary_threshold

        LOGGER.debug(
            f"Boundary detection: score={best_score:.3f}, threshold={self.boundary_threshold:.3f}, decision={should_create}",
            extra={
                "score": best_score,
                "threshold": self.boundary_threshold,
                "signal_count": len(best_cluster),
                "decision": should_create,
            },
        )

        return should_create, best_score, best_cluster

    async def _detect_semantic_boundary(
        self, msg_a: dict[str, Any], msg_b: dict[str, Any]
    ) -> BoundarySignal | None:
        """
        Detect semantic topic shift between consecutive messages.

        Low similarity = potential boundary.
        """
        text_a = self._extract_text(msg_a)
        text_b = self._extract_text(msg_b)

        # Skip if either message is too short
        if len(text_a.split()) < 3 or len(text_b.split()) < 3:
            return None

        try:
            # Get embeddings
            embedding_a = await self._get_or_embed(msg_a, text_a)
            embedding_b = await self._get_or_embed(msg_b, text_b)

            if not embedding_a or not embedding_b:
                return None

            # Calculate similarity
            similarity = self._cosine_similarity(embedding_a, embedding_b)

            # Low similarity indicates topic shift
            if similarity < self.medium_similarity:
                strength = (
                    1.0 - similarity
                )  # Invert: lower similarity = stronger signal

                return BoundarySignal(
                    message_id=msg_b["id"],
                    timestamp=msg_b["timestamp"],
                    signal_type="semantic",
                    strength=min(strength, 1.0),
                    reason=f"Low semantic similarity: {similarity:.2f}",
                    metadata={"similarity": similarity},
                )

        except Exception as e:
            LOGGER.warning(f"Failed to detect semantic boundary: {e}")

        return None

    async def _detect_temporal_boundary(
        self, msg_a: dict[str, Any], msg_b: dict[str, Any]
    ) -> BoundarySignal | None:
        """
        Detect time gap between consecutive messages.

        Large gaps indicate episode boundaries.
        """
        time_gap = msg_b["timestamp"] - msg_a["timestamp"]

        # No gap = no boundary
        if time_gap < self.short_gap:
            return None

        # Calculate strength based on gap size
        if time_gap >= self.long_gap:
            strength = 1.0
            reason = f"Long gap: {time_gap // 60} minutes"
        elif time_gap >= self.medium_gap:
            strength = 0.7
            reason = f"Medium gap: {time_gap // 60} minutes"
        else:  # >= short_gap
            strength = 0.4
            reason = f"Short gap: {time_gap // 60} minutes"

        return BoundarySignal(
            message_id=msg_b["id"],
            timestamp=msg_b["timestamp"],
            signal_type="temporal",
            strength=strength,
            reason=reason,
            metadata={"gap_seconds": time_gap},
        )

    async def _detect_topic_marker(self, msg: dict[str, Any]) -> BoundarySignal | None:
        """
        Detect explicit topic change markers in message text.

        Phrases like "let's talk about", "changing subject", etc.
        """
        text = self._extract_text(msg).lower()

        # Check against all patterns
        for pattern in self._topic_patterns:
            match = pattern.search(text)
            if match:
                return BoundarySignal(
                    message_id=msg["id"],
                    timestamp=msg["timestamp"],
                    signal_type="topic_marker",
                    strength=0.8,  # High confidence for explicit markers
                    reason=f"Topic marker detected: '{match.group()}'",
                    metadata={"marker": match.group(), "position": match.start()},
                )

        return None

    def _score_signal_cluster(self, signals: list[BoundarySignal]) -> float:
        """
        Score a cluster of boundary signals.

        Combines multiple signal types with weights.
        """
        if not signals:
            return 0.0

        # Group by type
        semantic_signals = [s for s in signals if s.signal_type == "semantic"]
        temporal_signals = [s for s in signals if s.signal_type == "temporal"]
        marker_signals = [s for s in signals if s.signal_type == "topic_marker"]

        # Calculate component scores (max strength per type)
        semantic_score = (
            max(s.strength for s in semantic_signals) if semantic_signals else 0.0
        )
        temporal_score = (
            max(s.strength for s in temporal_signals) if temporal_signals else 0.0
        )
        marker_score = (
            max(s.strength for s in marker_signals) if marker_signals else 0.0
        )

        # Weighted combination
        combined = (
            semantic_score * self.SEMANTIC_WEIGHT
            + temporal_score * self.TEMPORAL_WEIGHT
            + marker_score * self.TOPIC_MARKER_WEIGHT
        )

        # Bonus for multiple signal types (high confidence)
        signal_types = len(
            {s.signal_type for s in signals}
        )  # Count unique signal types
        if signal_types >= 2:
            combined *= 1.2  # 20% bonus for multi-signal confirmation
        if signal_types >= 3:
            combined *= 1.1  # Additional 10% for all three types

        return min(combined, 1.0)  # Cap at 1.0

    def _cluster_signals(
        self, signals: list[BoundarySignal], time_window: int
    ) -> list[list[BoundarySignal]]:
        """
        Group signals that occur close together in time.

        Returns list of signal clusters.
        """
        if not signals:
            return []

        # Sort by timestamp
        sorted_signals = sorted(signals, key=lambda s: s.timestamp)

        clusters = []
        current_cluster = [sorted_signals[0]]

        for signal in sorted_signals[1:]:
            # If within time window of last signal in cluster, add to cluster
            if signal.timestamp - current_cluster[-1].timestamp <= time_window:
                current_cluster.append(signal)
            else:
                # Start new cluster
                clusters.append(current_cluster)
                current_cluster = [signal]

        # Don't forget the last cluster
        if current_cluster:
            clusters.append(current_cluster)

        return clusters

    async def _get_or_embed(self, msg: dict[str, Any], text: str) -> list[float] | None:
        """
        Get embedding for message, using cached embedding if available.
        """
        # Check if message has embedding stored
        msg_id = msg.get("id")
        if msg_id and msg.get("embedding"):
            try:
                return json.loads(msg["embedding"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Generate new embedding
        try:
            return await self.gemini.embed_text(text)
        except Exception as e:
            LOGGER.warning(f"Failed to generate embedding: {e}")
            return None

    @staticmethod
    def _extract_text(msg: dict[str, Any]) -> str:
        """Extract text content from message."""
        # Handle both message dict formats
        if "text" in msg:
            return msg["text"]
        if "content" in msg:
            return msg["content"]
        return ""

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0

        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)
