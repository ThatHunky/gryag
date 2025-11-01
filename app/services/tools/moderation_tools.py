"""
This module defines tools for moderation, such as kicking or muting users in a chat.
"""

from app.services.telegram_service import TelegramService


def build_tool_definitions() -> list[dict]:
    """Builds the definitions for moderation tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "kick_user",
                "description": "Kicks a user from the chat.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "The ID of the user to kick.",
                        },
                        "chat_id": {
                            "type": "integer",
                            "description": "The ID of the chat to kick the user from.",
                        },
                    },
                    "required": ["user_id", "chat_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mute_user",
                "description": "Temporarily mutes a user in the chat.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "integer",
                            "description": "The ID of the user to mute.",
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
        },
    ]


def build_tool_callbacks(telegram_service: TelegramService) -> dict:
    """Builds the callbacks for moderation tools."""
    return {
        "kick_user": telegram_service.kick_user,
        "mute_user": telegram_service.mute_user,
    }
