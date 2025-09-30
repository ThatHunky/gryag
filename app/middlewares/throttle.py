from __future__ import annotations

import time
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.triggers import addressed_to_bot

try:  # Optional dependency for Redis support.
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - redis optional.
    Redis = Any  # type: ignore

SNARKY_REPLY = "Пригальмуй, балакучий. За годину вже досить."


class ThrottleMiddleware(BaseMiddleware):
    """Limit addressed interactions per user per chat."""

    def __init__(
        self,
        store: ContextStore,
        settings: Settings,
        redis_client: Redis | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._redis: Redis | None = redis_client

    async def __call__(self, handler, event: Message, data):  # type: ignore[override]
        if not isinstance(event, Message):
            return await handler(event, data)

        bot_username: str | None = data.get("bot_username")
        if not bot_username or event.from_user is None:
            return await handler(event, data)

        if not addressed_to_bot(event, bot_username):
            return await handler(event, data)

        chat_id = event.chat.id
        user_id = event.from_user.id
        base_limit = self._settings.per_user_per_hour

        if user_id in self._settings.admin_user_ids:
            data["throttle_passed"] = True
            return await handler(event, data)

        now = int(time.time())
        recent_times = await self._store.recent_request_times(
            chat_id=chat_id,
            user_id=user_id,
            window_seconds=3 * 3600,
            limit=max(20, base_limit * 2),
        )

        dynamic_limit = base_limit
        if not recent_times:
            dynamic_limit = base_limit + max(1, base_limit // 2)
        else:
            latest_gap = now - recent_times[0]
            if latest_gap > 1800 or len(recent_times) < max(1, base_limit // 2):
                dynamic_limit = base_limit + max(1, base_limit // 2)
            else:
                if len(recent_times) >= base_limit:
                    idx = min(len(recent_times) - 1, base_limit - 1)
                    span = recent_times[0] - recent_times[idx]
                    if span < 900:
                        dynamic_limit = max(1, base_limit - 2)

        recent_count = sum(1 for ts in recent_times if now - ts <= 3600)

        redis_meta: tuple[str, int] | None = None
        blocked = False
        if self._redis is not None:
            key = f"gryag:quota:{chat_id}:{user_id}"
            await self._redis.zremrangebyscore(key, 0, now - 3600)
            redis_count = await self._redis.zcard(key)
            if redis_count >= dynamic_limit:
                if await self._store.should_send_notice(chat_id, user_id, "quota_exceeded", ttl_seconds=3600):
                    await event.reply(SNARKY_REPLY)
                blocked = True
            else:
                redis_meta = (key, now)
        else:
            if recent_count >= dynamic_limit:
                if await self._store.should_send_notice(chat_id, user_id, "quota_exceeded", ttl_seconds=3600):
                    await event.reply(SNARKY_REPLY)
                blocked = True

        if blocked:
            data["throttle_blocked"] = True
        elif redis_meta:
            data["redis_quota"] = redis_meta

        return await handler(event, data)
