"""Підарас дня: one chat member, chosen at random, once a day.

A joke with two constraints that are not jokes. It must never call the model — the pool of
phrases is generated offline and shipped as data. And it must be stable: the same day must
produce the same person no matter how many times anybody asks, or how many people ask at
once.
"""

from __future__ import annotations

import html

from gryag.handlers import kyiv_day

__all__ = ["kyiv_day", "choose", "mention"]


def choose(
    candidates: list[int], previous: int | None, roll: float, min_players: int
) -> int | None:
    """Who it is today. `roll` is a float in [0, 1]; passing it in keeps this testable.

    Yesterday's winner is dropped, but only while enough people remain: in a chat of four,
    refusing to repeat would be a stronger constraint than the randomness it protects.
    """
    if len(candidates) < min_players:
        return None
    pool = [c for c in candidates if c != previous]
    if len(pool) < min_players:
        pool = list(candidates)
    return pool[min(int(roll * len(pool)), len(pool) - 1)]


def mention(user_id: int, username: str | None, display_name: str) -> str:
    """HTML, because a person with no username can only be mentioned by link.

    The display name is text the person chose, going into a message sent with
    parse_mode="HTML", so it is escaped.
    """
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{html.escape(display_name)}</a>'
