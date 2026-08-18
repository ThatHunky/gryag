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
