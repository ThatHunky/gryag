from __future__ import annotations

import asyncio
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient

try:  # Optional dependency for Redis support.
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - redis optional.
    Redis = Any  # type: ignore


class ChatMetaMiddleware(BaseMiddleware):
    """Inject frequently used services into handler context."""

    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        store: ContextStore,
        gemini: GeminiClient,
        redis_client: Redis | None = None,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._store = store
        self._gemini = gemini
        self._redis = redis_client
        self._bot_username: str | None = None
        self._lock = asyncio.Lock()

    async def _ensure_bot_username(self) -> str:
        if self._bot_username:
            return self._bot_username
        async with self._lock:
            if not self._bot_username:
                me = await self._bot.get_me()
                self._bot_username = me.username or ""
        return self._bot_username or ""

    async def __call__(self, handler, event: Message, data):  # type: ignore[override]
        if isinstance(event, Message):
            data["bot_username"] = await self._ensure_bot_username()
        data["settings"] = self._settings
        data["store"] = self._store
        data["gemini_client"] = self._gemini
        if self._redis is not None:
            data["redis_client"] = self._redis
        return await handler(event, data)
