"""Database connection utilities for SQLite with proper concurrency handling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

logger = logging.getLogger(__name__)


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
    for attempt in range(max_retries):
        try:
            async with aiosqlite.connect(db_path, timeout=timeout) as db:
                # Enable WAL mode for better concurrent access
                await db.execute("PRAGMA journal_mode=WAL")
                # Set busy timeout to handle locks automatically (in milliseconds)
                # Increased to 10 seconds to handle contentious locks
                await db.execute("PRAGMA busy_timeout=10000")
                yield db
            return
        except aiosqlite.OperationalError as e:
            if "database is locked" not in str(e):
                raise
            last_error = e
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
