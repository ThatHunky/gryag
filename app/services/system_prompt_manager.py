"""System Prompt Manager for custom admin-configured prompts."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
from app.infrastructure.query_converter import convert_query_to_postgres
from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class SystemPrompt:
    """Represents a custom system prompt."""

    id: int
    admin_id: int
    chat_id: int | None
    scope: str  # 'global', 'chat', 'personal'
    prompt_text: str
    is_active: bool
    version: int
    notes: str | None
    created_at: int
    updated_at: int
    activated_at: int | None


class SystemPromptManager:
    """Manages custom system prompts for admin configuration.

    Supports:
    - Global prompts (apply everywhere)
    - Chat-specific prompts (override global for specific chat)
    - Personal chat prompts (for direct messages with bot)
    - Version history and rollback
    - Prompt caching for token efficiency
    """

    def __init__(self, database_url: str):
        """Initialize manager.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = str(database_url)

        # Cache for assembled prompts (reduces token overhead)
        self._prompt_cache: dict[int | None, tuple[SystemPrompt | None, float]] = {}
        self._cache_ttl = 3600  # 1 hour cache TTL
        self._last_cache_hit = False

    async def init(self) -> None:
        """Initialize database tables (idempotent)."""
        # Schema is created in db/schema_postgresql.sql, but ensure it exists
        async with get_db_connection(self.database_url) as conn:
            try:
                await conn.execute("SELECT 1 FROM system_prompts LIMIT 1")
                logger.info("system_prompts table exists")
            except asyncpg.PostgresError:
                logger.warning(
                    "system_prompts table missing, it will be created on next schema migration"
                )

    async def get_active_prompt(
        self, chat_id: int | None = None
    ) -> SystemPrompt | None:
        """Get the active system prompt for a chat.

        Precedence:
        1. Chat-specific prompt (if chat_id provided)
        2. Global prompt
        3. None (use default hardcoded prompt)

        Uses caching to reduce database lookups.

        Args:
            chat_id: Telegram chat ID. None for global context.

        Returns:
            Active SystemPrompt or None if no custom prompt
        """
        cache_key = chat_id
        now = time.time()

        cached_entry = self._prompt_cache.get(cache_key)
        if cached_entry:
            prompt_obj, cached_at = cached_entry
            if now - cached_at < self._cache_ttl:
                self._last_cache_hit = True
                return prompt_obj
            self._prompt_cache.pop(cache_key, None)

        # Try using cached global prompt for chat-specific requests
        if chat_id is not None:
            global_cached = self._prompt_cache.get(None)
            if global_cached:
                prompt_obj, cached_at = global_cached
                if now - cached_at < self._cache_ttl:
                    self._cache_prompt(chat_id, prompt_obj)
                    self._last_cache_hit = True
                    return prompt_obj

        self._last_cache_hit = False

        async with get_db_connection(self.database_url) as conn:
            if chat_id is not None:
                query, params = convert_query_to_postgres(
                    """
                    SELECT * FROM system_prompts
                    WHERE chat_id = $1 AND is_active = 1 AND scope = 'chat'
                    ORDER BY activated_at DESC
                    LIMIT 1
                    """,
                    (chat_id,),
                )
                row = await conn.fetchrow(query, *params)
                if row:
                    prompt = self._row_to_prompt(row)
                    self._cache_prompt(chat_id, prompt)
                    return prompt

            query, params = convert_query_to_postgres(
                """
                SELECT * FROM system_prompts
                WHERE chat_id IS NULL AND is_active = 1 AND scope = 'global'
                ORDER BY activated_at DESC
                LIMIT 1
                """,
                (),
            )
            row = await conn.fetchrow(query, *params)
            if row:
                prompt = self._row_to_prompt(row)
                # Cache for global key and requesting chat (if any)
                self._cache_prompt(None, prompt)
                if chat_id is not None:
                    self._cache_prompt(chat_id, prompt)
                return prompt

            # No active prompts found; cache sentinel for this chat
            self._cache_prompt(chat_id, None)
            return None

    async def set_prompt(
        self,
        admin_id: int,
        prompt_text: str,
        chat_id: int | None = None,
        scope: str = "global",
        notes: str | None = None,
    ) -> SystemPrompt:
        """Set a new system prompt.

        This deactivates any existing active prompt for the same scope/chat
        and creates a new active prompt (versioning for rollback).

        Args:
            admin_id: Telegram user ID of admin
            prompt_text: The system prompt text
            chat_id: Chat ID for chat-specific prompts, None for global
            scope: 'global', 'chat', or 'personal'
            notes: Optional admin notes

        Returns:
            Created SystemPrompt
        """
        if scope == "chat" and chat_id is None:
            raise ValueError("chat_id required for scope='chat'")

        if scope == "global":
            chat_id = None  # Enforce NULL for global

        now = int(time.time())

        async with get_db_connection(self.database_url) as conn:
            # Deactivate existing active prompts for this scope/chat
            query, params = convert_query_to_postgres(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = $1
                WHERE chat_id IS NOT DISTINCT FROM $2 AND scope = $3 AND is_active = 1
                """,
                (now, chat_id, scope),
            )
            await conn.execute(query, *params)

            # Get next version number
            query, params = convert_query_to_postgres(
                """
                SELECT COALESCE(MAX(version), 0) + 1 as next_version
                FROM system_prompts
                WHERE chat_id IS NOT DISTINCT FROM $1 AND scope = $2
                """,
                (chat_id, scope),
            )
            row = await conn.fetchrow(query, *params)
            next_version = row["next_version"] if row else 1

            # Insert new active prompt
            query, params = convert_query_to_postgres(
                """
                INSERT INTO system_prompts (
                    admin_id, chat_id, scope, prompt_text,
                    is_active, version, notes,
                    created_at, updated_at, activated_at
                ) VALUES ($1, $2, $3, $4, 1, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                (
                    admin_id,
                    chat_id,
                    scope,
                    prompt_text,
                    next_version,
                    notes,
                    now,
                    now,
                    now,
                ),
            )
            row = await conn.fetchrow(query, *params)
            prompt_id = row["id"] if row else 0

            logger.info(
                f"Set system prompt: admin={admin_id}, scope={scope}, "
                f"chat_id={chat_id}, version={next_version}, id={prompt_id}"
            )

            # Fetch and return created prompt
            query, params = convert_query_to_postgres(
                "SELECT * FROM system_prompts WHERE id = $1", (prompt_id,)
            )
            row = await conn.fetchrow(query, *params)
            if not row:
                raise RuntimeError(f"Failed to fetch created prompt {prompt_id}")
            prompt = self._row_to_prompt(row)
            if scope == "global":
                self._invalidate_cache()
                self._cache_prompt(None, prompt)
            else:
                self._invalidate_cache(chat_id)
                self._cache_prompt(chat_id, prompt)
            return prompt

    async def reset_to_default(
        self, admin_id: int, chat_id: int | None = None, scope: str = "global"
    ) -> bool:
        """Reset to default system prompt by deactivating custom prompts.

        Args:
            admin_id: Telegram user ID of admin (for audit)
            chat_id: Chat ID for chat-specific reset, None for global
            scope: 'global', 'chat', or 'personal'

        Returns:
            True if any prompts were deactivated
        """
        if scope == "global":
            chat_id = None

        now = int(time.time())

        async with get_db_connection(self.database_url) as conn:
            query, params = convert_query_to_postgres(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = $1
                WHERE chat_id IS NOT DISTINCT FROM $2 AND scope = $3 AND is_active = 1
                """,
                (now, chat_id, scope),
            )
            result = await conn.execute(query, *params)
            count = int(result.split()[-1]) if result.split()[-1].isdigit() else 0

            if count > 0:
                logger.info(
                    f"Reset system prompt: admin={admin_id}, scope={scope}, "
                    f"chat_id={chat_id}, deactivated={count}"
                )
                if scope == "global":
                    self._invalidate_cache()
                else:
                    self._invalidate_cache(chat_id)

            return count > 0

    async def get_prompt_history(
        self, chat_id: int | None = None, scope: str = "global", limit: int = 10
    ) -> list[SystemPrompt]:
        """Get version history of prompts.

        Args:
            chat_id: Chat ID filter, None for global
            scope: Scope filter
            limit: Max number of versions to return

        Returns:
            List of SystemPrompts ordered by version (newest first)
        """
        if scope == "global":
            chat_id = None

        query, params = convert_query_to_postgres(
            """
            SELECT * FROM system_prompts
            WHERE chat_id IS NOT DISTINCT FROM $1 AND scope = $2
            ORDER BY version DESC
            LIMIT $3
            """,
            (chat_id, scope, limit),
        )
        async with get_db_connection(self.database_url) as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_prompt(row) for row in rows]

    async def activate_version(
        self,
        admin_id: int,
        version: int,
        chat_id: int | None = None,
        scope: str = "global",
    ) -> SystemPrompt | None:
        """Activate a specific version from history (rollback).

        Args:
            admin_id: Telegram user ID of admin (for audit)
            version: Version number to activate
            chat_id: Chat ID context
            scope: Scope context

        Returns:
            Activated SystemPrompt or None if version not found
        """
        if scope == "global":
            chat_id = None

        now = int(time.time())

        async with get_db_connection(self.database_url) as conn:
            # Find the target version
            query, params = convert_query_to_postgres(
                """
                SELECT * FROM system_prompts
                WHERE chat_id IS NOT DISTINCT FROM $1 AND scope = $2 AND version = $3
                """,
                (chat_id, scope, version),
            )
            target_row = await conn.fetchrow(query, *params)

            if not target_row:
                return None

            # Deactivate current active prompts
            query, params = convert_query_to_postgres(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = $1
                WHERE chat_id IS NOT DISTINCT FROM $2 AND scope = $3 AND is_active = 1
                """,
                (now, chat_id, scope),
            )
            await conn.execute(query, *params)

            # Activate target version
            query, params = convert_query_to_postgres(
                """
                UPDATE system_prompts
                SET is_active = 1, updated_at = $1, activated_at = $2
                WHERE id = $3
                """,
                (now, now, target_row["id"]),
            )
            await conn.execute(query, *params)

            logger.info(
                f"Activated version {version}: admin={admin_id}, scope={scope}, "
                f"chat_id={chat_id}, id={target_row['id']}"
            )

            # Return updated prompt
            query, params = convert_query_to_postgres(
                "SELECT * FROM system_prompts WHERE id = $1", (target_row["id"],)
            )
            row = await conn.fetchrow(query, *params)
            if not row:
                raise RuntimeError(f"Failed to fetch prompt {target_row['id']}")
            prompt = self._row_to_prompt(row)
            if scope == "global":
                self._invalidate_cache()
                self._cache_prompt(None, prompt)
            else:
                self._invalidate_cache(chat_id)
                self._cache_prompt(chat_id, prompt)
            return prompt

    def _row_to_prompt(self, row: asyncpg.Record) -> SystemPrompt:
        """Convert database row to SystemPrompt."""
        return SystemPrompt(
            id=row["id"],
            admin_id=row["admin_id"],
            chat_id=row["chat_id"],
            scope=row["scope"],
            prompt_text=row["prompt_text"],
            is_active=bool(row["is_active"]),
            version=row["version"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            activated_at=row["activated_at"],
        )

    @property
    def last_cache_hit(self) -> bool:
        """Return whether the last get_active_prompt call hit the cache."""
        return self._last_cache_hit

    def _cache_prompt(
        self, chat_id: int | None, prompt: SystemPrompt | None, timestamp: float | None = None
    ) -> None:
        """Store prompt result in local cache."""
        self._prompt_cache[chat_id] = (prompt, timestamp or time.time())

    def _invalidate_cache(self, chat_id: int | None = None) -> None:
        """Invalidate prompt cache for a specific chat or all chats."""
        if chat_id is not None:
            self._prompt_cache.pop(chat_id, None)
        else:
            # Invalidate all
            self._prompt_cache.clear()
        self._last_cache_hit = False
        logger.debug(f"Invalidated prompt cache for chat_id={chat_id}")

    def clear_cache(self) -> None:
        """Clear all cached prompts (for testing or manual refresh)."""
        self._prompt_cache.clear()
        self._last_cache_hit = False
        logger.info("Cleared all prompt caches")
