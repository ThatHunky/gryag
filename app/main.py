from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import get_settings
from app.handlers.admin import router as admin_router
from app.handlers.chat import router as chat_router
from app.middlewares.chat_meta import ChatMetaMiddleware
from app.middlewares.throttle import ThrottleMiddleware
from app.services.context_store import ContextStore
from app.services.gemini import GeminiClient
from app.services.user_profile import UserProfileStore, FactExtractor

try:  # Optional dependency
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - redis optional.
    redis = None  # type: ignore


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

    fact_extractor = FactExtractor(gemini_client)

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
            redis_client=redis_client,
        )
    )
    dispatcher.message.middleware(
        ThrottleMiddleware(store, settings, redis_client=redis_client)
    )

    dispatcher.include_router(admin_router)
    dispatcher.include_router(chat_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, skip_updates=True)
    finally:
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
