"""Service messages: joins, leaves, pins, renames, the migration from a plain group.

They arrive as ordinary `Message` objects with no text, so until now they fell through
the handler, were stored as empty rows and then filtered straight back out of the context.
Neither Telegram nor a later export can be asked for them again, which is the whole reason
this exists.

The action names here are the shared vocabulary. The live handler produces them from
aiogram fields; `import_export` produces the same names from the export's own, quite
different, `action` strings. Anything that reads `events` reads one list.
"""

from __future__ import annotations

ACTIONS = ("join", "leave", "pin", "title", "migrate", "boost", "topic")


def _people(users: list) -> dict:
    return {
        "members": [getattr(u, "full_name", "") for u in users],
        "member_ids": [getattr(u, "id", None) for u in users],
    }


def detect(message) -> tuple[str, dict] | None:
    """(action, payload) for a service message, or None for an ordinary one.

    The payload is whatever the renderer might want to say out loud — a title, the people
    who joined, the id of the pinned message — rather than a column per action.
    """
    if getattr(message, "new_chat_members", None):
        return "join", _people(message.new_chat_members)
    if getattr(message, "left_chat_member", None):
        return "leave", _people([message.left_chat_member])
    if getattr(message, "pinned_message", None) is not None:
        pinned = message.pinned_message
        return "pin", {
            "message_id": getattr(pinned, "message_id", None),
            "text": (getattr(pinned, "text", None) or getattr(pinned, "caption", None) or ""),
        }
    if getattr(message, "new_chat_title", None):
        return "title", {"title": message.new_chat_title}
    if getattr(message, "migrate_from_chat_id", None):
        return "migrate", {"from_chat_id": message.migrate_from_chat_id}
    if getattr(message, "boost_added", None) is not None:
        return "boost", {"boosts": getattr(message.boost_added, "boost_count", 1)}
    for field in ("forum_topic_created", "forum_topic_edited"):
        topic = getattr(message, field, None)
        if topic is not None:
            return "topic", {"title": getattr(topic, "name", "") or ""}
    return None
