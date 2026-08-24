from gryag import store


async def _seed_user(db, user_id=1, alias="oleh"):
    await store.upsert_user(
        db, chat_id=-100, user_id=user_id, display_name=f"User {user_id}", alias=alias
    )


async def test_saves_and_reads_back_in_chronological_order(db):
    await _seed_user(db)
    for n in range(3):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=10)

    assert [r["text"] for r in rows] == ["msg 0", "msg 1", "msg 2"]
    assert rows[0]["alias"] == "oleh"


async def test_recent_messages_returns_the_newest_but_still_oldest_first(db):
    await _seed_user(db)
    for n in range(5):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=2)

    assert [r["text"] for r in rows] == ["msg 3", "msg 4"]


async def test_saving_the_same_message_twice_does_not_duplicate(db):
    await _seed_user(db)
    for _ in range(2):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=7,
            user_id=1,
            ts="2026-08-19T10:00:00",
            text="once",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=10)

    assert len(rows) == 1


async def test_reply_chain_walks_back_to_the_root(db):
    await _seed_user(db)
    parents = [None, 1, 2]
    for n, parent in enumerate(parents, start=1):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=parent,
            is_bot=False,
        )

    chain = await store.reply_chain(db, -100, message_id=3)

    assert [r["message_id"] for r in chain] == [1, 2, 3]


async def test_reply_chain_survives_a_missing_parent(db):
    await _seed_user(db)
    await store.save_message(
        db,
        chat_id=-100,
        message_id=9,
        user_id=1,
        ts="2026-08-19T10:00:00",
        text="orphan",
        media_kind=None,
        file_id=None,
        reply_to=4242,
        is_bot=False,
    )

    chain = await store.reply_chain(db, -100, message_id=9)

    assert [r["message_id"] for r in chain] == [9]


async def test_counts_only_this_chats_bot_replies_after_the_cutoff(db):
    await _seed_user(db)
    rows = [
        (1, "2026-08-19T09:00:00", True, -100),
        (2, "2026-08-19T11:00:00", True, -100),
        (3, "2026-08-19T11:30:00", False, -100),
        (4, "2026-08-19T11:40:00", True, -200),
    ]
    for message_id, ts, is_bot, chat_id in rows:
        await store.save_message(
            db,
            chat_id=chat_id,
            message_id=message_id,
            user_id=1,
            ts=ts,
            text="x",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=is_bot,
        )

    count = await store.count_replies_since(db, -100, "2026-08-19T10:00:00")

    assert count == 1


async def test_usage_rows_are_recorded(db):
    await store.record_usage(
        db,
        chat_id=-100,
        purpose="reply",
        model="gemini-flash-latest",
        prompt_tok=1800,
        cached_tok=0,
        visible_tok=20,
        thought_tok=150,
        latency_ms=2100,
        cost_usd=0.0019,
    )

    async with db.execute("SELECT model, thought_tok FROM usage") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]

    assert rows == [("gemini-flash-latest", 150)]


async def _bot_msg(db, message_id, ts, *, sender_is_bot, chat_id=-100):
    await store.save_message(
        db, chat_id=chat_id, message_id=message_id, user_id=1, ts=ts, text="x",
        media_kind=None, file_id=None, reply_to=None, is_bot=False,
        sender_is_bot=sender_is_bot,
    )


async def test_bot_streak_is_zero_when_a_human_spoke_last(db):
    await _seed_user(db)
    await _bot_msg(db, 1, "2026-08-19T10:00:00", sender_is_bot=True)
    await _bot_msg(db, 2, "2026-08-19T10:01:00", sender_is_bot=False)

    assert await store.bot_streak(db, -100) == 0


async def test_bot_streak_counts_only_the_tail(db):
    await _seed_user(db)
    await _bot_msg(db, 1, "2026-08-19T10:00:00", sender_is_bot=True)
    await _bot_msg(db, 2, "2026-08-19T10:01:00", sender_is_bot=False)
    await _bot_msg(db, 3, "2026-08-19T10:02:00", sender_is_bot=True)
    await _bot_msg(db, 4, "2026-08-19T10:03:00", sender_is_bot=True)

    assert await store.bot_streak(db, -100) == 2


async def test_our_own_replies_count_as_bot_messages(db):
    await _seed_user(db)
    await store.save_message(
        db, chat_id=-100, message_id=1, user_id=1, ts="2026-08-19T10:00:00", text="x",
        media_kind=None, file_id=None, reply_to=None, is_bot=True,
    )

    assert await store.bot_streak(db, -100) == 1


async def test_an_edit_updates_the_stored_text(db):
    await _seed_user(db)
    await store.save_message(
        db, chat_id=-100, message_id=5, user_id=1, ts="2026-08-19T10:00:00",
        text="оригінал", media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )

    assert await store.update_message_text(db, -100, 5, "виправлено") is True

    rows = await store.recent_messages(db, -100, limit=5)
    assert rows[0]["text"] == "виправлено"


async def test_editing_a_message_we_never_saw_changes_nothing(db):
    assert await store.update_message_text(db, -100, 999, "щось") is False


async def test_forgetting_a_chat_erases_every_trace(db):
    await _seed_user(db)
    await store.save_message(
        db, chat_id=-100, message_id=1, user_id=1, ts="2026-08-19T10:00:00",
        text="щось", media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )
    await store.record_usage(
        db, chat_id=-100, purpose="reply", model="m", prompt_tok=1, cached_tok=0,
        visible_tok=1, thought_tok=0, latency_ms=1, cost_usd=0.0,
    )

    removed = await store.forget_chat(db, -100)

    assert removed["messages"] == 1
    assert await store.recent_messages(db, -100, limit=10) == []
    async with db.execute("SELECT COUNT(*) FROM usage WHERE chat_id = -100") as cur:
        assert (await cur.fetchone())[0] == 0


async def test_a_username_is_remembered(db):
    await store.upsert_user(
        db,
        chat_id=-100,
        user_id=7,
        display_name="Віталій Нижник",
        alias="віталік",
        username="nailsad_eleos",
    )

    names = await store.user_names(db, -100, [7])

    assert names[7] == ("nailsad_eleos", "Віталій Нижник")


async def test_a_user_without_a_username_is_still_returned(db):
    await store.upsert_user(
        db, chat_id=-100, user_id=8, display_name="Хтось", alias="хтось"
    )

    names = await store.user_names(db, -100, [8])

    assert names[8] == (None, "Хтось")


async def test_losing_a_username_does_not_wipe_the_stored_one(db):
    """Telegram omits the field for users who have none, and a later update that omits it
    must not erase what an earlier one recorded."""
    await store.upsert_user(
        db, chat_id=-100, user_id=9, display_name="Хто", alias="хто", username="hto"
    )
    await store.upsert_user(db, chat_id=-100, user_id=9, display_name="Хто", alias="хто")

    names = await store.user_names(db, -100, [9])

    assert names[9][0] == "hto"


async def test_asking_for_nobody_returns_nothing(db):
    assert await store.user_names(db, -100, []) == {}


async def _said(db, chat_id, user_id, ts, message_id, *, sender_is_bot=False):
    await store.save_message(
        db,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        ts=ts,
        text="привіт",
        media_kind=None,
        file_id=None,
        reply_to=None,
        is_bot=sender_is_bot,
        sender_is_bot=sender_is_bot,
    )


async def test_only_people_who_spoke_inside_the_window_are_candidates(db):
    await _said(db, -100, 1, "2026-08-19T10:00:00+00:00", 1)
    await _said(db, -100, 2, "2026-07-01T10:00:00+00:00", 2)

    ids = await store.active_user_ids(db, -100, "2026-08-01T00:00:00+00:00")

    assert ids == [1]


async def test_bots_are_not_candidates(db):
    await _said(db, -100, 1, "2026-08-19T10:00:00+00:00", 1)
    await _said(db, -100, 99, "2026-08-19T10:00:00+00:00", 2, sender_is_bot=True)

    ids = await store.active_user_ids(db, -100, "2026-08-01T00:00:00+00:00")

    assert ids == [1]


async def test_recording_a_winner_returns_that_winner(db):
    won = await store.pidor_record(db, -100, "2026-08-19", 7, "2026-08-19T09:00:00+00:00")

    assert won == 7
    assert await store.pidor_winner(db, -100, "2026-08-19") == 7


async def test_a_second_roll_on_the_same_day_loses_to_the_first(db):
    await store.pidor_record(db, -100, "2026-08-19", 7, "2026-08-19T09:00:00+00:00")

    won = await store.pidor_record(db, -100, "2026-08-19", 8, "2026-08-19T09:00:01+00:00")

    assert won == 7


async def test_two_simultaneous_rolls_produce_one_winner(db):
    import asyncio

    results = await asyncio.gather(
        store.pidor_record(db, -100, "2026-08-19", 7, "2026-08-19T09:00:00+00:00"),
        store.pidor_record(db, -100, "2026-08-19", 8, "2026-08-19T09:00:00+00:00"),
    )

    assert results[0] == results[1]


async def test_nobody_has_won_a_day_that_never_happened(db):
    assert await store.pidor_winner(db, -100, "2026-08-18") is None


async def test_counts_are_ordered_by_wins(db):
    for day, user_id in (("2026-08-17", 7), ("2026-08-18", 8), ("2026-08-19", 8)):
        await store.pidor_record(db, -100, day, user_id, f"{day}T09:00:00+00:00")

    assert await store.pidor_counts(db, -100) == [(8, 2), (7, 1)]


async def test_counts_can_be_limited_to_a_year(db):
    for day, user_id in (("2025-12-31", 7), ("2026-08-19", 8)):
        await store.pidor_record(db, -100, day, user_id, f"{day}T09:00:00+00:00")

    assert await store.pidor_counts(db, -100, since_day="2026-01-01") == [(8, 1)]


async def test_forgetting_a_chat_forgets_its_game(db):
    await store.pidor_record(db, -100, "2026-08-19", 7, "2026-08-19T09:00:00+00:00")

    await store.forget_chat(db, -100)

    assert await store.pidor_winner(db, -100, "2026-08-19") is None


async def test_a_days_figures_are_kept_and_read_back(db):
    await store.pidrahuika_save(db, "2026-08-19", "2026-08-19T09:00:00+00:00", {"killed": 1})

    assert await store.pidrahuika_payload(db, "2026-08-19") == {"killed": 1}


async def test_saving_the_same_day_twice_overwrites(db):
    await store.pidrahuika_save(db, "2026-08-19", "2026-08-19T09:00:00+00:00", {"killed": 1})
    await store.pidrahuika_save(db, "2026-08-19", "2026-08-19T10:00:00+00:00", {"killed": 2})

    assert await store.pidrahuika_payload(db, "2026-08-19") == {"killed": 2}


async def test_a_day_that_was_never_saved_reads_as_nothing(db):
    assert await store.pidrahuika_payload(db, "1999-01-01") is None


async def test_posting_is_recorded_per_chat_and_day(db):
    assert await store.pidrahuika_posted(db, -100, "2026-08-19") is False

    await store.pidrahuika_mark(db, -100, "2026-08-19")

    assert await store.pidrahuika_posted(db, -100, "2026-08-19") is True
    assert await store.pidrahuika_posted(db, -200, "2026-08-19") is False


async def test_forgetting_a_chat_forgets_that_it_was_posted_to(db):
    await store.pidrahuika_mark(db, -100, "2026-08-19")

    await store.forget_chat(db, -100)

    assert await store.pidrahuika_posted(db, -100, "2026-08-19") is False


async def test_forgetting_a_chat_keeps_the_figures_themselves(db):
    """The killboard's numbers are not the chat's data — they are the same for everybody,
    and losing them would break tomorrow's delta for every other chat."""
    await store.pidrahuika_save(db, "2026-08-19", "2026-08-19T09:00:00+00:00", {"killed": 1})

    await store.forget_chat(db, -100)

    assert await store.pidrahuika_payload(db, "2026-08-19") is not None


async def test_a_bot_with_pre_migration_messages_is_not_a_candidate(db):
    """`sender_is_bot` arrived by migration with DEFAULT 0, so every message a bot sent
    before it landed reads as human. One such row was enough to put гряг itself into the
    pool: the live database had ten."""
    await _said(db, -100, 1, "2026-08-19T10:00:00+00:00", 1)
    await _said(db, -100, 99, "2026-08-19T10:00:00+00:00", 2)  # the stale row
    await _said(db, -100, 99, "2026-08-19T11:00:00+00:00", 3, sender_is_bot=True)

    ids = await store.active_user_ids(db, -100, "2026-08-01T00:00:00+00:00")

    assert ids == [1]


async def test_the_bots_own_messages_do_not_empty_the_pool(db):
    """gryag stores its own lines with user_id NULL, and `x NOT IN (… NULL …)` is NULL
    for every x — which excluded everybody, not just the bots."""
    await _said(db, -100, 1, "2026-08-19T10:00:00+00:00", 1)
    await store.save_message(
        db,
        chat_id=-100,
        message_id=2,
        user_id=None,
        ts="2026-08-19T10:01:00+00:00",
        text="я щось сказав",
        media_kind=None,
        file_id=None,
        reply_to=None,
        is_bot=True,
    )

    assert await store.active_user_ids(db, -100, "2026-08-01T00:00:00+00:00") == [1]


async def _seed_message(db, message_id=1, user_id=1, ts="2026-08-19T10:00:00+00:00",
                        text="msg", media_kind=None, is_bot=False):
    await store.save_message(
        db,
        chat_id=-100,
        message_id=message_id,
        user_id=user_id,
        ts=ts,
        text=text,
        media_kind=media_kind,
        file_id=None,
        reply_to=None,
        is_bot=is_bot,
    )


async def test_a_reaction_that_was_added_starts_at_one(db):
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["😁"], removed=[], ts="2026-08-19T10:00:00+00:00"
    )

    assert await store.reactions_for(db, -100, 7) == [("😁", 1)]


async def test_two_people_reacting_with_the_same_emoji_count_twice(db):
    for _ in range(2):
        await store.apply_reaction(
            db, chat_id=-100, message_id=7, added=["😁"], removed=[],
            ts="2026-08-19T10:00:00+00:00",
        )

    assert await store.reactions_for(db, -100, 7) == [("😁", 2)]


async def test_taking_a_reaction_back_to_zero_removes_the_row(db):
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["😁"], removed=[], ts="2026-08-19T10:00:00+00:00"
    )

    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=[], removed=["😁"], ts="2026-08-19T10:01:00+00:00"
    )

    assert await store.reactions_for(db, -100, 7) == []


async def test_removing_a_reaction_that_was_never_recorded_does_not_go_negative(db):
    """Reaction updates are not replayed across downtime, so the bot regularly sees a
    removal for something it never saw added."""
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=[], removed=["❤"], ts="2026-08-19T10:00:00+00:00"
    )

    assert await store.reactions_for(db, -100, 7) == []


async def test_swapping_one_reaction_for_another_moves_the_count(db):
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["😁"], removed=[], ts="2026-08-19T10:00:00+00:00"
    )

    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["❤"], removed=["😁"],
        ts="2026-08-19T10:01:00+00:00",
    )

    assert await store.reactions_for(db, -100, 7) == [("❤", 1)]


async def test_the_importer_sets_a_count_absolutely(db):
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["😁"], removed=[], ts="2026-08-19T10:00:00+00:00"
    )

    await store.set_reaction_count(
        db, chat_id=-100, message_id=7, emoji="😁", count=12, ts="2026-08-19T10:02:00+00:00"
    )

    assert await store.reactions_for(db, -100, 7) == [("😁", 12)]


async def test_an_event_is_stored_with_its_payload(db):
    await store.save_event(
        db, chat_id=-100, message_id=3, ts="2026-08-19T10:00:00+00:00",
        action="title", actor_id=1, payload={"title": "чат матсурі"},
    )

    events = await store.events_between(db, -100, "2026-08-19T00:00:00+00:00", "2026-08-20T00:00:00+00:00")

    assert [(e["action"], e["payload"]["title"]) for e in events] == [("title", "чат матсурі")]


async def test_events_outside_the_window_are_not_returned(db):
    await store.save_event(
        db, chat_id=-100, message_id=3, ts="2026-08-17T10:00:00+00:00",
        action="pin", actor_id=1, payload={},
    )

    events = await store.events_between(db, -100, "2026-08-19T00:00:00+00:00", "2026-08-20T00:00:00+00:00")

    assert events == []


async def test_an_event_carries_the_actors_alias(db):
    await _seed_user(db, user_id=1, alias="oleh")
    await store.save_event(
        db, chat_id=-100, message_id=3, ts="2026-08-19T10:00:00+00:00",
        action="pin", actor_id=1, payload={"message_id": 2},
    )

    events = await store.events_between(db, -100, "2026-08-19T00:00:00+00:00", "2026-08-20T00:00:00+00:00")

    # The whole name, not the eight-character prompt alias: this is read by people.
    assert events[0]["alias"] == "User 1"


async def test_storing_the_same_event_twice_does_not_duplicate(db):
    for _ in range(2):
        await store.save_event(
            db, chat_id=-100, message_id=3, ts="2026-08-19T10:00:00+00:00",
            action="pin", actor_id=1, payload={},
        )

    events = await store.events_between(db, -100, "2026-08-19T00:00:00+00:00", "2026-08-20T00:00:00+00:00")

    assert len(events) == 1


async def test_the_first_lore_version_is_one(db):
    version = await store.save_lore(
        db, chat_id=-100, text="# лор", model="m", tokens=2,
        window_start="2026-08-17T00:00:00+00:00", window_end="2026-08-19T00:00:00+00:00",
        created_at="2026-08-19T05:00:00+00:00",
    )

    assert version == 1


async def test_every_lore_version_is_kept_and_the_latest_is_returned(db):
    for n, text in enumerate(("перша", "друга"), start=1):
        await store.save_lore(
            db, chat_id=-100, text=text, model="m", tokens=1,
            window_start="2026-08-17T00:00:00+00:00", window_end=f"2026-08-{n + 18}T00:00:00+00:00",
            created_at=f"2026-08-{n + 18}T05:00:00+00:00",
        )

    latest = await store.latest_lore(db, -100)

    assert latest["version"] == 2
    assert latest["text"] == "друга"
    assert latest["window_end"] == "2026-08-20T00:00:00+00:00"
    async with db.execute("SELECT COUNT(*) FROM lore WHERE chat_id = ?", (-100,)) as cur:
        assert (await cur.fetchone())[0] == 2


async def test_a_chat_with_no_lore_has_none(db):
    assert await store.latest_lore(db, -100) is None


async def test_when_the_lore_was_last_sent_survives_a_restart(db):
    await store.mark_lore_sent(db, -100, "2026-08-19T10:00:00+00:00")

    assert await store.lore_sent_at(db, -100) == "2026-08-19T10:00:00+00:00"


async def test_a_chat_that_never_asked_for_the_lore_has_no_timestamp(db):
    assert await store.lore_sent_at(db, -100) is None


async def test_marking_the_lore_sent_does_not_clear_a_mute(db):
    """chat_state is one row per chat and four different features write to it."""
    await store.set_mute(db, -100, "2999-01-01T00:00:00+00:00")

    await store.mark_lore_sent(db, -100, "2026-08-19T10:00:00+00:00")

    assert await store.muted_until(db, -100, "2026-08-19T10:00:00+00:00") is not None


async def test_messages_between_spans_days_and_excludes_the_far_end(db):
    await _seed_user(db)
    for n, ts in enumerate(
        ("2026-08-18T23:00:00+00:00", "2026-08-19T10:00:00+00:00", "2026-08-20T10:00:00+00:00")
    ):
        await _seed_message(db, message_id=n, ts=ts, text=f"msg {n}")

    rows = await store.messages_between(
        db, -100, "2026-08-18T00:00:00+00:00", "2026-08-20T00:00:00+00:00"
    )

    assert [r["text"] for r in rows] == ["msg 0", "msg 1"]
    assert rows[0]["alias"] == "oleh"


async def test_the_oldest_message_is_where_a_first_lore_window_starts(db):
    await _seed_user(db)
    await _seed_message(db, message_id=2, ts="2026-08-19T10:00:00+00:00")
    await _seed_message(db, message_id=1, ts="2026-08-18T10:00:00+00:00")

    assert await store.oldest_message_ts(db, -100) == "2026-08-18T10:00:00+00:00"


async def test_a_chat_with_no_messages_has_no_oldest(db):
    assert await store.oldest_message_ts(db, -100) is None


async def test_an_edit_is_counted_not_just_applied(db):
    await _seed_user(db)
    await _seed_message(db, message_id=1, text="before")

    await store.update_message_text(db, -100, 1, "after")
    await store.update_message_text(db, -100, 1, "after again")

    async with db.execute(
        "SELECT text, edits FROM messages WHERE chat_id = ? AND message_id = ?", (-100, 1)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "after again"
    assert row[1] == 2


async def test_forgetting_a_chat_forgets_its_reactions_events_and_lore(db):
    await store.apply_reaction(
        db, chat_id=-100, message_id=7, added=["😁"], removed=[], ts="2026-08-19T10:00:00+00:00"
    )
    await store.save_event(
        db, chat_id=-100, message_id=3, ts="2026-08-19T10:00:00+00:00",
        action="pin", actor_id=1, payload={},
    )
    await store.save_lore(
        db, chat_id=-100, text="# лор", model="m", tokens=2,
        window_start="2026-08-17T00:00:00+00:00", window_end="2026-08-19T00:00:00+00:00",
        created_at="2026-08-19T05:00:00+00:00",
    )

    removed = await store.forget_chat(db, -100)

    assert removed["reactions"] == 1
    assert removed["events"] == 1
    assert removed["lore"] == 1
    assert await store.latest_lore(db, -100) is None
