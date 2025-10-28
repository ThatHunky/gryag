"""
Tool definitions and callbacks for chat handler.

This module contains all tool definitions (function calling) and their
callback implementations used by the Gemini model during chat interactions.

Tools include:
- search_messages: Semantic search in chat history
- search_web: Web search (if enabled)
- calculator: Mathematical calculations
- weather: Weather information
- currency: Currency conversion
- polls: Poll creation and voting
- Memory tools: remember_memory, recall_memories, forget_memory, forget_all_memories, set_pronouns
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from app.services.calculator import calculator_tool, CALCULATOR_TOOL_DEFINITION
from app.services.weather import weather_tool, WEATHER_TOOL_DEFINITION
from app.services.currency import currency_tool, CURRENCY_TOOL_DEFINITION
from app.services.polls import polls_tool, POLLS_TOOL_DEFINITION
from app.services.search_tool import search_web_tool, SEARCH_WEB_TOOL_DEFINITION
from app.services.image_generation import (
    GENERATE_IMAGE_TOOL_DEFINITION,
    EDIT_IMAGE_TOOL_DEFINITION,
    QuotaExceededError,
    ImageGenerationError,
)
from app.services.tools import (
    REMEMBER_MEMORY_DEFINITION,
    RECALL_MEMORIES_DEFINITION,
    FORGET_MEMORY_DEFINITION,
    FORGET_ALL_MEMORIES_DEFINITION,
    SET_PRONOUNS_DEFINITION,
    remember_memory_tool,
    recall_memories_tool,
    forget_memory_tool,
    forget_all_memories_tool,
    set_pronouns_tool,
)
from app.services.context_store import ContextStore, format_metadata
from app.services.gemini import GeminiClient
from app.services.user_profile import UserProfileStore
from app.repositories.memory_repository import MemoryRepository
from app.config import Settings
from app.services.media import collect_media_parts
from app.services.profile_photo_tool import get_user_profile_photo
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


def create_search_messages_tool(
    store: ContextStore,
    gemini_client: GeminiClient,
    chat_id: int,
    thread_id: int | None,
) -> Callable[[dict[str, Any]], Awaitable[str]]:
    """
    Create a search_messages tool callback for the current chat context.

    Args:
        store: Context store for message retrieval
        gemini_client: Gemini client for embeddings
        chat_id: Current chat ID
        thread_id: Current thread ID (if any)

    Returns:
        Async callback function for search_messages tool
    """

    async def search_messages_tool(params: dict[str, Any]) -> str:
        """Search chat history using semantic search."""
        query = (params or {}).get("query", "")
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"results": []})

        limit = params.get("limit", 5)
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 5
        limit_int = max(1, min(limit_int, 10))

        thread_only = params.get("thread_only", True)
        target_thread = thread_id if thread_only else None

        embedding = await gemini_client.embed_text(query)
        matches = await store.semantic_search(
            chat_id=chat_id,
            thread_id=target_thread,
            query_embedding=embedding,
            limit=limit_int,
        )

        payload = []
        for item in matches:
            meta_dict = item.get("metadata", {})
            payload.append(
                {
                    "score": round(float(item.get("score", 0.0)), 4),
                    "metadata": meta_dict,
                    "metadata_text": format_metadata(meta_dict),
                    "text": (item.get("text") or "")[:400],
                    "role": item.get("role"),
                    "message_id": item.get("message_id"),
                }
            )
        return json.dumps({"results": payload})

    return search_messages_tool


def get_search_messages_definition() -> dict[str, Any]:
    """Get the tool definition for search_messages."""
    return {
        "function_declarations": [
            {
                "name": "search_messages",
                "description": (
                    "Шукати релевантні повідомлення в історії чату за семантичною подібністю."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Запит або фраза для пошуку",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Скільки результатів повернути (1-10)",
                        },
                        "thread_only": {
                            "type": "boolean",
                            "description": "Чи обмежуватися поточним тредом",
                        },
                    },
                    "required": ["query"],
                },
            }
        ]
    }


def build_tool_definitions(settings: Settings) -> list[dict[str, Any]]:
    """
    Build the complete list of tool definitions based on settings.

    Args:
        settings: Application settings

    Returns:
        List of tool definitions in Gemini function calling format
    """
    tool_definitions: list[dict[str, Any]] = []

    # Always include search_messages
    tool_definitions.append(get_search_messages_definition())

    # Web search (if enabled)
    if settings.enable_search_grounding:
        tool_definitions.append(SEARCH_WEB_TOOL_DEFINITION)

    # Calculator
    tool_definitions.append(CALCULATOR_TOOL_DEFINITION)

    # Weather
    tool_definitions.append(WEATHER_TOOL_DEFINITION)

    # Currency
    tool_definitions.append(CURRENCY_TOOL_DEFINITION)

    # Polls
    tool_definitions.append(POLLS_TOOL_DEFINITION)

    # Image generation tools (if enabled)
    if settings.enable_image_generation:
        tool_definitions.append(GENERATE_IMAGE_TOOL_DEFINITION)
        tool_definitions.append(EDIT_IMAGE_TOOL_DEFINITION)

    # Memory tools
    if settings.enable_tool_based_memory:
        tool_definitions.append(REMEMBER_MEMORY_DEFINITION)
        tool_definitions.append(RECALL_MEMORIES_DEFINITION)
        tool_definitions.append(FORGET_MEMORY_DEFINITION)
        tool_definitions.append(FORGET_ALL_MEMORIES_DEFINITION)
        tool_definitions.append(SET_PRONOUNS_DEFINITION)

    # Media analysis helpers (always available; use reply/current message media)
    tool_definitions.append(
        {
            "function_declarations": [
                {
                    "name": "describe_media",
                    "description": (
                        "Отримати короткий опис зображення(з) у поточному або попередньому (reply) повідомленні."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "use_reply": {
                                "type": "boolean",
                                "description": "Якщо є reply — брати медіа звідти (за замовчуванням true)",
                            },
                            "max_items": {
                                "type": "integer",
                                "description": "Скільки зображень аналізувати (1-3)",
                            },
                        },
                    },
                }
            ]
        }
    )

    # Profile photo analysis tool
    tool_definitions.append(
        {
            "function_declarations": [
                {
                    "name": "analyze_profile_photo",
                    "description": (
                        "Analyze, comment on, or edit a user's profile photo. You can provide witty observations, "
                        "ask clarifying questions, or generate edited versions based on the context of the conversation."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_id": {
                                "type": "integer",
                                "description": "Telegram user ID of the user whose profile photo to analyze",
                            },
                        },
                        "required": ["user_id"],
                    },
                }
            ]
        }
    )

    tool_definitions.append(
        {
            "function_declarations": [
                {
                    "name": "transcribe_audio",
                    "description": (
                        "Розшифрувати аудіо/voice з поточного або попереднього (reply) повідомлення українською."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "use_reply": {
                                "type": "boolean",
                                "description": "Якщо є reply — брати медіа звідти (за замовчуванням true)",
                            },
                        },
                    },
                }
            ]
        }
    )

    return tool_definitions


def build_tool_callbacks(
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    profile_store: UserProfileStore,
    memory_repo: MemoryRepository,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
    tools_used_tracker: list[str] | None = None,
    *,
    # Optional runtime dependencies for certain tools
    user_id: int | None = None,
    bot: Any | None = None,
    message: Any | None = None,
    image_gen_service: Any | None = None,
    feature_limiter: Any | None = None,
) -> dict[str, Callable[[dict[str, Any]], Awaitable[str]]]:
    """
    Build the complete dictionary of tool callbacks.

    Args:
        settings: Application settings
        store: Context store
        gemini_client: Gemini client
        profile_store: User profile store
        chat_id: Current chat ID
        thread_id: Current thread ID (if any)
        message_id: Current message ID
        tools_used_tracker: Optional list to track which tools are called
        feature_limiter: Feature rate limiter for throttling (optional)

    Returns:
        Dictionary mapping tool names to callback functions
    """

    def make_tracked_callback(
        tool_name: str, original_callback: Callable[[dict[str, Any]], Awaitable[str]]
    ) -> Callable[[dict[str, Any]], Awaitable[str]]:
        """Wrapper to track tool usage and inject throttling metadata."""

        async def wrapper(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append(tool_name)

            # Inject throttling metadata for feature-level throttling
            # These are internal params starting with underscore
            # Make a copy to avoid mutating the original params that may be sent to Gemini
            enriched_params = dict(params)
            if user_id and feature_limiter:
                enriched_params["_user_id"] = user_id
                enriched_params["_feature_limiter"] = feature_limiter

            return await original_callback(enriched_params)

        return wrapper

    callbacks: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {}

    # Search messages tool
    search_messages = create_search_messages_tool(
        store, gemini_client, chat_id, thread_id
    )
    callbacks["search_messages"] = make_tracked_callback(
        "search_messages", search_messages
    )

    # Calculator
    callbacks["calculator"] = make_tracked_callback("calculator", calculator_tool)

    # Weather
    callbacks["weather"] = make_tracked_callback("weather", weather_tool)

    # Currency
    callbacks["currency"] = make_tracked_callback("currency", currency_tool)

    # Polls
    callbacks["polls"] = make_tracked_callback("polls", polls_tool)

    # Web search (if enabled)
    if settings.enable_search_grounding:
        # Use separate API key if provided, otherwise fall back to main key
        search_api_key = settings.web_search_api_key or settings.gemini_api_key
        callbacks["search_web"] = make_tracked_callback(
            "search_web",
            lambda params: search_web_tool(
                params,
                gemini_client,
                api_key=search_api_key,
            ),
        )

    # Memory tools (if enabled)
    if settings.enable_tool_based_memory:
        # Helper to filter out internal underscore-prefixed params
        def _filter_internal_params(params: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in params.items() if not k.startswith("_")}

        callbacks["remember_memory"] = make_tracked_callback(
            "remember_memory",
            lambda params: remember_memory_tool(
                **_filter_internal_params(params),
                chat_id=chat_id,
                memory_repo=memory_repo,
            ),
        )
        callbacks["recall_memories"] = make_tracked_callback(
            "recall_memories",
            lambda params: recall_memories_tool(
                **_filter_internal_params(params),
                chat_id=chat_id,
                memory_repo=memory_repo,
            ),
        )
        callbacks["forget_memory"] = make_tracked_callback(
            "forget_memory",
            lambda params: forget_memory_tool(
                **_filter_internal_params(params),
                chat_id=chat_id,
                memory_repo=memory_repo,
            ),
        )
        callbacks["forget_all_memories"] = make_tracked_callback(
            "forget_all_memories",
            lambda params: forget_all_memories_tool(
                **_filter_internal_params(params),
                chat_id=chat_id,
                memory_repo=memory_repo,
            ),
        )
        callbacks["set_pronouns"] = make_tracked_callback(
            "set_pronouns",
            lambda params: set_pronouns_tool(
                **_filter_internal_params(params),
                chat_id=chat_id,
                profile_store=profile_store,
            ),
        )

    # Image tools (if enabled and dependencies provided)
    if (
        settings.enable_image_generation
        and image_gen_service is not None
        and bot is not None
        and message is not None
        and user_id is not None
    ):

        async def generate_image_tool(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append("generate_image")
            prompt = params.get("prompt", "")
            aspect_ratio = params.get("aspect_ratio", "1:1")
            if not prompt:
                return json.dumps(
                    {"success": False, "error": "Потрібен опис зображення"}
                )
            try:
                image_bytes = await image_gen_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    user_id=user_id,
                    chat_id=chat_id,
                )
                photo = BufferedInputFile(image_bytes, filename="generated.png")
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=None,
                        message_thread_id=thread_id,
                        reply_to_message_id=message_id,
                    )
                except TelegramBadRequest as e:
                    if "thread not found" in str(e).lower():
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=None,
                            reply_to_message_id=message_id,
                        )
                    else:
                        raise
                stats = await image_gen_service.get_usage_stats(user_id, chat_id)
                remaining = stats.get("remaining", 0)
                limit = stats.get("daily_limit", 1)
                result_msg = "Зображення згенеровано! "
                if not stats.get("is_admin"):
                    result_msg += f"Залишилось сьогодні: {remaining}/{limit}"
                return json.dumps({"success": True, "message": result_msg})
            except QuotaExceededError as e:
                return json.dumps({"success": False, "error": str(e)})
            except ImageGenerationError as e:
                return json.dumps({"success": False, "error": str(e)})
            except Exception:
                logger.exception("Image generation failed")
                return json.dumps(
                    {"success": False, "error": "Помилка при генерації зображення"}
                )

        async def edit_image_tool(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append("edit_image")
            prompt = params.get("prompt", "")
            if not prompt:
                return json.dumps(
                    {"success": False, "error": "Потрібна інструкція для редагування"}
                )

            # First, try to get image from reply
            image_bytes = None
            reply = getattr(message, "reply_to_message", None)

            if reply:
                try:
                    reply_media_raw = await collect_media_parts(bot, reply)
                    image_bytes_list = [
                        part.get("bytes")
                        for part in reply_media_raw
                        if part.get("kind") == "image"
                    ]
                    if image_bytes_list:
                        image_bytes = image_bytes_list[0]
                except Exception:
                    logger.warning(
                        "Failed to collect media from reply message", exc_info=True
                    )

            # If no image from reply, search recent message history
            if not image_bytes:
                from app.handlers.chat import _RECENT_CONTEXT

                key = (chat_id, thread_id)
                stored_queue = _RECENT_CONTEXT.get(key)
                if stored_queue:
                    # Search backwards through recent messages for an image
                    for item in reversed(stored_queue):
                        media_parts = item.get("media_parts")
                        if media_parts:
                            # Check if any media part is an image
                            for part in media_parts:
                                if isinstance(part, dict) and "inline_data" in part:
                                    mime = part.get("inline_data", {}).get(
                                        "mime_type", ""
                                    )
                                    if mime.startswith("image/"):
                                        # Reconstruct image bytes from inline_data
                                        import base64

                                        data = part.get("inline_data", {}).get(
                                            "data", ""
                                        )
                                        if data:
                                            try:
                                                image_bytes = base64.b64decode(data)
                                                logger.info(
                                                    f"Found image in recent history from message_id={item.get('message_id')}"
                                                )
                                                break
                                            except Exception:
                                                logger.warning(
                                                    "Failed to decode image from history",
                                                    exc_info=True,
                                                )
                        if image_bytes:
                            break

            if not image_bytes:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Не знайшов жодного зображення в недавній історії. Пришли фото або відповідь на нього.",
                    }
                )

            # Detect aspect ratio from original image
            detected_aspect_ratio = "1:1"  # Default fallback
            try:
                from PIL import Image
                from io import BytesIO

                img = Image.open(BytesIO(image_bytes))
                width, height = img.size

                # Calculate ratio and map to closest supported aspect ratio
                ratio = width / height

                # Map to closest standard aspect ratio
                aspect_ratios = {
                    "1:1": 1.0,
                    "16:9": 16 / 9,
                    "9:16": 9 / 16,
                    "4:3": 4 / 3,
                    "3:4": 3 / 4,
                    "3:2": 3 / 2,
                    "2:3": 2 / 3,
                    "4:5": 4 / 5,
                    "5:4": 5 / 4,
                    "21:9": 21 / 9,
                }

                # Find closest aspect ratio
                closest_ratio = min(
                    aspect_ratios.items(), key=lambda x: abs(x[1] - ratio)
                )
                detected_aspect_ratio = closest_ratio[0]
                logger.info(
                    f"Detected aspect ratio: {detected_aspect_ratio} (original: {width}x{height}, ratio: {ratio:.3f})"
                )
            except Exception:
                logger.warning(
                    "Failed to detect aspect ratio, using default 1:1", exc_info=True
                )

            try:
                edited_bytes = await image_gen_service.generate_image(
                    prompt=prompt,
                    context_images=[image_bytes],
                    aspect_ratio=detected_aspect_ratio,
                    user_id=user_id,
                    chat_id=chat_id,
                )
                photo = BufferedInputFile(edited_bytes, filename="edited.png")
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=None,
                        message_thread_id=thread_id,
                        reply_to_message_id=message_id,
                    )
                except TelegramBadRequest as e:
                    if "thread not found" in str(e).lower():
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=None,
                            reply_to_message_id=message_id,
                        )
                    else:
                        raise
                stats = await image_gen_service.get_usage_stats(user_id, chat_id)
                remaining = stats.get("remaining", 0)
                limit = stats.get("daily_limit", 1)
                result_msg = "Зображення відредаговано! "
                if not stats.get("is_admin"):
                    result_msg += f"Залишилось сьогодні: {remaining}/{limit}"
                return json.dumps({"success": True, "message": result_msg})
            except QuotaExceededError as e:
                return json.dumps({"success": False, "error": str(e)})
            except ImageGenerationError as e:
                return json.dumps({"success": False, "error": str(e)})
            except Exception:
                logger.exception("Edit image failed")
                return json.dumps(
                    {"success": False, "error": "Помилка при редагуванні зображення"}
                )

        callbacks["generate_image"] = generate_image_tool
        callbacks["edit_image"] = edit_image_tool

    # Media analysis tools (require bot+message to fetch media)
    if bot is not None and message is not None:

        async def describe_media_tool(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append("describe_media")
            use_reply = params.get("use_reply", True)
            max_items = params.get("max_items", 1)
            try:
                max_items = int(max_items)
            except Exception:
                max_items = 1
            max_items = max(1, min(max_items, 3))

            target_msg = (
                message.reply_to_message
                if use_reply and getattr(message, "reply_to_message", None)
                else message
            )
            try:
                media_raw = await collect_media_parts(bot, target_msg)
            except Exception:
                logger.exception("Failed to collect media for describe_media tool")
                media_raw = []

            # Filter images only
            images = [
                m
                for m in media_raw
                if (
                    m.get("kind") == "image"
                    or str(m.get("mime", "")).lower().startswith("image/")
                )
            ]
            if not images:
                return json.dumps(
                    {"success": False, "error": "Немає зображень у повідомленні"}
                )

            images = images[:max_items]
            parts = gemini_client.build_media_parts(images, logger=logger)
            if not parts:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Не вдалося підготувати медіа для аналізу",
                    }
                )

            prompt = "Опиши зображення лаконічно (1-2 речення). Якщо на ньому є текст — процитуй головне."
            user_parts = [{"text": prompt}] + parts
            try:
                response_data = await gemini_client.generate(
                    system_prompt="Ти візуальний асистент, який стисло описує зображення.",
                    history=[],
                    user_parts=user_parts,
                    tools=None,
                    tool_callbacks=None,
                )
                text = response_data.get("text", "")
                return json.dumps({"success": True, "description": text.strip()})
            except Exception:
                logger.exception("describe_media generation failed")
                return json.dumps(
                    {"success": False, "error": "Не вийшло описати зображення"}
                )

        async def transcribe_audio_tool(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append("transcribe_audio")
            use_reply = params.get("use_reply", True)
            target_msg = (
                message.reply_to_message
                if use_reply and getattr(message, "reply_to_message", None)
                else message
            )
            try:
                media_raw = await collect_media_parts(bot, target_msg)
            except Exception:
                logger.exception("Failed to collect media for transcribe_audio tool")
                media_raw = []

            # Prefer audio/voice
            audios = [
                m
                for m in media_raw
                if (
                    m.get("kind") == "audio"
                    or str(m.get("mime", "")).lower().startswith("audio/")
                )
            ]
            if not audios:
                return json.dumps(
                    {"success": False, "error": "Немає аудіо у повідомленні"}
                )

            parts = gemini_client.build_media_parts([audios[0]], logger=logger)
            if not parts:
                return json.dumps(
                    {"success": False, "error": "Не вдалось підготувати аудіо"}
                )

            prompt = "Розшифруй аудіо українською максимально точно."
            user_parts = [{"text": prompt}] + parts
            try:
                response_data = await gemini_client.generate(
                    system_prompt="Ти асистент-транскриптор українською.",
                    history=[],
                    user_parts=user_parts,
                    tools=None,
                    tool_callbacks=None,
                )
                text = response_data.get("text", "")
                return json.dumps({"success": True, "transcript": text.strip()})
            except Exception:
                logger.exception("transcribe_audio generation failed")
                return json.dumps(
                    {"success": False, "error": "Не вийшло розшифрувати аудіо"}
                )

        callbacks["describe_media"] = describe_media_tool
        callbacks["transcribe_audio"] = transcribe_audio_tool

    # Profile photo analysis tool (requires bot and message context)
    if bot is not None and message is not None and user_id is not None:

        async def analyze_profile_photo_tool(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append("analyze_profile_photo")

            target_user_id = params.get("user_id")
            if not target_user_id:
                return json.dumps(
                    {
                        "success": False,
                        "error": "User ID не передано",
                    }
                )

            try:
                target_user_id = int(target_user_id)
            except (ValueError, TypeError):
                return json.dumps(
                    {
                        "success": False,
                        "error": "Невалідний user ID",
                    }
                )

            # Validate user access: must be group member, current user, or replied-to user
            is_current_user = target_user_id == user_id
            is_replied_user = (
                getattr(message, "reply_to_message", None) is not None
                and getattr(message.reply_to_message, "from_user", None) is not None
                and message.reply_to_message.from_user.id == target_user_id
            )
            # Note: For group members check, we trust that the user_id came from the group chat
            # A full validation would require checking group membership, but we'll allow any group member to be analyzed

            if not (is_current_user or is_replied_user):
                # Still allow analysis - the user may be any group member
                pass

            # Fetch the profile photo
            photo_data = await get_user_profile_photo(bot, target_user_id)
            if photo_data is None:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Не знайшов профіль-фото для user {target_user_id}",
                    }
                )

            # Build media parts for Gemini
            parts = gemini_client.build_media_parts([photo_data], logger=logger)
            if not parts:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Не вдалося підготувати фото для аналізу",
                    }
                )

            # Build a prompt based on context - let Gemini decide what to do
            prompt = (
                "Проаналізуй профіль-фото. Можеш прокоментувати, пожартувати, запропонувати правки "
                "або що завгодно інше, залежно від контексту розмови. Будь творчим!"
            )
            user_parts = [{"text": prompt}] + parts

            try:
                # Generate response using Gemini
                response_data = await gemini_client.generate(
                    system_prompt="Ти експерт з аналізу фотографій. Дай цікаву, творчу відповідь щодо профіль-фото.",
                    history=[],
                    user_parts=user_parts,
                    tools=None,
                    tool_callbacks=None,
                )
                text = response_data.get("text", "")
                return json.dumps({"success": True, "analysis": text.strip()})
            except Exception:
                logger.exception("analyze_profile_photo generation failed")
                return json.dumps(
                    {
                        "success": False,
                        "error": "Помилка при аналізі фото",
                    }
                )

        callbacks["analyze_profile_photo"] = analyze_profile_photo_tool

    return callbacks
