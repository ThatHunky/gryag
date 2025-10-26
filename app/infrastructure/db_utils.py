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
        max_retries: Maximum number of retries for database locked errors (default: 3)
        
    Yields:
        aiosqlite.Connection with WAL mode enabled
        
    This context manager:
    - Enables WAL (Write-Ahead Logging) mode for better concurrency
    - Sets a reasonable busy timeout
    - Retries on database locked errors
    """
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            async with aiosqlite.connect(db_path, timeout=timeout) as db:
                # Enable WAL mode for better concurrent access
                await db.execute("PRAGMA journal_mode=WAL")
                # Set busy timeout (milliseconds)
                await db.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
                yield db
                return
        except aiosqlite.OperationalError as e:
            if "database is locked" in str(e):
                retry_count += 1
                last_error = e
                if retry_count < max_retries:
                    # Exponential backoff: 0.1s, 0.2s, 0.4s
                    wait_time = 0.1 * (2 ** (retry_count - 1))
                    logger.warning(
                        f"Database locked, retrying in {wait_time}s (attempt {retry_count}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
            raise
    
    # If we exhausted all retries, raise the last error
    if last_error:
        logger.error(f"Failed to acquire database connection after {max_retries} retries")
        raise last_error
    

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
