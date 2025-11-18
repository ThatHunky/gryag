"""Application initialization and service setup.

This module contains helper functions for initializing various services
and components of the bot application.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import Settings

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient
else:
    RedisClient = Any

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # type: ignore


logger = logging.getLogger(__name__)


async def init_redis_client(settings: Settings) -> RedisClient | None:
    """Initialize Redis client if enabled and available.

    Args:
        settings: Application settings

    Returns:
        Redis client instance if enabled and connected, None otherwise
    """
    if not settings.use_redis or redis is None:
        return None

    if not settings.redis_url:
        logger.warning("Redis enabled but REDIS_URL not configured")
        return None

    import asyncio

    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=False,
            )
            # Test connection
            await redis_client.ping()
            logger.info(f"Redis connection established: {settings.redis_url}")
            return redis_client
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Redis connection attempt {attempt + 1}/{max_retries} failed: {exc}. Retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.warning(
                    f"Не вдалося під'єднати Redis після {max_retries} спроб: {exc}"
                )
                return None

    return None
