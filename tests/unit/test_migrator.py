"""Unit tests for database migrator."""

import pytest
from pathlib import Path
import aiosqlite
from app.infrastructure.database.migrator import DatabaseMigrator, Migration


@pytest.fixture
def empty_db(tmp_path):
    """Create empty test database."""
    db_path = tmp_path / "test_migrations.db"
    return db_path


@pytest.mark.asyncio
async def test_migrator_initialization(empty_db):
    """Test migrator can be initialized."""
    migrator = DatabaseMigrator(empty_db)

    assert migrator.db_path == empty_db
    assert migrator.migrations_dir.exists()


@pytest.mark.asyncio
async def test_migrator_creates_migrations_table(empty_db):
    """Test migrator creates schema_migrations table."""
    migrator = DatabaseMigrator(empty_db)

    # Run migrate (no migrations yet)
    await migrator.migrate()

    # Verify table exists
    async with aiosqlite.connect(empty_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        row = await cursor.fetchone()
        assert row is not None


@pytest.mark.asyncio
async def test_migrator_applies_migrations(empty_db):
    """Test migrator applies migrations in order."""
    migrator = DatabaseMigrator(empty_db)

    # Migrate should apply all existing migrations
    count = await migrator.migrate()

    # Should have applied migrations (001, 002, 003, 004, 005)
    assert count >= 5

    # Verify migrations were recorded
    async with aiosqlite.connect(empty_db) as db:
        cursor = await db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        versions = [row[0] for row in await cursor.fetchall()]

        assert 1 in versions  # Initial schema
        assert 2 in versions  # User profiling
        assert 3 in versions  # Continuous monitoring


@pytest.mark.asyncio
async def test_migrator_skips_applied_migrations(empty_db):
    """Test migrator doesn't reapply migrations."""
    migrator = DatabaseMigrator(empty_db)

    # First run
    count1 = await migrator.migrate()
    assert count1 > 0

    # Second run should apply nothing
    count2 = await migrator.migrate()
    assert count2 == 0


@pytest.mark.asyncio
async def test_migrator_get_current_version(empty_db):
    """Test getting current database version."""
    migrator = DatabaseMigrator(empty_db)

    # Initially version 0
    version = await migrator.get_current_version()
    assert version == 0

    # After migration
    await migrator.migrate()
    version = await migrator.get_current_version()
    assert version >= 5  # Latest migration


@pytest.mark.asyncio
async def test_migration_object():
    """Test Migration object creation."""
    migration = Migration(
        version=1, name="test_migration", sql="CREATE TABLE test (id INTEGER);"
    )

    assert migration.version == 1
    assert migration.name == "test_migration"
    assert "CREATE TABLE" in migration.sql


@pytest.mark.asyncio
async def test_migrator_rollback(empty_db):
    """Test rolling back migrations."""
    migrator = DatabaseMigrator(empty_db)

    # Apply migrations
    await migrator.migrate()

    # Rollback to version 2
    count = await migrator.rollback(target_version=2)
    assert count > 0

    # Verify version is 2
    version = await migrator.get_current_version()
    assert version == 2


@pytest.mark.asyncio
async def test_migrator_rollback_all(empty_db):
    """Test rolling back all migrations."""
    migrator = DatabaseMigrator(empty_db)

    # Apply migrations
    await migrator.migrate()

    # Rollback all
    count = await migrator.rollback(target_version=0)
    assert count > 0

    # Verify version is 0
    version = await migrator.get_current_version()
    assert version == 0
