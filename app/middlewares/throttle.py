from __future__ import annotations

import time
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.triggers import addressed_to_bot
from app.services.redis_types import RedisLike
from app.services import telemetry

SNARKY_REPLY = "Пригальмуй, балакучий. За годину вже досить."


LOGGER = logging.getLogger(__name__)


class ThrottleMiddleware(BaseMiddleware):
    """Limit addressed interactions per user per chat."""

    def __init__(
        self,
        store: ContextStore,
        settings: Settings,
        redis_client: RedisLike | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._redis: RedisLike | None = redis_client

    async def __call__(self, handler, event: Message, data):  # type: ignore[override]
        if not isinstance(event, Message):
            return await handler(event, data)

        bot_username: str | None = data.get("bot_username")
        bot_id: int | None = data.get("bot_id")
        if (not bot_username and bot_id is None) or event.from_user is None:
            return await handler(event, data)

        if not addressed_to_bot(event, bot_username or "", bot_id):
            return await handler(event, data)

        chat_id = event.chat.id
        user_id = event.from_user.id
        base_limit = self._settings.per_user_per_hour

        if user_id in self._settings.admin_user_ids:
            telemetry.increment_counter("throttle.admin_bypass")
            data["throttle_passed"] = True
            return await handler(event, data)

        now = int(time.time())
        window_seconds = 3 * 3600
        limit_window = max(20, base_limit * 2)
        recent_times: list[int] = []
        quota_source = "sqlite"
        redis_key: str | None = None
        if self._redis is not None:
            redis_key = f"gryag:quota:{chat_id}:{user_id}"
            try:
                await self._redis.zremrangebyscore(redis_key, 0, now - window_seconds)
                entries = await self._redis.zrange(
                    redis_key,
                    0,
                    limit_window - 1,
                    desc=True,
                    withscores=True,
                )
                redis_times = [int(score) for _, score in entries]
                if redis_times:
                    recent_times = redis_times
                    quota_source = "redis"
            except Exception:  # pragma: no cover - network/runtime failures
                LOGGER.exception(
                    "Redis quota lookup failed for chat=%s user=%s", chat_id, user_id
                )
        if not recent_times:
            recent_times = await self._store.recent_request_times(
                chat_id=chat_id,
                user_id=user_id,
                window_seconds=window_seconds,
                limit=limit_window,
            )
            quota_source = "sqlite"

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
            if recent_count >= dynamic_limit:
                if await self._store.should_send_notice(
                    chat_id, user_id, "quota_exceeded", ttl_seconds=3600
                ):
                    await event.reply(SNARKY_REPLY)
                blocked = True
            else:
                redis_meta = (redis_key or f"gryag:quota:{chat_id}:{user_id}", now)
        else:
            if recent_count >= dynamic_limit:
                if await self._store.should_send_notice(
                    chat_id, user_id, "quota_exceeded", ttl_seconds=3600
                ):
                    await event.reply(SNARKY_REPLY)
                blocked = True

        if blocked:
            telemetry.increment_counter("throttle.blocked")
            data["throttle_blocked"] = True
            data["throttle_reason"] = {
                "limit": dynamic_limit,
                "recent": recent_count,
                "source": quota_source,
            }
            LOGGER.info(
                "Throttle block chat=%s user=%s source=%s limit=%s recent=%s",
                chat_id,
                user_id,
                quota_source,
                dynamic_limit,
                recent_count,
            )
        else:
            telemetry.increment_counter("throttle.passed")
            if redis_meta:
                data["redis_quota"] = redis_meta

        return await handler(event, data)
