"""Unit tests for repository base class."""

import pytest
from pathlib import Path
from dataclasses import dataclass
from app.repositories.base import Repository
from app.core.exceptions import DatabaseError


@dataclass
class TestEntity:
    """Test entity for repository tests."""

    id: int
    name: str


class TestRepository(Repository[TestEntity]):
    """Concrete repository for testing."""

    async def find_by_id(self, id: int):
        row = await self._fetch_one("SELECT * FROM test_table WHERE id = ?", (id,))
        if not row:
            return None
        return TestEntity(row["id"], row["name"])

    async def save(self, entity: TestEntity):
        await self._execute(
            "INSERT OR REPLACE INTO test_table (id, name) VALUES (?, ?)",
            (entity.id, entity.name),
        )
        return entity

    async def delete(self, id: int):
        cursor = await self._execute("DELETE FROM test_table WHERE id = ?", (id,))
        return cursor.rowcount > 0


@pytest.mark.asyncio
async def test_repository_connection(test_db):
    """Test repository can connect to database."""
    repo = TestRepository(str(test_db))

    # Create test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.commit()
    await conn.close()

    # Should not raise
    assert repo.db_path == str(test_db)


@pytest.mark.asyncio
async def test_repository_execute(test_db):
    """Test repository can execute queries."""
    repo = TestRepository(str(test_db))

    # Create test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.commit()
    await conn.close()

    # Insert data
    await repo._execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "test"))

    # Verify
    row = await repo._fetch_one("SELECT * FROM test_table WHERE id = ?", (1,))
    assert row["name"] == "test"


@pytest.mark.asyncio
async def test_repository_fetch_one(test_db):
    """Test repository can fetch single row."""
    repo = TestRepository(str(test_db))

    # Create and populate test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.execute("INSERT INTO test_table (id, name) VALUES (1, 'first')")
    await conn.commit()
    await conn.close()

    row = await repo._fetch_one("SELECT * FROM test_table WHERE id = ?", (1,))

    assert row is not None
    assert row["name"] == "first"


@pytest.mark.asyncio
async def test_repository_fetch_all(test_db):
    """Test repository can fetch multiple rows."""
    repo = TestRepository(str(test_db))

    # Create and populate test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.execute("INSERT INTO test_table (id, name) VALUES (1, 'first')")
    await conn.execute("INSERT INTO test_table (id, name) VALUES (2, 'second')")
    await conn.commit()
    await conn.close()

    rows = await repo._fetch_all("SELECT * FROM test_table ORDER BY id")

    assert len(rows) == 2
    assert rows[0]["name"] == "first"
    assert rows[1]["name"] == "second"


@pytest.mark.asyncio
async def test_repository_save_and_find(test_db):
    """Test repository save and find operations."""
    repo = TestRepository(str(test_db))

    # Create test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.commit()
    await conn.close()

    # Save entity
    entity = TestEntity(id=42, name="Test Entity")
    await repo.save(entity)

    # Find entity
    found = await repo.find_by_id(42)

    assert found is not None
    assert found.id == 42
    assert found.name == "Test Entity"


@pytest.mark.asyncio
async def test_repository_delete(test_db):
    """Test repository delete operation."""
    repo = TestRepository(str(test_db))

    # Create and populate test table
    conn = await repo._get_connection()
    await conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    await conn.execute("INSERT INTO test_table (id, name) VALUES (1, 'to_delete')")
    await conn.commit()
    await conn.close()

    # Delete entity
    deleted = await repo.delete(1)
    assert deleted is True

    # Verify deletion
    found = await repo.find_by_id(1)
    assert found is None


@pytest.mark.asyncio
async def test_repository_error_handling(test_db):
    """Test repository handles database errors."""
    repo = TestRepository(str(test_db))

    # Try to query non-existent table
    with pytest.raises(DatabaseError) as exc_info:
        await repo._fetch_one("SELECT * FROM nonexistent_table")

    error = exc_info.value
    assert "Failed to fetch row" in error.message
    assert error.cause is not None
