"""System Prompt Manager for custom admin-configured prompts."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    """

    def __init__(self, db_path: str | Path):
        """Initialize manager.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self) -> None:
        """Initialize database tables (idempotent)."""
        # Schema is created in db/schema.sql, but ensure it exists
        conn = self._get_connection()
        try:
            conn.execute("SELECT 1 FROM system_prompts LIMIT 1")
            logger.info("system_prompts table exists")
        except sqlite3.OperationalError:
            logger.warning(
                "system_prompts table missing, it will be created on next schema migration"
            )
        finally:
            conn.close()

    async def get_active_prompt(
        self, chat_id: int | None = None
    ) -> SystemPrompt | None:
        """Get the active system prompt for a chat.

        Precedence:
        1. Chat-specific prompt (if chat_id provided)
        2. Global prompt
        3. None (use default hardcoded prompt)

        Args:
            chat_id: Telegram chat ID. None for global context.

        Returns:
            Active SystemPrompt or None if no custom prompt
        """
        conn = self._get_connection()
        try:
            # First try chat-specific prompt
            if chat_id is not None:
                cursor = conn.execute(
                    """
                    SELECT * FROM system_prompts
                    WHERE chat_id = ? AND is_active = 1 AND scope = 'chat'
                    ORDER BY activated_at DESC
                    LIMIT 1
                    """,
                    (chat_id,),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_prompt(row)

            # Fall back to global prompt
            cursor = conn.execute(
                """
                SELECT * FROM system_prompts
                WHERE chat_id IS NULL AND is_active = 1 AND scope = 'global'
                ORDER BY activated_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_prompt(row)

            return None
        finally:
            conn.close()

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

        conn = self._get_connection()
        now = int(time.time())

        try:
            # Deactivate existing active prompts for this scope/chat
            conn.execute(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = ?
                WHERE chat_id IS ? AND scope = ? AND is_active = 1
                """,
                (now, chat_id, scope),
            )

            # Get next version number
            cursor = conn.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1 as next_version
                FROM system_prompts
                WHERE chat_id IS ? AND scope = ?
                """,
                (chat_id, scope),
            )
            next_version = cursor.fetchone()["next_version"]

            # Insert new active prompt
            cursor = conn.execute(
                """
                INSERT INTO system_prompts (
                    admin_id, chat_id, scope, prompt_text,
                    is_active, version, notes,
                    created_at, updated_at, activated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
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

            prompt_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"Set system prompt: admin={admin_id}, scope={scope}, "
                f"chat_id={chat_id}, version={next_version}, id={prompt_id}"
            )

            # Fetch and return created prompt
            cursor = conn.execute(
                "SELECT * FROM system_prompts WHERE id = ?", (prompt_id,)
            )
            return self._row_to_prompt(cursor.fetchone())

        finally:
            conn.close()

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

        conn = self._get_connection()
        now = int(time.time())

        try:
            cursor = conn.execute(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = ?
                WHERE chat_id IS ? AND scope = ? AND is_active = 1
                """,
                (now, chat_id, scope),
            )
            count = cursor.rowcount
            conn.commit()

            if count > 0:
                logger.info(
                    f"Reset system prompt: admin={admin_id}, scope={scope}, "
                    f"chat_id={chat_id}, deactivated={count}"
                )

            return count > 0

        finally:
            conn.close()

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

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM system_prompts
                WHERE chat_id IS ? AND scope = ?
                ORDER BY version DESC
                LIMIT ?
                """,
                (chat_id, scope, limit),
            )
            return [self._row_to_prompt(row) for row in cursor.fetchall()]
        finally:
            conn.close()

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

        conn = self._get_connection()
        now = int(time.time())

        try:
            # Find the target version
            cursor = conn.execute(
                """
                SELECT * FROM system_prompts
                WHERE chat_id IS ? AND scope = ? AND version = ?
                """,
                (chat_id, scope, version),
            )
            target_row = cursor.fetchone()

            if not target_row:
                return None

            # Deactivate current active prompts
            conn.execute(
                """
                UPDATE system_prompts
                SET is_active = 0, updated_at = ?
                WHERE chat_id IS ? AND scope = ? AND is_active = 1
                """,
                (now, chat_id, scope),
            )

            # Activate target version
            conn.execute(
                """
                UPDATE system_prompts
                SET is_active = 1, updated_at = ?, activated_at = ?
                WHERE id = ?
                """,
                (now, now, target_row["id"]),
            )

            conn.commit()

            logger.info(
                f"Activated version {version}: admin={admin_id}, scope={scope}, "
                f"chat_id={chat_id}, id={target_row['id']}"
            )

            # Return updated prompt
            cursor = conn.execute(
                "SELECT * FROM system_prompts WHERE id = ?", (target_row["id"],)
            )
            return self._row_to_prompt(cursor.fetchone())

        finally:
            conn.close()

    def _row_to_prompt(self, row: sqlite3.Row) -> SystemPrompt:
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
