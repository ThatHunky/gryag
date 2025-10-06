"""Database infrastructure.

Provides database migrations and connection management.
"""

from app.infrastructure.database.migrator import DatabaseMigrator

__all__ = ["DatabaseMigrator"]
