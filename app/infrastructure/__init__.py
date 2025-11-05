"""Database infrastructure.

Provides database migrations and connection management.
"""

# Lazy import to avoid aiosqlite dependency at startup
# DatabaseMigrator is only used for CLI migrations, not in main app
def __getattr__(name: str):
    if name == "DatabaseMigrator":
        from app.infrastructure.database.migrator import DatabaseMigrator
        return DatabaseMigrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["DatabaseMigrator"]
