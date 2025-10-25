from __future__ import annotations

from typing import Any, Mapping, Protocol


class RedisLike(Protocol):
    async def zadd(
        self, name: str, mapping: Mapping[Any, Any], *args: Any, **kwargs: Any
    ) -> Any: ...

    async def expire(self, name: str, time: Any, *args: Any, **kwargs: Any) -> Any: ...

    async def zremrangebyscore(
        self, name: str, min: Any, max: Any, *args: Any, **kwargs: Any
    ) -> Any: ...

    async def zcard(self, name: str) -> int: ...

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *args: Any,
        **kwargs: Any,
    ) -> list[Any]: ...

    async def scan(
        self,
        cursor: int = 0,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[int, list[str]]: ...

    async def delete(self, *names: Any) -> Any: ...

    async def close(self) -> Any: ...
