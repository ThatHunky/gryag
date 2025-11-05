"""Application initialization and service setup.

This module contains helper functions for initializing various services
and components of the bot application.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import Settings
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.user_profile_adapter import UserProfileStoreAdapter
from app.repositories.chat_profile import ChatProfileRepository
from app.services.fact_extractors import create_hybrid_extractor
from app.services.profile_summarization import ProfileSummarizer
from app.services.rate_limiter import RateLimiter
from app.services.system_prompt_manager import SystemPromptManager
from app.services.context import HybridSearchEngine, EpisodicMemoryStore
from app.services.context.episode_boundary_detector import EpisodeBoundaryDetector
from app.services.context.episode_monitor import EpisodeMonitor
from app.services.context.episode_summarizer import EpisodeSummarizer
from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine

if TYPE_CHECKING:
    from app.services.fact_extractors.base import FactExtractor
    from redis.asyncio import Redis as RedisClient
else:
    FactExtractor = Any
    RedisClient = Any

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # type: ignore


logger = logging.getLogger(__name__)


class ServiceContainer:
    """Container for all initialized services."""

    def __init__(
        self,
        bot: Bot,
        dispatcher: Dispatcher,
        settings: Settings,
        store: ContextStore,
        rate_limiter: RateLimiter,
        gemini_client: GeminiClient,
        profile_store: UserProfileStoreAdapter,
        chat_profile_store: Optional[ChatProfileRepository],
        fact_extractor: FactExtractor,
        profile_summarizer: ProfileSummarizer,
        hybrid_search: HybridSearchEngine,
        episodic_memory: EpisodicMemoryStore,
        prompt_manager: SystemPromptManager,
        episode_monitor: EpisodeMonitor,
        bot_profile: Optional[BotProfileStore],
        bot_learning: Optional[BotLearningEngine],
        redis_client: Optional[RedisClient],
        image_gen_service: Optional[Any],
    ):
        self.bot = bot
        self.dispatcher = dispatcher
        self.settings = settings
        self.store = store
        self.rate_limiter = rate_limiter
        self.gemini_client = gemini_client
        self.profile_store = profile_store
        self.chat_profile_store = chat_profile_store
        self.fact_extractor = fact_extractor
        self.profile_summarizer = profile_summarizer
        self.hybrid_search = hybrid_search
        self.episodic_memory = episodic_memory
        self.prompt_manager = prompt_manager
        self.episode_monitor = episode_monitor
        self.bot_profile = bot_profile
        self.bot_learning = bot_learning
        self.redis_client = redis_client
        self.image_gen_service = image_gen_service


async def init_bot_and_dispatcher(settings: Settings) -> tuple[Bot, Dispatcher]:
    """Initialize the Telegram bot and dispatcher.

    Args:
        settings: Application settings

    Returns:
        Tuple of (Bot, Dispatcher)
    """
    bot = Bot(
        token=settings.telegram_token, default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()
    return bot, dispatcher


async def init_core_services(settings: Settings) -> tuple[
    ContextStore,
    RateLimiter,
    GeminiClient,
    UserProfileStoreAdapter,
]:
    """Initialize core services (database, rate limiter, API client, profile store).

    Args:
        settings: Application settings

    Returns:
        Tuple of (ContextStore, RateLimiter, GeminiClient, UserProfileStoreAdapter)
    """
    store = ContextStore(settings.db_path)
    await store.init()

    rate_limiter = RateLimiter(settings.db_path, settings.per_user_per_hour)
    await rate_limiter.init()

    gemini_client = GeminiClient(
        settings.gemini_api_key,
        settings.gemini_model,
        settings.gemini_embed_model,
        api_keys=settings.gemini_api_keys_list,
        free_tier_mode=settings.free_tier_mode,
        quota_block_seconds=settings.gemini_quota_block_seconds,
        enable_thinking=settings.gemini_enable_thinking,
        thinking_budget_tokens=settings.thinking_budget_tokens,
    )

    profile_store = UserProfileStoreAdapter(settings.db_path)
    await profile_store.init()

    return store, rate_limiter, gemini_client, profile_store


async def init_chat_memory(settings: Settings) -> Optional[ChatProfileRepository]:
    """Initialize chat public memory system if enabled.

    Args:
        settings: Application settings

    Returns:
        ChatProfileRepository instance if enabled, None otherwise
    """
    if not settings.enable_chat_memory:
        logger.info("Chat public memory disabled (ENABLE_CHAT_MEMORY=false)")
        return None

    chat_profile_store = ChatProfileRepository(db_path=settings.db_path)

    logger.info(
        "Chat public memory initialized",
        extra={
            "fact_extraction": settings.enable_chat_fact_extraction,
            "extraction_method": settings.chat_fact_extraction_method,
            "max_facts_in_context": settings.max_chat_facts_in_context,
        },
    )

    return chat_profile_store


async def init_context_services(
    settings: Settings,
    gemini_client: GeminiClient,
) -> tuple[HybridSearchEngine, EpisodicMemoryStore]:
    """Initialize hybrid search and episodic memory services.

    Args:
        settings: Application settings
        gemini_client: Initialized Gemini client

    Returns:
        Tuple of (HybridSearchEngine, EpisodicMemoryStore)
    """
    hybrid_search = HybridSearchEngine(
        db_path=settings.db_path,
        gemini_client=gemini_client,
        settings=settings,
    )

    episodic_memory = EpisodicMemoryStore(
        db_path=settings.db_path,
        gemini_client=gemini_client,
        settings=settings,
    )
    await episodic_memory.init()

    logger.info(
        "Multi-level context services initialized",
        extra={
            "hybrid_search": True,
            "episodic_memory": True,
        },
    )

    return hybrid_search, episodic_memory


async def init_episode_monitoring(
    settings: Settings,
    gemini_client: GeminiClient,
    episodic_memory: EpisodicMemoryStore,
) -> EpisodeMonitor:
    """Initialize episode boundary detection and monitoring.

    Args:
        settings: Application settings
        gemini_client: Initialized Gemini client
        episodic_memory: Initialized episodic memory store

    Returns:
        EpisodeMonitor instance
    """
    episode_boundary_detector = EpisodeBoundaryDetector(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini_client,
    )

    episode_monitor = EpisodeMonitor(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini_client,
        episodic_memory=episodic_memory,
        boundary_detector=episode_boundary_detector,
        summarizer=EpisodeSummarizer(settings=settings, gemini_client=gemini_client),
    )

    if settings.auto_create_episodes:
        await episode_monitor.start()
        logger.info("Episode monitoring started")
    else:
        logger.info("Episode monitoring disabled (AUTO_CREATE_EPISODES=false)")

    return episode_monitor


async def init_bot_learning(
    settings: Settings,
    bot: Bot,
    gemini_client: GeminiClient,
) -> tuple[Optional[BotProfileStore], Optional[BotLearningEngine]]:
    """Initialize bot self-learning system if enabled.

    Args:
        settings: Application settings
        bot: Telegram bot instance
        gemini_client: Initialized Gemini client

    Returns:
        Tuple of (BotProfileStore, BotLearningEngine) if enabled, (None, None) otherwise
    """
    if not settings.enable_bot_self_learning:
        logger.info("Bot self-learning disabled (ENABLE_BOT_SELF_LEARNING=false)")
        return None, None

    me = await bot.get_me()
    bot_id = me.id

    bot_profile = BotProfileStore(
        db_path=settings.db_path_str,
        bot_id=bot_id,
        gemini_client=gemini_client,
        enable_temporal_decay=settings.enable_temporal_decay,
        enable_semantic_dedup=settings.enable_semantic_dedup,
    )
    await bot_profile.init()

    bot_learning = BotLearningEngine(
        bot_profile=bot_profile,
        gemini_client=gemini_client,
        enable_gemini_insights=settings.enable_gemini_insights,
    )

    logger.info(
        "Bot self-learning initialized",
        extra={
            "bot_id": bot_id,
            "temporal_decay": settings.enable_temporal_decay,
            "semantic_dedup": settings.enable_semantic_dedup,
            "gemini_insights": settings.enable_gemini_insights,
        },
    )

    return bot_profile, bot_learning


async def init_image_generation(settings: Settings) -> Optional[Any]:
    """Initialize image generation service if enabled.

    Args:
        settings: Application settings

    Returns:
        ImageGenerationService instance if enabled, None otherwise
    """
    if not settings.enable_image_generation:
        logger.info("Image generation disabled (ENABLE_IMAGE_GENERATION=false)")
        return None

    from app.services.image_generation import ImageGenerationService

    # Use separate API key if provided, otherwise fall back to main Gemini key
    image_api_key = settings.image_generation_api_key or settings.gemini_api_key

    image_gen_service = ImageGenerationService(
        api_key=image_api_key,
        db_path=settings.db_path,
        daily_limit=settings.image_generation_daily_limit,
        admin_user_ids=settings.admin_user_ids_list,
    )

    using_separate_key = settings.image_generation_api_key is not None
    logger.info(
        "Image generation service initialized",
        extra={
            "daily_limit": settings.image_generation_daily_limit,
            "model": "gemini-2.5-flash-image",
            "separate_api_key": using_separate_key,
        },
    )

    return image_gen_service


async def init_redis_client(settings: Settings) -> Optional[RedisClient]:
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
                logger.warning(f"Не вдалося під'єднати Redis після {max_retries} спроб: {exc}")
                return None
    
    return None
