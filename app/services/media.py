from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.types import Message
import asyncio
import logging


LOGGER = logging.getLogger(__name__)

# In-memory cache for album messages (media groups)
# Key: (chat_id, thread_id, media_group_id), Value: list of (message, timestamp)
_ALBUM_CACHE: dict[tuple[int, int | None, str], list[tuple[Message, float]]] = (
    defaultdict(list)
)
# Cleanup old entries every 60 seconds (albums arrive within seconds)
_ALBUM_CACHE_CLEANUP_INTERVAL = 60.0
_ALBUM_CACHE_MAX_AGE = 30.0  # Remove entries older than 30 seconds
_last_cleanup_time: float = 0.0  # Track last cleanup time for reliable periodic cleanup

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
    """Download a file from Telegram servers with retries and validation.

    Returns:
        bytes: File content, or empty bytes if download failed
    """
    # Resolve file path first (may raise) and then perform HTTP GET with retries
    file = None
    try:
        # Add timeout to bot.get_file() call (15 seconds for metadata)
        file = await asyncio.wait_for(bot.get_file(file_id), timeout=15.0)
    except asyncio.TimeoutError:
        LOGGER.warning(
            "Timed out fetching file metadata for %s (timeout: 15s)", file_id
        )
        return b""
    except Exception as exc:  # network or API error fetching file metadata
        LOGGER.warning(
            "Failed to fetch file metadata for %s: %s", file_id, exc, exc_info=True
        )
        return b""

    file_path = file.file_path
    if not file_path:
        LOGGER.warning("File path not available for file_id %s", file_id)
        return b""

    # Validate file size before downloading (warn if >20MB, but still try)
    file_size = getattr(file, "file_size", None)
    if file_size and file_size > MAX_INLINE_SIZE:
        LOGGER.warning(
            "File size %d bytes exceeds inline limit %d for file_id %s. "
            "Download will proceed but may fail at Gemini API.",
            file_size,
            MAX_INLINE_SIZE,
            file_id,
        )

    url = f"https://api.telegram.org/file/bot{bot.token}/{quote(file_path)}"

    # Progressive timeout: 60s for download (longer for large files)
    # Connect timeout: 10s (increased from 5s for better reliability)
    timeout = aiohttp.ClientTimeout(total=60, connect=10)

    # Retry loop for transient network errors (DNS, TCP resets, timeouts)
    max_attempts = 3
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.read()

                    # Validate downloaded data size matches expected (if available)
                    if file_size and len(data) != file_size:
                        LOGGER.warning(
                            "Downloaded file size mismatch for %s: expected %d, got %d",
                            file_id,
                            file_size,
                            len(data),
                        )
                        # Still return data if it's close (within 10% tolerance)
                        if abs(len(data) - file_size) > file_size * 0.1:
                            raise ValueError(
                                f"File size mismatch: expected {file_size}, got {len(data)}"
                            )

                    # Validate minimum size (empty files are suspicious)
                    if len(data) == 0:
                        LOGGER.warning("Downloaded empty file for file_id %s", file_id)
                        if attempt < max_attempts:
                            # Apply exponential backoff before retrying empty file
                            backoff_time = 0.5 * (2 ** (attempt - 1))  # 0.5s, 1s, 2s
                            await asyncio.sleep(backoff_time)
                            continue  # Retry on empty file
                        return b""

                    return data

        except asyncio.TimeoutError as exc:
            last_exception = exc
            LOGGER.warning(
                "Timed out downloading Telegram file %s (timeout: %ss) attempt=%d/%d: %s",
                file_id,
                timeout.total,
                attempt,
                max_attempts,
                exc,
            )
        except aiohttp.ClientError as exc:
            last_exception = exc
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
            last_exception = exc
            # Low-level socket errors (Connection reset, DNS failures)
            LOGGER.warning(
                "OS error downloading Telegram file %s on attempt %d/%d: %s",
                file_id,
                attempt,
                max_attempts,
                exc,
                exc_info=(attempt == max_attempts),
            )
        except ValueError as exc:
            # File size validation error
            last_exception = exc
            LOGGER.warning(
                "File validation error for %s on attempt %d/%d: %s",
                file_id,
                attempt,
                max_attempts,
                exc,
            )
            if attempt < max_attempts:
                # Apply exponential backoff before retrying validation error
                backoff_time = 0.5 * (2 ** (attempt - 1))  # 0.5s, 1s, 2s
                await asyncio.sleep(backoff_time)
                continue  # Retry on validation error
            return b""

        # Exponential backoff before next attempt (avoid tight retry loops)
        if attempt < max_attempts:
            backoff_time = 0.5 * (2 ** (attempt - 1))  # 0.5s, 1s, 2s
            await asyncio.sleep(backoff_time)

    LOGGER.error(
        "Failed to download Telegram file %s after %d attempts%s",
        file_id,
        max_attempts,
        f": {last_exception}" if last_exception else "",
    )
    return b""


def _validate_media_data(data: bytes, mime: str) -> bool:
    """
    Validate media data by checking file signatures (magic bytes) and size.

    Args:
        data: File content bytes
        mime: Expected MIME type

    Returns:
        True if data appears valid, False otherwise
    """
    if not data or len(data) < 4:
        return False

    mime_lower = mime.lower()

    # Check file signatures (magic bytes)
    if mime_lower.startswith("image/"):
        # JPEG: FF D8 FF
        if data[:3] == b"\xff\xd8\xff":
            return True
        # PNG: 89 50 4E 47
        if data[:4] == b"\x89PNG":
            return True
        # GIF: 47 49 46 38 (GIF8)
        if data[:4] == b"GIF8":
            return True
        # WebP: RIFF...WEBP
        if data[:4] == b"RIFF" and len(data) > 8 and data[8:12] == b"WEBP":
            return True
        # HEIC/HEIF: ftyp...heic/heif
        if data[4:8] in (b"ftyp", b"heic", b"heif"):
            return True
        # If it's an image MIME but doesn't match known signatures, still allow
        # (might be a valid format we don't recognize)
        return True

    elif mime_lower.startswith("video/"):
        # MP4: ftyp...isom/mp41/mp42
        if data[4:8] == b"ftyp":
            # Check for common MP4 brands
            if b"isom" in data[8:20] or b"mp41" in data[8:20] or b"mp42" in data[8:20]:
                return True
        # WebM: 1A 45 DF A3 (EBML header)
        if data[:4] == b"\x1a\x45\xdf\xa3":
            return True
        # AVI: RIFF...AVI
        if data[:4] == b"RIFF" and len(data) > 8 and data[8:12] == b"AVI ":
            return True
        # MOV/QuickTime: ftyp...qt
        if data[4:8] == b"ftyp" and b"qt" in data[8:20]:
            return True
        # If it's a video MIME but doesn't match known signatures, still allow
        # (might be a valid format we don't recognize)
        return True

    elif mime_lower.startswith("audio/"):
        # MP3: FF FB or FF F3 or ID3 tag
        if data[:2] in (b"\xff\xfb", b"\xff\xf3") or data[:3] == b"ID3":
            return True
        # OGG: OggS
        if data[:4] == b"OggS":
            return True
        # WAV: RIFF...WAVE
        if data[:4] == b"RIFF" and len(data) > 8 and data[8:12] == b"WAVE":
            return True
        # FLAC: fLaC
        if data[:4] == b"fLaC":
            return True
        # If it's an audio MIME but doesn't match known signatures, still allow
        # (might be a valid format we don't recognize)
        return True

    # For unknown MIME types, just check minimum size
    return len(data) > 0


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


def _cleanup_album_cache():
    """Remove old entries from album cache."""
    now = time.time()
    keys_to_remove = []
    for key, messages in _ALBUM_CACHE.items():
        # Keep only recent messages (within max age)
        recent_messages = [
            (msg, ts) for msg, ts in messages if now - ts < _ALBUM_CACHE_MAX_AGE
        ]
        if recent_messages:
            _ALBUM_CACHE[key] = recent_messages
        else:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del _ALBUM_CACHE[key]


async def _fetch_album_messages(
    bot: Bot,
    chat_id: int,
    thread_id: int | None,
    media_group_id: str,
    current_message: Message,
) -> list[Message]:
    """
    Fetch all messages from the same media group (album).

    Uses an in-memory cache to track album messages as they arrive.
    Since album messages arrive in quick succession (within seconds),
    we cache them temporarily and retrieve all messages with the same media_group_id.

    Args:
        bot: Bot instance
        chat_id: Chat ID
        thread_id: Thread ID (for supergroups)
        media_group_id: Media group ID to search for
        current_message: Current message (to include in results)

    Returns:
        List of Message objects from the same media group, including current_message
    """
    cache_key = (chat_id, thread_id, media_group_id)
    now = time.time()

    # Cleanup old cache entries periodically (every 60 seconds)
    global _last_cleanup_time
    if now - _last_cleanup_time >= _ALBUM_CACHE_CLEANUP_INTERVAL:
        _cleanup_album_cache()
        _last_cleanup_time = now

    # Register current message in cache
    _register_album_message(current_message, chat_id, thread_id)

    # Check if we already have multiple messages in the cache (album already partially processed)
    # Only wait if we don't already have other messages in the cache
    # This avoids unnecessary delays when processing subsequent messages from the same album
    cached_messages = _ALBUM_CACHE.get(cache_key, [])
    existing_count = len(
        [
            msg
            for msg, _ in cached_messages
            if msg.message_id != current_message.message_id
        ]
    )

    if existing_count == 0:
        # Wait a short time for other album messages to arrive (up to 2 seconds)
        # Album messages typically arrive within 1-2 seconds
        wait_time = 1.5
        await asyncio.sleep(wait_time)
    else:
        LOGGER.debug(
            "Skipping wait - already have %d other message(s) in album cache (media_group_id=%s)",
            existing_count,
            media_group_id,
        )

    # Cleanup and get fresh cache
    _cleanup_album_cache()
    cached_messages = _ALBUM_CACHE.get(cache_key, [])

    # Collect all unique messages from cache, including current message
    album_messages: list[Message] = []
    seen_ids: set[int] = set()

    # Always include current message first
    album_messages.append(current_message)
    seen_ids.add(current_message.message_id)

    # Add other cached messages
    for msg, _ in cached_messages:
        if msg.message_id not in seen_ids:
            album_messages.append(msg)
            seen_ids.add(msg.message_id)

    if len(album_messages) > 1:
        LOGGER.info(
            "Found %d message(s) in album (media_group_id=%s, chat_id=%s, thread_id=%s)",
            len(album_messages),
            media_group_id,
            chat_id,
            thread_id,
        )
    else:
        LOGGER.debug(
            "Only current message in album (media_group_id=%s, chat_id=%s, thread_id=%s). "
            "Other album messages may not have arrived yet or were processed separately.",
            media_group_id,
            chat_id,
            thread_id,
        )

    return album_messages


def _register_album_message(message: Message, chat_id: int, thread_id: int | None):
    """
    Register a message in the album cache if it has a media_group_id.

    This should be called when processing any message to build up the cache.
    """
    if not message.media_group_id:
        return

    cache_key = (chat_id, thread_id, message.media_group_id)
    now = time.time()

    # Add message to cache
    cached_messages = _ALBUM_CACHE.get(cache_key, [])
    # Check if message already in cache
    if not any(msg.message_id == message.message_id for msg, _ in cached_messages):
        cached_messages.append((message, now))
        _ALBUM_CACHE[cache_key] = cached_messages
        LOGGER.debug(
            "Registered album message %s in cache (media_group_id=%s, total=%d)",
            message.message_id,
            message.media_group_id,
            len(cached_messages),
        )


async def collect_media_parts(
    bot: Bot,
    message: Message,
    chat_id: int | None = None,
    thread_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Collect Gemini-friendly media descriptors from a Telegram message.

    If the message is part of an album (media group), collects media from all messages
    in the album.

    Supports:
    - Photos (image/jpeg, image/png, image/webp)
    - Documents (images, audio, video)
    - Voice messages (audio/ogg)
    - Audio files (audio/*)
    - Video files (video/*)
    - Video notes (video/mp4)
    - Animations/GIFs (video/mp4)
    - Stickers (image/webp)
    - Albums (media groups with multiple photos/videos)

    Args:
        bot: Bot instance
        message: Telegram message to collect media from
        chat_id: Chat ID (required for album detection)
        thread_id: Thread ID (optional, for supergroups)

    Returns list of dicts with:
    - bytes: file content
    - mime: MIME type
    - kind: 'image', 'audio', or 'video'
    - size: file size in bytes (optional)
    """
    # Register message in album cache if it has media_group_id
    if message.media_group_id and chat_id is not None:
        _register_album_message(message, chat_id, thread_id)

    # Check if this is part of an album
    album_messages: list[Message] = []
    if message.media_group_id and chat_id is not None:
        try:
            album_messages = await _fetch_album_messages(
                bot, chat_id, thread_id, message.media_group_id, message
            )
            if len(album_messages) > 1:
                LOGGER.info(
                    "Processing album with %d message(s) (media_group_id=%s)",
                    len(album_messages),
                    message.media_group_id,
                )
        except Exception as e:
            LOGGER.warning(
                "Failed to fetch album messages, processing single message only: %s",
                e,
                exc_info=True,
            )
            album_messages = [message]
    else:
        album_messages = [message]

    parts: list[dict[str, Any]] = []
    download_failures: list[tuple[str, str]] = (
        []
    )  # Track (media_type, file_id) failures
    seen_file_ids: set[str] = (
        set()
    )  # Deduplicate media by file_id across album messages

    async def _collect_from_single_message(msg: Message) -> list[dict[str, Any]]:
        """Collect media from a single message (helper for album processing)."""
        msg_parts: list[dict[str, Any]] = []
        msg_failures: list[tuple[str, str]] = []

        # Photos (compressed by Telegram)
        if msg.photo:
            # Largest size is last in the list
            photo = msg.photo[-1]
            data = await _download(bot, photo.file_id)
            if data:
                # Validate downloaded data
                if not _validate_media_data(data, DEFAULT_PHOTO_MIME):
                    msg_failures.append(("photo", photo.file_id))
                    LOGGER.warning(
                        "Downloaded photo data failed validation (file_id=%s) from message %s",
                        photo.file_id,
                        msg.message_id,
                    )
                else:
                    # Downscale/compress to reduce payload
                    data, mime, size = _maybe_downscale_image(data, DEFAULT_PHOTO_MIME)
                    # Check for duplicate file_id
                    if photo.file_id not in seen_file_ids:
                        msg_parts.append(
                            {"bytes": data, "mime": mime, "kind": "image", "size": size}
                        )
                        seen_file_ids.add(photo.file_id)
                        LOGGER.debug(
                            "Collected photo: %d bytes, %s from message %s",
                            size,
                            mime,
                            msg.message_id,
                        )
            else:
                msg_failures.append(("photo", photo.file_id))
                LOGGER.warning(
                    "Failed to download photo (file_id=%s) from message %s",
                    photo.file_id,
                    msg.message_id,
                )

        # Stickers (WebP, TGS animated, or WebM video)
        if msg.sticker:
            sticker = msg.sticker

            # Check sticker type
            if sticker.is_animated:
                # Animated stickers are TGS (Lottie) format - Gemini doesn't support this
                # Try to use the thumbnail instead
                if sticker.thumbnail:
                    data = await _download(bot, sticker.thumbnail.file_id)
                    if data:
                        mime = "image/jpeg"  # Thumbnails are JPEG
                        if not _validate_media_data(data, mime):
                            msg_failures.append(
                                (
                                    "animated_sticker_thumbnail",
                                    sticker.thumbnail.file_id,
                                )
                            )
                            LOGGER.warning(
                                "Downloaded animated sticker thumbnail data failed validation (file_id=%s) from message %s",
                                sticker.thumbnail.file_id,
                                msg.message_id,
                            )
                        else:
                            data, mime, size = _maybe_downscale_image(data, mime)
                            if sticker.thumbnail.file_id not in seen_file_ids:
                                msg_parts.append(
                                    {
                                        "bytes": data,
                                        "mime": mime,
                                        "kind": "image",
                                        "size": size,
                                    }
                                )
                                seen_file_ids.add(sticker.thumbnail.file_id)
                            LOGGER.debug(
                                "Collected animated sticker thumbnail: %d bytes, %s",
                                size,
                                mime,
                            )
                    else:
                        msg_failures.append(
                            ("animated_sticker_thumbnail", sticker.thumbnail.file_id)
                        )
                        LOGGER.warning(
                            "Failed to download animated sticker thumbnail (file_id=%s) from message %s",
                            sticker.thumbnail.file_id,
                            msg.message_id,
                        )
                else:
                    LOGGER.debug(
                        "Skipping animated sticker (TGS format not supported by Gemini, no thumbnail available)"
                    )
            elif sticker.is_video:
                # Video stickers are WebM format
                data = await _download(bot, sticker.file_id)
                if data:
                    mime = "video/webm"
                    if not _validate_media_data(data, mime):
                        msg_failures.append(("video_sticker", sticker.file_id))
                        LOGGER.warning(
                            "Downloaded video sticker data failed validation (file_id=%s) from message %s",
                            sticker.file_id,
                            msg.message_id,
                        )
                    else:
                        if sticker.file_id not in seen_file_ids:
                            msg_parts.append(
                                {
                                    "bytes": data,
                                    "mime": mime,
                                    "kind": "video",
                                    "size": len(data),
                                }
                            )
                            seen_file_ids.add(sticker.file_id)
                        LOGGER.debug(
                            "Collected video sticker: %d bytes, %s", len(data), mime
                        )
                else:
                    msg_failures.append(("video_sticker", sticker.file_id))
                    LOGGER.warning(
                        "Failed to download video sticker (file_id=%s) from message %s",
                        sticker.file_id,
                        msg.message_id,
                    )
            else:
                # Static stickers are WebP format
                data = await _download(bot, sticker.file_id)
                if data:
                    mime = "image/webp"
                    if not _validate_media_data(data, mime):
                        msg_failures.append(("static_sticker", sticker.file_id))
                        LOGGER.warning(
                            "Downloaded static sticker data failed validation (file_id=%s) from message %s",
                            sticker.file_id,
                            msg.message_id,
                        )
                    else:
                        # For WebP, try converting to JPEG if it helps reduce size
                        data, mime, size = _maybe_downscale_image(data, mime)
                        if sticker.file_id not in seen_file_ids:
                            msg_parts.append(
                                {
                                    "bytes": data,
                                    "mime": mime,
                                    "kind": "image",
                                    "size": size,
                                }
                            )
                            seen_file_ids.add(sticker.file_id)
                        LOGGER.debug(
                            "Collected static sticker: %d bytes, %s", size, mime
                        )
                else:
                    msg_failures.append(("static_sticker", sticker.file_id))
                    LOGGER.warning(
                        "Failed to download static sticker (file_id=%s) from message %s",
                        sticker.file_id,
                        msg.message_id,
                    )

        # Voice messages (OGG/Opus)
        if msg.voice:
            voice = msg.voice
            mime = voice.mime_type or "audio/ogg"
            data = await _download(bot, voice.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    msg_failures.append(("voice", voice.file_id))
                    LOGGER.warning(
                        "Downloaded voice message data failed validation (file_id=%s) from message %s",
                        voice.file_id,
                        msg.message_id,
                    )
                else:
                    if voice.file_id not in seen_file_ids:
                        msg_parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "audio",
                                "size": len(data),
                            }
                        )
                        seen_file_ids.add(voice.file_id)
                    LOGGER.debug(
                        "Collected voice message: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        voice.duration or 0,
                    )
            else:
                msg_failures.append(("voice", voice.file_id))
                LOGGER.warning(
                    "Failed to download voice message (file_id=%s) from message %s",
                    voice.file_id,
                    msg.message_id,
                )

        # Audio files
        if msg.audio:
            audio = msg.audio
            mime = audio.mime_type or DEFAULT_AUDIO_MIME
            data = await _download(bot, audio.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    msg_failures.append(("audio", audio.file_id))
                    LOGGER.warning(
                        "Downloaded audio file data failed validation (file_id=%s) from message %s",
                        audio.file_id,
                        msg.message_id,
                    )
                else:
                    if audio.file_id not in seen_file_ids:
                        msg_parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "audio",
                                "size": len(data),
                            }
                        )
                        seen_file_ids.add(audio.file_id)
                    LOGGER.debug(
                        "Collected audio file: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        audio.duration or 0,
                    )
            else:
                msg_failures.append(("audio", audio.file_id))
                LOGGER.warning(
                    "Failed to download audio file (file_id=%s) from message %s",
                    audio.file_id,
                    msg.message_id,
                )

        # Video files
        if msg.video:
            video = msg.video
            mime = video.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, video.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    msg_failures.append(("video", video.file_id))
                    LOGGER.warning(
                        "Downloaded video data failed validation (file_id=%s) from message %s",
                        video.file_id,
                        msg.message_id,
                    )
                else:
                    if video.file_id not in seen_file_ids:
                        msg_parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "video",
                                "size": len(data),
                            }
                        )
                        seen_file_ids.add(video.file_id)
                    LOGGER.debug(
                        "Collected video: %d bytes, %s, duration=%ds, %dx%d",
                        len(data),
                        mime,
                        video.duration or 0,
                        video.width or 0,
                        video.height or 0,
                    )
            else:
                msg_failures.append(("video", video.file_id))
                LOGGER.warning(
                    "Failed to download video (file_id=%s) from message %s",
                    video.file_id,
                    msg.message_id,
                )

        # Video notes (round videos)
        if msg.video_note:
            video_note = msg.video_note
            mime = DEFAULT_VIDEO_MIME
            data = await _download(bot, video_note.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    msg_failures.append(("video_note", video_note.file_id))
                    LOGGER.warning(
                        "Downloaded video note data failed validation (file_id=%s) from message %s",
                        video_note.file_id,
                        msg.message_id,
                    )
                else:
                    if video_note.file_id not in seen_file_ids:
                        msg_parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "video",
                                "size": len(data),
                            }
                        )
                        seen_file_ids.add(video_note.file_id)
                    LOGGER.debug(
                        "Collected video note: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        video_note.duration or 0,
                    )
            else:
                msg_failures.append(("video_note", video_note.file_id))
                LOGGER.warning(
                    "Failed to download video note (file_id=%s) from message %s",
                    video_note.file_id,
                    msg.message_id,
                )

        # Animations (GIFs, sent as MP4)
        if msg.animation:
            animation = msg.animation
            mime = animation.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, animation.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    msg_failures.append(("animation", animation.file_id))
                    LOGGER.warning(
                        "Downloaded animation/GIF data failed validation (file_id=%s) from message %s",
                        animation.file_id,
                        msg.message_id,
                    )
                else:
                    if animation.file_id not in seen_file_ids:
                        msg_parts.append(
                            {
                                "bytes": data,
                                "mime": mime,
                                "kind": "video",  # GIFs are treated as videos by Gemini
                                "size": len(data),
                            }
                        )
                        seen_file_ids.add(animation.file_id)
                    LOGGER.debug(
                        "Collected animation/GIF: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        animation.duration or 0,
                    )
            else:
                msg_failures.append(("animation", animation.file_id))
                LOGGER.warning(
                    "Failed to download animation/GIF (file_id=%s) from message %s",
                    animation.file_id,
                    msg.message_id,
                )

        # Documents (can be images, audio, video, or other files)
        document = msg.document
        if document and document.mime_type:
            mime = document.mime_type

            # Only process media types that Gemini supports
            if mime.startswith(("image/", "audio/", "video/")):
                data = await _download(bot, document.file_id)
                if data:
                    if not _validate_media_data(data, mime):
                        msg_failures.append(("document", document.file_id))
                        LOGGER.warning(
                            "Downloaded document data failed validation (file_id=%s, mime=%s) from message %s",
                            document.file_id,
                            mime,
                            msg.message_id,
                        )
                    else:
                        # Determine kind from MIME type
                        if mime.startswith("image/"):
                            kind = "image"
                            data, mime, size = _maybe_downscale_image(data, mime)
                            if document.file_id not in seen_file_ids:
                                msg_parts.append(
                                    {
                                        "bytes": data,
                                        "mime": mime,
                                        "kind": kind,
                                        "size": size,
                                    }
                                )
                                seen_file_ids.add(document.file_id)
                        elif mime.startswith("audio/"):
                            kind = "audio"
                            if document.file_id not in seen_file_ids:
                                msg_parts.append(
                                    {
                                        "bytes": data,
                                        "mime": mime,
                                        "kind": kind,
                                        "size": len(data),
                                    }
                                )
                                seen_file_ids.add(document.file_id)
                        elif mime.startswith("video/"):
                            kind = "video"
                            if document.file_id not in seen_file_ids:
                                msg_parts.append(
                                    {
                                        "bytes": data,
                                        "mime": mime,
                                        "kind": kind,
                                        "size": len(data),
                                    }
                                )
                                seen_file_ids.add(document.file_id)
                        else:
                            kind = "document"
                            if document.file_id not in seen_file_ids:
                                msg_parts.append(
                                    {
                                        "bytes": data,
                                        "mime": mime,
                                        "kind": kind,
                                        "size": len(data),
                                    }
                                )
                                seen_file_ids.add(document.file_id)
                        LOGGER.debug(
                            "Collected document: %d bytes, %s, kind=%s",
                            (size if kind == "image" else len(data)),
                            mime,
                            kind,
                        )
                else:
                    msg_failures.append(("document", document.file_id))
                    LOGGER.warning(
                        "Failed to download document (file_id=%s, mime=%s) from message %s",
                        document.file_id,
                        mime,
                        msg.message_id,
                    )
            else:
                LOGGER.debug(f"Skipping unsupported document MIME type: {mime}")

        return msg_parts, msg_failures

    try:
        # Process all messages in the album
        for album_msg in album_messages:
            msg_parts, msg_failures = await _collect_from_single_message(album_msg)
            parts.extend(msg_parts)
            download_failures.extend(msg_failures)

        # Check total size
        total_size = sum(part.get("size", 0) for part in parts)
        if total_size > MAX_INLINE_SIZE:
            LOGGER.warning(
                "Total media size %d bytes exceeds %d MB limit. "
                "Large files may fail. Consider implementing Files API.",
                total_size,
                MAX_INLINE_SIZE // (1024 * 1024),
            )

        # Log summary of download failures
        if download_failures:
            failure_summary = ", ".join(
                f"{media_type}({file_id[:8]}...)"
                for media_type, file_id in download_failures
            )
            LOGGER.warning(
                "Media collection completed with %d failure(s) for album (message %s): %s",
                len(download_failures),
                message.message_id,
                failure_summary,
            )

        if len(album_messages) > 1:
            LOGGER.info(
                "Collected %d media item(s) from album with %d message(s)",
                len(parts),
                len(album_messages),
            )
            # Import telemetry here to avoid circular imports
            from app.core import telemetry

            telemetry.increment_counter("media.album_collected", len(album_messages))
            telemetry.increment_counter("media.album_items_collected", len(parts))

    except Exception as e:  # pragma: no cover - downstream fetch issues
        LOGGER.error(
            f"Failed to collect media parts for message {message.message_id}: {e}",
            exc_info=True,
        )
        # Return partial results if available (some parts may have been collected before the error)

    return parts
