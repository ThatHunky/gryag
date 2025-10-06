from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.types import Message
import asyncio
import logging


LOGGER = logging.getLogger(__name__)

DEFAULT_PHOTO_MIME = "image/jpeg"
DEFAULT_VIDEO_MIME = "video/mp4"
DEFAULT_AUDIO_MIME = "audio/mpeg"

# Max size for inline data (20MB per Gemini docs)
MAX_INLINE_SIZE = 20 * 1024 * 1024

# YouTube URL patterns
YOUTUBE_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)


async def _download(bot: Bot, file_id: str) -> bytes:
    """Download a file from Telegram servers."""
    file = await bot.get_file(file_id)
    file_path = file.file_path
    if not file_path:
        return b""
    url = f"https://api.telegram.org/file/bot{bot.token}/{quote(file_path)}"
    timeout = aiohttp.ClientTimeout(total=60, connect=10)  # Increased for videos
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()
    except asyncio.TimeoutError:
        LOGGER.warning("Timed out downloading Telegram file %s", file_id)
    except aiohttp.ClientError as exc:
        LOGGER.warning("Failed to download Telegram file %s: %s", file_id, exc)
    except Exception:  # pragma: no cover - unexpected runtime error
        LOGGER.exception("Unexpected error while downloading Telegram file %s", file_id)
    return b""


def extract_youtube_urls(text: str | None) -> list[str]:
    """Extract YouTube URLs from text."""
    if not text:
        return []
    matches = YOUTUBE_REGEX.findall(text)
    return [f"https://www.youtube.com/watch?v={video_id}" for video_id in matches]


async def collect_media_parts(bot: Bot, message: Message) -> list[dict[str, Any]]:
    """
    Collect Gemini-friendly media descriptors from a Telegram message.

    Supports:
    - Photos (image/jpeg, image/png, image/webp)
    - Documents (images, audio, video)
    - Voice messages (audio/ogg)
    - Audio files (audio/*)
    - Video files (video/*)
    - Video notes (video/mp4)
    - Animations/GIFs (video/mp4)
    - Stickers (image/webp)

    Returns list of dicts with:
    - bytes: file content
    - mime: MIME type
    - kind: 'image', 'audio', or 'video'
    - size: file size in bytes (optional)
    """
    parts: list[dict[str, Any]] = []

    try:
        # Photos (compressed by Telegram)
        if message.photo:
            # Largest size is last in the list
            photo = message.photo[-1]
            data = await _download(bot, photo.file_id)
            if data:
                parts.append(
                    {
                        "bytes": data,
                        "mime": DEFAULT_PHOTO_MIME,
                        "kind": "image",
                        "size": len(data),
                    }
                )
                LOGGER.debug(
                    "Collected photo: %d bytes, %s", len(data), DEFAULT_PHOTO_MIME
                )

        # Stickers (WebP, TGS animated, or WebM video)
        if message.sticker:
            sticker = message.sticker

            # Check sticker type
            if sticker.is_animated:
                # Animated stickers are TGS (Lottie) format - Gemini doesn't support this
                # Try to use the thumbnail instead
                if sticker.thumbnail:
                    data = await _download(bot, sticker.thumbnail.file_id)
                    if data:
                        mime = "image/jpeg"  # Thumbnails are JPEG
                        parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "image",
                                "size": len(data),
                            }
                        )
                        LOGGER.debug(
                            "Collected animated sticker thumbnail: %d bytes, %s",
                            len(data),
                            mime,
                        )
                else:
                    LOGGER.debug(
                        "Skipping animated sticker (TGS format not supported by Gemini)"
                    )
            elif sticker.is_video:
                # Video stickers are WebM format
                data = await _download(bot, sticker.file_id)
                if data:
                    mime = "video/webm"
                    parts.append(
                        {
                            "bytes": data,
                            "mime": mime,
                            "kind": "video",
                            "size": len(data),
                        }
                    )
                    LOGGER.debug(
                        "Collected video sticker: %d bytes, %s", len(data), mime
                    )
            else:
                # Static stickers are WebP format
                data = await _download(bot, sticker.file_id)
                if data:
                    mime = "image/webp"
                    parts.append(
                        {
                            "bytes": data,
                            "mime": mime,
                            "kind": "image",
                            "size": len(data),
                        }
                    )
                    LOGGER.debug(
                        "Collected static sticker: %d bytes, %s", len(data), mime
                    )

        # Voice messages (OGG/Opus)
        if message.voice:
            voice = message.voice
            mime = voice.mime_type or "audio/ogg"
            data = await _download(bot, voice.file_id)
            if data:
                parts.append(
                    {"bytes": data, "mime": mime, "kind": "audio", "size": len(data)}
                )
                LOGGER.debug(
                    "Collected voice message: %d bytes, %s, duration=%ds",
                    len(data),
                    mime,
                    voice.duration or 0,
                )

        # Audio files
        if message.audio:
            audio = message.audio
            mime = audio.mime_type or DEFAULT_AUDIO_MIME
            data = await _download(bot, audio.file_id)
            if data:
                parts.append(
                    {"bytes": data, "mime": mime, "kind": "audio", "size": len(data)}
                )
                LOGGER.debug(
                    "Collected audio file: %d bytes, %s, duration=%ds",
                    len(data),
                    mime,
                    audio.duration or 0,
                )

        # Video files
        if message.video:
            video = message.video
            mime = video.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, video.file_id)
            if data:
                parts.append(
                    {"bytes": data, "mime": mime, "kind": "video", "size": len(data)}
                )
                LOGGER.debug(
                    "Collected video: %d bytes, %s, duration=%ds, %dx%d",
                    len(data),
                    mime,
                    video.duration or 0,
                    video.width or 0,
                    video.height or 0,
                )

        # Video notes (round videos)
        if message.video_note:
            video_note = message.video_note
            mime = DEFAULT_VIDEO_MIME
            data = await _download(bot, video_note.file_id)
            if data:
                parts.append(
                    {"bytes": data, "mime": mime, "kind": "video", "size": len(data)}
                )
                LOGGER.debug(
                    "Collected video note: %d bytes, %s, duration=%ds",
                    len(data),
                    mime,
                    video_note.duration or 0,
                )

        # Animations (GIFs, sent as MP4)
        if message.animation:
            animation = message.animation
            mime = animation.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, animation.file_id)
            if data:
                parts.append(
                    {
                        "bytes": data,
                        "mime": mime,
                        "kind": "video",  # GIFs are treated as videos by Gemini
                        "size": len(data),
                    }
                )
                LOGGER.debug(
                    "Collected animation/GIF: %d bytes, %s, duration=%ds",
                    len(data),
                    mime,
                    animation.duration or 0,
                )

        # Documents (can be images, audio, video, or other files)
        document = message.document
        if document and document.mime_type:
            mime = document.mime_type

            # Only process media types that Gemini supports
            if mime.startswith(("image/", "audio/", "video/")):
                data = await _download(bot, document.file_id)
                if data:
                    # Determine kind from MIME type
                    if mime.startswith("image/"):
                        kind = "image"
                    elif mime.startswith("audio/"):
                        kind = "audio"
                    elif mime.startswith("video/"):
                        kind = "video"
                    else:
                        kind = "document"

                    parts.append(
                        {"bytes": data, "mime": mime, "kind": kind, "size": len(data)}
                    )
                    LOGGER.debug(
                        "Collected document: %d bytes, %s, kind=%s",
                        len(data),
                        mime,
                        kind,
                    )
            else:
                LOGGER.debug("Skipping unsupported document MIME type: %s", mime)

        # Check total size
        total_size = sum(part.get("size", 0) for part in parts)
        if total_size > MAX_INLINE_SIZE:
            LOGGER.warning(
                "Total media size %d bytes exceeds %d MB limit. "
                "Large files may fail. Consider implementing Files API.",
                total_size,
                MAX_INLINE_SIZE // (1024 * 1024),
            )

    except Exception:  # pragma: no cover - downstream fetch issues
        LOGGER.exception(
            "Failed to collect media parts for message %s", message.message_id
        )

    return parts
