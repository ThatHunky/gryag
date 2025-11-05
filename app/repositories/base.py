"""Base repository interface.

Provides common CRUD operations for all repositories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, TypeVar

import asyncpg

from app.core.exceptions import DatabaseError
from app.infrastructure.db_utils import get_db_connection

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

    def __init__(self, database_url: str):
        """Initialize repository.

        Args:
            database_url: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        """
        self.database_url = database_url

    def _get_connection(self):
        """Get database connection manager from PostgreSQL pool.

        Returns:
            Async context manager for database connection

        Note:
            This uses get_db_connection() which provides:
            - Connection pooling for efficient connection reuse
            - Automatic connection management
            - Proper error handling
        """
        return get_db_connection(self.database_url)
    

    async def _execute(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> str:
        """Execute query and return result.

        Args:
            query: SQL query string (use $1, $2, etc. for parameters)
            params: Query parameters (tuple or dict)

        Returns:
            Result status string (e.g., "INSERT 0 1")

        Raises:
            DatabaseError: If query execution fails
        """
        try:
            async with self._get_connection() as conn:
                if params:
                    if isinstance(params, dict):
                        result = await conn.execute(query, **params)
                    else:
                        result = await conn.execute(query, *params)
                else:
                    result = await conn.execute(query)
                return result
        except asyncpg.PostgresError as e:
            raise DatabaseError(
                "Query execution failed",
                context={"query": query[:100], "params": str(params)[:100]},
                cause=e,
            )

    async def _fetch_one(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> Optional[asyncpg.Record]:
        """Fetch single row from query.

        Args:
            query: SQL query string (use $1, $2, etc. for parameters)
            params: Query parameters

        Returns:
            Single row record or None if not found

        Raises:
            DatabaseError: If query fails
        """
        try:
            async with self._get_connection() as conn:
                if params:
                    if isinstance(params, dict):
                        row = await conn.fetchrow(query, **params)
                    else:
                        row = await conn.fetchrow(query, *params)
                else:
                    row = await conn.fetchrow(query)
                return row
        except asyncpg.PostgresError as e:
            raise DatabaseError(
                "Failed to fetch row",
                context={"query": query[:100]},
                cause=e,
            )

    async def _fetch_all(
        self,
        query: str,
        params: tuple | Dict[str, Any] | None = None,
    ) -> List[asyncpg.Record]:
        """Fetch all rows from query.

        Args:
            query: SQL query string (use $1, $2, etc. for parameters)
            params: Query parameters

        Returns:
            List of row records (may be empty)

        Raises:
            DatabaseError: If query fails
        """
        try:
            async with self._get_connection() as conn:
                if params:
                    if isinstance(params, dict):
                        rows = await conn.fetch(query, **params)
                    else:
                        rows = await conn.fetch(query, *params)
                else:
                    rows = await conn.fetch(query)
                return list(rows)
        except asyncpg.PostgresError as e:
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
