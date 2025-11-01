"""Database connection utilities for SQLite with proper concurrency handling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

logger = logging.getLogger(__name__)


async def execute_with_retry(
    coro_func,
    max_retries: int = 5,
    initial_delay: float = 0.1,
    max_delay: float = 2.0,
) -> None:
    """
    Execute an async operation with exponential backoff retry for database locks.

    Args:
        coro_func: Async function to execute
        max_retries: Maximum number of attempts
        initial_delay: Initial delay in seconds for retry
        max_delay: Maximum delay cap for backoff
    """
    import aiosqlite

    last_error = None
    for attempt in range(max_retries):
        try:
            return await coro_func()
        except aiosqlite.OperationalError as e:
            if "database is locked" not in str(e):
                raise
            last_error = e
            if attempt < max_retries - 1:
                delay = min(initial_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(delay)

    if last_error:
        logger.error(f"Failed after {max_retries} retries: {last_error}")
        raise last_error
    raise RuntimeError("Database operation failed")


@asynccontextmanager
async def get_db_connection(
    db_path: Path | str,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> AsyncIterator[aiosqlite.Connection]:
    """
    Get a database connection with proper WAL mode and timeout settings.

    Args:
        db_path: Path to SQLite database file
        timeout: Connection timeout in seconds (default: 30.0)
        max_retries: Maximum number of retries for connection setup errors (default: 3)

    Yields:
        aiosqlite.Connection with WAL mode enabled

    This context manager:
    - Enables WAL (Write-Ahead Logging) mode for better concurrency
    - Sets a reasonable busy timeout to handle database locks automatically
    - Retries on connection setup errors
    """
    last_error = None

    # Retry loop for connection setup
    db = None
    for attempt in range(max_retries):
        try:
            db = await aiosqlite.connect(db_path, timeout=timeout)
            # Enable WAL mode for better concurrent access
            await db.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to handle locks automatically (in milliseconds)
            # Increased to 30 seconds to handle contentious locks with many concurrent operations
            await db.execute("PRAGMA busy_timeout=30000")
            # Connection setup succeeded, break out of retry loop
            break
        except aiosqlite.OperationalError as e:
            if "database is locked" not in str(e):
                raise
            last_error = e
            if db is not None:
                try:
                    await db.close()
                except Exception:
                    pass
                db = None
            if attempt < max_retries - 1:
                # Exponential backoff: 0.1s, 0.2s, 0.4s
                wait_time = 0.1 * (2 ** attempt)
                logger.warning(
                    f"Database locked during connection setup, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to acquire database connection after {max_retries} retries")
                raise

    # If connection setup succeeded, yield it (no retry logic here)
    if db is None:
        raise RuntimeError("Failed to establish database connection")

    try:
        yield db
    finally:
        await db.close()
    

async def init_database(db_path: Path | str) -> None:
    """
    Initialize database with WAL mode and optimal settings.
    
    Args:
        db_path: Path to SQLite database file
    """
    async with get_db_connection(db_path) as db:
        # WAL mode is already set by get_db_connection
        # Set some additional optimizations
        await db.execute("PRAGMA synchronous=NORMAL")  # Faster than FULL, still safe with WAL
        await db.execute("PRAGMA cache_size=-64000")   # 64MB cache
        await db.execute("PRAGMA temp_store=MEMORY")   # Store temp tables in memory
        await db.commit()
        logger.info(f"Database initialized with WAL mode at {db_path}")
