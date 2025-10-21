"""Base repository interface.

Provides common CRUD operations for all repositories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, TypeVar

import aiosqlite

from app.core.exceptions import DatabaseError

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """Base repository with common CRUD operations.

    All repositories should inherit from this class to ensure
    consistent data access patterns.

    Type parameter T represents the entity type this repository manages.

    Example:
        >>> class UserRepository(Repository[User]):
        ...     async def find_by_id(self, user_id: int) -> Optional[User]:
        ...         # implementation
    """

    def __init__(self, db_path: str | Path):
        """Initialize repository.

        Args:
            db_path: Path to SQLite database file (str or Path object)
        """
        self.db_path = str(db_path) if isinstance(db_path, Path) else db_path

    def _get_connection(self) -> aiosqlite.Connection:
        """Get database connection manager.

        Returns:
            Database connection manager (context manager for async with)

        Note:
            This returns the connection manager from aiosqlite.connect(),
            which should be used with 'async with' in calling code.
            Row factory is set after connection is opened.
        """
        return aiosqlite.connect(self.db_path)

    async def _execute(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> aiosqlite.Cursor:
        """Execute query and return cursor.

        Args:
            query: SQL query string
            params: Query parameters (tuple or dict)

        Returns:
            Cursor with query results

        Raises:
            DatabaseError: If query execution fails
        """
        try:
            async with self._get_connection() as db:
                db.row_factory = aiosqlite.Row
                if params:
                    cursor = await db.execute(query, params)
                else:
                    cursor = await db.execute(query)
                await db.commit()
                return cursor
        except aiosqlite.Error as e:
            raise DatabaseError(
                "Query execution failed",
                context={"query": query[:100], "params": str(params)[:100]},
                cause=e,
            )

    async def _fetch_one(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> Optional[aiosqlite.Row]:
        """Fetch single row from query.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Single row or None if not found

        Raises:
            DatabaseError: If query fails
        """
        try:
            async with self._get_connection() as db:
                db.row_factory = aiosqlite.Row
                if params:
                    cursor = await db.execute(query, params)
                else:
                    cursor = await db.execute(query)
                return await cursor.fetchone()
        except aiosqlite.Error as e:
            raise DatabaseError(
                "Failed to fetch row",
                context={"query": query[:100]},
                cause=e,
            )

    async def _fetch_all(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> List[aiosqlite.Row]:
        """Fetch all rows from query.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of rows (may be empty)

        Raises:
            DatabaseError: If query fails
        """
        try:
            async with self._get_connection() as db:
                db.row_factory = aiosqlite.Row
                if params:
                    cursor = await db.execute(query, params)
                else:
                    cursor = await db.execute(query)
                return list(await cursor.fetchall())
        except aiosqlite.Error as e:
            raise DatabaseError(
                "Failed to fetch rows",
                context={"query": query[:100]},
                cause=e,
            )

    @abstractmethod
    async def find_by_id(self, id: Any) -> Optional[T]:
        """Find entity by ID.

        Args:
            id: Entity identifier

        Returns:
            Entity or None if not found
        """
        pass

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save entity to database.

        Args:
            entity: Entity to save

        Returns:
            Saved entity with generated ID if applicable
        """
        pass

    @abstractmethod
    async def delete(self, id: Any) -> bool:
        """Delete entity by ID.

        Args:
            id: Entity identifier

        Returns:
            True if deleted, False if not found
        """
        pass
