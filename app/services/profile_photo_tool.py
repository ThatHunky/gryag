"""
Profile photo retrieval and analysis service.

Provides functionality to fetch user profile photos from Telegram
and prepare them for analysis/editing with Gemini.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from app.services.media import _download, _maybe_downscale_image, DEFAULT_PHOTO_MIME

logger = logging.getLogger(__name__)


async def get_user_profile_photo(
    bot: Bot, user_id: int
) -> dict[str, Any] | None:
    """
    Fetch a user's profile photo from Telegram.

    Args:
        bot: Telegram bot instance
        user_id: User ID to fetch photo for

    Returns:
        Dictionary with 'bytes', 'mime', and 'kind' keys, or None if no photo found
    """
    try:
        # Get user's profile photos
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)

        if not photos.photos:
            logger.debug(f"User {user_id} has no profile photos")
            return None

        # Get the first (most recent) photo, and use the largest available size
        photo_sizes = photos.photos[0]
        if not photo_sizes:
            return None

        # Get the largest photo (last in list)
        largest_photo = photo_sizes[-1]

        # Download the photo
        data = await _download(bot, largest_photo.file_id)
        if not data:
            logger.warning(f"Failed to download profile photo for user {user_id}")
            return None

        # Downscale/compress if needed
        data, mime, size = _maybe_downscale_image(data, DEFAULT_PHOTO_MIME)

        logger.debug(
            f"Retrieved profile photo for user {user_id}: {size} bytes, {mime}"
        )

        return {"bytes": data, "mime": mime, "kind": "image", "size": size}

    except Exception as exc:
        logger.warning(f"Failed to get profile photo for user {user_id}: {exc}")
        return None
