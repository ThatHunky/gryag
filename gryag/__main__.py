"""Entrypoint.

Two delivery modes. Webhook is the design's choice (spec §13), but it needs a DNS record
for WEBHOOK_BASE that did not exist when phase 1 shipped, so polling is the default until
that record is created. At ~35 replies a day the difference is not observable; the mode is
one environment variable, and nothing else in the bot depends on it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from gryag import admin, config, digest, handlers, llm, proactive, store

WEBHOOK_PATH = "/webhook"
PERSONA_PATH = Path(__file__).resolve().parent.parent / "eval" / "persona-v3.txt"


async def build(secrets: config.Secrets) -> tuple[Bot, Dispatcher]:
    """Everything is constructed inside the running loop.

    The database connection, the bot session and the aiohttp app must all belong to the
    same event loop, so none of this may happen at import time or in a separate
    `asyncio.run`.
    """
    db = await store.connect(secrets.db_path)
    client = llm.build_client(secrets.gemini_api_key)

    # The persona lives in a mutable box so the menu can swap it without a restart.
    # Editing it and waiting for a deploy is how a voice never gets tuned.
    persona = {"text": PERSONA_PATH.read_text()}

    def reload_persona() -> int:
        persona["text"] = PERSONA_PATH.read_text()
        logging.info("persona reloaded, %s characters", len(persona["text"]))
        return len(persona["text"]) // 3

    async def rerun_digest(conn, chat_id: int) -> None:
        await digest.run(conn, client, day=digest.yesterday())

    bot = Bot(secrets.bot_token, default=DefaultBotProperties(parse_mode=None))
    me = await bot.get_me()
    logging.info("running as @%s (id %s)", me.username, me.id)

    dispatcher = Dispatcher(db=db, client=client, persona=persona, bot_id=me.id)
    dispatcher.include_router(
        admin.build_router(secrets.admin_ids, on_reload=reload_persona, on_digest=rerun_digest)
    )
    dispatcher.include_router(handlers.build_router())
    return bot, dispatcher


async def serve_webhook(secrets: config.Secrets) -> None:
    bot, dispatcher = await build(secrets)
    asyncio.create_task(proactive.loop(db, client, bot, persona))

    await bot.set_webhook(
        f"{secrets.webhook_base}{WEBHOOK_PATH}",
        secret_token=secrets.webhook_secret,
        drop_pending_updates=False,
        allowed_updates=["message", "edited_message", "callback_query"],
    )
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=secrets.webhook_secret
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host="127.0.0.1", port=secrets.port).start()
    logging.info("webhook mode, listening on 127.0.0.1:%s", secrets.port)
    await asyncio.Event().wait()


async def serve_polling(secrets: config.Secrets) -> None:
    bot, dispatcher = await build(secrets)
    # Do NOT drop pending updates. Telegram holds them for 24 hours, and dropping them
    # punched 11-16 message holes in the stored history at every restart — a quarter of
    # the chat went missing across six restarts. The backlog is replayed and stored;
    # `max_reply_age` in the gate is what stops the bot answering stale messages.
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(proactive.loop(db, client, bot, persona))
    logging.info("polling mode")
    await dispatcher.start_polling(
        bot, allowed_updates=["message", "edited_message", "callback_query"]
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    secrets = config.secrets()
    mode = os.environ.get("MODE", "polling")
    asyncio.run(serve_webhook(secrets) if mode == "webhook" else serve_polling(secrets))


if __name__ == "__main__":
    main()
