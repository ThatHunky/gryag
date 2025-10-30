"""
Unified Fact Repository - Single source of truth for all facts.

Replaces separate UserProfileStore and ChatProfileRepository with a single
repository that handles both user-level and chat-level facts.

This repository automatically detects entity type:
- Positive IDs → user facts (with chat_context)
- Negative IDs → chat facts (no chat_context)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)


class UnifiedFactRepository:
    """
    Single repository for all fact operations (user and chat facts).

    Auto-detects entity type:
    - entity_id > 0 → user fact
    - entity_id < 0 → chat fact (Telegram chat IDs are negative)
    """

    def __init__(self, db_path: str | Path):
        """Initialize repository with database path."""
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

    async def add_fact(
        self,
        entity_id: int,
        fact_category: str,
        fact_key: str,
        fact_value: str,
        confidence: float = 0.7,
        chat_context: int | None = None,
        evidence_text: str | None = None,
        source_message_id: int | None = None,
        fact_description: str | None = None,
        participant_consensus: float | None = None,
        embedding: list[float] | None = None,
    ) -> int:
        """
        Store a fact (auto-detects user vs chat based on entity_id sign).

        Args:
            entity_id: User ID (positive) or Chat ID (negative)
            fact_category: Category from unified taxonomy
            fact_key: Standardized identifier
            fact_value: The actual fact content
            confidence: Confidence score (0-1)
            chat_context: Chat where learned (only for user facts)
            evidence_text: Supporting quotes
            source_message_id: Message ID where learned
            fact_description: Human-readable summary
            participant_consensus: For chat facts, % agreement
            embedding: Vector embedding for semantic search

        Returns:
            Fact ID
        """
        entity_type: Literal["user", "chat"] = "chat" if entity_id < 0 else "user"

        # Chat facts shouldn't have chat_context
        if entity_type == "chat":
            chat_context = None

        now = int(time.time())
        embedding_json = json.dumps(embedding) if embedding else None

        async with get_db_connection(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO facts (
                    entity_type, entity_id, chat_context,
                    fact_category, fact_key, fact_value, fact_description,
                    confidence, evidence_count, evidence_text, source_message_id,
                    participant_consensus,
                    first_observed, last_reinforced, is_active,
                    created_at, updated_at, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id, chat_context, fact_category, fact_key)
                DO UPDATE SET
                    fact_value = excluded.fact_value,
                    confidence = excluded.confidence,
                    evidence_count = evidence_count + 1,
                    evidence_text = COALESCE(excluded.evidence_text, evidence_text),
                    last_reinforced = excluded.last_reinforced,
                    updated_at = excluded.updated_at,
                    embedding = COALESCE(excluded.embedding, embedding)
                """,
                (
                    entity_type,
                    entity_id,
                    chat_context,
                    fact_category,
                    fact_key,
                    fact_value,
                    fact_description,
                    confidence,
                    1,  # evidence_count
                    evidence_text,
                    source_message_id,
                    participant_consensus,
                    now,  # first_observed
                    now,  # last_reinforced
                    1,  # is_active
                    now,  # created_at
                    now,  # updated_at
                    embedding_json,
                ),
            )
            await db.commit()

            fact_id = cursor.lastrowid

            logger.info(
                f"Stored {entity_type} fact: {fact_category}.{fact_key} = {fact_value[:50]}... "
                f"(entity_id={entity_id}, id={fact_id})"
            )

            return fact_id

    async def get_facts(
        self,
        entity_id: int,
        categories: list[str] | None = None,
        chat_context: int | None = None,
        include_inactive: bool = False,
        limit: int = 100,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve facts for an entity (user or chat).

        Args:
            entity_id: User ID (positive) or Chat ID (negative)
            categories: Filter by categories (optional)
            chat_context: For user facts, filter by chat context (optional)
            include_inactive: Include soft-deleted facts
            limit: Max results
            min_confidence: Minimum confidence threshold

        Returns:
            List of fact dictionaries
        """
        entity_type: Literal["user", "chat"] = "chat" if entity_id < 0 else "user"

        query = """
            SELECT 
                id, entity_type, entity_id, chat_context,
                fact_category, fact_key, fact_value, fact_description,
                confidence, evidence_count, evidence_text, source_message_id,
                participant_consensus,
                first_observed, last_reinforced, is_active, decay_rate,
                created_at, updated_at, embedding
            FROM facts
            WHERE entity_type = ? AND entity_id = ?
        """
        params: list[Any] = [entity_type, entity_id]

        if chat_context is not None:
            query += " AND chat_context = ?"
            params.append(chat_context)

        if not include_inactive:
            query += " AND is_active = 1"

        if categories:
            placeholders = ",".join("?" * len(categories))
            query += f" AND fact_category IN ({placeholders})"
            params.extend(categories)

        if min_confidence > 0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY confidence DESC, last_reinforced DESC LIMIT ?"
        params.append(limit)

        async with get_db_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        facts = []
        for row in rows:
            fact = dict(row)
            # Parse embedding JSON back to list
            if fact.get("embedding"):
                try:
                    fact["embedding"] = json.loads(fact["embedding"])
                except (json.JSONDecodeError, TypeError):
                    fact["embedding"] = None
            facts.append(fact)

        logger.debug(
            f"Retrieved {len(facts)} facts for {entity_type} {entity_id} "
            f"(categories={categories}, min_confidence={min_confidence})"
        )

        return facts

    async def get_fact_by_id(self, fact_id: int) -> dict[str, Any] | None:
        """Get a single fact by ID."""
        async with get_db_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,))
            row = await cursor.fetchone()

        if not row:
            return None

        fact = dict(row)
        if fact.get("embedding"):
            try:
                fact["embedding"] = json.loads(fact["embedding"])
            except (json.JSONDecodeError, TypeError):
                fact["embedding"] = None

        return fact

    async def update_fact(
        self,
        fact_id: int,
        fact_value: str | None = None,
        confidence: float | None = None,
        evidence_text: str | None = None,
        fact_description: str | None = None,
        embedding: list[float] | None = None,
    ) -> bool:
        """
        Update an existing fact.

        Returns:
            True if updated, False if not found
        """
        updates = []
        params: list[Any] = []

        if fact_value is not None:
            updates.append("fact_value = ?")
            params.append(fact_value)

        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)

        if evidence_text is not None:
            updates.append("evidence_text = ?")
            params.append(evidence_text)

        if fact_description is not None:
            updates.append("fact_description = ?")
            params.append(fact_description)

        if embedding is not None:
            updates.append("embedding = ?")
            params.append(json.dumps(embedding))

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(int(time.time()))

        updates.append("last_reinforced = ?")
        params.append(int(time.time()))

        params.append(fact_id)

        async with get_db_connection(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE facts SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            await db.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(f"Updated fact {fact_id}")
        else:
            logger.warning(f"Fact {fact_id} not found for update")

        return updated

    async def delete_fact(self, fact_id: int, soft: bool = True) -> bool:
        """
        Delete a fact (soft or hard).

        Args:
            fact_id: Fact ID to delete
            soft: If True, set is_active=0; if False, actually delete row

        Returns:
            True if deleted, False if not found
        """
        async with get_db_connection(self.db_path) as db:
            if soft:
                cursor = await db.execute(
                    "UPDATE facts SET is_active = 0, updated_at = ? WHERE id = ?",
                    (int(time.time()), fact_id),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM facts WHERE id = ?",
                    (fact_id,),
                )
            await db.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"{'Soft-' if soft else ''}deleted fact {fact_id}")
        else:
            logger.warning(f"Fact {fact_id} not found for deletion")

        return deleted

    async def delete_all_facts(
        self,
        entity_id: int,
        chat_context: int | None = None,
        soft: bool = True,
    ) -> int:
        """
        Delete all facts for an entity.

        Args:
            entity_id: User ID or Chat ID
            chat_context: For user facts, delete only from specific chat
            soft: If True, set is_active=0; if False, actually delete rows

        Returns:
            Number of facts deleted
        """
        entity_type: Literal["user", "chat"] = "chat" if entity_id < 0 else "user"

        params: list[Any] = [entity_type, entity_id]
        where_clause = "entity_type = ? AND entity_id = ?"

        if chat_context is not None:
            where_clause += " AND chat_context = ?"
            params.append(chat_context)

        async with get_db_connection(self.db_path) as db:
            if soft:
                params.insert(0, int(time.time()))
                cursor = await db.execute(
                    f"UPDATE facts SET is_active = 0, updated_at = ? WHERE {where_clause}",
                    params,
                )
            else:
                cursor = await db.execute(
                    f"DELETE FROM facts WHERE {where_clause}",
                    params,
                )
            await db.commit()
            count = cursor.rowcount

        logger.info(
            f"{'Soft-' if soft else ''}deleted {count} facts for "
            f"{entity_type} {entity_id}"
        )

        return count

    async def search_facts(
        self,
        query: str,
        entity_id: int | None = None,
        categories: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search facts by text query (simple text search).

        For semantic search, use embedding-based search separately.

        Args:
            query: Search query
            entity_id: Filter by entity (optional)
            categories: Filter by categories (optional)
            limit: Max results

        Returns:
            List of matching facts
        """
        query_lower = f"%{query.lower()}%"

        sql = """
            SELECT * FROM facts
            WHERE is_active = 1
            AND (
                LOWER(fact_key) LIKE ?
                OR LOWER(fact_value) LIKE ?
                OR LOWER(fact_description) LIKE ?
                OR LOWER(evidence_text) LIKE ?
            )
        """
        params: list[Any] = [query_lower, query_lower, query_lower, query_lower]

        if entity_id is not None:
            entity_type = "chat" if entity_id < 0 else "user"
            sql += " AND entity_type = ? AND entity_id = ?"
            params.extend([entity_type, entity_id])

        if categories:
            placeholders = ",".join("?" * len(categories))
            sql += f" AND fact_category IN ({placeholders})"
            params.extend(categories)

        sql += " ORDER BY confidence DESC, last_reinforced DESC LIMIT ?"
        params.append(limit)

        async with get_db_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()

        facts = []
        for row in rows:
            fact = dict(row)
            if fact.get("embedding"):
                try:
                    fact["embedding"] = json.loads(fact["embedding"])
                except (json.JSONDecodeError, TypeError):
                    fact["embedding"] = None
            facts.append(fact)

        return facts

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about facts in the repository."""
        async with get_db_connection(self.db_path) as db:
            # Total counts
            cursor = await db.execute(
                "SELECT entity_type, COUNT(*) FROM facts WHERE is_active = 1 GROUP BY entity_type"
            )
            entity_counts = dict(await cursor.fetchall())

            # Category counts
            cursor = await db.execute(
                "SELECT fact_category, COUNT(*) FROM facts WHERE is_active = 1 GROUP BY fact_category"
            )
            category_counts = dict(await cursor.fetchall())

            # Average confidence
            cursor = await db.execute(
                "SELECT AVG(confidence) FROM facts WHERE is_active = 1"
            )
            avg_confidence = (await cursor.fetchone())[0] or 0.0

        return {
            "total_facts": sum(entity_counts.values()),
            "user_facts": entity_counts.get("user", 0),
            "chat_facts": entity_counts.get("chat", 0),
            "categories": category_counts,
            "avg_confidence": round(avg_confidence, 3),
        }
