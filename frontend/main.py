"""
Gryag V2 — Python Telegram Frontend

A lightweight Telegram router that forwards messages to the Go backend.
It performs no thinking — it is purely a dumb pipe.
"""

import base64
import asyncio
import logging
import os
import uuid

import aiohttp
import structlog
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatAction, ContentType, ParseMode
from aiogram.types import BotCommand, BufferedInputFile
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
ENABLE_PROACTIVE_MESSAGING = os.getenv("ENABLE_PROACTIVE_MESSAGING", "false").lower() in ("true", "1", "yes")
PROACTIVE_POLL_INTERVAL_SEC = int(os.getenv("PROACTIVE_POLL_INTERVAL_SEC", "90"))


# ── Bot & Dispatcher ────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Max size (bytes) to send media to backend; larger files are skipped to avoid timeouts (plan: size limits).
MEDIA_MAX_BYTES = int(os.getenv("MEDIA_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB default


async def download_media_as_base64(file_id: str, mime_type: str | None = None) -> tuple[str, str] | None:
    """Download file by file_id and return (base64_string, mime_type). Returns None if too large or download fails."""
    try:
        tg_file = await bot.get_file(file_id)
        if tg_file.file_size and tg_file.file_size > MEDIA_MAX_BYTES:
            return None
        data = await bot.download_file(tg_file.file_path)
        if data is None:
            return None
        raw = data.getvalue() if hasattr(data, "getvalue") else (data.read() if hasattr(data, "read") else b"")
        if not isinstance(raw, bytes):
            raw = b""
        if len(raw) > MEDIA_MAX_BYTES:
            return None
        mime = mime_type or "application/octet-stream"
        return base64.b64encode(raw).decode("ascii"), mime
    except Exception:
        return None


def _mime_for_media_type(media_type: str, document_mime: str | None) -> str:
    if document_mime:
        return document_mime
    return {
        "photo": "image/jpeg",
        "video": "video/mp4",
        "document": "image/png",
        "voice": "audio/ogg",
        "video_note": "video/mp4",
        "sticker": "image/webp",
        "animation": "video/mp4",
    }.get(media_type, "application/octet-stream")


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

        # Download media and send as base64 so the backend/LLM can see it (plan: all media types)
        media_base64 = None
        mime_type = None
        if file_id:
            doc_mime = getattr(message.document, "mime_type", None) if message.document else None
            mime_type = _mime_for_media_type(media_type or "", doc_mime)
            result = await download_media_as_base64(file_id, mime_type)
            if result:
                media_base64, mime_type = result
            else:
                logger.warning("media_download_failed", file_id=file_id, media_type=media_type)

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
        if getattr(message, "reply_to_message", None):
            payload["reply_to_message_id"] = message.reply_to_message.message_id
            payload["reply_to_text"] = (
                message.reply_to_message.text or message.reply_to_message.caption or ""
            )
        if media_base64:
            payload["media_base64"] = media_base64
            payload["mime_type"] = mime_type
            logger.info("sending_media_to_backend", media_type=media_type, mime_type=mime_type, size_bytes=len(media_base64) * 3 // 4)

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
                    media_base64 = data.get("media_base64", "")

                    # Convert markdown to Telegram HTML
                    reply_html = md_to_telegram_html(reply_text) if reply_text else ""

                    # Handle media responses (image generation results)
                    if (media_url or media_base64) and media_type == "photo":
                        try:
                            photo_data = media_url
                            if media_base64:
                                photo_bytes = base64.b64decode(media_base64)
                                photo_data = BufferedInputFile(photo_bytes, filename="generated.png")

                            await message.answer_photo(
                                photo=photo_data,
                                caption=reply_html[:1024] if reply_html else None,
                                parse_mode=ParseMode.HTML,
                            )
                            logger.info("photo_sent", has_base64=bool(media_base64), media_url=media_url)
                        except Exception as e:
                            logger.error("photo_send_failed", error=str(e))
                            # Fall back to text with URL
                            if reply_html:
                                await message.answer(
                                    f"{reply_html}\n\n🖼 {media_url if media_url else '<Image generated but upload failed>'}",
                                    parse_mode=ParseMode.HTML,
                                )
                    elif (media_url or media_base64) and media_type == "document":
                        try:
                            document_data = media_url
                            if media_base64:
                                doc_bytes = base64.b64decode(media_base64)
                                document_data = BufferedInputFile(doc_bytes, filename="generated.png")
                            await message.answer_document(
                                document=document_data,
                                caption=reply_html[:1024] if reply_html else None,
                                parse_mode=ParseMode.HTML,
                            )
                            logger.info("document_sent", has_base64=bool(media_base64), media_url=media_url)
                        except Exception as e:
                            logger.error("document_send_failed", error=str(e))
                            if reply_html:
                                await message.answer(
                                    f"{reply_html}\n\n📎 {media_url if media_url else '<File generated but upload failed>'}",
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


# ── Proactive messaging poller ───────────────────────────────────────────
async def proactive_poller_loop() -> None:
    """Poll backend for queued proactive messages and send them to Telegram."""
    logger = log.bind(component="proactive_poller")
    while True:
        try:
            await asyncio.sleep(PROACTIVE_POLL_INTERVAL_SEC)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BACKEND_URL}/api/v1/proactive",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 204:
                        continue
                    if resp.status != 200:
                        logger.warning("proactive_poll_bad_status", status=resp.status)
                        continue
                    data = await resp.json()
                    chat_id = data.get("chat_id")
                    reply = data.get("reply", "")
                    if not reply or chat_id is None:
                        continue
                    html = md_to_telegram_html(reply)
                    await bot.send_message(chat_id=chat_id, text=html, parse_mode=ParseMode.HTML)
                    logger.info("proactive_sent", chat_id=chat_id, reply_length=len(reply))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("proactive_poller_error", error=str(e))


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

    # Start proactive poller when enabled
    if ENABLE_PROACTIVE_MESSAGING:
        asyncio.create_task(proactive_poller_loop())
        log.info("proactive_poller_started", interval_sec=PROACTIVE_POLL_INTERVAL_SEC)

    # Start polling
    log.info("starting_polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
