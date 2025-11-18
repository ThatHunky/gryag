from __future__ import annotations

import re
from collections.abc import Iterable

from aiogram.types import Message, MessageEntity

# Default trigger pattern for backwards compatibility
# Will be overridden by persona configuration or BOT_TRIGGER_PATTERNS setting
_DEFAULT_TRIGGER_PATTERN = re.compile(
    r"\b(?:гр[яи]г[аоуеєіїюяьґ]*|gr[yi]ag\w*)\b", re.IGNORECASE | re.UNICODE
)

# Global trigger patterns (set by initialize_triggers function)
_TRIGGER_PATTERNS: list[re.Pattern[str]] = [_DEFAULT_TRIGGER_PATTERN]


def initialize_triggers(patterns: list[str] | None = None) -> None:
    """Initialize trigger patterns from configuration.

    Args:
        patterns: List of regex pattern strings. If None, uses default pattern.
    """
    global _TRIGGER_PATTERNS

    if patterns:
        _TRIGGER_PATTERNS = [
            re.compile(pattern, re.IGNORECASE | re.UNICODE) for pattern in patterns
        ]
    else:
        _TRIGGER_PATTERNS = [_DEFAULT_TRIGGER_PATTERN]


def _contains_keyword(text: str | None) -> bool:
    if not text:
        return False
    # Check all trigger patterns
    return any(pattern.search(text) for pattern in _TRIGGER_PATTERNS)


def _matches_mention(
    text: str | None,
    entities: Iterable[MessageEntity] | None,
    username: str | None,
    bot_id: int | None,
) -> bool:
    if not text or not entities:
        return False
    target = username.lstrip("@").lower() if username else ""
    for entity in entities:
        if entity.type == "mention":
            mention = text[entity.offset : entity.offset + entity.length]
            if mention.lstrip("@").lower() == target:
                return True
        if entity.type == "text_mention" and entity.user:
            if bot_id is not None and entity.user.id == bot_id:
                return True
            if (
                target
                and entity.user.username
                and entity.user.username.lower() == target
            ):
                return True
    return False


def addressed_to_bot(
    message: Message,
    bot_username: str,
    bot_id: int | None = None,
    chat_id: int | None = None,
) -> bool:
    """Return True if the incoming message is directed to the bot.

    Args:
        message: The incoming message
        bot_username: Bot's username
        bot_id: Bot's user ID
        chat_id: Chat ID (positive for personal chats, negative for groups).
                 If positive (personal chat), keyword trigger is not required.
    """

    username = (bot_username or "").lstrip("@").lower()

    if username:
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_user = message.reply_to_message.from_user
            reply_username = (reply_user.username or "").lower()
            if reply_username == username or (
                bot_id is not None and reply_user.id == bot_id
            ):
                return True

        if _matches_mention(message.text, message.entities, username, bot_id):
            return True
        if _matches_mention(
            message.caption, message.caption_entities, username, bot_id
        ):
            return True

    if _contains_keyword(message.text) or _contains_keyword(message.caption):
        return True

    # In personal chats (chat_id > 0), respond without keyword trigger
    if chat_id is not None and chat_id > 0:
        return True

    return False
