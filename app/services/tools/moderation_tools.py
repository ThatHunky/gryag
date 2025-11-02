"""
This module defines tools for moderation, such as kicking or muting users in a chat.
"""

import json
import logging
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


def build_tool_definitions() -> dict:
    """Builds the definitions for moderation tools in Gemini format."""
    return {
        "function_declarations": [
            {
                "name": "find_user",
                "description": "Find a user in the chat by username, display name, or first name. Returns the user_id needed for moderation actions. Always call this first to resolve user references to user_ids.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The username, display name, or name to search for (e.g., 'john_smith', 'John', or '@john'). Case-insensitive.",
                        },
                        "chat_id": {
                            "type": "integer",
                            "description": "The ID of the chat to search within.",
                        },
                    },
                    "required": ["query", "chat_id"],
                },
            },
            {
                "name": "kick_user",
                "description": "Kicks a user from the chat. IMPORTANT: Always use find_user first to resolve the user_id from a username or name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "The ID of the user to kick. Get this from find_user.",
                        },
                        "chat_id": {
                            "type": "integer",
                            "description": "The ID of the chat to kick the user from.",
                        },
                    },
                    "required": ["user_id", "chat_id"],
                },
            },
            {
                "name": "mute_user",
                "description": "Temporarily mutes a user in the chat. IMPORTANT: Always use find_user first to resolve the user_id from a username or name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "The ID of the user to mute. Get this from find_user.",
                        },
                        "chat_id": {
                            "type": "integer",
                            "description": "The ID of the chat to mute the user in.",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "The duration of the mute in minutes.",
                        },
                    },
                    "required": ["user_id", "chat_id"],
                },
            },
            {
                "name": "unmute_user",
                "description": "Unmutes a user in the chat, restoring all permissions. IMPORTANT: Always use find_user first to resolve the user_id from a username or name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "The ID of the user to unmute. Get this from find_user.",
                        },
                        "chat_id": {
                            "type": "integer",
                            "description": "The ID of the chat to unmute the user in.",
                        },
                    },
                    "required": ["user_id", "chat_id"],
                },
            },
        ]
    }


def build_tool_callbacks(telegram_service: TelegramService) -> dict:
    """Builds the callbacks for moderation tools."""

    async def find_user_callback(params: dict) -> str:
        """Wrapper for find_user that unpacks parameters from dict."""
        logger.info(f"find_user_callback invoked with params: {params}")
        query = params.get("query")
        chat_id = params.get("chat_id")

        if query is None or chat_id is None:
            logger.warning(f"Missing required parameters: query={query}, chat_id={chat_id}")
            return json.dumps({"error": "Missing query or chat_id"})

        try:
            logger.info(f"Calling find_user with query='{query}', chat_id={chat_id}")
            result = await telegram_service.find_user(
                query=str(query),
                chat_id=int(chat_id)
            )
            logger.info(f"find_user returned: {result}")
            return json.dumps(result)
        except Exception as e:
            logger.error(f"Failed to find user: {e}", exc_info=True)
            return json.dumps({"error": f"Failed to find user: {str(e)}"})

    async def kick_user_callback(params: dict) -> str:
        """Wrapper for kick_user that unpacks parameters from dict."""
        logger.info(f"kick_user_callback invoked with params: {params}")
        user_id = params.get("user_id")
        chat_id = params.get("chat_id")

        if user_id is None or chat_id is None:
            logger.warning(f"Missing required parameters: user_id={user_id}, chat_id={chat_id}")
            return json.dumps({"success": False, "error": "Missing user_id or chat_id"})

        try:
            logger.info(f"Calling kick_user with user_id={user_id}, chat_id={chat_id}")
            result = await telegram_service.kick_user(
                user_id=int(user_id),
                chat_id=int(chat_id)
            )
            logger.info(f"kick_user returned: {result}")
            return json.dumps({"success": True, "message": result})
        except Exception as e:
            logger.error(f"Failed to kick user: {e}", exc_info=True)
            return json.dumps({"success": False, "error": f"Failed to kick user: {str(e)}"})

    async def mute_user_callback(params: dict) -> str:
        """Wrapper for mute_user that unpacks parameters from dict."""
        logger.info(f"mute_user_callback invoked with params: {params}")
        user_id = params.get("user_id")
        chat_id = params.get("chat_id")
        duration_minutes = params.get("duration_minutes")

        if user_id is None or chat_id is None:
            logger.warning(f"Missing required parameters: user_id={user_id}, chat_id={chat_id}")
            return json.dumps({"success": False, "error": "Missing user_id or chat_id"})

        try:
            logger.info(f"Calling mute_user with user_id={user_id}, chat_id={chat_id}, duration={duration_minutes}")
            result = await telegram_service.mute_user(
                user_id=int(user_id),
                chat_id=int(chat_id),
                duration_minutes=int(duration_minutes) if duration_minutes else None
            )
            logger.info(f"mute_user returned: {result}")
            return json.dumps({"success": True, "message": result})
        except Exception as e:
            logger.error(f"Failed to mute user: {e}", exc_info=True)
            return json.dumps({"success": False, "error": f"Failed to mute user: {str(e)}"})

    async def unmute_user_callback(params: dict) -> str:
        """Wrapper for unmute_user that unpacks parameters from dict."""
        logger.info(f"unmute_user_callback invoked with params: {params}")
        user_id = params.get("user_id")
        chat_id = params.get("chat_id")

        if user_id is None or chat_id is None:
            logger.warning(f"Missing required parameters: user_id={user_id}, chat_id={chat_id}")
            return json.dumps({"success": False, "error": "Missing user_id or chat_id"})

        try:
            logger.info(f"Calling unmute_user with user_id={user_id}, chat_id={chat_id}")
            result = await telegram_service.unmute_user(
                user_id=int(user_id),
                chat_id=int(chat_id)
            )
            logger.info(f"unmute_user returned: {result}")
            return json.dumps({"success": True, "message": result})
        except Exception as e:
            logger.error(f"Failed to unmute user: {e}", exc_info=True)
            return json.dumps({"success": False, "error": f"Failed to unmute user: {str(e)}"})

    return {
        "find_user": find_user_callback,
        "kick_user": kick_user_callback,
        "mute_user": mute_user_callback,
        "unmute_user": unmute_user_callback,
    }
