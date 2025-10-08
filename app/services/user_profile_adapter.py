"""
Adapter to make UnifiedFactRepository compatible with memory tools.

This adapter provides the UserProfileStore interface while using
UnifiedFactRepository as the backend. This allows gradual migration
without rewriting all the memory tools.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.repositories.fact_repository import UnifiedFactRepository

logger = logging.getLogger(__name__)


class UserProfileStoreAdapter:
    """
    Adapter that wraps UnifiedFactRepository to provide UserProfileStore interface.

    This allows memory tools to continue using the old API while we migrate
    to the unified fact storage system.
    """

    def __init__(self, db_path: str | Path):
        """Initialize adapter with UnifiedFactRepository."""
        self._fact_repo = UnifiedFactRepository(db_path)
        self._db_path = db_path  # For compatibility with old code

    async def init(self) -> None:
        """Initialize (no-op for compatibility)."""
        # UnifiedFactRepository doesn't need initialization
        # The facts table already exists from migration
        pass

    async def add_fact(
        self,
        user_id: int,
        chat_id: int,
        fact_type: str,
        fact_key: str,
        fact_value: str,
        confidence: float,
        evidence_text: str | None = None,
        source_message_id: int | None = None,
    ) -> int:
        """
        Add a fact (adapter method).

        Maps old API to UnifiedFactRepository:
        - fact_type → fact_category
        - Determines entity type based on user_id sign
        - Sets chat_context appropriately
        """
        # Auto-detect if this is a chat fact (user_id < 0 means it's actually a chat_id)
        entity_id = user_id
        chat_context = chat_id if user_id > 0 else None

        return await self._fact_repo.add_fact(
            entity_id=entity_id,
            fact_category=fact_type,  # Direct mapping for now
            fact_key=fact_key,
            fact_value=fact_value,
            confidence=confidence,
            chat_context=chat_context,
            evidence_text=evidence_text,
            source_message_id=source_message_id,
        )

    async def get_facts(
        self,
        user_id: int,
        chat_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get facts (adapter method).

        Maps UnifiedFactRepository response to old format.
        """
        entity_id = user_id
        chat_context = chat_id if user_id > 0 else None

        facts = await self._fact_repo.get_facts(
            entity_id=entity_id,
            chat_context=chat_context,
            limit=limit,
        )

        # Map new schema to old schema format
        adapted_facts = []
        for fact in facts:
            adapted_fact = {
                "id": fact["id"],
                "user_id": fact["entity_id"],
                "chat_id": fact.get("chat_context") or chat_id,
                "fact_type": fact["fact_category"],  # fact_category → fact_type
                "fact_key": fact["fact_key"],
                "fact_value": fact["fact_value"],
                "confidence": fact["confidence"],
                "evidence_text": fact.get("evidence_text"),
                "source_message_id": fact.get("source_message_id"),
                "is_active": fact["is_active"],
                "created_at": fact["created_at"],
                "updated_at": fact["updated_at"],
            }
            adapted_facts.append(adapted_fact)

        return adapted_facts
