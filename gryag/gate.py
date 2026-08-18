"""The decision to speak.

Deliberately pure: no database, no network, no clock. Everything it needs is passed in, so
the whole of the bot's behaviour can be tested without spending a cent. This is the
structural difference from the legacy bot, where deciding whether to answer cost money.

Phase 1 implements direct address only. Ambient interjection and proactive speech arrive in
phase 3 and will extend GateInput rather than replace it.

Other bots are allowed to talk to gryag, but never to trap it: a bot must address it
explicitly, and the exchange dies after `bot_exchange_limit` messages without a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GateInput:
    text: str
    is_bot: bool
    is_self: bool
    chat_enabled: bool
    mentions_bot: bool
    replies_to_bot: bool
    keywords: tuple[str, ...]
    replies_today: int
    replies_this_hour: int
    daily_cap: int
    hourly_cap: int
    bot_streak: int
    bot_exchange_limit: int
    age_seconds: float = 0.0
    max_reply_age: int = 300


@dataclass(frozen=True)
class GateDecision:
    speak: bool
    reason: str


def mentions_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """True when a keyword starts a word.

    Matching on a word boundary followed by the keyword catches Ukrainian inflections
    (гряг, гряга, грягу, грягом) with a single configured stem, while refusing to fire on
    words that merely contain it, like `шпаргалка`.
    """
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}", text, re.IGNORECASE):
            return True
    return False


def should_speak(g: GateInput) -> GateDecision:
    if not g.chat_enabled:
        return GateDecision(False, "chat_disabled")
    if g.is_self:
        return GateDecision(False, "sender_is_self")
    if g.age_seconds > g.max_reply_age:
        # A backlog replayed after downtime must be stored but not answered: nobody wants
        # the bot waking up and replying to an argument that ended an hour ago.
        return GateDecision(False, "too_old")
    if g.replies_today >= g.daily_cap:
        return GateDecision(False, "daily_cap")
    if g.replies_this_hour >= g.hourly_cap:
        return GateDecision(False, "hourly_cap")

    addressed = (
        g.mentions_bot
        or g.replies_to_bot
        or mentions_keyword(g.text, g.keywords)
    )
    if g.is_bot:
        # Другий бот may be talked to, but only when it speaks first and only for a few
        # turns. `bot_streak` counts messages since the last human said anything, so two
        # bots left alone run down the limit and stop; any human line resets it to zero.
        if not addressed:
            return GateDecision(False, "bot_not_addressed")
        if g.bot_streak >= g.bot_exchange_limit:
            return GateDecision(False, "bot_exchange_limit")

    if g.mentions_bot:
        return GateDecision(True, "mention")
    if g.replies_to_bot:
        return GateDecision(True, "reply_to_bot")
    if mentions_keyword(g.text, g.keywords):
        return GateDecision(True, "keyword")

    return GateDecision(False, "not_addressed")
