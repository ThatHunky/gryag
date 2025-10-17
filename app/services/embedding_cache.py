"""
Centralized embedding cache to reduce API calls and improve performance.

Provides in-memory LRU cache with optional persistence for text embeddings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import aiosqlite

LOGGER = logging.getLogger(__name__)


class EmbeddingCache:
    """
    In-memory LRU cache for text embeddings with optional SQLite persistence.

    Reduces redundant API calls to embedding services and improves response times.
    """

    def __init__(
        self,
        max_size: int = 10000,
        db_path: Path | str | None = None,
        enable_persistence: bool = True,
    ):
        """
        Initialize embedding cache.

        Args:
            max_size: Maximum number of embeddings to keep in memory
            db_path: Optional path to SQLite DB for persistence
            enable_persistence: Whether to persist cache to disk
        """
        self.max_size = max_size
        self.db_path = Path(db_path) if db_path else None
        self.enable_persistence = enable_persistence and self.db_path is not None

        # In-memory LRU cache: key -> (embedding, timestamp)
        self._cache: OrderedDict[str, tuple[list[float], int]] = OrderedDict()
        self._lock = asyncio.Lock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0

        # Initialization flag
        self._initialized = False

    async def init(self) -> None:
        """Initialize cache and optionally create persistence table."""
        if self._initialized:
            return

        if self.enable_persistence and self.db_path:
            async with aiosqlite.connect(self.db_path) as db:
                # Create embeddings cache table if not exists
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        text_hash TEXT PRIMARY KEY,
                        text_preview TEXT NOT NULL,
                        embedding TEXT NOT NULL,
                        model TEXT,
                        cached_at INTEGER NOT NULL,
                        last_accessed INTEGER NOT NULL,
                        access_count INTEGER DEFAULT 1
                    )
                    """
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_embedding_cache_accessed ON embedding_cache(last_accessed DESC)"
                )
                await db.commit()

            LOGGER.info(
                f"Embedding cache initialized with persistence (max_size={self.max_size})"
            )
        else:
            LOGGER.info(
                f"Embedding cache initialized (memory-only, max_size={self.max_size})"
            )

        self._initialized = True

    @staticmethod
    def _hash_text(text: str) -> str:
        """Generate stable hash for text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def get(self, text: str, model: str = "default") -> list[float] | None:
        """
        Get embedding from cache.

        Args:
            text: Text to get embedding for
            model: Model identifier (for multi-model caching)

        Returns:
            Cached embedding or None if not found
        """
        await self.init()

        cache_key = f"{model}:{self._hash_text(text)}"

        async with self._lock:
            # Check in-memory cache first
            if cache_key in self._cache:
                embedding, _ = self._cache[cache_key]
                # Move to end (LRU)
                self._cache.move_to_end(cache_key)
                self._hits += 1

                LOGGER.debug(
                    f"Embedding cache hit (in-memory)",
                    extra={"text_preview": text[:50], "model": model},
                )
                return embedding

        # Check persistent cache
        if self.enable_persistence and self.db_path:
            text_hash = self._hash_text(text)

            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT embedding, cached_at FROM embedding_cache WHERE text_hash = ? AND model = ?",
                    (text_hash, model),
                ) as cursor:
                    row = await cursor.fetchone()

                if row:
                    embedding_json, cached_at = row
                    try:
                        embedding = json.loads(embedding_json)

                        # Update access tracking
                        now = int(time.time())
                        await db.execute(
                            "UPDATE embedding_cache SET last_accessed = ?, access_count = access_count + 1 WHERE text_hash = ? AND model = ?",
                            (now, text_hash, model),
                        )
                        await db.commit()

                        # Add to in-memory cache
                        async with self._lock:
                            self._cache[cache_key] = (embedding, cached_at)
                            self._evict_if_needed()
                            self._hits += 1

                        LOGGER.debug(
                            f"Embedding cache hit (persistent)",
                            extra={"text_preview": text[:50], "model": model},
                        )
                        return embedding
                    except json.JSONDecodeError:
                        LOGGER.warning(
                            f"Failed to decode cached embedding",
                            extra={"text_hash": text_hash},
                        )

        # Cache miss
        async with self._lock:
            self._misses += 1

        return None

    async def put(
        self, text: str, embedding: list[float], model: str = "default"
    ) -> None:
        """
        Store embedding in cache.

        Args:
            text: Text that was embedded
            embedding: Embedding vector
            model: Model identifier
        """
        await self.init()

        cache_key = f"{model}:{self._hash_text(text)}"
        now = int(time.time())

        async with self._lock:
            # Add to in-memory cache
            self._cache[cache_key] = (embedding, now)
            self._evict_if_needed()

        # Persist if enabled
        if self.enable_persistence and self.db_path:
            text_hash = self._hash_text(text)
            text_preview = text[:200]  # Store preview for debugging
            embedding_json = json.dumps(embedding)

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO embedding_cache (text_hash, text_preview, embedding, model, cached_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(text_hash) DO UPDATE SET
                        embedding = excluded.embedding,
                        last_accessed = excluded.last_accessed,
                        access_count = access_count + 1
                    """,
                    (text_hash, text_preview, embedding_json, model, now, now),
                )
                await db.commit()

    def _evict_if_needed(self) -> None:
        """Evict oldest entry if cache is full (must hold lock)."""
        if len(self._cache) > self.max_size:
            # Remove oldest (first item in OrderedDict)
            self._cache.popitem(last=False)
            self._evictions += 1

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        async with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": len(self._cache),
                "max_size": self.max_size,
                "hit_rate": hit_rate,
            }

    async def clear(self) -> None:
        """Clear in-memory cache."""
        async with self._lock:
            self._cache.clear()
        LOGGER.info("Embedding cache cleared")

    async def prune_persistent(self, retention_days: int = 30) -> int:
        """
        Remove old entries from persistent cache.

        Args:
            retention_days: Keep entries accessed in last N days

        Returns:
            Number of entries removed
        """
        if not self.enable_persistence or not self.db_path:
            return 0

        cutoff = int(time.time()) - (retention_days * 86400)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM embedding_cache WHERE last_accessed < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount or 0
            await db.commit()

        if deleted > 0:
            LOGGER.info(
                f"Pruned {deleted} old embeddings from cache (retention: {retention_days} days)"
            )

        return deleted


# Global cache instance (initialized on first use)
_global_cache: EmbeddingCache | None = None
_cache_lock = asyncio.Lock()


async def get_global_cache(
    db_path: Path | str | None = None,
    max_size: int = 10000,
    enable_persistence: bool = True,
) -> EmbeddingCache:
    """
    Get or create global embedding cache instance.

    Args:
        db_path: Path to database (used only on first call)
        max_size: Maximum cache size (used only on first call)
        enable_persistence: Enable persistent caching (used only on first call)

    Returns:
        Shared EmbeddingCache instance
    """
    global _global_cache

    async with _cache_lock:
        if _global_cache is None:
            _global_cache = EmbeddingCache(
                max_size=max_size,
                db_path=db_path,
                enable_persistence=enable_persistence,
            )
            await _global_cache.init()

        return _global_cache
