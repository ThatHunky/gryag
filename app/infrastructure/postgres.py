"""PostgreSQL connection pool utilities using asyncpg."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)

# Global connection pool
_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool(database_url: str, min_size: int = 5, max_size: int = 10) -> asyncpg.Pool:
    """Get or create PostgreSQL connection pool.
    
    Args:
        database_url: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        min_size: Minimum number of connections in pool
        max_size: Maximum number of connections in pool
        
    Returns:
        Connection pool instance
    """
    global _pool
    
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                database_url,
                min_size=min_size,
                max_size=max_size,
                command_timeout=60,
            )
            logger.info(f"PostgreSQL connection pool created (min={min_size}, max={max_size})")
    
    return _pool


async def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
            logger.info("PostgreSQL connection pool closed")


@asynccontextmanager
async def get_db_connection(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    """Get a database connection from the pool.
    
    Args:
        database_url: PostgreSQL connection string
        
    Yields:
        asyncpg.Connection from pool
    """
    pool = await get_pool(database_url)
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)

