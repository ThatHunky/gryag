"""
Gryag V2 — Python Telegram Frontend

A lightweight Telegram router that forwards messages to the Go backend.
It performs no thinking — it is purely a dumb pipe.
"""

import asyncio
import logging
import os
import uuid

import aiohttp
import structlog
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatAction, ContentType, ParseMode
from aiogram.types import BotCommand
from aiohttp import web

from md_to_tg import md_to_telegram_html

# ── Structured JSON Logging (Section 15.2) ──────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger()

# ── Configuration ────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = f"http://{os.getenv('BACKEND_HOST', 'gryag-backend')}:{os.getenv('BACKEND_PORT', '27710')}"
HEALTH_PORT = int(os.getenv("FRONTEND_HEALTH_PORT", "27711"))


# ── Bot & Dispatcher ────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def send_typing_loop(chat_id: int, stop_event: asyncio.Event) -> None:
    """Continuously emit typing indicators until the backend responds (Section 10)."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        await asyncio.sleep(4)


@dp.message()
async def handle_message(message: types.Message) -> None:
    """Forward every incoming message to the Go backend."""
    request_id = str(uuid.uuid4())
    logger = log.bind(request_id=request_id)

    logger.info(
        "incoming_message",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        text=message.text[:100] if message.text else None,
        content_type=message.content_type,
    )

    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(message.chat.id, stop_typing))

    try:
        # Extract file_id from media messages for storage in DB (media recall)
        file_id = None
        media_type = None
        if message.photo:
            file_id = message.photo[-1].file_id  # Highest resolution
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"
        elif message.document:
            file_id = message.document.file_id
            media_type = "document"
        elif message.voice:
            file_id = message.voice.file_id
            media_type = "voice"
        elif message.video_note:
            file_id = message.video_note.file_id
            media_type = "video_note"
        elif message.sticker:
            file_id = message.sticker.file_id
            media_type = "sticker"
        elif message.animation:
            file_id = message.animation.file_id
            media_type = "animation"

        # Build the payload for the backend
        payload = {
            "chat_id": message.chat.id,
            "user_id": message.from_user.id if message.from_user else None,
            "username": message.from_user.username if message.from_user else None,
            "first_name": message.from_user.first_name if message.from_user else None,
            "text": message.text or message.caption or "",
            "message_id": message.message_id,
            "date": message.date.isoformat() if message.date else None,
            "file_id": file_id,
            "media_type": media_type,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_URL}/api/v1/process",
                json=payload,
                headers={"X-Request-ID": request_id},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    reply_text = data.get("reply", "")
                    media_url = data.get("media_url", "")
                    media_type = data.get("media_type", "")

                    # Convert markdown to Telegram HTML
                    reply_html = md_to_telegram_html(reply_text) if reply_text else ""

                    # Handle media responses (image generation results)
                    if media_url and media_type == "photo":
                        try:
                            await message.answer_photo(
                                photo=media_url,
                                caption=reply_html[:1024] if reply_html else None,
                                parse_mode=ParseMode.HTML,
                            )
                            logger.info("photo_sent", media_url=media_url)
                        except Exception as e:
                            logger.error("photo_send_failed", error=str(e))
                            # Fall back to text with URL
                            if reply_html:
                                await message.answer(
                                    f"{reply_html}\n\n🖼 {media_url}",
                                    parse_mode=ParseMode.HTML,
                                )
                    elif media_url and media_type == "document":
                        try:
                            await message.answer_document(
                                document=media_url,
                                caption=reply_html[:1024] if reply_html else None,
                                parse_mode=ParseMode.HTML,
                            )
                            logger.info("document_sent", media_url=media_url)
                        except Exception as e:
                            logger.error("document_send_failed", error=str(e))
                            if reply_html:
                                await message.answer(
                                    f"{reply_html}\n\n📎 {media_url}",
                                    parse_mode=ParseMode.HTML,
                                )
                    elif reply_html:
                        # Split long messages (Telegram limit: 4096 chars)
                        for i in range(0, len(reply_html), 4096):
                            chunk = reply_html[i : i + 4096]
                            await message.answer(chunk, parse_mode=ParseMode.HTML)
                        logger.info("reply_sent", reply_length=len(reply_text))

                elif resp.status == 204:
                    # Rate limited — strict silence (Section 10)
                    logger.info("throttled_silent", chat_id=message.chat.id)
                else:
                    logger.warn("backend_error", status=resp.status)

    except asyncio.TimeoutError:
        logger.error("backend_timeout")
    except Exception as e:
        logger.error("backend_exception", error=str(e))
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ── Health Endpoint (Section 15.2) ──────────────────────────────────────
async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def start_health_server() -> None:
    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    log.info("health_server_started", port=HEALTH_PORT)


# ── Main ────────────────────────────────────────────────────────────────
async def main() -> None:
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is not set")
        return

    log.info("starting_frontend", backend_url=BACKEND_URL)

    # Set up Telegram command hints
    commands = [
        BotCommand(command="start", description="Start chatting"),
        BotCommand(command="help", description="Show what the bot can do"),
        BotCommand(command="stats", description="Admin: backend stats"),
        BotCommand(command="reload_persona", description="Admin: reload persona config"),
    ]
    await bot.set_my_commands(commands)
    log.info("commands_set")

    # Start health check server
    await start_health_server()

    # Start polling
    log.info("starting_polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
