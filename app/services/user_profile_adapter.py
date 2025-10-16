"""
Adapter to make UnifiedFactRepository compatible with memory tools.

This adapter provides the UserProfileStore interface while using
UnifiedFactRepository as the backend. This allows gradual migration
without rewriting all the memory tools.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

from app.repositories.fact_repository import UnifiedFactRepository

logger = logging.getLogger(__name__)


def _coerce_timestamp(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _augment_profile(profile: dict[str, Any]) -> dict[str, Any]:
    result = dict(profile)
    result["membership_status"] = result.get("membership_status") or "unknown"

    created_at = _coerce_timestamp(result.get("created_at"))
    if created_at is not None:
        result["created_at"] = created_at

    last_seen = _coerce_timestamp(result.get("last_seen"))
    if last_seen is not None:
        result["last_seen"] = last_seen

    result.setdefault("last_interaction_at", result.get("last_seen"))

    return result


class UserProfileStoreAdapter:
    """
    Adapter that wraps UnifiedFactRepository to provide UserProfileStore interface.

    This allows memory tools to continue using the old API while we migrate
    to the unified fact storage system.
    """

    def __init__(self, db_path: str | Path):
        """Initialize adapter with UnifiedFactRepository."""
        self._db_path = Path(db_path)
        self._fact_repo = UnifiedFactRepository(self._db_path)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    @property
    def fact_repository(self) -> UnifiedFactRepository:
        """Expose underlying fact repository for advanced operations."""
        return self._fact_repo

    async def init(self) -> None:
        """Ensure compatibility columns exist."""
        async with self._init_lock:
            if self._initialized:
                return

            async with aiosqlite.connect(self._db_path) as db:
                try:
                    await db.execute(
                        "ALTER TABLE user_profiles ADD COLUMN pronouns TEXT"
                    )
                    await db.commit()
                    logger.info("Added pronouns column to user_profiles (adapter)")
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE user_profiles ADD COLUMN membership_status TEXT DEFAULT 'unknown'"
                    )
                    await db.commit()
                    logger.info(
                        "Added membership_status column to user_profiles (adapter)"
                    )
                except aiosqlite.OperationalError:
                    pass

            self._initialized = True

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
        fact_type: str | None = None,
        limit: int = 100,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Get facts (adapter method).

        Maps UnifiedFactRepository response to old format.

        Args:
            user_id: User ID (or chat ID if negative)
            chat_id: Chat context for user facts
            fact_type: Optional filter by fact type (maps to fact_category)
            limit: Max number of facts to retrieve
            min_confidence: Minimum confidence threshold (0.0-1.0)
        """
        entity_id = user_id
        chat_context = chat_id if user_id > 0 else None

        # Convert fact_type to categories list if provided
        categories = [fact_type] if fact_type else None

        facts = await self._fact_repo.get_facts(
            entity_id=entity_id,
            chat_context=chat_context,
            categories=categories,
            limit=limit,
            min_confidence=min_confidence,
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

    async def get_fact_count(self, user_id: int, chat_id: int) -> int:
        """Get count of active facts for a user."""
        entity_id = user_id
        chat_context = chat_id if user_id > 0 else None
        entity_type = "chat" if user_id < 0 else "user"

        async with aiosqlite.connect(self._db_path) as db:
            query = """
                SELECT COUNT(*) FROM facts 
                WHERE entity_type = ? AND entity_id = ? AND is_active = 1
            """
            params: list[Any] = [entity_type, entity_id]

            if chat_context is not None:
                query += " AND chat_context = ?"
                params.append(chat_context)

            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_or_create_profile(
        self,
        user_id: int,
        chat_id: int,
        display_name: str | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """
        Get existing profile or create a new one.

        Returns profile dict with all fields.
        """
        await self.init()
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # Try to get existing profile
            async with db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                updates = [
                    "last_seen = ?",
                    "updated_at = ?",
                    "membership_status = ?",
                ]
                params: list[Any] = [now, now, "member"]

                if display_name:
                    updates.append("display_name = ?")
                    params.append(display_name)
                if username:
                    updates.append("username = ?")
                    params.append(username)

                params.extend([user_id, chat_id])

                await db.execute(
                    f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ? AND chat_id = ?",
                    params,
                )
                await db.commit()

                async with db.execute(
                    "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                    (user_id, chat_id),
                ) as cursor:
                    row = await cursor.fetchone()
                    return _augment_profile(dict(row)) if row else {}

            await db.execute(
                """
                INSERT INTO user_profiles 
                (user_id, chat_id, display_name, username, pronouns, membership_status,
                 first_seen, last_seen, interaction_count, message_count,
                 profile_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    chat_id,
                    display_name,
                    username,
                    None,
                    "member",
                    now,
                    now,
                    0,
                    0,
                    1,
                    now,
                    now,
                ),
            )
            await db.commit()

            async with db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()
                return _augment_profile(dict(row)) if row else {}

    async def get_profile(
        self, user_id: int, chat_id: int | None = None, limit: int | None = None
    ) -> dict[str, Any] | None:
        """Get profile for a user in a chat, or None if not exists."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            if chat_id is None:
                # Get user's most recent profile as base
                async with db.execute(
                    """
                    SELECT * FROM user_profiles 
                    WHERE user_id = ?
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    return _augment_profile(dict(row))
            else:
                # Get specific profile
                async with db.execute(
                    "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                    (user_id, chat_id),
                ) as cursor:
                    row = await cursor.fetchone()
                    return _augment_profile(dict(row)) if row else None

    async def update_interaction_count(
        self, user_id: int, chat_id: int, thread_id: int | None = None
    ) -> None:
        """Increment interaction counters and refresh last seen metadata."""
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            updates = [
                "interaction_count = interaction_count + 1",
                "message_count = message_count + 1",
                "last_seen = ?",
                "updated_at = ?",
                "membership_status = 'member'",
            ]
            params: list[Any] = [now, now]

            if thread_id is not None:
                updates.append("last_active_thread = ?")
                params.append(thread_id)

            params.extend([user_id, chat_id])

            await db.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ? AND chat_id = ?",
                params,
            )
            await db.commit()

    async def update_profile(self, user_id: int, chat_id: int, **kwargs: Any) -> None:
        """Update profile fields with automatic timestamp refresh."""
        await self.init()

        if not kwargs:
            return

        now = int(time.time())
        kwargs["updated_at"] = now

        columns = [f"{key} = ?" for key in kwargs.keys()]
        params = list(kwargs.values())
        params.extend([user_id, chat_id])

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE user_profiles SET {', '.join(columns)} WHERE user_id = ? AND chat_id = ?",
                params,
            )
            await db.commit()

    async def list_chat_users(
        self,
        chat_id: int,
        limit: int | None = None,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        """Return known users in a chat ordered by activity."""
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT user_id, display_name, username, pronouns, membership_status,
                       interaction_count, message_count, last_seen, created_at, updated_at
                FROM user_profiles
                WHERE chat_id = ?
            """
            params: list[Any] = [chat_id]

            if not include_inactive:
                query += " AND membership_status IN ('member', 'administrator', 'creator')"

            query += """
                ORDER BY 
                    CASE membership_status
                        WHEN 'member' THEN 0
                        WHEN 'administrator' THEN 0
                        WHEN 'creator' THEN 0
                        ELSE 1
                    END,
                    last_seen DESC
            """

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [_augment_profile(dict(row)) for row in rows]

    async def get_relationships(
        self, user_id: int, chat_id: int, min_strength: float = 0.0
    ) -> list[dict[str, Any]]:
        """Get relationships for a user, sorted by strength."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM user_relationships 
                WHERE user_id = ? AND chat_id = ? AND strength >= ?
                ORDER BY strength DESC, interaction_count DESC
                """,
                (user_id, chat_id, min_strength),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_user_summary(
        self,
        user_id: int,
        chat_id: int,
        include_facts: bool = True,
        include_relationships: bool = True,
        min_confidence: float = 0.7,
        max_facts: int = 10,
    ) -> str:
        """
        Generate a compact text summary of a user profile.

        Format: "@username (Name): Summary. Facts: key=value, ... Relationships: label, ..."
        """
        profile = await self.get_profile(user_id, chat_id)
        if not profile:
            return f"User #{user_id} (no profile)"

        parts: list[str] = []

        username = profile.get("username") or ""
        display_name = profile.get("display_name") or ""
        if username and display_name:
            parts.append(f"{username} ({display_name})")
        elif username:
            parts.append(username)
        elif display_name:
            parts.append(display_name)
        else:
            parts.append(f"User #{user_id}")

        pronouns = (profile.get("pronouns") or "").strip()
        if pronouns:
            parts.append(f" [{pronouns}]")

        profile_summary = profile.get("profile_summary")
        if profile_summary:
            parts.append(f": {profile_summary}")

        if include_facts:
            facts = await self.get_facts(
                user_id, chat_id, min_confidence=min_confidence, limit=max_facts
            )
            if facts:
                fact_strs = [
                    f"{f['fact_key']}={f['fact_value']}" for f in facts[:max_facts]
                ]
                parts.append(f". Facts: {', '.join(fact_strs)}")

        if include_relationships:
            relationships = await self.get_relationships(user_id, chat_id)
            if relationships:
                rel_strs = [r["relationship_label"] for r in relationships[:5]]
                parts.append(f". Relationships: {', '.join(rel_strs)}")

        return "".join(parts)

    async def update_pronouns(
        self, user_id: int, chat_id: int, pronouns: str | None
    ) -> None:
        """Set or clear pronouns for a user profile."""
        await self.init()
        await self.get_or_create_profile(user_id, chat_id)

        normalized = pronouns.strip() if pronouns else None
        if normalized == "":
            normalized = None

        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE user_profiles
                SET pronouns = ?, updated_at = ?
                WHERE user_id = ? AND chat_id = ?
                """,
                (normalized, now, user_id, chat_id),
            )
            await db.commit()
