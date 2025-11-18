"""PostgreSQL connection pool utilities using asyncpg."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

logger = logging.getLogger(__name__)

# Global connection pool
_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool(
    database_url: str, min_size: int = 10, max_size: int = 20
) -> asyncpg.Pool:
    """Get or create PostgreSQL connection pool.

    Args:
        database_url: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        min_size: Minimum number of connections in pool (increased from 5 to 10)
        max_size: Maximum number of connections in pool (increased from 10 to 20)

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
            logger.info(
                f"PostgreSQL connection pool created (min={min_size}, max={max_size}, command_timeout=60s)"
            )

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

    Logs pool statistics when connection is acquired/released to help identify contention.
    """
    import time as time_module

    pool = await get_pool(database_url)
    acquire_start = time_module.time()

    # Log pool status before acquiring
    pool_stats = {
        "size": pool.get_size(),
        "idle_size": pool.get_idle_size(),
        "active_connections": pool.get_size() - pool.get_idle_size(),
    }

    # Warn if pool is getting full (80% utilization)
    utilization = (
        (pool_stats["active_connections"] / pool_stats["size"]) * 100
        if pool_stats["size"] > 0
        else 0
    )
    if utilization > 80:
        logger.warning(
            f"PostgreSQL connection pool high utilization: {utilization:.1f}% "
            f"({pool_stats['active_connections']}/{pool_stats['size']} connections in use)"
        )

    conn = await pool.acquire()
    acquire_time = int((time_module.time() - acquire_start) * 1000)

    # Log if connection acquisition took significant time (>100ms)
    if acquire_time > 100:
        logger.warning(
            f"Slow connection acquisition: {acquire_time}ms (pool: {pool_stats['active_connections']}/{pool_stats['size']} active)"
        )

    try:
        yield conn
    finally:
        release_start = time_module.time()
        await pool.release(conn)
        release_time = int((time_module.time() - release_start) * 1000)

        # Log if connection release took significant time (>50ms)
        if release_time > 50:
            logger.warning(f"Slow connection release: {release_time}ms")
