"""Media the bot is asked to look at.

Context always carries a cheap marker like `[фото]`; that costs two tokens and keeps the
conversation from looking torn. Actually *looking* is the expensive path and only happens
when the bot is addressed about a specific file, because it was measured that 17% of this
chat is media and paying for all of it on every call is absurd.

Without this the model bluffs. Asked "як тобі" about a GIF it never saw, it will happily
review it.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

MAX_BYTES = 15 * 1024 * 1024
"""Gemini takes inline data up to about 20MB per request; leave room for the prompt."""

MIME_BY_KIND = {
    "photo": "image/jpeg",
    "animation": "video/mp4",
    "video": "video/mp4",
    "video_note": "video/mp4",
    "voice": "audio/ogg",
    "audio": "audio/mpeg",
    "sticker": "image/webp",
}

LOOKABLE = frozenset(MIME_BY_KIND)


def detect(message) -> tuple[str | None, str | None]:
    """Return (kind, file_id). Photos arrive as a size ladder; take the largest."""
    if getattr(message, "photo", None):
        return "photo", message.photo[-1].file_id
    for kind in ("animation", "voice", "video_note", "video", "audio", "sticker", "document"):
        item = getattr(message, kind, None)
        if item is not None:
            return kind, item.file_id
    return None, None


def mime_for(kind: str, message=None) -> str | None:
    """Animated stickers are .tgs, a gzipped Lottie file, which no model can read."""
    if kind == "sticker" and message is not None:
        sticker = getattr(message, "sticker", None)
        if getattr(sticker, "is_animated", False) or getattr(sticker, "is_video", False):
            return None
    if kind == "document" and message is not None:
        document = getattr(message, "document", None)
        mime = getattr(document, "mime_type", None)
        return mime if mime and mime.split("/")[0] in {"image", "video", "audio"} else None
    return MIME_BY_KIND.get(kind)


async def fetch(bot, file_id: str, mime: str) -> tuple[bytes, str] | None:
    """Download a file for the model. Returns None rather than raising: a file we cannot
    read is a reason to answer without it, never a reason to fall silent."""
    try:
        file = await bot.get_file(file_id)
        if file.file_size and file.file_size > MAX_BYTES:
            log.info("skipping %s: %s bytes is over the inline limit", file_id, file.file_size)
            return None
        buffer = io.BytesIO()
        await bot.download(file, destination=buffer)
        return buffer.getvalue(), mime
    except Exception:
        log.exception("could not download %s", file_id)
        return None


def target(message) -> tuple[str, str, object] | None:
    """The file the bot is being asked about: the one attached to the triggering message,
    otherwise the one in the message it replies to."""
    for candidate in (message, getattr(message, "reply_to_message", None)):
        if candidate is None:
            continue
        kind, file_id = detect(candidate)
        if kind is None or file_id is None:
            continue
        mime = mime_for(kind, candidate)
        if mime is None:
            continue
        return file_id, mime, candidate
    return None
