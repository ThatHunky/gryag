"""The fixture is invented. The real export holds real names, real messages and real
photographs of real people, is gitignored for that reason, and none of it belongs here."""

from pathlib import Path

from gryag import import_export, store

FIXTURE = Path(__file__).parent / "fixtures" / "export_slice.json"
CHAT = -1004291515714


def test_a_private_supergroup_id_gets_the_hundred_prefix():
    assert import_export.chat_id_for({"id": 4291515714, "type": "private_supergroup"}) == CHAT


def test_a_plain_group_id_is_only_negated():
    assert import_export.chat_id_for({"id": 1234, "type": "private_group"}) == -1234


def test_a_user_peer_becomes_an_integer():
    assert import_export.peer_id("user8792101665") == 8792101665


def test_a_channel_peer_has_no_user_behind_it():
    assert import_export.peer_id("channel4291515714") is None
    assert import_export.peer_id(None) is None


def test_text_entities_are_joined_into_plain_text():
    entities = [
        {"type": "bold", "text": "У мене криза."},
        {"type": "plain", "text": " Мемів нема."},
    ]

    assert import_export.plain_text(entities) == "У мене криза. Мемів нема."


def test_a_message_with_no_entities_is_empty_not_missing():
    assert import_export.plain_text([]) == ""


def test_the_timestamp_is_taken_from_unixtime_not_from_the_local_date_string():
    """The export's `date` is Kyiv local with no offset, three hours off what the bot
    stored for the very same message."""
    ts = import_export.utc_ts({"date": "2026-08-19T00:40:54", "date_unixtime": "1787089254"})

    assert ts.endswith("+00:00")
    assert ts == "2026-08-18T21:40:54+00:00"


def test_media_kinds_are_mapped_onto_the_names_the_bot_already_uses():
    assert import_export.media_kind_for({"photo": "photos/1.jpg"}) == "photo"
    assert import_export.media_kind_for({"media_type": "voice_message"}) == "voice"
    assert import_export.media_kind_for({"media_type": "video_message"}) == "video_note"
    assert import_export.media_kind_for({"media_type": "audio_file"}) == "audio"
    assert import_export.media_kind_for({"media_type": "video_file"}) == "video"
    assert import_export.media_kind_for({"media_type": "sticker"}) == "sticker"
    assert import_export.media_kind_for({"media_type": "animation"}) == "animation"
    assert import_export.media_kind_for({"file": "files/a.zip"}) == "document"
    assert import_export.media_kind_for({"text": "просто текст"}) is None


async def test_importing_the_slice_stores_its_messages(db):
    counts = await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    assert counts["messages"] == len(rows)
    assert "мемна криза" in " ".join(r["text"] or "" for r in rows)


async def test_the_chat_is_created_but_not_switched_on(db):
    await import_export.load(db, str(FIXTURE))

    async with db.execute("SELECT title, enabled FROM chats WHERE chat_id = ?", (CHAT,)) as cur:
        row = await cur.fetchone()
    assert row[0] == "тестовий чат"
    assert row[1] == 0


async def test_users_come_out_with_the_same_aliases_the_bot_would_give_them(db):
    await import_export.load(db, str(FIXTURE))

    async with db.execute(
        "SELECT alias FROM users WHERE chat_id = ? AND user_id = ?", (CHAT, 493770201)
    ) as cur:
        assert (await cur.fetchone())[0] == "андрійни"


async def test_reactions_are_stored_with_the_counts_the_export_states(db):
    await import_export.load(db, str(FIXTURE))

    assert await store.reactions_for(db, CHAT, 5) == [("😁", 3), ("❤", 1)]


async def test_service_messages_become_events_and_not_messages(db):
    await import_export.load(db, str(FIXTURE))

    stored = await store.events_between(
        db, CHAT, "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"
    )
    assert sorted(e["action"] for e in stored) == ["join", "pin", "title"]
    assert all(r["message_id"] != 6 for r in await store.recent_messages(db, CHAT, limit=50))


async def test_a_pin_keeps_the_id_of_what_was_pinned(db):
    await import_export.load(db, str(FIXTURE))

    stored = await store.events_between(
        db, CHAT, "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"
    )
    pin = next(e for e in stored if e["action"] == "pin")
    assert pin["payload"]["message_id"] == 5


async def test_a_channel_post_is_skipped_because_it_has_no_user(db):
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    assert all(r["message_id"] != 9 for r in rows)


async def test_the_bots_own_messages_come_back_marked_as_the_bot(db):
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    gryag = next(r for r in rows if r["message_id"] == 8)
    assert gryag["is_bot"] == 1
    assert gryag["sender_is_bot"] == 1


async def test_another_bot_is_marked_as_a_bot_but_not_as_gryag(db):
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    other = next(r for r in rows if r["message_id"] == 10)
    assert other["is_bot"] == 0
    assert other["sender_is_bot"] == 1


async def test_a_reply_into_another_chat_does_not_become_a_reply_here(db):
    """Eight messages in the real export carry `reply_to_peer_id`: their
    reply_to_message_id is somebody else's numbering and would build a false chain."""
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    foreign = next(r for r in rows if r["message_id"] == 11)
    assert foreign["reply_to"] is None


async def test_an_ordinary_reply_survives_the_import(db):
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    assert next(r for r in rows if r["message_id"] == 7)["reply_to"] == 5


async def test_an_edited_message_arrives_already_counted_as_edited(db):
    await import_export.load(db, str(FIXTURE))

    async with db.execute(
        "SELECT edits FROM messages WHERE chat_id = ? AND message_id = ?", (CHAT, 5)
    ) as cur:
        assert (await cur.fetchone())[0] == 1


async def test_running_the_importer_twice_inserts_nothing_the_second_time(db):
    first = await import_export.load(db, str(FIXTURE))
    second = await import_export.load(db, str(FIXTURE))

    assert first["messages"] > 0
    assert second["messages"] == 0
    assert second["skipped"] == first["messages"]


async def test_a_live_row_always_wins_over_the_export(db):
    await store.upsert_user(
        db, chat_id=CHAT, user_id=493770201, display_name="андрійний колайдер", alias="андрійни"
    )
    await store.save_message(
        db, chat_id=CHAT, message_id=5, user_id=493770201,
        ts="2026-08-11T14:01:02+00:00", text="ЖИВИЙ РЯДОК", media_kind=None,
        file_id=None, reply_to=None, is_bot=False,
    )

    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    assert next(r for r in rows if r["message_id"] == 5)["text"] == "ЖИВИЙ РЯДОК"


async def test_reactions_are_still_imported_for_a_message_that_was_already_live(db):
    """The export is a richer record of the overlapping days precisely because of this."""
    await store.save_message(
        db, chat_id=CHAT, message_id=5, user_id=493770201,
        ts="2026-08-11T14:01:02+00:00", text="ЖИВИЙ РЯДОК", media_kind=None,
        file_id=None, reply_to=None, is_bot=False,
    )

    await import_export.load(db, str(FIXTURE))

    assert await store.reactions_for(db, CHAT, 5) == [("😁", 3), ("❤", 1)]


async def test_the_report_counts_every_table(db):
    counts = await import_export.load(db, str(FIXTURE))

    assert set(counts) == {"messages", "skipped", "users", "reactions", "events"}
    assert counts["users"] > 0
    assert counts["reactions"] == 2
    assert counts["events"] == 3


async def test_a_person_who_calls_themselves_гряг_is_not_the_bot(db):
    """@gria_g is a human in this chat whose display name is «гряг», the same as the
    bot's. Matching the bot by display name marked 445 of their messages as gryag's own,
    which drives the reply caps, the bot streak and who is in the підарас draw."""
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    human = next(r for r in rows if r["message_id"] == 13)
    assert human["is_bot"] == 0
    assert human["sender_is_bot"] == 0


async def test_the_bot_is_recognised_by_its_id_not_its_name(db):
    await import_export.load(db, str(FIXTURE))

    rows = await store.recent_messages(db, CHAT, limit=50)
    assert next(r for r in rows if r["message_id"] == 8)["is_bot"] == 1
