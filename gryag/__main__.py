"""Entrypoint. Webhook mode behind Caddy."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from gryag import admin, config, handlers, llm, store

WEBHOOK_PATH = "/webhook"
PERSONA_PATH = Path(__file__).resolve().parent.parent / "eval" / "persona-v3.txt"


async def build_app() -> web.Application:
    """Everything is constructed inside the running loop.

    The database connection, the aiohttp app and the bot session must all belong to the
    same event loop. Building the app with `asyncio.run` and then handing it to
    `web.run_app` would create them in a loop that is closed before the server starts.
    """
    secrets = config.secrets()
    logging.basicConfig(level=logging.INFO)

    db = await store.connect(secrets.db_path)
    client = llm.build_client(secrets.gemini_api_key)
    persona = PERSONA_PATH.read_text()

    bot = Bot(secrets.bot_token, default=DefaultBotProperties(parse_mode=None))
    me = await bot.get_me()

    dispatcher = Dispatcher(db=db, client=client, persona=persona, bot_id=me.id)
    dispatcher.include_router(admin.build_router(secrets.admin_ids))
    dispatcher.include_router(handlers.build_router())

    await bot.set_webhook(
        f"{secrets.webhook_base}{WEBHOOK_PATH}",
        secret_token=secrets.webhook_secret,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=secrets.webhook_secret
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    return app


async def serve() -> None:
    app = await build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=8081)
    await site.start()
    logging.info("listening on 127.0.0.1:8081")
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
