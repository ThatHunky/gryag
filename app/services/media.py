from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.types import Message

DEFAULT_PHOTO_MIME = "image/jpeg"


async def _download(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    file_path = file.file_path
    if not file_path:
        return b""
    url = f"https://api.telegram.org/file/bot{bot.token}/{quote(file_path)}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def collect_media_parts(bot: Bot, message: Message) -> list[dict[str, Any]]:
    """Collect Gemini-friendly media descriptors from a Telegram message."""

    parts: list[dict[str, Any]] = []

    if message.photo:
        # Largest size is last in the list.
        photo = message.photo[-1]
        data = await _download(bot, photo.file_id)
        if data:
            parts.append({"bytes": data, "mime": DEFAULT_PHOTO_MIME, "kind": "image"})

    document = message.document
    if document and document.mime_type:
        mime = document.mime_type
        if mime.startswith("image/") or mime.startswith("audio/"):
            data = await _download(bot, document.file_id)
            if data:
                kind = "image" if mime.startswith("image/") else "audio"
                parts.append({"bytes": data, "mime": mime, "kind": kind})

    voice = message.voice
    if voice:
        mime = voice.mime_type or "audio/ogg"
        data = await _download(bot, voice.file_id)
        if data:
            parts.append({"bytes": data, "mime": mime, "kind": "audio"})

    return parts
