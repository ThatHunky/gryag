"""
Polls tool for GRYAG bot.

Provides poll creation, voting, and results tracking functionality.
Supports anonymous and named voting modes.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass
from enum import Enum

# Import logging framework
try:
    from app.services.tool_logging import log_tool_execution, ToolLogger
except ImportError:
    # Fallback if logging framework not available
    log_tool_execution = lambda name: lambda f: f  # No-op decorator
    ToolLogger = None

# Setup tool logger
tool_logger = ToolLogger("polls") if ToolLogger else None
logger = logging.getLogger(__name__)


# Temporary in-memory storage for polls (will be replaced with database)
_active_polls = {}
_poll_votes = {}


def _generate_poll_id(chat_id: int, thread_id: Optional[int]) -> str:
    """Generate a unique poll ID."""
    return f"poll_{chat_id}_{thread_id or 0}_{int(time.time())}"


def _format_poll_display(poll_data: dict[str, Any]) -> str:
    """Format poll for display."""
    poll_text = f"📋 Опитування\n\n"
    poll_text += f"❓ {poll_data['question']}\n\n"

    total_votes = sum(opt["votes"] for opt in poll_data["options"])

    for i, option in enumerate(poll_data["options"]):
        votes = option["votes"]
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
        poll_text += f"{i + 1}. {option['text']}"
        if votes > 0:
            poll_text += f" ({votes} - {percentage:.1f}%)"
        poll_text += "\n"

    poll_text += "\n"

    if poll_data.get("allow_multiple"):
        poll_text += "✅ Можна обрати кілька варіантів\n"

    if poll_data.get("is_anonymous"):
        poll_text += "🕶️ Анонімне голосування\n"

    if poll_data.get("expires_at"):
        expires = datetime.fromisoformat(poll_data["expires_at"])
        if datetime.now() > expires:
            poll_text += "⏰ Опитування завершено\n"
        else:
            remaining = expires - datetime.now()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            poll_text += f"⏰ Залишилось: {hours}г {minutes}хв\n"

    poll_text += f"\n💬 Для голосування напишіть номер варіанту"

    return poll_text


def _create_poll_data(
    chat_id: int,
    thread_id: Optional[int],
    creator_id: int,
    question: str,
    options: list[str],
    poll_type: str = "regular",
    duration_hours: Optional[int] = None,
) -> dict[str, Any]:
    """Create poll data structure."""
    poll_id = _generate_poll_id(chat_id, thread_id)

    expires_at = None
    if duration_hours:
        expires_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()

    return {
        "id": poll_id,
        "chat_id": chat_id,
        "thread_id": thread_id,
        "creator_id": creator_id,
        "question": question.strip(),
        "options": [
            {"text": opt.strip()[:100], "votes": 0} for opt in options if opt.strip()
        ],
        "poll_type": poll_type,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "is_closed": False,
        "allow_multiple": (poll_type == "multiple"),
        "is_anonymous": (poll_type == "anonymous"),
    }


@log_tool_execution("polls")
async def polls_tool(params: dict[str, Any]) -> str:
    """
    Polls tool function for GRYAG bot.

    Handles poll creation, voting, and results.

    Args:
        params: Tool parameters containing action and relevant data

    Returns:
        JSON string with operation result
    """
    action = params.get("action", "")

    try:
        if tool_logger:
            tool_logger.debug(
                f"Poll action: {action}",
                action=action,
                params_keys=list(params.keys()),
            )

        if action == "create":
            return await _handle_create_poll(params)
        elif action == "vote":
            return await _handle_vote_poll(params)
        elif action == "results":
            return await _handle_get_results(params)
        else:
            return json.dumps(
                {"success": False, "error": f"Невідома дія: {action}"},
                ensure_ascii=False,
            )

    except Exception as e:
        logger.error(f"Poll tool error: {e}", exc_info=True)
        if tool_logger:
            tool_logger.error(f"Poll tool error: {e}", exc_info=True)

        return json.dumps(
            {"success": False, "error": "Внутрішня помилка сервісу опитувань"},
            ensure_ascii=False,
        )


async def _handle_create_poll(params: dict[str, Any]) -> str:
    """Handle poll creation."""
    chat_id = params.get("chat_id")
    thread_id = params.get("thread_id")
    creator_id = params.get("creator_id")
    question = params.get("question", "")
    options = params.get("options", [])
    poll_type = params.get("poll_type", "regular")
    duration_hours = params.get("duration_hours")

    # Validate inputs
    if not all([chat_id, creator_id, question]):
        return json.dumps(
            {"success": False, "error": "Відсутні обов'язкові параметри"},
            ensure_ascii=False,
        )

    # Validate and convert types
    try:
        chat_id_int = int(chat_id) if chat_id is not None else None
        creator_id_int = int(creator_id) if creator_id is not None else None
        thread_id_int = int(thread_id) if thread_id is not None else None
    except (ValueError, TypeError):
        return json.dumps(
            {"success": False, "error": "Невірний тип параметрів (chat_id, creator_id, thread_id мають бути числами)"},
            ensure_ascii=False,
        )

    # Validate question
    if not isinstance(question, str):
        question = str(question) if question is not None else ""
    if not question.strip():
        return json.dumps(
            {"success": False, "error": "Питання не може бути порожнім"},
            ensure_ascii=False,
        )

    # Validate options
    if not isinstance(options, list):
        return json.dumps(
            {"success": False, "error": "Параметр options має бути списком"},
            ensure_ascii=False,
        )

    if len(options) < 2:
        return json.dumps(
            {
                "success": False,
                "error": "Опитування повинно мати принаймні 2 варіанти відповіді",
            },
            ensure_ascii=False,
        )

    if len(options) > 10:
        return json.dumps(
            {
                "success": False,
                "error": "Опитування може мати максимум 10 варіантів відповіді",
            },
            ensure_ascii=False,
        )

    if len(question) > 200:
        return json.dumps(
            {"success": False, "error": "Питання не може перевищувати 200 символів"},
            ensure_ascii=False,
        )

    # Validate poll_type
    if poll_type not in ("regular", "multiple", "anonymous"):
        poll_type = "regular"

    # Validate duration_hours
    duration_hours_int = None
    if duration_hours is not None:
        try:
            duration_hours_int = int(duration_hours)
            if duration_hours_int < 0:
                return json.dumps(
                    {"success": False, "error": "Тривалість не може бути від'ємною"},
                    ensure_ascii=False,
                )
        except (ValueError, TypeError):
            return json.dumps(
                {"success": False, "error": "Невірний тип параметра duration_hours"},
                ensure_ascii=False,
            )

    # Create poll
    poll_data = _create_poll_data(
        chat_id_int,
        thread_id_int,
        creator_id_int,
        question,
        options,
        poll_type,
        duration_hours_int,
    )

    # Store in memory (will be database later)
    _active_polls[poll_data["id"]] = poll_data
    _poll_votes[poll_data["id"]] = {}

    # Format for display
    poll_text = _format_poll_display(poll_data)

    if tool_logger:
        tool_logger.info(
            "Poll created",
            poll_id=poll_data["id"],
            options_count=len(options),
            poll_type=poll_type,
        )

    return json.dumps(
        {
            "success": True,
            "poll_id": poll_data["id"],
            "poll_text": poll_text,
            "expires_at": poll_data.get("expires_at"),
        },
        ensure_ascii=False,
    )


async def _handle_vote_poll(params: dict[str, Any]) -> str:
    """Handle voting on a poll."""
    poll_id = params.get("poll_id", "")
    user_id = params.get("user_id")
    option_indices = params.get("option_indices", [])

    if not all([poll_id, user_id]):
        return json.dumps(
            {"success": False, "error": "Відсутні обов'язкові параметри"},
            ensure_ascii=False,
        )

    # Validate types
    if not isinstance(poll_id, str) or not poll_id.strip():
        return json.dumps(
            {"success": False, "error": "Невірний poll_id"},
            ensure_ascii=False,
        )

    try:
        user_id_int = int(user_id) if user_id is not None else None
    except (ValueError, TypeError):
        return json.dumps(
            {"success": False, "error": "Невірний тип user_id"},
            ensure_ascii=False,
        )

    # Validate option_indices
    if not isinstance(option_indices, list):
        return json.dumps(
            {"success": False, "error": "option_indices має бути списком"},
            ensure_ascii=False,
        )

    # Get poll
    poll_data = _active_polls.get(poll_id)
    if not poll_data:
        return json.dumps(
            {"success": False, "error": "Опитування не знайдено"}, ensure_ascii=False
        )

    # Check if poll is expired
    if poll_data.get("expires_at"):
        expires = datetime.fromisoformat(poll_data["expires_at"])
        if datetime.now() > expires:
            poll_data["is_closed"] = True
            return json.dumps(
                {"success": False, "error": "Термін опитування минув"},
                ensure_ascii=False,
            )

    if poll_data["is_closed"]:
        return json.dumps(
            {"success": False, "error": "Опитування закрито"}, ensure_ascii=False
        )

    # Validate option indices
    valid_indices = []
    for idx in option_indices:
        if 0 <= idx < len(poll_data["options"]):
            valid_indices.append(idx)

    if not valid_indices:
        return json.dumps(
            {"success": False, "error": "Некоректні варіанти відповіді"},
            ensure_ascii=False,
        )

    # Check voting rules
    if not poll_data["allow_multiple"] and len(valid_indices) > 1:
        return json.dumps(
            {
                "success": False,
                "error": "В цьому опитуванні можна обрати лише один варіант",
            },
            ensure_ascii=False,
        )

    # Check if user already voted
    poll_votes = _poll_votes.get(poll_id, {})
    if user_id_int in poll_votes and not poll_data["allow_multiple"]:
        return json.dumps(
            {"success": False, "error": "Ви вже проголосували в цьому опитуванні"},
            ensure_ascii=False,
        )

    # Record votes
    if user_id_int not in poll_votes:
        poll_votes[user_id_int] = []

    # Remove old votes if not allowing multiple votes
    if not poll_data["allow_multiple"]:
        for old_idx in poll_votes[user_id_int]:
            if 0 <= old_idx < len(poll_data["options"]):
                poll_data["options"][old_idx]["votes"] -= 1
        poll_votes[user_id_int] = []

    # Add new votes
    for idx in valid_indices:
        if idx not in poll_votes[user_id_int]:
            poll_votes[user_id_int].append(idx)
            poll_data["options"][idx]["votes"] += 1

    _poll_votes[poll_id] = poll_votes

    # Format updated poll
    poll_text = _format_poll_display(poll_data)

    if tool_logger:
        tool_logger.info(
            "Vote recorded",
            poll_id=poll_id,
            user_id=user_id_int,
            votes_cast=len(valid_indices),
        )

    return json.dumps(
        {"success": True, "poll_text": poll_text, "message": "Ваш голос зараховано!"},
        ensure_ascii=False,
    )


async def _handle_get_results(params: dict[str, Any]) -> str:
    """Handle getting poll results."""
    poll_id = params.get("poll_id", "")

    if not poll_id:
        return json.dumps(
            {"success": False, "error": "Відсутній ID опитування"}, ensure_ascii=False
        )

    poll_data = _active_polls.get(poll_id)
    if not poll_data:
        return json.dumps(
            {"success": False, "error": "Опитування не знайдено"}, ensure_ascii=False
        )

    # Generate detailed results
    total_votes = sum(opt["votes"] for opt in poll_data["options"])

    results_text = f"📊 Результати опитування:\n\n"
    results_text += f"❓ {poll_data['question']}\n\n"

    for i, option in enumerate(poll_data["options"]):
        votes = option["votes"]
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
        bar_length = int(percentage / 10)  # 10% per bar segment
        bar = "█" * bar_length + "░" * (10 - bar_length)
        results_text += f"{i + 1}. {option['text']}\n"
        results_text += f"{bar} {votes} ({percentage:.1f}%)\n\n"

    results_text += f"👥 Всього голосів: {total_votes}\n"

    if poll_data.get("expires_at"):
        expires = datetime.fromisoformat(poll_data["expires_at"])
        if datetime.now() > expires:
            results_text += "⏰ Опитування завершено\n"
        else:
            remaining = expires - datetime.now()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            results_text += f"⏰ Залишилось: {hours}г {minutes}хв\n"

    if tool_logger:
        tool_logger.info(
            "Results retrieved",
            poll_id=poll_id,
            total_votes=total_votes,
        )

    return json.dumps(
        {
            "success": True,
            "results_text": results_text,
            "total_votes": total_votes,
        },
        ensure_ascii=False,
    )


# Tool definition for Gemini integration
POLLS_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "polls",
            "description": "Створення опитувань, голосування та перегляд результатів",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "vote", "results"],
                        "description": "Дія: create - створити опитування, vote - проголосувати, results - показати результати",
                    },
                    "chat_id": {
                        "type": "integer",
                        "description": "ID чату (для створення опитування)",
                    },
                    "thread_id": {
                        "type": "integer",
                        "description": "ID треду/топіку (опціонально)",
                    },
                    "creator_id": {
                        "type": "integer",
                        "description": "ID користувача-створювача (для створення)",
                    },
                    "question": {
                        "type": "string",
                        "description": "Питання опитування (для створення)",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Варіанти відповідей (для створення)",
                    },
                    "poll_type": {
                        "type": "string",
                        "enum": ["regular", "multiple", "anonymous"],
                        "description": "Тип опитування: regular - звичайне, multiple - багатовибір, anonymous - анонімне",
                    },
                    "duration_hours": {
                        "type": "integer",
                        "description": "Тривалість опитування в годинах (опціонально)",
                    },
                    "poll_id": {
                        "type": "string",
                        "description": "ID опитування (для голосування та результатів)",
                    },
                    "user_id": {
                        "type": "integer",
                        "description": "ID користувача (для голосування)",
                    },
                    "option_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Індекси обраних варіантів (0-based, для голосування)",
                    },
                },
                "required": ["action"],
            },
        }
    ]
}
