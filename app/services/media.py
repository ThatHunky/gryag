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
    download_failures: list[tuple[str, str]] = []  # Track (media_type, file_id) failures

    try:
        # Photos (compressed by Telegram)
        if message.photo:
            # Largest size is last in the list
            photo = message.photo[-1]
            data = await _download(bot, photo.file_id)
            if data:
                # Validate downloaded data
                if not _validate_media_data(data, DEFAULT_PHOTO_MIME):
                    download_failures.append(("photo", photo.file_id))
                    LOGGER.warning(
                        "Downloaded photo data failed validation (file_id=%s) from message %s",
                        photo.file_id,
                        message.message_id,
                    )
                else:
                    # Downscale/compress to reduce payload
                    data, mime, size = _maybe_downscale_image(data, DEFAULT_PHOTO_MIME)
                    parts.append(
                        {"bytes": data, "mime": mime, "kind": "image", "size": size}
                    )
                    LOGGER.debug("Collected photo: %d bytes, %s", size, mime)
            else:
                download_failures.append(("photo", photo.file_id))
                LOGGER.warning(
                    "Failed to download photo (file_id=%s) from message %s",
                    photo.file_id,
                    message.message_id,
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
                        if not _validate_media_data(data, mime):
                            download_failures.append(("animated_sticker_thumbnail", sticker.thumbnail.file_id))
                            LOGGER.warning(
                                "Downloaded animated sticker thumbnail data failed validation (file_id=%s) from message %s",
                                sticker.thumbnail.file_id,
                                message.message_id,
                            )
                        else:
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
                        download_failures.append(("animated_sticker_thumbnail", sticker.thumbnail.file_id))
                        LOGGER.warning(
                            "Failed to download animated sticker thumbnail (file_id=%s) from message %s",
                            sticker.thumbnail.file_id,
                            message.message_id,
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
                        download_failures.append(("video_sticker", sticker.file_id))
                        LOGGER.warning(
                            "Downloaded video sticker data failed validation (file_id=%s) from message %s",
                            sticker.file_id,
                            message.message_id,
                        )
                    else:
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
                    download_failures.append(("video_sticker", sticker.file_id))
                    LOGGER.warning(
                        "Failed to download video sticker (file_id=%s) from message %s",
                        sticker.file_id,
                        message.message_id,
                    )
            else:
                # Static stickers are WebP format
                data = await _download(bot, sticker.file_id)
                if data:
                    mime = "image/webp"
                    if not _validate_media_data(data, mime):
                        download_failures.append(("static_sticker", sticker.file_id))
                        LOGGER.warning(
                            "Downloaded static sticker data failed validation (file_id=%s) from message %s",
                            sticker.file_id,
                            message.message_id,
                        )
                    else:
                        # For WebP, try converting to JPEG if it helps reduce size
                        data, mime, size = _maybe_downscale_image(data, mime)
                        parts.append(
                            {"bytes": data, "mime": mime, "kind": "image", "size": size}
                        )
                        LOGGER.debug("Collected static sticker: %d bytes, %s", size, mime)
                else:
                    download_failures.append(("static_sticker", sticker.file_id))
                    LOGGER.warning(
                        "Failed to download static sticker (file_id=%s) from message %s",
                        sticker.file_id,
                        message.message_id,
                    )

        # Voice messages (OGG/Opus)
        if message.voice:
            voice = message.voice
            mime = voice.mime_type or "audio/ogg"
            data = await _download(bot, voice.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    download_failures.append(("voice", voice.file_id))
                    LOGGER.warning(
                        "Downloaded voice message data failed validation (file_id=%s) from message %s",
                        voice.file_id,
                        message.message_id,
                    )
                else:
                    parts.append(
                        {"bytes": data, "mime": mime, "kind": "audio", "size": len(data)}
                    )
                    LOGGER.debug(
                        "Collected voice message: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        voice.duration or 0,
                    )
            else:
                download_failures.append(("voice", voice.file_id))
                LOGGER.warning(
                    "Failed to download voice message (file_id=%s) from message %s",
                    voice.file_id,
                    message.message_id,
                )

        # Audio files
        if message.audio:
            audio = message.audio
            mime = audio.mime_type or DEFAULT_AUDIO_MIME
            data = await _download(bot, audio.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    download_failures.append(("audio", audio.file_id))
                    LOGGER.warning(
                        "Downloaded audio file data failed validation (file_id=%s) from message %s",
                        audio.file_id,
                        message.message_id,
                    )
                else:
                    parts.append(
                        {"bytes": data, "mime": mime, "kind": "audio", "size": len(data)}
                    )
                    LOGGER.debug(
                        "Collected audio file: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        audio.duration or 0,
                    )
            else:
                download_failures.append(("audio", audio.file_id))
                LOGGER.warning(
                    "Failed to download audio file (file_id=%s) from message %s",
                    audio.file_id,
                    message.message_id,
                )

        # Video files
        if message.video:
            video = message.video
            mime = video.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, video.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    download_failures.append(("video", video.file_id))
                    LOGGER.warning(
                        "Downloaded video data failed validation (file_id=%s) from message %s",
                        video.file_id,
                        message.message_id,
                    )
                else:
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
            else:
                download_failures.append(("video", video.file_id))
                LOGGER.warning(
                    "Failed to download video (file_id=%s) from message %s",
                    video.file_id,
                    message.message_id,
                )

        # Video notes (round videos)
        if message.video_note:
            video_note = message.video_note
            mime = DEFAULT_VIDEO_MIME
            data = await _download(bot, video_note.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    download_failures.append(("video_note", video_note.file_id))
                    LOGGER.warning(
                        "Downloaded video note data failed validation (file_id=%s) from message %s",
                        video_note.file_id,
                        message.message_id,
                    )
                else:
                    parts.append(
                        {"bytes": data, "mime": mime, "kind": "video", "size": len(data)}
                    )
                    LOGGER.debug(
                        "Collected video note: %d bytes, %s, duration=%ds",
                        len(data),
                        mime,
                        video_note.duration or 0,
                    )
            else:
                download_failures.append(("video_note", video_note.file_id))
                LOGGER.warning(
                    "Failed to download video note (file_id=%s) from message %s",
                    video_note.file_id,
                    message.message_id,
                )

        # Animations (GIFs, sent as MP4)
        if message.animation:
            animation = message.animation
            mime = animation.mime_type or DEFAULT_VIDEO_MIME
            data = await _download(bot, animation.file_id)
            if data:
                if not _validate_media_data(data, mime):
                    download_failures.append(("animation", animation.file_id))
                    LOGGER.warning(
                        "Downloaded animation/GIF data failed validation (file_id=%s) from message %s",
                        animation.file_id,
                        message.message_id,
                    )
                else:
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
            else:
                download_failures.append(("animation", animation.file_id))
                LOGGER.warning(
                    "Failed to download animation/GIF (file_id=%s) from message %s",
                    animation.file_id,
                    message.message_id,
                )

        # Documents (can be images, audio, video, or other files)
        document = message.document
        if document and document.mime_type:
            mime = document.mime_type

            # Only process media types that Gemini supports
            if mime.startswith(("image/", "audio/", "video/")):
                data = await _download(bot, document.file_id)
                if data:
                    if not _validate_media_data(data, mime):
                        download_failures.append(("document", document.file_id))
                        LOGGER.warning(
                            "Downloaded document data failed validation (file_id=%s, mime=%s) from message %s",
                            document.file_id,
                            mime,
                            message.message_id,
                        )
                    else:
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
                    download_failures.append(("document", document.file_id))
                    LOGGER.warning(
                        "Failed to download document (file_id=%s, mime=%s) from message %s",
                        document.file_id,
                        mime,
                        message.message_id,
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

        # Log summary of download failures
        if download_failures:
            failure_summary = ", ".join(f"{media_type}({file_id[:8]}...)" for media_type, file_id in download_failures)
            LOGGER.warning(
                "Media collection completed with %d failure(s) for message %s: %s",
                len(download_failures),
                message.message_id,
                failure_summary,
            )

    except Exception as e:  # pragma: no cover - downstream fetch issues
        LOGGER.error(
            f"Failed to collect media parts for message {message.message_id}: {e}",
            exc_info=True,
        )
        # Return partial results if available (some parts may have been collected before the error)

    return parts
