from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.redis_types import RedisLike

if TYPE_CHECKING:
    from app.services.user_profile import UserProfileStore
    from app.services.user_profile_adapter import UserProfileStoreAdapter

    ProfileStoreType = UserProfileStore | UserProfileStoreAdapter
else:
    ProfileStoreType = Any
from app.services.context import (
    HybridSearchEngine,
    EpisodicMemoryStore,
    MultiLevelContextManager,
)
from app.services.context.episode_monitor import EpisodeMonitor
from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine
from app.services.system_prompt_manager import SystemPromptManager
from app.services.rate_limiter import RateLimiter
from app.services.persona import PersonaLoader


class ChatMetaMiddleware(BaseMiddleware):
    """Inject frequently used services into handler context."""

    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        store: ContextStore,
        gemini: GeminiClient,
        profile_store: ProfileStoreType,
        chat_profile_store: Any | None = None,
        hybrid_search: HybridSearchEngine | None = None,
        episodic_memory: EpisodicMemoryStore | None = None,
        episode_monitor: EpisodeMonitor | None = None,
        bot_profile: BotProfileStore | None = None,
        bot_learning: BotLearningEngine | None = None,
        prompt_manager: SystemPromptManager | None = None,
        redis_client: RedisLike | None = None,
        rate_limiter: RateLimiter | None = None,
        image_gen_service: Any | None = None,
        feature_limiter: Any | None = None,
        donation_scheduler: Any | None = None,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._store = store
        self._gemini = gemini
        self._profile_store = profile_store
        self._chat_profile_store = chat_profile_store
        self._hybrid_search = hybrid_search
        self._episodic_memory = episodic_memory
        self._episode_monitor = episode_monitor
        self._bot_profile = bot_profile
        self._bot_learning = bot_learning
        self._prompt_manager = prompt_manager
        self._redis = redis_client
        self._rate_limiter = rate_limiter
        self._image_gen_service = image_gen_service
        self._feature_limiter = feature_limiter
        self._donation_scheduler = donation_scheduler
        self._bot_username: str | None = None
        self._bot_id: int | None = None
        self._lock = asyncio.Lock()
        self._multi_level_context_manager: MultiLevelContextManager | None = None

        # Phase 3: Initialize PersonaLoader for response templates
        self._persona_loader: PersonaLoader | None = None
        if settings.enable_persona_templates:
            self._persona_loader = PersonaLoader(
                persona_config_path=settings.persona_config or None,
                response_templates_path=settings.response_templates or None,
            )

    async def _ensure_bot_identity(self) -> tuple[str, int | None]:
        if self._bot_username is not None and self._bot_id is not None:
            return self._bot_username, self._bot_id
        async with self._lock:
            if self._bot_username is None or self._bot_id is None:
                me = await self._bot.get_me()
                self._bot_username = me.username or ""
                self._bot_id = me.id
        return self._bot_username or "", self._bot_id

    async def __call__(self, handler, event: Message | CallbackQuery, data):  # type: ignore[override]
        if isinstance(event, Message):
            bot_username, bot_id = await self._ensure_bot_identity()
            data["bot_username"] = bot_username
            data["bot_id"] = bot_id
        elif isinstance(event, CallbackQuery):
            # Also inject bot identity for callback queries
            bot_username, bot_id = await self._ensure_bot_identity()
            data["bot_username"] = bot_username
            data["bot_id"] = bot_id
        data["settings"] = self._settings
        data["store"] = self._store
        data["gemini_client"] = self._gemini
        data["profile_store"] = self._profile_store
        data["chat_profile_store"] = self._chat_profile_store
        data["hybrid_search"] = self._hybrid_search
        data["episodic_memory"] = self._episodic_memory
        data["episode_monitor"] = self._episode_monitor
        data["bot_profile"] = self._bot_profile
        data["bot_learning"] = self._bot_learning
        data["prompt_manager"] = self._prompt_manager
        data["feature_limiter"] = self._feature_limiter
        if (
            self._multi_level_context_manager is None
            and self._settings.enable_multi_level_context
            and self._hybrid_search is not None
            and self._episodic_memory is not None
        ):
            self._multi_level_context_manager = MultiLevelContextManager(
                db_path=self._settings.db_path,
                settings=self._settings,
                context_store=self._store,
                profile_store=self._profile_store,
                chat_profile_store=self._chat_profile_store,
                hybrid_search=self._hybrid_search,
                episode_store=self._episodic_memory,
                gemini_client=self._gemini,
            )
        if self._multi_level_context_manager is not None:
            data["multi_level_context_manager"] = self._multi_level_context_manager
        if self._redis is not None:
            data["redis_client"] = self._redis
        if self._rate_limiter is not None:
            data["rate_limiter"] = self._rate_limiter
        if self._persona_loader is not None:
            data["persona_loader"] = self._persona_loader
        if self._image_gen_service is not None:
            data["image_gen_service"] = self._image_gen_service
        if self._donation_scheduler is not None:
            data["donation_scheduler"] = self._donation_scheduler
        return await handler(event, data)
