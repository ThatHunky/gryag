"""Repository for the simplified user memory system."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import DatabaseError
from app.repositories.base import Repository


@dataclass
class UserMemory:
    """Represents a single memory for a user."""

    id: int
    user_id: int
    chat_id: int
    memory_text: str
    created_at: int
    updated_at: int


class MemoryRepository(Repository[UserMemory]):
    """Repository for managing user memories in the database."""

    async def init(self) -> None:
        """Initializes the repository by ensuring the table exists."""
        # This is a no-op if the schema is managed externally,
        # but good practice for repositories that might manage their own schema.
        pass

    async def find_by_id(self, id: Any) -> UserMemory | None:
        """Finds a memory by its primary key."""
        return await self.get_memory_by_id(id)

    async def save(self, entity: UserMemory) -> UserMemory:
        """Saves a memory entity. Not implemented, use add_memory."""
        raise NotImplementedError("Use add_memory for creating new memories.")

    async def delete(self, id: Any) -> bool:
        """Deletes a memory by its ID."""
        return await self.delete_memory(id)

    async def add_memory(
        self, user_id: int, chat_id: int, memory_text: str
    ) -> UserMemory:
        """
        Adds a new memory for a user.

        Args:
            user_id: The user's ID.
            chat_id: The chat's ID.
            memory_text: The text of the memory to add.

        Returns:
            The newly created UserMemory object.

        Raises:
            DatabaseError: If the memory already exists (UNIQUE constraint).

        Note:
            If the user has 15 memories, the oldest one is automatically deleted (FIFO).
        """
        now = int(datetime.now(UTC).timestamp())

        # First, check if the user is at the memory limit
        count_query = (
            "SELECT COUNT(*) FROM user_memories WHERE user_id = $1 AND chat_id = $2"
        )
        row = await self._fetch_one(count_query, (user_id, chat_id))
        if row and row[0] >= 15:
            # Auto-delete the oldest memory (FIFO) to make room
            delete_oldest_query = """
                DELETE FROM user_memories
                WHERE id = (
                    SELECT id FROM user_memories
                    WHERE user_id = $1 AND chat_id = $2
                    ORDER BY created_at ASC
                    LIMIT 1
                )
            """
            await self._execute(delete_oldest_query, (user_id, chat_id))

        # Insert the new memory with RETURNING clause to get the ID
        query = """
            INSERT INTO user_memories (user_id, chat_id, memory_text, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """
        try:
            row = await self._fetch_one(
                query, (user_id, chat_id, memory_text, now, now)
            )
            if not row or row["id"] is None:
                raise DatabaseError("Failed to get last row id.")
            return UserMemory(
                id=row["id"],
                user_id=user_id,
                chat_id=chat_id,
                memory_text=memory_text,
                created_at=now,
                updated_at=now,
            )
        except DatabaseError:
            raise
        except Exception as e:
            # The UNIQUE constraint on (user_id, chat_id, memory_text) might fail
            error_str = str(e).lower()
            if "unique constraint" in error_str or "duplicate key" in error_str:
                raise DatabaseError(
                    "This memory already exists for the user."
                ) from None
            raise DatabaseError(f"Failed to add memory: {e}") from e

    async def get_memories_for_user(
        self, user_id: int, chat_id: int, limit: int = 100, offset: int = 0
    ) -> list[UserMemory]:
        """
        Retrieves all memories for a given user in a specific chat.

        Args:
            user_id: The user's ID.
            chat_id: The chat's ID.
            limit: Maximum number of memories to return.
            offset: Number of memories to skip.

        Returns:
            A list of UserMemory objects.
        """
        query = "SELECT * FROM user_memories WHERE user_id = $1 AND chat_id = $2 ORDER BY created_at ASC LIMIT $3 OFFSET $4"
        rows = await self._fetch_all(query, (user_id, chat_id, limit, offset))
        return [UserMemory(**row) for row in rows]

    async def get_memory_by_id(self, memory_id: int) -> UserMemory | None:
        """
        Retrieves a single memory by its ID.

        Args:
            memory_id: The ID of the memory.

        Returns:
            A UserMemory object if found, otherwise None.
        """
        query = "SELECT * FROM user_memories WHERE id = $1"
        row = await self._fetch_one(query, (memory_id,))
        return UserMemory(**row) if row else None

    async def delete_memory(self, memory_id: int) -> bool:
        """
        Deletes a single memory by its ID.

        Args:
            memory_id: The ID of the memory to delete.

        Returns:
            True if a memory was deleted, False otherwise.
        """
        query = "DELETE FROM user_memories WHERE id = $1"
        result = await self._execute(query, (memory_id,))
        # PostgreSQL execute returns string like "DELETE 1" or "DELETE 0"
        # Extract the number to check if any rows were deleted
        match = re.search(r"DELETE (\d+)", result)
        if match:
            return int(match.group(1)) > 0
        return False

    async def delete_all_memories(self, user_id: int, chat_id: int) -> int:
        """
        Deletes all memories for a given user in a specific chat.

        Args:
            user_id: The user's ID.
            chat_id: The chat's ID.

        Returns:
            The number of memories deleted.
        """
        query = "DELETE FROM user_memories WHERE user_id = $1 AND chat_id = $2"
        result = await self._execute(query, (user_id, chat_id))
        # PostgreSQL execute returns string like "DELETE 5"
        # Extract the number to get count of deleted rows
        match = re.search(r"DELETE (\d+)", result)
        if match:
            return int(match.group(1))
        return 0
