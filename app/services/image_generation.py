"""
Image generation service for GRYAG bot.

Provides image generation using Gemini 2.5 Flash Image model.
Includes daily quota management and context image support.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import sqlite3
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

try:
    from app.services.tool_logging import log_tool_execution, ToolLogger
except ImportError:
    log_tool_execution = lambda name: lambda f: f
    ToolLogger = None

tool_logger = ToolLogger("image_generation") if ToolLogger else None


class ImageGenerationError(Exception):
    """Raised when image generation fails."""


class QuotaExceededError(ImageGenerationError):
    """Raised when user exceeds daily image generation quota."""


class ImageGenerationService:
    """Service for generating images using Gemini."""

    def __init__(
        self,
        api_key: str,
        db_path: Path | str,
        daily_limit: int = 3,
        admin_user_ids: list[int] | None = None,
    ):
        """
        Initialize image generation service.

        Args:
            api_key: Google Gemini API key
            db_path: Path to SQLite database
            daily_limit: Maximum images per user per day (default: 3)
            admin_user_ids: List of admin user IDs who bypass limits
        """
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash-image"
        self.db_path = Path(db_path)
        self.daily_limit = daily_limit
        self.admin_user_ids = set(admin_user_ids or [])
        self.logger = logging.getLogger(f"{__name__}.ImageGenerationService")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database connection and ensure schema exists."""
        # Schema is applied via db/schema.sql on startup
        # This just verifies the table exists
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='image_quotas'
                """
            )
            if not cursor.fetchone():
                self.logger.warning("image_quotas table not found - creating it")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS image_quotas (
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        generation_date TEXT NOT NULL,
                        images_generated INTEGER DEFAULT 0,
                        last_generation_ts INTEGER,
                        PRIMARY KEY (user_id, chat_id, generation_date)
                    )
                    """
                )
                conn.commit()
        finally:
            conn.close()

    def _get_today_date(self) -> str:
        """Get today's date in YYYY-MM-DD format (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is an admin (bypasses quotas)."""
        is_admin = user_id in self.admin_user_ids
        self.logger.info(
            f"Admin check: user_id={user_id}, admin_ids={self.admin_user_ids}, is_admin={is_admin}"
        )
        return is_admin

    async def check_quota(self, user_id: int, chat_id: int) -> tuple[bool, int, int]:
        """
        Check if user has remaining quota for today.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            Tuple of (has_quota, used_count, limit)
        """
        if self._is_admin(user_id):
            return True, 0, -1  # -1 indicates unlimited

        today = self._get_today_date()

        def _check() -> tuple[int, int]:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT images_generated FROM image_quotas
                    WHERE user_id = ? AND chat_id = ? AND generation_date = ?
                    """,
                    (user_id, chat_id, today),
                )
                row = cursor.fetchone()
                used = row[0] if row else 0
                return used, self.daily_limit
            finally:
                conn.close()

        used, limit = await asyncio.to_thread(_check)
        has_quota = used < limit
        return has_quota, used, limit

    async def increment_quota(self, user_id: int, chat_id: int) -> None:
        """
        Increment user's image generation count for today.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID
        """
        if self._is_admin(user_id):
            return  # Admins don't track quota

        today = self._get_today_date()
        now = int(time.time())

        def _increment() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO image_quotas 
                        (user_id, chat_id, generation_date, images_generated, last_generation_ts)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(user_id, chat_id, generation_date) 
                    DO UPDATE SET 
                        images_generated = images_generated + 1,
                        last_generation_ts = ?
                    """,
                    (user_id, chat_id, today, now, now),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_increment)

    async def generate_image(
        self,
        prompt: str,
        context_images: list[bytes] | None = None,
        aspect_ratio: str = "1:1",
        user_id: int | None = None,
        chat_id: int | None = None,
    ) -> bytes:
        """
        Generate an image from a text prompt.

        Args:
            prompt: Text description of the image to generate
            context_images: Optional list of context images (as bytes) for editing/composition
            aspect_ratio: Image aspect ratio (default: "1:1")
                Valid: "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
            user_id: Telegram user ID (for quota checking)
            chat_id: Telegram chat ID (for quota checking)

        Returns:
            Generated image as bytes (PNG format)

        Raises:
            QuotaExceededError: If user exceeds daily limit
            ImageGenerationError: If generation fails
        """
        start_time = time.time()

        # Check quota if user/chat provided
        if user_id is not None and chat_id is not None:
            has_quota, used, limit = await self.check_quota(user_id, chat_id)
            if not has_quota:
                self.logger.warning(
                    f"Quota exceeded for user {user_id} in chat {chat_id}: {used}/{limit}"
                )
                raise QuotaExceededError(
                    f"Перевищено денний ліміт ({used}/{limit} зображень). "
                    "Спробуй завтра!"
                )

        try:
            # Build content list (prompt + optional context images)
            contents: list[str | Image.Image] = [prompt]

            if context_images:
                for img_bytes in context_images[:3]:  # Max 3 context images
                    try:
                        img = Image.open(BytesIO(img_bytes))
                        contents.append(img)
                    except Exception as e:
                        self.logger.warning(f"Failed to load context image: {e}")

            # Configure generation
            config = types.GenerateContentConfig(
                response_modalities=["Image"],  # Only return images, no text
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            )

            self.logger.info(
                f"Generating image: prompt_len={len(prompt)}, "
                f"context_images={len(context_images) if context_images else 0}, "
                f"aspect_ratio={aspect_ratio}"
            )

            # Generate image
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            # Extract image from response safely
            image_bytes = None
            try:
                candidates = getattr(response, "candidates", None) or []
                if candidates:
                    content = getattr(candidates[0], "content", None)
                    parts = getattr(content, "parts", None) or []
                    for part in parts:
                        if getattr(part, "inline_data", None) is not None:
                            image_bytes = part.inline_data.data
                            break
            except Exception as parse_exc:  # pragma: no cover - defensive
                self.logger.warning(f"Failed to parse image from response: {parse_exc}")

            if not image_bytes:
                self.logger.error("No image returned in response")
                raise ImageGenerationError("Gemini не повернув зображення")

            # Increment quota if user/chat provided
            if user_id is not None and chat_id is not None:
                await self.increment_quota(user_id, chat_id)

            duration = time.time() - start_time
            if tool_logger:
                tool_logger.performance("generate_image", duration, status="success")

            self.logger.info(f"Image generated successfully in {duration:.2f}s")
            return image_bytes

        except QuotaExceededError:
            raise  # Re-raise quota errors
        except Exception as e:
            duration = time.time() - start_time
            if tool_logger:
                tool_logger.performance("generate_image", duration, status="error")

            self.logger.error(f"Image generation failed: {e}", exc_info=True)

            # User-friendly error messages
            error_msg = "Не вдалося згенерувати зображення"
            if "safety" in str(e).lower():
                error_msg = "Запит відхилено через політику безпеки"
            elif "quota" in str(e).lower() or "limit" in str(e).lower():
                error_msg = "Перевищено ліміт API. Спробуй пізніше"
            elif "timeout" in str(e).lower():
                error_msg = "Тайм-аут генерації. Спробуй ще раз"

            raise ImageGenerationError(error_msg) from e

    async def get_usage_stats(self, user_id: int, chat_id: int) -> dict[str, Any]:
        """
        Get image generation usage statistics for a user.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            Dictionary with usage stats
        """
        if self._is_admin(user_id):
            return {
                "is_admin": True,
                "used_today": 0,
                "daily_limit": -1,
                "remaining": -1,
                "unlimited": True,
            }

        has_quota, used, limit = await self.check_quota(user_id, chat_id)
        remaining = max(0, limit - used)

        return {
            "is_admin": False,
            "used_today": used,
            "daily_limit": limit,
            "remaining": remaining,
            "unlimited": False,
        }


# Tool definition for Gemini function calling
GENERATE_IMAGE_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "generate_image",
            "description": (
                "Генерує ФОТОРЕАЛІСТИЧНЕ зображення (фото) з текстового опису, якщо користувач не вказав інший стиль (малюнок, ілюстрація, мультик). "
                "Викликай ЦЕЙ інструмент КОЖНОГО РАЗУ, коли користувач просить намалювати/згенерувати картинку або фото. "
                "Не відмовляй текстом і не посилайся на ліміти — сервер сам перевіряє ліміти і поверне відповідь. "
                "ВАЖЛИВО: Завжди пиши prompt АНГЛІЙСЬКОЮ мовою для кращого результату."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Detailed image description IN ENGLISH for generation. "
                            "BY DEFAULT generate PHOTOREALISTIC images (like photos) unless user asks for different style. "
                            "For photos use phrases like 'photorealistic', 'photo', 'realistic photography', 'cinematic lighting'. "
                            "More detail = better result. "
                            "Describe style, lighting, details, composition. "
                            "ALWAYS write this prompt in ENGLISH, even if user's request was in Ukrainian - translate their request to English."
                        ),
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "description": "Співвідношення сторін (за замовчуванням 1:1)",
                        "enum": [
                            "1:1",
                            "2:3",
                            "3:2",
                            "3:4",
                            "4:3",
                            "4:5",
                            "5:4",
                            "9:16",
                            "16:9",
                            "21:9",
                        ],
                        "default": "1:1",
                    },
                },
                "required": ["prompt"],
            },
        }
    ]
}

# Tool definition for image editing (uses a replied image as context)
EDIT_IMAGE_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "edit_image",
            "description": (
                "Редагує існуюче зображення за інструкцією. "
                "ЗАВЖДИ викликай цей інструмент, якщо користувач описав зміну до фото (навіть якщо не відповів на фото безпосередньо). "
                "Інструмент сам знайде останнє фото в історії розмови, якщо користувач не відповів на конкретне. "
                "Автоматично зберігає оригінальні пропорції зображення. "
                "Ліміти перевіряє сервер; якщо перевищено, інструмент поверне відповідь. "
                "ВАЖЛИВО: Завжди пиши prompt АНГЛІЙСЬКОЮ мовою для кращого результату."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Edit instruction IN ENGLISH (what to add/change/remove, style, details). "
                            "BY DEFAULT preserve PHOTOREALISTIC style of original unless user asks for different style. "
                            "ALWAYS write this prompt in ENGLISH, even if user's request was in Ukrainian - translate their request to English."
                        ),
                    },
                },
                "required": ["prompt"],
            },
        }
    ]
}
