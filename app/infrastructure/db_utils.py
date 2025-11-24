"""Database connection utilities for PostgreSQL with connection pooling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg

from app.infrastructure.postgres import get_db_connection as get_pg_connection

logger = logging.getLogger(__name__)


async def execute_with_retry(
    coro_func,
    max_retries: int = 5,
    initial_delay: float = 0.1,
    max_delay: float = 2.0,
    operation_name: str = "database operation",
) -> None:
    """
    Execute an async operation with exponential backoff retry for database errors.

    Args:
        coro_func: Async function to execute
        max_retries: Maximum number of attempts
        initial_delay: Initial delay in seconds for retry
        max_delay: Maximum delay cap for backoff
        operation_name: Name of operation for logging (helps identify bottlenecks)
    """
    import time as time_module

    last_error = None
    operation_start = time_module.time()

    for attempt in range(max_retries):
        try:
            result = await coro_func()
            operation_time = int((time_module.time() - operation_start) * 1000)

            # Log slow operations (>500ms) to identify bottlenecks
            if operation_time > 500:
                logger.info(
                    f"Slow {operation_name}: {operation_time}ms (attempt {attempt + 1})"
                )

            return result
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(initial_delay * (2**attempt), max_delay)
                logger.warning(
                    f"Database connection error in {operation_name}, retrying in {delay:.2f}s "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                await asyncio.sleep(delay)

    if last_error:
        operation_time = int((time_module.time() - operation_start) * 1000)
        logger.error(
            f"{operation_name} failed after {max_retries} retries "
            f"(total time: {operation_time}ms): {last_error}"
        )
        raise last_error
    raise RuntimeError("Database operation failed")


_pg_pool = None


async def close_pg_pool():
    """Close the global PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None


@asynccontextmanager
async def get_pg_connection(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    """
    Get a PostgreSQL connection from the pool.
    Creates the pool if it doesn't exist.
    """
    global _pg_pool
    if _pg_pool is None:
        try:
            _pg_pool = await asyncpg.create_pool(database_url)
        except Exception as e:
            # If pool creation fails, we might be in a new loop with an old pool object?
            # No, _pg_pool is None here.
            raise e

    async with _pg_pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_db_connection(
    database_url: str,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> AsyncIterator[Any]:
    """
    Get a database connection (PostgreSQL pool).

    Args:
        database_url: Connection string (postgresql://...)
        timeout: Connection timeout in seconds
        max_retries: Maximum number of retries

    Yields:
        Connection object (asyncpg.Connection)
    """
    # The original code had `async with get_pg_connection(str(database_url)) as conn:`.
    # Assuming `get_pg_connection` is now the function defined above,
    # and this `get_db_connection` is an alias or wrapper for it.
    async with get_pg_connection(str(database_url)) as conn:
        yield conn



async def init_database(database_url: str) -> None:
    """
    Initialize PostgreSQL database by running schema migrations.

    Args:
        database_url: PostgreSQL connection string
    """

    # Read PostgreSQL schema
    schema_path = Path(__file__).resolve().parents[2] / "db" / "schema_postgresql.sql"
    if not schema_path.exists():
        # Fallback to legacy location
        schema_path = (
            Path(__file__).resolve().parent.parent / "db" / "schema_postgresql.sql"
        )

    if not schema_path.exists():
        logger.warning(
            f"PostgreSQL schema not found at {schema_path}, skipping initialization"
        )
        return

    async with get_db_connection(database_url) as conn:
        schema_sql = schema_path.read_text(encoding="utf-8")
        # Execute schema in a transaction
        # Use DO block to handle errors gracefully for idempotent schema
        try:
            async with conn.transaction():
                await conn.execute(schema_sql)
            logger.info(f"PostgreSQL database initialized from {schema_path}")
        except Exception as e:
            # If schema already exists, that's okay - just log it
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                logger.info(
                    f"PostgreSQL schema already initialized (some objects already exist): {e}"
                )
            else:
                logger.error(f"Failed to initialize PostgreSQL database: {e}")
                raise


async def apply_migrations(database_url: str) -> None:
    """
    Apply versioned SQL migrations from db/migrations/ directory.

    - Creates a tracking table migrations_applied(filename TEXT PRIMARY KEY, applied_at BIGINT)
    - Applies any .sql files not yet recorded, in lexical order
    - Runs each migration in its own transaction
    """
    import time

    migrations_dir_candidates = [
        Path(__file__).resolve().parents[2] / "db" / "migrations",
        Path(__file__).resolve().parent.parent / "db" / "migrations",
    ]
    migrations_dir = None
    for p in migrations_dir_candidates:
        if p.exists():
            migrations_dir = p
            break
    if migrations_dir is None:
        logger.info("No migrations directory found; skipping migrations")
        return

    migration_files = sorted(
        [f for f in migrations_dir.iterdir() if f.suffix.lower() == ".sql"]
    )
    if not migration_files:
        logger.info("No migration files found; nothing to apply")
        return

    async with get_db_connection(database_url) as conn:
        # Ensure tracking table exists
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS migrations_applied (
                filename TEXT PRIMARY KEY,
                applied_at BIGINT NOT NULL
            )
            """
        )
        rows = await conn.fetch("SELECT filename FROM migrations_applied")
        already_applied = {r["filename"] for r in rows}

        to_apply = [mf for mf in migration_files if mf.name not in already_applied]
        if not to_apply:
            logger.info("All migrations already applied")
            return

        logger.info(
            "Applying migrations",
            extra={"count": len(to_apply), "files": [f.name for f in to_apply]},
        )

        for mf in to_apply:
            sql = mf.read_text(encoding="utf-8")
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO migrations_applied (filename, applied_at) VALUES ($1, $2)",
                        mf.name,
                        int(time.time()),
                    )
                logger.info(f"Applied migration {mf.name}")
            except Exception as e:
                logger.error(f"Failed to apply migration {mf.name}: {e}", exc_info=True)
                raise
