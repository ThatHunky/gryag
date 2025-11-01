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
    # Resolve file path first (may raise) and then perform HTTP GET with retries
    try:
        file = await bot.get_file(file_id)
    except Exception as exc:  # network or API error fetching file metadata
        LOGGER.warning(
            "Failed to fetch file metadata for %s: %s", file_id, exc, exc_info=True
        )
        return b""

    file_path = file.file_path
    if not file_path:
        return b""

    url = f"https://api.telegram.org/file/bot{bot.token}/{quote(file_path)}"
    timeout = aiohttp.ClientTimeout(total=60, connect=10)  # keep existing timeout

    # Retry loop for transient network errors (DNS, TCP resets, timeouts)
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
                    return data

        except asyncio.TimeoutError:
            LOGGER.warning(
                "Timed out downloading Telegram file %s (timeout: %ss) attempt=%d/%d",
                file_id,
                timeout.total,
                attempt,
                max_attempts,
            )
        except aiohttp.ClientError as exc:
            # Includes ClientConnectorError, ClientOSError, etc.
            LOGGER.warning(
                "HTTP error downloading Telegram file %s on attempt %d/%d: %s",
                file_id,
                attempt,
                max_attempts,
                exc,
                exc_info=(attempt == max_attempts),
            )
        except OSError as exc:
            # Low-level socket errors (Connection reset, DNS failures)
            LOGGER.warning(
                "OS error downloading Telegram file %s on attempt %d/%d: %s",
                file_id,
                attempt,
                max_attempts,
                exc,
                exc_info=(attempt == max_attempts),
            )

        # Backoff before next attempt (avoid tight retry loops)
        if attempt < max_attempts:
            await asyncio.sleep(0.1 * (2 ** (attempt - 1)))

    LOGGER.error(
        "Failed to download Telegram file %s after %d attempts", file_id, max_attempts
    )
    return b""


def _maybe_downscale_image(data: bytes, mime: str) -> tuple[bytes, str, int]:
    """Downscale and recompress large images to reduce inline payload.

    - Converts to JPEG (quality 80)
    - Max dimension: 1600px (preserve aspect ratio)
    - Only applies when original size > 1MB or any dimension > 1600

    Returns: (bytes, mime, size)
    """
    try:
        from PIL import Image
        import io

        # Quick size check to avoid work on small files
        if len(data) <= 1 * 1024 * 1024 and mime.lower() != "image/webp":
            return data, mime, len(data)

        with Image.open(io.BytesIO(data)) as im:
            # If it's not an image PIL can decode, bail out
            im.load()
            width, height = im.size
            max_dim = 1600
            needs_resize = max(width, height) > max_dim

            # Convert to RGB for JPEG
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")

            if needs_resize:
                im.thumbnail((max_dim, max_dim))

            out = io.BytesIO()
            # Prefer JPEG for broad compatibility and good compression
            im.save(out, format="JPEG", quality=80, optimize=True)
            compressed = out.getvalue()

            # Only use compressed version if it meaningfully reduces size
            if (
                len(compressed) < len(data) * 0.95
                or needs_resize
                or mime.lower() == "image/webp"
            ):
                return compressed, "image/jpeg", len(compressed)
            return data, mime, len(data)
    except Exception:
        # On any failure, just return original bytes
        LOGGER.debug("Image downscale skipped due to processing error", exc_info=True)
        return data, mime, len(data)


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
                # Downscale/compress to reduce payload
                data, mime, size = _maybe_downscale_image(data, DEFAULT_PHOTO_MIME)
                parts.append(
                    {"bytes": data, "mime": mime, "kind": "image", "size": size}
                )
                LOGGER.debug("Collected photo: %d bytes, %s", size, mime)

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
                        data, mime, size = _maybe_downscale_image(data, mime)
                        parts.append(
                            {"bytes": data, "mime": mime, "kind": "image", "size": size}
                        )
                        LOGGER.debug(
                            "Collected animated sticker thumbnail: %d bytes, %s",
                            size,
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
                    # For WebP, try converting to JPEG if it helps reduce size
                    data, mime, size = _maybe_downscale_image(data, mime)
                    parts.append(
                        {"bytes": data, "mime": mime, "kind": "image", "size": size}
                    )
                    LOGGER.debug("Collected static sticker: %d bytes, %s", size, mime)

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
                        data, mime, size = _maybe_downscale_image(data, mime)
                        parts.append(
                            {"bytes": data, "mime": mime, "kind": kind, "size": size}
                        )
                    elif mime.startswith("audio/"):
                        kind = "audio"
                        parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": kind,
                                "size": len(data),
                            }
                        )
                    elif mime.startswith("video/"):
                        kind = "video"
                        parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": kind,
                                "size": len(data),
                            }
                        )
                    else:
                        kind = "document"
                        parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": kind,
                                "size": len(data),
                            }
                        )
                    LOGGER.debug(
                        "Collected document: %d bytes, %s, kind=%s",
                        (size if kind == "image" else len(data)),
                        mime,
                        kind,
                    )
            else:
                LOGGER.debug(f"Skipping unsupported document MIME type: {mime}")

        # Check total size
        total_size = sum(part.get("size", 0) for part in parts)
        if total_size > MAX_INLINE_SIZE:
            LOGGER.warning(
                "Total media size %d bytes exceeds %d MB limit. "
                "Large files may fail. Consider implementing Files API.",
                total_size,
                MAX_INLINE_SIZE // (1024 * 1024),
            )

    except Exception as e:  # pragma: no cover - downstream fetch issues
        LOGGER.error(
            f"Failed to collect media parts for message {message.message_id}: {e}",
            exc_info=True,
        )
        # Return partial results if available (some parts may have been collected before the error)

    return parts
