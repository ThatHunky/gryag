from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from app.config import get_settings
from app.handlers.admin import router as admin_router, ADMIN_COMMANDS
from app.handlers.chat import router as chat_router
from app.handlers.profile_admin import router as profile_admin_router, PROFILE_COMMANDS
from app.middlewares.chat_meta import ChatMetaMiddleware
from app.middlewares.throttle import ThrottleMiddleware
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.user_profile import UserProfileStore
from app.services.fact_extractors import create_hybrid_extractor
from app.services.profile_summarization import ProfileSummarizer
from app.services.resource_monitor import get_resource_monitor
from app.services.resource_optimizer import (
    get_resource_optimizer,
    periodic_optimization_check,
)
from app.services.monitoring.continuous_monitor import ContinuousMonitor
from app.services.context import HybridSearchEngine, EpisodicMemoryStore
from app.services.context.episode_boundary_detector import EpisodeBoundaryDetector
from app.services.context.episode_monitor import EpisodeMonitor
from app.services.context.episode_summarizer import EpisodeSummarizer

try:  # Optional dependency
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - redis optional.
    redis = None  # type: ignore


async def setup_bot_commands(bot: Bot) -> None:
    """Set up bot commands with descriptions for the command menu."""
    all_commands = (
        [
            BotCommand(
                command="gryag",
                description="Запитати бота (альтернатива @mention або reply)",
            ),
        ]
        + ADMIN_COMMANDS
        + PROFILE_COMMANDS
    )

    try:
        await bot.set_my_commands(commands=all_commands)
        logging.info(f"Bot commands registered: {len(all_commands)} commands")
    except Exception as e:
        logging.warning(f"Failed to set bot commands: {e}")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    settings = get_settings()

    bot = Bot(
        token=settings.telegram_token, default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()

    store = ContextStore(settings.db_path)
    await store.init()

    gemini_client = GeminiClient(
        settings.gemini_api_key,
        settings.gemini_model,
        settings.gemini_embed_model,
    )

    # Initialize user profiling system
    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()

    # Create hybrid fact extractor based on configuration
    fact_extractor = await create_hybrid_extractor(
        extraction_method=settings.fact_extraction_method,
        local_model_path=settings.local_model_path,
        local_model_threads=settings.local_model_threads,
        enable_gemini_fallback=settings.enable_gemini_fallback,
        gemini_client=gemini_client if settings.enable_gemini_fallback else None,
    )

    # Initialize profile summarization (Phase 2)
    profile_summarizer = ProfileSummarizer(settings, profile_store, gemini_client)
    await profile_summarizer.start()

    # Phase 3: Initialize hybrid search and episodic memory
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

    logging.info(
        "Multi-level context services initialized",
        extra={
            "hybrid_search": True,
            "episodic_memory": True,
        },
    )

    # Phase 4: Initialize episode boundary detector and monitor
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

    # Start background monitoring if enabled
    if settings.auto_create_episodes:
        await episode_monitor.start()
        logging.info("Episode monitoring started")
    else:
        logging.info("Episode monitoring disabled (AUTO_CREATE_EPISODES=false)")

    # Phase 1+: Initialize continuous monitoring system
    continuous_monitor = ContinuousMonitor(
        settings=settings,
        context_store=store,
        gemini_client=gemini_client,
        user_profile_store=profile_store,
        fact_extractor=fact_extractor,
        enable_monitoring=settings.enable_continuous_monitoring,
        enable_filtering=settings.enable_message_filtering,
        enable_async_processing=settings.enable_async_processing,
    )

    # Start async processing if enabled (Phase 3+)
    await continuous_monitor.start()
    logging.info(
        "Continuous monitoring initialized",
        extra={
            "enabled": settings.enable_continuous_monitoring,
            "filtering": settings.enable_message_filtering,
            "async_processing": settings.enable_async_processing,
        },
    )

    # Phase 3: Initialize resource monitoring
    resource_monitor = get_resource_monitor()
    if resource_monitor.is_available():
        logging.info("Resource monitoring enabled")
        # Log initial stats
        resource_monitor.log_resource_summary()
    else:
        logging.warning(
            "Resource monitoring unavailable (psutil not installed). "
            "Install with: pip install psutil"
        )

    # Phase 3: Create background task for periodic resource monitoring with optimization
    resource_optimizer = get_resource_optimizer()

    async def monitor_resources() -> None:
        """Periodically check and log resource usage with auto-optimization."""
        while True:
            try:
                # Check and apply optimizations
                optimization_result = await resource_optimizer.check_and_optimize()

                if optimization_result.get("level_changed"):
                    logging.info(
                        "Resource optimization applied", extra=optimization_result
                    )

                # Regular resource monitoring
                if resource_monitor.is_available():
                    resource_monitor.check_memory_pressure()
                    resource_monitor.check_cpu_pressure()

                    # Log detailed summary every 10 minutes
                    import time

                    if (
                        int(time.time()) % 600 < 60
                    ):  # Within first minute of 10-min window
                        resource_monitor.log_resource_summary()

                        # Also log optimization stats
                        opt_stats = resource_optimizer.get_stats()
                        if opt_stats["current_optimization_level"] > 0:
                            logging.info("Resource optimizer active", extra=opt_stats)

            except Exception as e:
                logging.error(f"Error in resource monitoring: {e}", exc_info=True)

            # Adaptive sleep based on optimization level
            sleep_time = 60
            if resource_optimizer.is_emergency_mode():
                sleep_time = 30  # Check more frequently in emergency mode

            await asyncio.sleep(sleep_time)

    monitor_task: asyncio.Task[None] | None = None
    if resource_monitor.is_available():
        monitor_task = asyncio.create_task(monitor_resources())

    redis_client: Optional[Any] = None
    if settings.use_redis and redis is not None:
        try:
            redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=False,
            )
        except Exception as exc:  # pragma: no cover - connection errors
            logging.warning("Не вдалося під'єднати Redis: %s", exc)

    dispatcher.message.middleware(
        ChatMetaMiddleware(
            bot,
            settings,
            store,
            gemini_client,
            profile_store,
            fact_extractor,
            hybrid_search=hybrid_search,
            episodic_memory=episodic_memory,
            episode_monitor=episode_monitor,
            continuous_monitor=continuous_monitor,
            redis_client=redis_client,
        )
    )
    dispatcher.message.middleware(
        ThrottleMiddleware(store, settings, redis_client=redis_client)
    )

    dispatcher.include_router(admin_router)
    dispatcher.include_router(profile_admin_router)
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

        # Cleanup: Stop continuous monitoring
        await continuous_monitor.stop()
        logging.info("Continuous monitoring stopped")

        # Cleanup phase 3: cancel resource monitoring task
        if monitor_task is not None:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        # Cleanup profile summarizer
        await profile_summarizer.stop()

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
