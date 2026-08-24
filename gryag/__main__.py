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
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from gryag import (
    admin,
    config,
    digest,
    handlers,
    llm,
    lore,
    pidor,
    pidrahuika,
    proactive,
    screens,
    store,
)

@dataclass
class Runtime:
    """Everything built inside the loop. The proactive task needs the database, the
    client and the persona box, none of which used to leave `build`."""

    bot: Bot
    dispatcher: Dispatcher
    db: object
    client: object
    persona: dict


ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "message_reaction"]
"""`message_reaction` arrives only where the bot is an administrator, and only when it is
named here — the default list leaves it out. Where it never arrives, the lore is built
without reactions and nothing else changes."""

WEBHOOK_PATH = "/webhook"
PERSONA_PATH = Path(__file__).resolve().parent.parent / "eval" / "persona-v3.txt"


async def build(secrets: config.Secrets) -> "Runtime":
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
        screens._persona_size_hint["chars"] = len(persona["text"])
        logging.info("persona reloaded, %s characters", len(persona["text"]))
        return len(persona["text"]) // 3

    async def rerun_digest(conn, chat_id: int) -> None:
        """One chat, the one whose button was tapped.

        This used to call digest.run, which loops every enabled chat and bills for each,
        while the toast claimed only this chat had been regenerated.
        """
        day = digest.yesterday()
        model = await config.get(conn, "digest_model", chat_id)
        if await digest.summarise_day(conn, client, chat_id, day, model):
            await digest.rebuild_week(conn, client, chat_id, model)

    async def rerun_lore(conn, chat_id: int) -> bool:
        """One chat, the one whose button was tapped, and the interval is bypassed: the
        admin has already decided to pay for it."""
        return await lore.generate(conn, client, chat_id, force=True)

    bot = Bot(secrets.bot_token, default=DefaultBotProperties(parse_mode=None))
    me = await bot.get_me()
    logging.info("running as @%s (id %s)", me.username, me.id)

    # Only the public ones. /gryag, /nb and /unban stay off this list on purpose — a menu
    # entry nobody but the admin can use is an invitation to try it.
    await bot.set_my_commands([
        BotCommand(command="pidor", description="хто сьогодні підарас дня"),
        BotCommand(command="pidorstats", description="підараси року"),
        BotCommand(command="pidrahuika", description="підрахуйка СБС за сьогодні"),
        BotCommand(command="lore", description="лор чату"),
    ])

    dispatcher = Dispatcher(db=db, client=client, persona=persona, bot_id=me.id)
    dispatcher.include_router(
        admin.build_router(
            secrets.admin_ids,
            on_reload=reload_persona,
            on_digest=rerun_digest,
            on_lore=rerun_lore,
            persona=persona,
        )
    )
    dispatcher.include_router(pidor.build_router())
    dispatcher.include_router(pidrahuika.build_router())
    dispatcher.include_router(lore.build_router())
    dispatcher.include_router(handlers.build_router())
    return Runtime(bot=bot, dispatcher=dispatcher, db=db, client=client, persona=persona)


_background: set[asyncio.Task] = set()


async def start(secrets: config.Secrets) -> "Runtime":
    """Build everything and start the proactive loop.

    Both transports go through here. Having two copies of this is what broke polling:
    the Runtime fix was applied to the webhook path and its twin kept unpacking a
    dataclass as a tuple, so the default MODE could not start at all.
    """
    rt = await build(secrets)
    task = asyncio.create_task(proactive.loop(rt.db, rt.client, rt.bot, rt.persona))
    # Keep a reference: asyncio only holds a weak one, and a bare task can be collected
    # mid-flight.
    _background.add(task)
    task.add_done_callback(_background.discard)
    return rt


async def serve_webhook(secrets: config.Secrets) -> None:
    rt = await start(secrets)
    bot, dispatcher = rt.bot, rt.dispatcher

    await bot.set_webhook(
        f"{secrets.webhook_base}{WEBHOOK_PATH}",
        secret_token=secrets.webhook_secret,
        drop_pending_updates=False,
        allowed_updates=ALLOWED_UPDATES,
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
    rt = await start(secrets)
    # Do NOT drop pending updates. Telegram holds them for 24 hours, and dropping them
    # punched 11-16 message holes in the stored history at every restart — a quarter of
    # the chat went missing across six restarts. The backlog is replayed and stored;
    # `max_reply_age` in the gate is what stops the bot answering stale messages.
    await rt.bot.delete_webhook(drop_pending_updates=False)
    logging.info("polling mode")
    await rt.dispatcher.start_polling(rt.bot, allowed_updates=ALLOWED_UPDATES)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    secrets = config.secrets()
    mode = os.environ.get("MODE", "polling")
    asyncio.run(serve_webhook(secrets) if mode == "webhook" else serve_polling(secrets))


if __name__ == "__main__":
    main()
