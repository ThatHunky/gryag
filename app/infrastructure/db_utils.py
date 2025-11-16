"""Database connection utilities for PostgreSQL with connection pooling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from app.infrastructure.postgres import get_db_connection as get_pg_connection, close_pool

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
                delay = min(initial_delay * (2 ** attempt), max_delay)
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


@asynccontextmanager
async def get_db_connection(
    database_url: str,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> AsyncIterator[asyncpg.Connection]:
    """
    Get a database connection from PostgreSQL connection pool.

    Args:
        database_url: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        timeout: Connection timeout in seconds (default: 30.0) - unused for pool
        max_retries: Maximum number of retries for connection setup errors (default: 3) - unused for pool

    Yields:
        asyncpg.Connection from connection pool

    This context manager:
    - Uses connection pooling for efficient connection reuse
    - Automatically handles connection acquisition and release
    - No manual connection management needed
    """
    async with get_pg_connection(database_url) as conn:
        yield conn
    

async def init_database(database_url: str) -> None:
    """
    Initialize PostgreSQL database by running schema migrations.
    
    Args:
        database_url: PostgreSQL connection string
    """
    from pathlib import Path
    
    # Read PostgreSQL schema
    schema_path = Path(__file__).resolve().parents[2] / "db" / "schema_postgresql.sql"
    if not schema_path.exists():
        # Fallback to legacy location
        schema_path = Path(__file__).resolve().parent.parent / "db" / "schema_postgresql.sql"
    
    if not schema_path.exists():
        logger.warning(f"PostgreSQL schema not found at {schema_path}, skipping initialization")
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
                logger.info(f"PostgreSQL schema already initialized (some objects already exist): {e}")
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
    from pathlib import Path
    
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
    
    migration_files = sorted([f for f in migrations_dir.iterdir() if f.suffix.lower() == ".sql"])
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
