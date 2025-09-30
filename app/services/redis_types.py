from __future__ import annotations

from typing import Any, Protocol


class RedisLike(Protocol):
    async def zadd(self, key: str, mapping: dict[str, float]) -> Any: ...

    async def expire(self, key: str, seconds: int) -> Any: ...

    async def zremrangebyscore(self, key: str, min: float, max: float) -> Any: ...

    async def zcard(self, key: str) -> int: ...

    async def zrange(
        self,
        key: str,
        start: int,
        end: int,
        desc: bool = False,
        withscores: bool = False,
    ) -> list[Any]: ...

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]: ...

    async def delete(self, *keys: str) -> Any: ...

    async def close(self) -> Any: ...
