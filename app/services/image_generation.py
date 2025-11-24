"""
Image generation service for GRYAG bot.

Provides image generation using Gemini 2.5 Flash Image model or Pollinations.ai.
Includes daily quota management and context image support.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import aiohttp
import asyncpg
from google import genai
from google.genai import types
from PIL import Image

from app.infrastructure.db_utils import get_db_connection
from app.infrastructure.query_converter import convert_query_to_postgres

try:
    from app.services.tool_logging import ToolLogger, log_tool_execution
except ImportError:

    def log_tool_execution(name):
        return lambda f: f

    ToolLogger = None

tool_logger = ToolLogger("image_generation") if ToolLogger else None


class ImageGenerationError(Exception):
    """Raised when image generation fails."""


class QuotaExceededError(ImageGenerationError):
    """Raised when user exceeds daily image generation quota."""


class PollinationsImageGenerator:
    """Client for generating images using Pollinations.ai API."""

    BASE_URL = "https://pollinations.ai/p"

    def __init__(self):
        """Initialize Pollinations.ai image generator."""
        self.logger = logging.getLogger(f"{__name__}.PollinationsImageGenerator")
        self.timeout = aiohttp.ClientTimeout(total=90.0)

    async def generate(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        context_images: list[bytes] | None = None,
    ) -> bytes:
        """
        Generate an image using Pollinations.ai.

        Args:
            prompt: Text description of the image to generate
            aspect_ratio: Image aspect ratio (ignored by Pollinations.ai, kept for API compatibility)
            context_images: Optional context images (ignored by Pollinations.ai, kept for API compatibility)

        Returns:
            Generated image as bytes (JPEG/PNG format)

        Raises:
            ImageGenerationError: If generation fails
        """
        if context_images:
            self.logger.warning(
                "Pollinations.ai does not support context images, ignoring them"
            )
        if aspect_ratio != "1:1":
            self.logger.warning(
                f"Pollinations.ai does not support aspect ratio {aspect_ratio}, using default"
            )

        # URL-encode the prompt
        encoded_prompt = quote(prompt)
        url = f"{self.BASE_URL}/{encoded_prompt}"

        self.logger.info(f"Generating image with Pollinations.ai: prompt_len={len(prompt)}")

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(
                            f"Pollinations.ai API error: status={response.status}, "
                            f"response={error_text[:200]}"
                        )
                        raise ImageGenerationError(
                            f"Pollinations.ai повернув помилку (статус {response.status})"
                        )

                    image_bytes = await response.read()
                    if not image_bytes:
                        raise ImageGenerationError("Pollinations.ai не повернув зображення")

                    # Verify it's actually an image
                    try:
                        Image.open(BytesIO(image_bytes))
                    except Exception as e:
                        self.logger.error(f"Invalid image data from Pollinations.ai: {e}")
                        raise ImageGenerationError(
                            "Pollinations.ai повернув некоректні дані зображення"
                        ) from e

                    self.logger.info(
                        f"Image generated successfully with Pollinations.ai: {len(image_bytes)} bytes"
                    )
                    return image_bytes

        except asyncio.TimeoutError as e:
            self.logger.error("Pollinations.ai request timed out after 90 seconds")
            raise ImageGenerationError(
                "Генерація зображення зайняла забагато часу. Спробуй ще раз або спрости запит."
            ) from e
        except aiohttp.ClientError as e:
            self.logger.error(f"Pollinations.ai request failed: {e}", exc_info=True)
            raise ImageGenerationError("Не вдалося згенерувати зображення через помилку мережі") from e
        except Exception as e:
            self.logger.error(f"Unexpected error in Pollinations.ai generation: {e}", exc_info=True)
            raise ImageGenerationError("Не вдалося згенерувати зображення") from e


class ImageGenerationService:
    """Service for generating images using Gemini or Pollinations.ai."""

    def __init__(
        self,
        provider: str = "gemini",
        api_key: str | None = None,
        database_url: str = "",
        daily_limit: int = 3,
        admin_user_ids: list[int] | None = None,
    ):
        """
        Initialize image generation service.

        Args:
            provider: Image generation provider ("gemini" or "pollinations")
            api_key: Google Gemini API key (required for "gemini" provider)
            database_url: PostgreSQL connection string
            daily_limit: Maximum images per user per day (default: 3)
            admin_user_ids: List of admin user IDs who bypass limits
        """
        self.provider = provider.lower()
        self.database_url = str(database_url)
        self.daily_limit = daily_limit
        self.admin_user_ids = set(admin_user_ids or [])
        self.logger = logging.getLogger(f"{__name__}.ImageGenerationService")

        if self.provider == "gemini":
            if not api_key:
                raise ValueError("api_key is required for Gemini provider")
            self.client = genai.Client(api_key=api_key)
            self.model = "gemini-2.5-flash-image"
            self.pollinations_generator = None
        elif self.provider == "pollinations":
            self.pollinations_generator = PollinationsImageGenerator()
            self.client = None
            self.model = None
        else:
            raise ValueError(f"Unknown provider: {provider}. Must be 'gemini' or 'pollinations'")

        self.logger.info(f"Image generation service initialized with provider: {self.provider}")

    async def _init_db(self) -> None:
        """Initialize database connection and ensure schema exists."""
        # Schema is applied via db/schema_postgresql.sql on startup
        # This just verifies the table exists
        async with get_db_connection(self.database_url) as conn:
            try:
                await conn.execute("SELECT 1 FROM image_quotas LIMIT 1")
                self.logger.info("image_quotas table exists")
            except asyncpg.PostgresError:
                self.logger.warning(
                    "image_quotas table missing, it will be created on next schema migration"
                )

    def _get_today_date(self) -> str:
        """Get today's date in YYYY-MM-DD format (UTC)."""
        return datetime.now(UTC).strftime("%Y-%m-%d")

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

        query, params = convert_query_to_postgres(
            """
            SELECT images_generated FROM image_quotas
            WHERE user_id = $1 AND chat_id = $2 AND generation_date = $3
            """,
            (user_id, chat_id, today),
        )
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(query, *params)
            used = row["images_generated"] if row else 0
            # Always return true and -1 for limit to disable quotas
            return True, used, -1

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

        # Use PostgreSQL's INSERT ... ON CONFLICT for atomic upsert
        query, params = convert_query_to_postgres(
            """
            INSERT INTO image_quotas (user_id, chat_id, generation_date, images_generated, last_generation_ts)
            VALUES ($1, $2, $3, 1, $4)
            ON CONFLICT (user_id, chat_id, generation_date)
            DO UPDATE SET
                images_generated = image_quotas.images_generated + 1,
                last_generation_ts = $4
            """,
            (user_id, chat_id, today, now),
        )
        async with get_db_connection(self.database_url) as conn:
            await conn.execute(query, *params)

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
            # Route to appropriate provider
            if self.provider == "gemini":
                image_bytes = await self._generate_with_gemini(
                    prompt, context_images, aspect_ratio
                )
            elif self.provider == "pollinations":
                image_bytes = await self._generate_with_pollinations(
                    prompt, context_images, aspect_ratio
                )
            else:
                raise ImageGenerationError(f"Unknown provider: {self.provider}")

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

    async def _generate_with_gemini(
        self,
        prompt: str,
        context_images: list[bytes] | None,
        aspect_ratio: str,
    ) -> bytes:
        """Generate image using Gemini API."""
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
            f"Generating image with Gemini: prompt_len={len(prompt)}, "
            f"context_images={len(context_images) if context_images else 0}, "
            f"aspect_ratio={aspect_ratio}"
        )

        # Generate image with timeout (90 seconds max)
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                ),
                timeout=90.0,
            )
        except TimeoutError as e:
            self.logger.error("Image generation timed out after 90 seconds")
            raise ImageGenerationError(
                "Генерація зображення зайняла забагато часу. Спробуй ще раз або спрости запит."
            ) from e

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

        return image_bytes

    async def _generate_with_pollinations(
        self,
        prompt: str,
        context_images: list[bytes] | None,
        aspect_ratio: str,
    ) -> bytes:
        """Generate image using Pollinations.ai API."""
        if not self.pollinations_generator:
            raise ImageGenerationError("Pollinations generator not initialized")

        self.logger.info(
            f"Generating image with Pollinations.ai: prompt_len={len(prompt)}"
        )

        return await self.pollinations_generator.generate(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            context_images=context_images,
        )

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

        if limit == -1:
            remaining = -1
            unlimited = True
        else:
            remaining = max(0, limit - used)
            unlimited = False

        return {
            "is_admin": False,
            "used_today": used,
            "daily_limit": limit,
            "remaining": remaining,
            "unlimited": unlimited,
        }

    async def reset_user_quota(self, user_id: int, chat_id: int) -> bool:
        """
        Reset image generation quota for a specific user in a specific chat.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            True if quota was reset successfully (even if no records were deleted)
        """

        today = self._get_today_date()

        query, params = convert_query_to_postgres(
            """
            DELETE FROM image_quotas
            WHERE user_id = $1 AND chat_id = $2 AND generation_date = $3
            """,
            (user_id, chat_id, today),
        )
        try:
            async with get_db_connection(self.database_url) as conn:
                result = await conn.execute(query, *params)
                deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                self.logger.info(
                    f"Reset image quota for user {user_id} in chat {chat_id} (deleted {deleted} record(s))"
                )
                # Return True regardless of whether records were deleted
                # (no records = quota already reset)
                return True
        except Exception as e:
            self.logger.error(f"Failed to reset image quota for user {user_id}: {e}")
            return False

    async def reset_chat_quotas(self, chat_id: int) -> int:
        """
        Reset image generation quotas for all users in a specific chat for today.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Number of quota records deleted (0 if none existed)
        """

        today = self._get_today_date()

        query, params = convert_query_to_postgres(
            """
            DELETE FROM image_quotas
            WHERE chat_id = $1 AND generation_date = $2
            """,
            (chat_id, today),
        )
        try:
            async with get_db_connection(self.database_url) as conn:
                result = await conn.execute(query, *params)
                deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                self.logger.info(
                    f"Reset image quotas for {deleted} user(s) in chat {chat_id}"
                )
                return deleted
        except Exception as e:
            self.logger.error(f"Failed to reset image quotas for chat {chat_id}: {e}")
            return 0


# Tool definition for Gemini function calling
GENERATE_IMAGE_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "generate_image",
            "description": (
                "Генерує НОВЕ ФОТОРЕАЛІСТИЧНЕ зображення (фото) з текстового опису. "
                "Викликай ЛИШЕ коли користувач ЯВНО просить СТВОРИТИ/ЗГЕНЕРУВАТИ/НАМАЛЮВАТИ нове зображення. "
                "Якщо користувач хоче ЗНАЙТИ/ПОКАЗАТИ існуюче зображення (мальовник, фото, картинку) — використовуй search_web. "
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
