"""Database migrator for version-controlled schema changes.

This module provides a simple migration system that applies SQL
migrations in order and tracks which migrations have been applied.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from app.core.exceptions import DatabaseError
from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)


class Migration:
    """Represents a single database migration.

    Attributes:
        version: Migration version number
        name: Migration description
        sql: SQL statements to execute
    """

    def __init__(self, version: int, name: str, sql: str):
        self.version = version
        self.name = name
        self.sql = sql

    def __repr__(self) -> str:
        return f"Migration({self.version}, {self.name})"


class DatabaseMigrator:
    """Manages database migrations.

    Applies migrations in order and tracks which have been applied.

    Example:
        >>> migrator = DatabaseMigrator("postgresql://...")
        >>> await migrator.migrate()
        Applied 3 migrations
    """

    def __init__(self, db_url: str):
        """Initialize migrator.

        Args:
            db_url: PostgreSQL connection URL
        """
        self.db_url = db_url
        self.migrations_dir = Path(__file__).parent / "migrations"

    async def migrate(self) -> int:
        """Apply all pending migrations.

        Returns:
            Number of migrations applied

        Raises:
            DatabaseError: If migration fails
        """
        try:
            async with get_db_connection(self.db_url) as db:
                # Ensure migrations table exists
                await self._ensure_migrations_table(db)

                # Get applied migrations
                applied = await self._get_applied_migrations(db)

                # Get all migrations
                all_migrations = self._load_migrations()

                # Apply pending migrations
                count = 0
                for migration in all_migrations:
                    if migration.version not in applied:
                        logger.info(f"Applying migration {migration}")
                        await self._apply_migration(db, migration)
                        count += 1

                return count

        except Exception as e:
            raise DatabaseError(
                "Migration failed",
                context={"db_url": self.db_url},
                cause=e,
            ) from None

    async def get_current_version(self) -> int:
        """Get current database version.

        Returns:
            Latest applied migration version, or 0 if none applied
        """
        try:
            async with get_db_connection(self.db_url) as db:
                await self._ensure_migrations_table(db)
                row = await db.fetchrow("SELECT MAX(version) FROM schema_migrations")
                return row[0] if row and row[0] else 0

        except Exception as e:
            raise DatabaseError(
                "Failed to get database version",
                context={"db_url": self.db_url},
                cause=e,
            ) from None

    async def rollback(self, target_version: int = 0) -> int:
        """Rollback migrations to target version.

        Note: This is a destructive operation and should be used carefully.

        Args:
            target_version: Version to rollback to (default: 0 = all)

        Returns:
            Number of migrations rolled back

        Raises:
            DatabaseError: If rollback fails
        """
        try:
            async with get_db_connection(self.db_url) as db:
                await self._ensure_migrations_table(db)

                # Get applied migrations
                applied = await self._get_applied_migrations(db)

                # Remove migrations > target_version
                count = 0
                for version in sorted(applied, reverse=True):
                    if version > target_version:
                        await db.execute(
                            "DELETE FROM schema_migrations WHERE version = $1",
                            version,
                        )
                        # Note: We can't easily undo the SQL changes without down migrations
                        # For now, we just remove the record
                        logger.warning(f"Rolled back migration version {version} (record only)")
                        count += 1

                return count

        except Exception as e:
            raise DatabaseError(
                "Rollback failed",
                context={"target_version": target_version},
                cause=e,
            ) from None

    async def _ensure_migrations_table(self, db: asyncpg.Connection) -> None:
        """Create migrations tracking table if it doesn't exist."""
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    async def _get_applied_migrations(self, db: asyncpg.Connection) -> list[int]:
        """Get list of applied migration versions."""
        rows = await db.fetch(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        return [row["version"] for row in rows]

    async def _apply_migration(
        self, db: asyncpg.Connection, migration: Migration
    ) -> None:
        """Apply a single migration."""
        try:
            # Execute migration SQL
            # asyncpg doesn't support executescript, so we might need to split statements
            # or use a simple execute if it's one block.
            # Assuming migration.sql is a valid block or we can execute it directly.
            await db.execute(migration.sql)

            # Record migration
            await db.execute(
                """
                INSERT INTO schema_migrations (version, name)
                VALUES ($1, $2)
                """,
                migration.version, migration.name,
            )

            logger.info(f"Applied migration {migration.version}: {migration.name}")

        except Exception as e:
            raise DatabaseError(
                f"Failed to apply migration {migration.version}",
                context={"migration": migration.name},
                cause=e,
            ) from None

    def _load_migrations(self) -> list[Migration]:
        """Load all migration files from migrations directory.

        Migration files should be named: {version}_{name}.sql

        Returns:
            List of Migration objects sorted by version
        """
        if not self.migrations_dir.exists():
            logger.warning(f"Migrations directory not found: {self.migrations_dir}")
            return []

        migrations = []
        for file_path in sorted(self.migrations_dir.glob("*.sql")):
            # Parse filename: 001_initial_schema.sql
            parts = file_path.stem.split("_", 1)
            if len(parts) != 2:
                logger.warning(f"Skipping invalid migration file: {file_path.name}")
                continue

            try:
                version = int(parts[0])
                name = parts[1]
                sql = file_path.read_text()

                migrations.append(Migration(version, name, sql))
            except (ValueError, OSError) as e:
                logger.error(f"Failed to load migration {file_path.name}: {e}")
                continue

        return sorted(migrations, key=lambda m: m.version)
