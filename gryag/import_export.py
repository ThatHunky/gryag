"""One-time backfill from a Telegram JSON export.

Kept in the repo because there will be another export. Re-running it against a newer one
is safe: every message insert is ON CONFLICT DO NOTHING on (chat_id, message_id), so a
row the bot captured live always wins over the same row in the file.

Reactions are the exception, and deliberately so. The export states a total; live capture
only ever saw the deltas that arrived while the bot was running, and reaction updates are
never replayed across downtime. An export is therefore a strictly better record of them,
and its counts are written over whatever is stored.

    python -m gryag.import_export chat_exports/ChatExport_2026-08-24/result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone

import aiosqlite

from gryag import config, context, store

log = logging.getLogger(__name__)

MEDIA_KINDS = {
    "animation": "animation",
    "sticker": "sticker",
    "audio_file": "audio",
    "video_file": "video",
    "voice_message": "voice",
    "video_message": "video_note",
}
"""The export's `media_type` vocabulary onto the names `media.detect` already produces.
`photo` has no media_type of its own — it is a top-level `photo` key — and anything else
carrying a file is a document."""

EXPORT_ACTIONS = {
    "invite_members": "join",
    "join_group_by_link": "join",
    "join_group_by_request": "join",
    "remove_members": "leave",
    "pin_message": "pin",
    "edit_group_title": "title",
    "migrate_from_group": "migrate",
    "boost_apply": "boost",
    "topic_created": "topic",
    "topic_edit": "topic",
}
"""The export's action names onto `events.ACTIONS`. Anything unlisted is skipped and
logged — a shape change should cost that row, not the import."""


def chat_id_for(export: dict) -> int:
    """The export's bare id onto the id the Bot API uses.

    Supergroups and channels carry a -100 prefix; a plain group is only negated.
    """
    raw = int(export["id"])
    kind = str(export.get("type", ""))
    if "supergroup" in kind or "channel" in kind:
        return int(f"-100{raw}")
    return -raw


def peer_id(raw: str | None) -> int | None:
    """`user8792101665` -> 8792101665. A channel peer has no user behind it."""
    if not raw or not str(raw).startswith("user"):
        return None
    digits = str(raw)[4:]
    return int(digits) if digits.isdigit() else None


def plain_text(entities: list) -> str:
    """`text_entities` joined. Each entry carries the same characters as `text`, with the
    formatting split out, so concatenating them reproduces the message exactly."""
    return "".join(str(e.get("text", "")) for e in entities or [])


def utc_ts(message: dict) -> str:
    """The instant, as UTC ISO-8601 with an offset.

    `date` is local time with no offset — for this chat, three hours ahead of what the bot
    stored for the very same message. Only `date_unixtime` is unambiguous.
    """
    seconds = int(message["date_unixtime"])
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def media_kind_for(message: dict) -> str | None:
    if message.get("photo"):
        return "photo"
    kind = message.get("media_type")
    if kind:
        return MEDIA_KINDS.get(kind, "document")
    if message.get("file"):
        return "document"
    return None


BOT_USER_ID = 8082154386
"""@gryag_bot. Identity is the id, never the display name: a human in this chat calls
themselves «гряг» too, and matching on the name marked 445 of their messages as the
bot's own — which drives the reply caps, the bot streak, and who is left out of the
підарас draw."""


def _flags(sender: str, user_id: int, bot_id: int) -> tuple[int, int]:
    """(is_bot, sender_is_bot). `is_bot` means gryag said it and drives the reply caps."""
    if user_id == bot_id:
        return 1, 1
    return 0, int(sender in context.OTHER_BOT_ALIASES)


def _reply_to(message: dict) -> int | None:
    # `reply_to_peer_id` means the parent lives in another chat, so its id is somebody
    # else's numbering and would build a false chain against whatever shares that number
    # here.
    if message.get("reply_to_peer_id"):
        return None
    return message.get("reply_to_message_id")


async def load(
    db: aiosqlite.Connection, path: str, bot_id: int = BOT_USER_ID
) -> dict[str, int]:
    """Import one export. Returns how many rows landed in each table."""
    with open(path, encoding="utf-8") as handle:
        export = json.load(handle)

    chat_id = chat_id_for(export)
    await store.ensure_chat(db, chat_id, str(export.get("name") or chat_id))

    people: dict[int, str] = {}
    messages: list[tuple] = []
    reactions: list[tuple] = []
    events: list[tuple] = []
    unknown_actions = 0

    for item in export.get("messages", []):
        ts = utc_ts(item)
        if item.get("type") == "service":
            action = EXPORT_ACTIONS.get(str(item.get("action")))
            if action is None:
                unknown_actions += 1
                continue
            actor = peer_id(item.get("actor_id"))
            if actor is not None and item.get("actor"):
                people[actor] = str(item["actor"])
            payload = {
                k: item[k]
                for k in ("title", "new_title", "members", "message_id", "boosts", "inviter")
                if k in item
            }
            if action == "topic" and "new_title" in payload:
                payload["title"] = payload.pop("new_title")
            events.append(
                (chat_id, int(item["id"]), ts, action, actor,
                 json.dumps(payload, ensure_ascii=False))
            )
            continue

        user_id = peer_id(item.get("from_id"))
        if user_id is None:
            # A channel post has no user behind it, and every downstream query keys on one.
            continue
        sender = str(item.get("from") or "")
        people[user_id] = sender
        is_bot, sender_is_bot = _flags(sender, user_id, bot_id)
        messages.append(
            (
                chat_id,
                int(item["id"]),
                user_id,
                ts,
                plain_text(item.get("text_entities")),
                media_kind_for(item),
                None,  # file_id: an export's files are on disk, not in Telegram's storage
                _reply_to(item),
                is_bot,
                sender_is_bot,
                1 if item.get("edited") else 0,
            )
        )
        for reaction in item.get("reactions") or []:
            emoji = reaction.get("emoji")
            if reaction.get("type") != "emoji" or not emoji:
                continue
            reactions.append(
                (chat_id, int(item["id"]), emoji, int(reaction.get("count") or 0), ts)
            )

    for user_id, display_name in people.items():
        await store.upsert_user(
            db,
            chat_id=chat_id,
            user_id=user_id,
            display_name=display_name,
            alias=context.alias_for(display_name),
        )

    inserted = await store.bulk_insert_messages(db, messages)
    counts = {
        "messages": inserted,
        "skipped": len(messages) - inserted,
        "users": len(people),
        "reactions": await store.bulk_set_reactions(db, reactions),
        "events": await store.bulk_insert_events(db, events),
    }
    if unknown_actions:
        log.warning("skipped %s service messages with an unmapped action", unknown_actions)
    return counts


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Backfill from a Telegram JSON export")
    parser.add_argument("path", help="path to result.json")
    parser.add_argument("--db", default=None, help="database file (default: DB_PATH)")
    parser.add_argument(
        "--bot-id", type=int, default=BOT_USER_ID, help="whose messages are gryag's own"
    )
    args = parser.parse_args()

    db = await store.connect(args.db or config.secrets().db_path)
    try:
        counts = await load(db, args.path, args.bot_id)
    finally:
        await db.close()
    for table, number in counts.items():
        log.info("%s: %s", table, number)


if __name__ == "__main__":
    asyncio.run(main())
