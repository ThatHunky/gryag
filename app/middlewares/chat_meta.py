from __future__ import annotations

import asyncio
from aiogram import BaseMiddleware, Bot
from aiogram.types import Message

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.redis_types import RedisLike
from app.services.user_profile import UserProfileStore
from app.services.fact_extractors import FactExtractor


class ChatMetaMiddleware(BaseMiddleware):
    """Inject frequently used services into handler context."""

    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        store: ContextStore,
        gemini: GeminiClient,
        profile_store: UserProfileStore,
        fact_extractor: FactExtractor,
        redis_client: RedisLike | None = None,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._store = store
        self._gemini = gemini
        self._profile_store = profile_store
        self._fact_extractor = fact_extractor
        self._redis = redis_client
        self._bot_username: str | None = None
        self._bot_id: int | None = None
        self._lock = asyncio.Lock()

    async def _ensure_bot_identity(self) -> tuple[str, int | None]:
        if self._bot_username is not None and self._bot_id is not None:
            return self._bot_username, self._bot_id
        async with self._lock:
            if self._bot_username is None or self._bot_id is None:
                me = await self._bot.get_me()
                self._bot_username = me.username or ""
                self._bot_id = me.id
        return self._bot_username or "", self._bot_id

    async def __call__(self, handler, event: Message, data):  # type: ignore[override]
        if isinstance(event, Message):
            bot_username, bot_id = await self._ensure_bot_identity()
            data["bot_username"] = bot_username
            data["bot_id"] = bot_id
        data["settings"] = self._settings
        data["store"] = self._store
        data["gemini_client"] = self._gemini
        data["profile_store"] = self._profile_store
        data["fact_extractor"] = self._fact_extractor
        if self._redis is not None:
            data["redis_client"] = self._redis
        return await handler(event, data)
