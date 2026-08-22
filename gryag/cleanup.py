"""Sweeping the admin surface back out of the chat.

The menu, the spend report and the ban verdicts are plumbing: worth the ten
seconds an admin spends reading them, clutter in a group chat for the rest of
the day. Nothing here touches what gryag actually says to people — only the
technical output goes.

Timers are keyed by message, and re-arming one replaces the pending timer rather
than adding a second. That is what keeps the menu alive while it is being used:
every navigation edits the same message and pushes its deletion back out.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

# How long each kind of technical message stays up.
MENU_TTL = 180  # settings screens — re-armed on every navigation
REPORT_TTL = 120  # spend reports, tables, status dumps
NOTICE_TTL = 60  # one-line confirmations and verdicts

_timers: dict[tuple[int, int], asyncio.Task] = {}


async def _delete_later(bot, chat_id: int, message_id: int, after: int) -> None:
    try:
        await asyncio.sleep(after)
        await bot.delete_message(chat_id, message_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # already gone, too old, or not ours to delete
        log.debug("sweep failed for %s/%s: %s", chat_id, message_id, exc)
    finally:
        _timers.pop((chat_id, message_id), None)


def sweep(bot, chat_id: int, message_id: int, after: int = NOTICE_TTL) -> None:
    """Arm — or re-arm — deletion of one message."""
    key = (chat_id, message_id)
    pending = _timers.pop(key, None)
    if pending is not None:
        pending.cancel()
    _timers[key] = asyncio.create_task(_delete_later(bot, chat_id, message_id, after))


def sweep_message(message, after: int = NOTICE_TTL) -> None:
    """`sweep` for anything that already looks like a Message."""
    if message is None:
        return
    chat = getattr(message, "chat", None)
    bot = getattr(message, "bot", None)
    if chat is None or bot is None or getattr(message, "message_id", None) is None:
        return
    sweep(bot, chat.id, message.message_id, after)


def cancel_all() -> None:
    """Drop every pending timer. For tests, and for a clean shutdown."""
    for task in list(_timers.values()):
        task.cancel()
    _timers.clear()
