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
from typing import Any

from app.infrastructure.db_utils import get_db_connection
from app.repositories.fact_repository import UnifiedFactRepository
from app.services import telemetry
from app.services.redis_types import RedisLike

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

    def __init__(self, database_url: str, redis_client: RedisLike | None = None):
        """
        Initialize adapter with UnifiedFactRepository.

        Args:
            database_url: PostgreSQL connection string
            redis_client: Optional Redis client for caching
        """
        self._database_url = str(database_url)
        self._fact_repo = UnifiedFactRepository(database_url)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._redis = redis_client
        self._cache_ttl = 600  # 10 minutes

    @property
    def fact_repository(self) -> UnifiedFactRepository:
        """Expose underlying fact repository for advanced operations."""
        return self._fact_repo

    async def init(self) -> None:
        """Ensure compatibility columns exist."""
        async with self._init_lock:
            if self._initialized:
                return

            async with get_db_connection(self._database_url) as conn:
                try:
                    await conn.execute(
                        "ALTER TABLE user_profiles ADD COLUMN pronouns TEXT"
                    )
                    logger.info("Added pronouns column to user_profiles (adapter)")
                except Exception as e:
                    # Ignore if column already exists (Postgres or SQLite)
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        pass
                    else:
                        logger.warning(f"Failed to add pronouns column: {e}")

                try:
                    await conn.execute(
                        "ALTER TABLE user_profiles ADD COLUMN membership_status TEXT DEFAULT 'unknown'"
                    )
                    logger.info(
                        "Added membership_status column to user_profiles (adapter)"
                    )
                except Exception as e:
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        pass
                    else:
                        logger.warning(f"Failed to add membership_status column: {e}")

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

        params: list[Any] = [entity_type, entity_id]

        if chat_context is not None:
            query = """
                SELECT COUNT(*) as count FROM facts
                WHERE entity_type = $1 AND entity_id = $3 AND chat_context = $2 AND is_active = 1
            """
            params.insert(1, chat_context)
        else:
            query = """
                SELECT COUNT(*) as count FROM facts
                WHERE entity_type = $1 AND entity_id = $2 AND is_active = 1
            """

        async with get_db_connection(self._database_url) as conn:
            row = await conn.fetchrow(query, *params)
            return row["count"] if row else 0

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

        async with get_db_connection(self._database_url) as conn:
            # Try to get existing profile
            query = "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2"
            params = (user_id, chat_id)

            row = await conn.fetchrow(query, *params)

            if row:
                # Invalidate cache before updating
                await self._invalidate_profile_cache(user_id, chat_id)

                updates = [
                    "last_seen = $1",
                    "updated_at = $2",
                    "membership_status = $3",
                ]
                update_params: list[Any] = [now, now, "member"]

                param_idx = 4
                if display_name:
                    updates.append(f"display_name = ${param_idx}")
                    update_params.append(display_name)
                    param_idx += 1
                if username:
                    updates.append(f"username = ${param_idx}")
                    update_params.append(username)
                    param_idx += 1

                update_params.extend([user_id, chat_id])
                where_param_idx = param_idx

                # Construct UPDATE query
                query = f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}"

                await conn.execute(query, *update_params)

                query = "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2"
                params = (user_id, chat_id)

                row = await conn.fetchrow(query, *params)
                if row:
                    profile = _augment_profile(dict(row))
                    # Cache the result
                    await self._cache_profile(user_id, chat_id, profile)
                    return profile
                return {}

            query = """
                INSERT INTO user_profiles
                (user_id, chat_id, display_name, username, pronouns, membership_status,
                 first_seen, last_seen, interaction_count, message_count,
                 profile_version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING *
                """
            params = (
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
            )

            row = await conn.fetchrow(query, *params)
            return _augment_profile(dict(row)) if row else {}

    def _get_cache_key(self, user_id: int, chat_id: int | None) -> str:
        """Generate Redis cache key for profile."""
        if chat_id is None:
            return f"profile:user:{user_id}:chat:null"
        return f"profile:user:{user_id}:chat:{chat_id}"

    async def _get_cached_profile(
        self, user_id: int, chat_id: int | None
    ) -> dict[str, Any] | None:
        """Get cached profile from Redis."""
        if self._redis is None:
            return None

        try:
            import json

            key = self._get_cache_key(user_id, chat_id)
            cached_data = await self._redis.get(key)
            if cached_data is None:
                return None

            if isinstance(cached_data, bytes):
                cached_data = cached_data.decode("utf-8")

            return json.loads(cached_data)
        except Exception as exc:
            logger.warning(f"Redis profile cache get failed: {exc}")
            return None

    async def _cache_profile(
        self, user_id: int, chat_id: int | None, profile: dict[str, Any]
    ) -> None:
        """Cache profile in Redis."""
        if self._redis is None:
            return

        try:
            import json

            key = self._get_cache_key(user_id, chat_id)
            data = json.dumps(profile)
            await self._redis.set(key, data, ex=self._cache_ttl)
        except Exception as exc:
            logger.warning(f"Redis profile cache set failed: {exc}")

    async def _invalidate_profile_cache(
        self, user_id: int, chat_id: int | None
    ) -> None:
        """Invalidate cached profile."""
        if self._redis is None:
            return

        try:
            key = self._get_cache_key(user_id, chat_id)
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning(f"Redis profile cache invalidate failed: {exc}")

    async def get_profile(
        self, user_id: int, chat_id: int | None = None, limit: int | None = None
    ) -> dict[str, Any] | None:
        """Get profile for a user in a chat, or None if not exists."""
        # Try cache first
        if chat_id is not None:
            cached = await self._get_cached_profile(user_id, chat_id)
            if cached is not None:
                return cached

        async with get_db_connection(self._database_url) as conn:
            if chat_id is None:
                # Get user's most recent profile as base
                query = """
                    SELECT * FROM user_profiles
                    WHERE user_id = $1
                    ORDER BY last_seen DESC
                    LIMIT 1
                """
                params = (user_id,)

                row = await conn.fetchrow(query, *params)
                if not row:
                    return None
                return _augment_profile(dict(row))
            else:
                # Get specific profile
                query = "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2"
                params = (user_id, chat_id)

                row = await conn.fetchrow(query, *params)
                if row:
                    profile = _augment_profile(dict(row))
                    # Cache the result
                    await self._cache_profile(user_id, chat_id, profile)
                    return profile
                return None

    async def update_interaction_count(
        self, user_id: int, chat_id: int, thread_id: int | None = None
    ) -> None:
        """Increment interaction counters and refresh last seen metadata."""
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            updates = [
                "interaction_count = interaction_count + 1",
                "message_count = message_count + 1",
                "last_seen = $1",
                "updated_at = $2",
                "membership_status = 'member'",
            ]
            params: list[Any] = [now, now]
            param_idx = 3

            if thread_id is not None:
                updates.append(f"last_active_thread = ${param_idx}")
                params.append(thread_id)
                param_idx += 1

            params.extend([user_id, chat_id])
            where_param_idx = param_idx

            query = f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}"

            await conn.execute(query, *params)

    async def update_profile(self, user_id: int, chat_id: int, **kwargs: Any) -> None:
        """Update profile fields with automatic timestamp refresh."""
        await self.init()

        if not kwargs:
            return

        now = int(time.time())
        kwargs["updated_at"] = now

        param_idx = 1
        columns = []
        params = []
        for key in kwargs.keys():
            columns.append(f"{key} = ${param_idx}")
            params.append(kwargs[key])
            param_idx += 1

        params.extend([user_id, chat_id])
        where_param_idx = param_idx

        async with get_db_connection(self._database_url) as conn:
            query = f"UPDATE user_profiles SET {', '.join(columns)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}"

            await conn.execute(query, *params)

    async def list_chat_users(
        self,
        chat_id: int,
        limit: int | None = None,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        """Return known users in a chat ordered by activity."""
        await self.init()

        query = """
            SELECT user_id, display_name, username, pronouns, membership_status,
                   interaction_count, message_count, last_seen, created_at, updated_at
            FROM user_profiles
            WHERE chat_id = $1
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
            query += " LIMIT $2"
            params.append(limit)

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(query, *params)
            return [_augment_profile(dict(row)) for row in rows]

    async def get_relationships(
        self, user_id: int, chat_id: int, min_strength: float = 0.0
    ) -> list[dict[str, Any]]:
        """Get relationships for a user, sorted by strength."""
        query = """
            SELECT * FROM user_relationships
            WHERE user_id = $1 AND chat_id = $2 AND strength >= $3
            ORDER BY strength DESC, interaction_count DESC
        """
        params = (user_id, chat_id, min_strength)

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_profiles_needing_summarization(self, limit: int = 50) -> list[int]:
        """Return user IDs that require profile summarization."""
        await self.init()

        query = """
            SELECT DISTINCT p.user_id
            FROM user_profiles p
            WHERE EXISTS (
                SELECT 1 FROM facts f
                WHERE f.entity_type = 'user'
                  AND f.entity_id = p.user_id
                  AND f.is_active = 1
            )
            AND (
                p.summary IS NULL
                OR p.last_seen > COALESCE((SELECT MAX(updated_at) FROM user_profiles WHERE user_id = p.user_id), 0)
            )
            ORDER BY p.message_count DESC
            LIMIT $1
        """
        params = (limit,)

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(query, *params)
            return [row["user_id"] for row in rows]

    async def update_summary(self, user_id: int, summary: str) -> None:
        """Update cached summary text for a user across all chats."""
        await self.init()
        now = int(time.time())

        query = """
            UPDATE user_profiles
            SET summary = $1, updated_at = $2
            WHERE user_id = $3
        """
        params = (summary, now, user_id)

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(query, *params)

        logger.info(
            "Updated summary for user %s (adapter)",
            user_id,
            extra={
                "user_id": user_id,
                "summary_length": len(summary),
            },
        )
        telemetry.increment_counter("profile_summaries_updated")

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

        query = """
            UPDATE user_profiles
            SET pronouns = $1, updated_at = $2
            WHERE user_id = $3 AND chat_id = $4
        """
        params = (normalized, now, user_id, chat_id)

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(query, *params)
