from gryag import lore, store

CHAT = -100
START = "2026-08-18T00:00:00+00:00"
END = "2026-08-20T00:00:00+00:00"
BEFORE = "2026-08-16T00:00:00+00:00"


async def seed_window(db):
    """Two days, two people, a sticker, an edit, a reaction and three events."""
    await store.upsert_user(db, chat_id=CHAT, user_id=1, display_name="Олег", alias="oleh")
    await store.upsert_user(db, chat_id=CHAT, user_id=2, display_name="Марія", alias="maria")
    rows = [
        (1, 1, "2026-08-16T10:00:00+00:00", "давнє", None),
        (2, 1, "2026-08-16T11:00:00+00:00", "теж давнє", None),
        (3, 1, "2026-08-18T09:00:00+00:00", "доброго ранку", None),
        (4, 2, "2026-08-18T09:05:00+00:00", "здоров", None),
        (5, 1, "2026-08-18T22:00:00+00:00", "смішне", None),
        (6, 2, "2026-08-19T08:00:00+00:00", "", "sticker"),
        (7, 2, "2026-08-19T08:01:00+00:00", "", "sticker"),
        (8, 1, "2026-08-19T20:00:00+00:00", "останнє", None),
    ]
    for message_id, user_id, ts, text, kind in rows:
        await store.save_message(
            db, chat_id=CHAT, message_id=message_id, user_id=user_id, ts=ts,
            text=text, media_kind=kind, file_id=None, reply_to=None, is_bot=False,
        )
    await store.update_message_text(db, CHAT, 5, "смішне, виправлене")
    await store.apply_reaction(
        db, chat_id=CHAT, message_id=5, added=["😁", "😁", "❤"], removed=[],
        ts="2026-08-18T22:01:00+00:00",
    )
    await store.save_event(
        db, chat_id=CHAT, message_id=100, ts="2026-08-18T12:00:00+00:00",
        action="join", actor_id=2, payload={"members": ["Марія"], "member_ids": [2]},
    )
    await store.save_event(
        db, chat_id=CHAT, message_id=101, ts="2026-08-19T12:00:00+00:00",
        action="title", actor_id=1, payload={"title": "чат матсурі"},
    )
    await store.save_event(
        db, chat_id=CHAT, message_id=102, ts="2026-08-19T13:00:00+00:00",
        action="pin", actor_id=1, payload={"message_id": 5, "text": "смішне"},
    )


async def test_the_stats_count_only_the_window(db):
    await seed_window(db)

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert stats["total"] == 6


async def test_messages_per_person_carry_the_change_against_the_previous_window(db):
    await seed_window(db)

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert stats["per_person"] == [("maria", 3, 3), ("oleh", 3, 1)]


async def test_the_most_reacted_message_comes_back_with_its_reactions(db):
    await seed_window(db)

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert stats["top_reacted"] == [("oleh", "смішне, виправлене", 3, [("😁", 2), ("❤", 1)])]


async def test_a_reaction_on_a_message_outside_the_window_is_not_counted(db):
    await seed_window(db)
    await store.apply_reaction(
        db, chat_id=CHAT, message_id=1, added=["🔥"] * 50, removed=[],
        ts="2026-08-16T10:01:00+00:00",
    )

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert [r[1] for r in stats["top_reacted"]] == ["смішне, виправлене"]


async def test_the_longest_silence_is_the_biggest_gap_between_two_messages(db):
    await seed_window(db)

    seconds, from_ts, to_ts = (await store.lore_stats(db, CHAT, START, END, BEFORE))[
        "longest_silence"
    ]

    assert seconds == 12 * 3600 + 55 * 60
    assert from_ts == "2026-08-18T09:05:00+00:00"
    assert to_ts == "2026-08-18T22:00:00+00:00"


async def test_a_window_with_one_message_has_no_silence(db):
    await store.save_message(
        db, chat_id=CHAT, message_id=1, user_id=1, ts="2026-08-18T09:00:00+00:00",
        text="сам", media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )

    assert (await store.lore_stats(db, CHAT, START, END, BEFORE))["longest_silence"] is None


async def test_the_sticker_and_edit_champions(db):
    await seed_window(db)

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert stats["stickers"] == ("maria", 2)
    assert stats["edits"] == ("oleh", 1)


async def test_nobody_edited_anything_is_not_a_champion(db):
    await store.save_message(
        db, chat_id=CHAT, message_id=1, user_id=1, ts="2026-08-18T09:00:00+00:00",
        text="сам", media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )

    assert (await store.lore_stats(db, CHAT, START, END, BEFORE))["edits"] is None


async def test_events_inside_the_window_come_with_the_stats(db):
    await seed_window(db)

    stats = await store.lore_stats(db, CHAT, START, END, BEFORE)

    assert sorted(e["action"] for e in stats["events"]) == ["join", "pin", "title"]


async def test_utc_buckets_are_read_as_local_hours():
    """Stored timestamps are UTC; the chat lives in Kyiv, and a fixed +3 in SQL would be
    an hour wrong from the last Sunday of October."""
    counts = lore.local_hours([("2026-08-18T22", 5), ("2026-08-18T21", 2)])

    assert counts[1] == 5  # 22:00 UTC is 01:00 Kyiv
    assert counts[0] == 2
    assert sum(counts) == 7


async def test_the_rendered_block_states_the_numbers_it_was_given(db):
    await seed_window(db)

    text = lore.render_stats(await store.lore_stats(db, CHAT, START, END, BEFORE))

    assert "oleh 3" in text
    assert "maria 3" in text
    assert "смішне, виправлене" in text
    assert "😁 2" in text
    assert "чат матсурі" in text
    assert "стікер" in text.lower()


async def test_the_rendered_block_survives_an_empty_window(db):
    text = lore.render_stats(await store.lore_stats(db, CHAT, START, END, BEFORE))

    assert isinstance(text, str)
    assert "0" in text
