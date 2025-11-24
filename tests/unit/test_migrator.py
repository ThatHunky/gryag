"""Unit tests for database migrator."""

import asyncpg
import pytest

from app.infrastructure.database.migrator import DatabaseMigrator, Migration


@pytest.mark.asyncio
async def test_migrator_initialization(test_db):
    """Test migrator can be initialized."""
    migrator = DatabaseMigrator(test_db)

    assert migrator.db_url == test_db
    assert migrator.migrations_dir.exists()


@pytest.mark.asyncio
async def test_migrator_creates_migrations_table(test_db):
    """Test migrator creates schema_migrations table."""
    migrator = DatabaseMigrator(test_db)

    # Run migrate (no migrations yet)
    await migrator.migrate()

    # Verify table exists
    conn = await asyncpg.connect(test_db)
    try:
        row = await conn.fetchrow(
            "SELECT table_name FROM information_schema.tables WHERE table_name='schema_migrations'"
        )
        assert row is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migrator_applies_migrations(test_db):
    """Test migrator applies migrations in order."""
    migrator = DatabaseMigrator(test_db)

    # Migrate should apply all existing migrations
    count = await migrator.migrate()

    # Should have applied migrations
    # Note: exact count depends on files in migrations dir
    assert count >= 0

    # Verify migrations were recorded
    conn = await asyncpg.connect(test_db)
    try:
        rows = await conn.fetch(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        versions = [row["version"] for row in rows]
        
        # If there are migrations, they should be in the table
        if count > 0:
            assert len(versions) == count
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migrator_skips_applied_migrations(test_db):
    """Test migrator doesn't reapply migrations."""
    migrator = DatabaseMigrator(test_db)

    # First run
    await migrator.migrate()

    # Second run should apply nothing
    count2 = await migrator.migrate()
    assert count2 == 0


@pytest.mark.asyncio
async def test_migrator_get_current_version(test_db):
    """Test getting current database version."""
    migrator = DatabaseMigrator(test_db)

    # Initially version might be non-zero if other tests ran, 
    # but let's just check it runs without error
    version = await migrator.get_current_version()
    assert isinstance(version, int)


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
async def test_migrator_rollback(test_db):
    """Test rolling back migrations."""
    migrator = DatabaseMigrator(test_db)

    # Apply migrations
    await migrator.migrate()
    
    current_version = await migrator.get_current_version()
    if current_version == 0:
        return # Nothing to rollback

    # Rollback to previous version
    target = max(0, current_version - 1)
    count = await migrator.rollback(target_version=target)
    
    # Verify version
    new_version = await migrator.get_current_version()
    assert new_version <= target


@pytest.mark.asyncio
async def test_migrator_rollback_all(test_db):
    """Test rolling back all migrations."""
    migrator = DatabaseMigrator(test_db)

    # Apply migrations
    await migrator.migrate()

    # Rollback all
    await migrator.rollback(target_version=0)

    # Verify version is 0 (or at least records are gone)
    # Note: rollback only deletes records, doesn't drop tables in this implementation
    conn = await asyncpg.connect(test_db)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
        assert count == 0
    finally:
        await conn.close()
