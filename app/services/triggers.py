from __future__ import annotations

import re
from typing import Iterable

from aiogram.types import Message, MessageEntity

# Match all grammatical forms of гряг/gryag:
# - гряг, гряга, грягу, грягом, грязі, гряже, etc.
# - gryag, gryaga, gryagu, gryagom, etc.
# - гряґ and variations with apostrophe
_TRIGGER_PATTERN = re.compile(
    r"\b(?:гр[яи]г[аоуеєіїюяьґ]*|gr[yi]ag\w*)\b", re.IGNORECASE | re.UNICODE
)


def _contains_keyword(text: str | None) -> bool:
    if not text:
        return False
    return bool(_TRIGGER_PATTERN.search(text))


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
) -> bool:
    """Return True if the incoming message is directed to the bot."""

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

    return False
