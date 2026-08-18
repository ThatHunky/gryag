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
    busy: bool = False
    user_recent_replies: int = 0
    seconds_since_user_reply: float = 1e9
    throttle_after: int = 3
    throttle_step: int = 20
    own_commands: tuple[str, ...] = ()
    sender_banned: bool = False
    chat_muted: bool = False
    # ambient interjection
    ambient_enabled: bool = False
    ambient_roll: float = 1.0
    ambient_probability: float = 0.0
    seconds_since_bot_spoke: float = 1e9
    ambient_cooldown: int = 1200
    is_reply_to_other: bool = False
    media_only: bool = False
    local_hour: int = 12
    quiet_from: int = 2
    quiet_to: int = 8


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


def required_gap(recent_replies: int, throttle_after: int, throttle_step: int) -> int:
    """Seconds one person must wait, given how much they have already been answered.

    Free until `throttle_after` replies in the window, then a gap that grows by
    `throttle_step` each time: 20s, 40s, 60s. Someone chatting gets answered; someone
    hammering the bot gets answered more and more slowly, without ever being cut off.
    """
    over = recent_replies - throttle_after + 1
    return max(over, 0) * throttle_step


def foreign_command(text: str, own_commands: tuple[str, ...]) -> bool:
    """True for a slash command that belongs to some other bot.

    This chat runs three of them. `/slots 1.6` is a person talking to Пісюнбот, and gryag
    barging in on it is noise. Its own commands are handled by the admin router, so by the
    time the gate sees one it is somebody else's.
    """
    if not text.startswith("/"):
        return False
    word = text[1:].split()[0] if len(text) > 1 else ""
    return word.split("@")[0].lower() not in own_commands


def in_quiet_hours(hour: int, quiet_from: int, quiet_to: int) -> bool:
    """Quiet hours wrap midnight, so 22->6 is a range, not an empty set."""
    if quiet_from == quiet_to:
        return False
    if quiet_from < quiet_to:
        return quiet_from <= hour < quiet_to
    return hour >= quiet_from or hour < quiet_to


def is_ambient_candidate(g: GateInput) -> bool:
    """Whether a message is worth interrupting over, decided without a model call.

    Measured on the real chat: the median message is 19 characters, 17% carry no text at
    all, and 39% are replies. Rolling dice on every message would spend most interjections
    on "ага" and a sticker, which is precisely what makes a bot look stupid.
    """
    if g.media_only:
        return False
    if len(g.text.strip()) < 30:
        return False
    if g.is_reply_to_other:
        # Two people mid-exchange are having a conversation, not leaving a gap.
        return False
    return True


def should_speak(g: GateInput) -> GateDecision:
    if not g.chat_enabled:
        return GateDecision(False, "chat_disabled")
    if g.chat_muted:
        return GateDecision(False, "chat_muted")
    if g.is_self:
        return GateDecision(False, "sender_is_self")
    if foreign_command(g.text, g.own_commands):
        return GateDecision(False, "foreign_command")
    if g.sender_banned:
        # Ignored, not erased: their messages are still stored and still appear in the
        # context window, so the conversation reads correctly to everyone else.
        return GateDecision(False, "user_banned")
    if g.age_seconds > g.max_reply_age:
        # A backlog replayed after downtime must be stored but not answered: nobody wants
        # the bot waking up and replying to an argument that ended an hour ago.
        return GateDecision(False, "too_old")
    if g.busy:
        # Already writing an answer in this chat. Answering two people at once produces
        # two replies to a conversation that has moved on between them.
        return GateDecision(False, "busy")
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

    gap = required_gap(g.user_recent_replies, g.throttle_after, g.throttle_step)
    if gap and g.seconds_since_user_reply < gap:
        return GateDecision(False, "throttled")

    if g.mentions_bot:
        return GateDecision(True, "mention")
    if g.replies_to_bot:
        return GateDecision(True, "reply_to_bot")
    if mentions_keyword(g.text, g.keywords):
        return GateDecision(True, "keyword")

    if not g.ambient_enabled:
        return GateDecision(False, "not_addressed")
    if in_quiet_hours(g.local_hour, g.quiet_from, g.quiet_to):
        return GateDecision(False, "quiet_hours")
    if g.seconds_since_bot_spoke < g.ambient_cooldown:
        return GateDecision(False, "ambient_cooldown")
    if not is_ambient_candidate(g):
        return GateDecision(False, "not_worth_it")
    if g.ambient_roll >= g.ambient_probability:
        return GateDecision(False, "not_addressed")
    return GateDecision(True, "ambient")


@dataclass(frozen=True)
class ProactiveInput:
    chat_enabled: bool
    chat_muted: bool
    local_hour: int
    quiet_from: int
    quiet_to: int
    silent_seconds: float
    silence_needed: int
    seconds_since_proactive: float
    proactive_cooldown: int
    has_context: bool


def should_start_talking(p: ProactiveInput) -> GateDecision:
    """Whether to say something into a silent chat.

    Measured, this fires almost only in the morning: two days of the real chat held just
    18 gaps longer than fifteen minutes, against a median gap of six seconds.
    """
    if not p.chat_enabled:
        return GateDecision(False, "chat_disabled")
    if p.chat_muted:
        return GateDecision(False, "chat_muted")
    if not p.has_context:
        return GateDecision(False, "nothing_to_talk_about")
    if in_quiet_hours(p.local_hour, p.quiet_from, p.quiet_to):
        return GateDecision(False, "quiet_hours")
    if p.silent_seconds < p.silence_needed:
        return GateDecision(False, "not_silent_enough")
    if p.seconds_since_proactive < p.proactive_cooldown:
        return GateDecision(False, "proactive_cooldown")
    return GateDecision(True, "proactive")
