from __future__ import annotations

import re
from typing import Iterable

from aiogram.types import Message, MessageEntity

_TRIGGER_PATTERN = re.compile(r"\b(?:гряг|gryag)\b", re.IGNORECASE)


def _contains_keyword(text: str | None) -> bool:
    if not text:
        return False
    return bool(_TRIGGER_PATTERN.search(text))


def _matches_mention(text: str | None, entities: Iterable[MessageEntity] | None, username: str) -> bool:
    if not text or not entities or not username:
        return False
    target = username.lstrip("@").lower()
    for entity in entities:
        if entity.type == "mention":
            mention = text[entity.offset : entity.offset + entity.length]
            if mention.lstrip("@").lower() == target:
                return True
        if entity.type == "text_mention" and entity.user and entity.user.username:
            if entity.user.username.lower() == target:
                return True
    return False


def addressed_to_bot(message: Message, bot_username: str) -> bool:
    """Return True if the incoming message is directed to the bot."""

    username = (bot_username or "").lstrip("@").lower()

    if username:
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_user = message.reply_to_message.from_user
            reply_username = (reply_user.username or "").lower()
            if reply_username == username:
                return True

        if _matches_mention(message.text, message.entities, username):
            return True
        if _matches_mention(message.caption, message.caption_entities, username):
            return True

    if _contains_keyword(message.text) or _contains_keyword(message.caption):
        return True

    return False
