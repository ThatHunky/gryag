from __future__ import annotations

import asyncio
import logging
import socket

import aiohttp
from typing import Any, cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from app.config import get_settings
from app.constants import USER_COMMANDS, CHECKERS_COMMANDS
from app.handlers.admin import router as admin_router, ADMIN_COMMANDS
from app.handlers.chat import router as chat_router
from app.handlers.profile_admin import router as profile_admin_router, PROFILE_COMMANDS
from app.handlers.chat_admin import router as chat_admin_router, CHAT_COMMANDS
from app.handlers.prompt_admin import router as prompt_admin_router, PROMPT_COMMANDS
from app.handlers.chat_members import router as chat_members_router
from app.handlers.checkers import router as checkers_router
from app.middlewares.chat_filter import ChatFilterMiddleware
from app.middlewares.chat_meta import ChatMetaMiddleware
from app.middlewares.command_throttle import CommandThrottleMiddleware
from app.middlewares.processing_lock import ProcessingLockMiddleware
from app.core.initialization import init_redis_client
from app.services.context_store import ContextStore, run_retention_pruning_task
from app.services.gemini import GeminiClient
from app.services.user_profile_adapter import UserProfileStoreAdapter
from app.repositories.chat_profile import ChatProfileRepository
from app.services.profile_summarization import ProfileSummarizer
from app.services.rate_limiter import RateLimiter
from app.services.feature_rate_limiter import FeatureRateLimiter
from app.services.donation_scheduler import DonationScheduler
from app.services.resource_monitor import (
    get_resource_monitor,
    run_resource_monitoring_task,
)
from app.services.system_prompt_manager import SystemPromptManager
from app.services.resource_optimizer import (
    get_resource_optimizer,
    periodic_optimization_check,
)
from app.services.context import HybridSearchEngine, EpisodicMemoryStore
from app.services.context.episode_boundary_detector import EpisodeBoundaryDetector
from app.services.context.episode_monitor import EpisodeMonitor
from app.services.context.episode_summarizer import EpisodeSummarizer
from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine
from app.repositories.memory_repository import MemoryRepository
from app.services.telegram_service import TelegramService


async def get_public_ip() -> str:
    endpoints = (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    )
    timeout = aiohttp.ClientTimeout(total=3)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for endpoint in endpoints:
            try:
                async with session.get(endpoint) as response:
                    if response.status == 200:
                        ip = (await response.text()).strip()
                        if ip:
                            return ip
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "unknown"


async def setup_bot_commands(bot: Bot) -> None:
    """Set up bot commands with descriptions for the command menu."""
    all_commands = (
        USER_COMMANDS
        + ADMIN_COMMANDS
        + PROFILE_COMMANDS
        + CHAT_COMMANDS
        + PROMPT_COMMANDS
        + CHECKERS_COMMANDS
    )

    try:
        await bot.set_my_commands(commands=all_commands)
        logging.info(f"Bot commands registered: {len(all_commands)} commands")
    except Exception as e:
        logging.warning(f"Failed to set bot commands: {e}")


async def main() -> None:
    settings = get_settings()

    # Validate configuration at startup
    try:
        warnings = settings.validate_startup()
        if warnings:
            logging.warning("Configuration warnings detected:")
            for warning in warnings:
                logging.warning(f"  - {warning}")
    except ValueError as e:
        logging.error(f"Configuration validation failed: {e}")
        raise SystemExit(1) from e

    # Setup logging with rotation and cleanup
    from app.core.logging_config import setup_logging

    setup_logging(settings)

    public_ip = await get_public_ip()
    logging.info(f"Bot starting on public IP {public_ip}")

    # Phase 2: Initialize trigger patterns from configuration
    from app.services.triggers import initialize_triggers

    trigger_patterns = (
        settings.bot_trigger_patterns_list if settings.bot_trigger_patterns else None
    )
    initialize_triggers(trigger_patterns)

    if trigger_patterns:
        logging.info(f"Initialized {len(trigger_patterns)} custom trigger patterns")
    else:
        logging.info("Using default trigger patterns")

    bot = Bot(
        token=settings.telegram_token, default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()

    # Initialize PostgreSQL database
    from app.infrastructure.db_utils import init_database

    await init_database(settings.database_url)

    store = ContextStore(settings.database_url)
    await store.init()

    # Initialize Redis early for rate limiters
    redis_client = await init_redis_client(settings)

    rate_limiter = RateLimiter(
        settings.database_url, settings.per_user_per_hour, redis_client=redis_client
    )
    await rate_limiter.init()

    # Initialize feature-level rate limiter for command throttling
    feature_limiter = FeatureRateLimiter(
        settings.database_url,
        settings.admin_user_ids_list,
        redis_client=redis_client,
    )
    await feature_limiter.init()
    logging.info("Feature rate limiter initialized (command throttling: 1 per 5 min)")

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

    # Initialize user profiling system
    profile_store = UserProfileStoreAdapter(settings.database_url, redis_client=redis_client)
    await profile_store.init()

    # Initialize the new memory repository
    memory_repo = MemoryRepository(database_url=settings.database_url)
    await memory_repo.init()
    logging.info("MemoryRepository initialized for simple memory storage.")

    # Initialize chat profiling system (Phase 4: Chat Public Memory)
    chat_profile_store: ChatProfileRepository | None = None

    if settings.enable_chat_memory:
        chat_profile_store = ChatProfileRepository(database_url=settings.database_url)

        logging.info(
            "Chat public memory initialized",
            extra={
                "fact_extraction": settings.enable_chat_fact_extraction,
                "extraction_method": settings.chat_fact_extraction_method,
                "max_facts_in_context": settings.max_chat_facts_in_context,
            },
        )
    else:
        logging.info("Chat public memory disabled (ENABLE_CHAT_MEMORY=false)")

    # Initialize profile summarization (Phase 2)
    profile_summarizer = ProfileSummarizer(
        settings, cast(Any, profile_store), gemini_client
    )
    await profile_summarizer.start()

    # Initialize donation reminder scheduler
    if settings.enable_donation_scheduler:
        # Get target chat IDs from settings (whitelist if enabled, otherwise empty list for manual management)
        donation_chat_ids = (
            settings.allowed_chat_ids_list
            if settings.bot_behavior_mode == "whitelist"
            else []
        )
        donation_scheduler = DonationScheduler(
            bot=bot,
            db_path=settings.database_url,
            context_store=store,
            target_chat_ids=donation_chat_ids,
            ignored_chat_ids=settings.donation_ignored_chat_ids_list,
        )
        await donation_scheduler.start()
        logging.info(
            "Donation scheduler initialized (sends to groups with recent activity every 2 days at 18:00 Ukraine time)"
        )
    else:
        # Create a minimal donation scheduler instance without starting it
        # Still initialize database table for on-demand sends via /gryagdonate command
        donation_scheduler = DonationScheduler(
            bot=bot,
            db_path=settings.database_url,
            context_store=store,
            target_chat_ids=[],
            ignored_chat_ids=[],
        )
        await donation_scheduler.init()  # Initialize table even when scheduler is disabled
        logging.info("Donation scheduler disabled (ENABLE_DONATION_SCHEDULER=false), but table initialized for on-demand sends")

    # Phase 3: Initialize hybrid search and episodic memory
    hybrid_search = HybridSearchEngine(
        db_path=settings.database_url,
        gemini_client=gemini_client,
        settings=settings,
    )

    episodic_memory = EpisodicMemoryStore(
        db_path=settings.database_url,
        gemini_client=gemini_client,
        settings=settings,
    )
    await episodic_memory.init()

    logging.info(
        "Multi-level context services initialized",
        extra={
            "hybrid_search": True,
            "episodic_memory": True,
        },
    )

    # Initialize system prompt manager for admin configuration
    prompt_manager = SystemPromptManager(database_url=settings.database_url)
    await prompt_manager.init()
    logging.info("System prompt manager initialized")

    # Phase 4: Initialize episode boundary detector and monitor
    episode_boundary_detector = EpisodeBoundaryDetector(
        database_url=settings.database_url,
        settings=settings,
        gemini_client=gemini_client,
    )

    episode_monitor = EpisodeMonitor(
        database_url=settings.database_url,
        settings=settings,
        gemini_client=gemini_client,
        episodic_memory=episodic_memory,
        boundary_detector=episode_boundary_detector,
        summarizer=EpisodeSummarizer(settings=settings, gemini_client=gemini_client),
    )

    # Start background monitoring if enabled
    if settings.auto_create_episodes:
        await episode_monitor.start()
        logging.info("Episode monitoring started")
    else:
        logging.info("Episode monitoring disabled (AUTO_CREATE_EPISODES=false)")

    # Initialize image generation service
    image_gen_service = None
    if settings.enable_image_generation:
        from app.services.image_generation import ImageGenerationService

        # Use separate API key if provided, otherwise fall back to main Gemini key
        image_api_key = settings.image_generation_api_key or settings.gemini_api_key

        image_gen_service = ImageGenerationService(
            api_key=image_api_key,
            database_url=settings.database_url,
            daily_limit=settings.image_generation_daily_limit,
            admin_user_ids=settings.admin_user_ids_list,
        )

        using_separate_key = settings.image_generation_api_key is not None
        logging.info(
            "Image generation service initialized",
            extra={
                "daily_limit": settings.image_generation_daily_limit,
                "model": "gemini-2.5-flash-image",
                "separate_api_key": using_separate_key,
            },
        )
    else:
        logging.info("Image generation disabled (ENABLE_IMAGE_GENERATION=false)")

    # Log web search configuration
    if settings.enable_web_search:
        logging.info(
            "Web search enabled (using DuckDuckGo)",
            extra={
                "search_provider": "DuckDuckGo",
            },
        )
    else:
        logging.info("Web search disabled (ENABLE_WEB_SEARCH=false)")

    # Phase 5: Initialize bot self-learning system
    bot_profile: BotProfileStore | None = None
    bot_learning: BotLearningEngine | None = None

    if settings.enable_bot_self_learning:
        # Get bot ID early
        me = await bot.get_me()
        bot_id = me.id

        bot_profile = BotProfileStore(
            db_path=settings.database_url,
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

        logging.info(
            "Bot self-learning initialized",
            extra={
                "bot_id": bot_id,
                "temporal_decay": settings.enable_temporal_decay,
                "semantic_dedup": settings.enable_semantic_dedup,
                "gemini_insights": settings.enable_gemini_insights,
            },
        )
    else:
        logging.info("Bot self-learning disabled (ENABLE_BOT_SELF_LEARNING=false)")

    # Phase 3: Initialize resource monitoring
    resource_monitor = get_resource_monitor()
    if resource_monitor.is_available():
        logging.info("Resource monitoring enabled")
        # Log initial stats
        resource_monitor.log_resource_summary()
    else:
        logging.info("Resource monitoring disabled by configuration")

    # Phase 3: Create background task for periodic resource monitoring with optimization
    resource_optimizer = get_resource_optimizer()

    monitor_task: asyncio.Task[None] | None = None
    if resource_monitor.is_available():
        monitor_task = asyncio.create_task(
            run_resource_monitoring_task(resource_monitor, resource_optimizer)
        )

    # Background pruning task for retention (Phase B)
    prune_task: asyncio.Task[None] | None = None
    if settings.retention_enabled:
        prune_task = asyncio.create_task(
            run_retention_pruning_task(
                store,
                settings.retention_days,
                settings.retention_prune_interval_seconds,
            )
        )

    # Initialize Telegram service for moderation actions
    telegram_service = TelegramService(bot=bot, settings=settings)
    logging.info("Telegram service initialized for moderation actions.")

    chat_meta_middleware = ChatMetaMiddleware(
        bot,
        settings,
        store,
        gemini_client,
        profile_store,
        chat_profile_store=chat_profile_store,
        hybrid_search=hybrid_search,
        episodic_memory=episodic_memory,
        episode_monitor=episode_monitor,
        bot_profile=bot_profile,
        bot_learning=bot_learning,
        prompt_manager=prompt_manager,
        redis_client=redis_client,
        rate_limiter=rate_limiter,
        image_gen_service=image_gen_service,
        feature_limiter=feature_limiter,
        donation_scheduler=donation_scheduler,
        memory_repo=memory_repo,
        telegram_service=telegram_service,
    )

    dispatcher.message.middleware(chat_meta_middleware)
    dispatcher.callback_query.middleware(
        chat_meta_middleware
    )  # Also handle callback queries
    dispatcher.chat_member.middleware(chat_meta_middleware)

    # Chat filter must come BEFORE other processing to prevent wasting resources on blocked chats
    dispatcher.message.middleware(ChatFilterMiddleware(settings))

    # Processing lock: prevent multiple simultaneous messages per user (only process one at a time)
    processing_lock_middleware = ProcessingLockMiddleware(
        settings=settings,
        redis_client=redis_client,
    )
    dispatcher.message.middleware(processing_lock_middleware)

    # Command throttle: limit commands to 1 per 5 minutes (admins bypass)
    dispatcher.message.middleware(CommandThrottleMiddleware(settings, feature_limiter))

    dispatcher.include_router(admin_router)
    dispatcher.include_router(profile_admin_router)
    dispatcher.include_router(chat_admin_router)
    dispatcher.include_router(prompt_admin_router)
    dispatcher.include_router(chat_members_router)
    dispatcher.include_router(checkers_router)
    dispatcher.include_router(chat_router)

    # Setup bot commands with descriptions
    await setup_bot_commands(bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, skip_updates=True)
    finally:
        # Cleanup: Stop episode monitoring
        if settings.auto_create_episodes:
            await episode_monitor.stop()
            logging.info("Episode monitoring stopped")

        # Cleanup phase 3: cancel resource monitoring task
        if monitor_task is not None:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        # Cleanup: cancel retention pruning task
        if prune_task is not None:
            prune_task.cancel()
            try:
                await prune_task
            except asyncio.CancelledError:
                logging.info("Retention pruning task cancelled")

        # Cleanup profile summarizer
        await profile_summarizer.stop()

        # Cleanup donation scheduler
        await donation_scheduler.stop()
        logging.info("Donation scheduler stopped")

        # Cleanup: Close aiohttp sessions for external services
        from app.services.weather import cleanup_weather_service
        from app.services.currency import cleanup_currency_service

        try:
            await cleanup_weather_service()
            await cleanup_currency_service()
            logging.info("External service clients closed")
        except Exception as e:
            logging.warning(f"Error closing external service clients: {e}")

        if redis_client is not None:
            try:
                await redis_client.close()
            except Exception:  # pragma: no cover - cleanup
                pass


def run() -> None:
    """Synchronous entry point for console_scripts and python -m."""

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")


if __name__ == "__main__":
    run()
