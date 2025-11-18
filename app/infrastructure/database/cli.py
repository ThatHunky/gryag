#!/usr/bin/env python3
"""Database migration CLI tool.

Usage:
    python -m app.infrastructure.database.cli migrate  # Apply pending migrations
    python -m app.infrastructure.database.cli version  # Show current version
    python -m app.infrastructure.database.cli rollback <version>  # Rollback to version
"""

import asyncio
import sys

from app.config import Settings
from app.infrastructure.database.migrator import DatabaseMigrator


async def migrate():
    """Apply all pending migrations."""
    settings = Settings()
    migrator = DatabaseMigrator(settings.db_path)

    print(f"📦 Migrating database: {settings.db_path}")

    count = await migrator.migrate()

    if count == 0:
        print("✅ Database is up to date")
    else:
        print(f"✅ Applied {count} migration(s)")

    version = await migrator.get_current_version()
    print(f"📍 Current version: {version}")


async def version():
    """Show current database version."""
    settings = Settings()
    migrator = DatabaseMigrator(settings.db_path)

    version = await migrator.get_current_version()
    print(f"Current database version: {version}")


async def rollback(target_version: int):
    """Rollback to specific version."""
    settings = Settings()
    migrator = DatabaseMigrator(settings.db_path)

    current = await migrator.get_current_version()
    print(f"Current version: {current}")
    print(f"Rolling back to version: {target_version}")

    count = await migrator.rollback(target_version)

    if count == 0:
        print("✅ Nothing to rollback")
    else:
        print(f"⚠️  Rolled back {count} migration(s)")

    new_version = await migrator.get_current_version()
    print(f"📍 New version: {new_version}")


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "migrate":
        asyncio.run(migrate())
    elif command == "version":
        asyncio.run(version())
    elif command == "rollback":
        if len(sys.argv) < 3:
            print("Error: rollback requires target version")
            print("Usage: python -m app.infrastructure.database.cli rollback <version>")
            sys.exit(1)
        target = int(sys.argv[2])
        asyncio.run(rollback(target))
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
