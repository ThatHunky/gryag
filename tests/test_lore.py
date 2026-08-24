import json
import types as pytypes
from datetime import datetime, timedelta, timezone

from gryag import admin, config, context, lore, store

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



class FakeUsage:
    prompt_token_count = 60000
    cached_content_token_count = None
    candidates_token_count = 900
    thoughts_token_count = 4000


class FakeResponse:
    def __init__(self, text, blocked=False):
        self.text = text
        self.usage_metadata = FakeUsage()
        self.candidates = None if blocked else [object()]
        self.prompt_feedback = (
            pytypes.SimpleNamespace(block_reason="PROHIBITED_CONTENT") if blocked else None
        )


class FakeClient:
    """Replies in order; a `None` entry stands for a chunk Google refused outright."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.aio = pytypes.SimpleNamespace(models=self)

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        nxt = self._responses.pop(0) if self._responses else ""
        if nxt is None:
            return FakeResponse("", blocked=True)
        return FakeResponse(nxt)


def beats_payload(*whats):
    return json.dumps(
        {"beats": [{"who": ["oleh"], "what": w, "quote": "цитата", "kind": "joke"} for w in whats]}
    )


NOW = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)


def test_the_first_window_starts_at_the_oldest_message():
    window = lore.pick_window(None, "2026-08-19T10:00:00+00:00", NOW)

    assert window == ("2026-08-19T10:00:00+00:00", "2026-08-20T05:00:00+00:00")


def test_a_later_window_starts_where_the_last_one_stopped():
    previous = {"window_end": "2026-08-19T05:00:00+00:00"}

    window = lore.pick_window(previous, "2026-08-11T00:00:00+00:00", NOW)

    assert window[0] == "2026-08-19T05:00:00+00:00"


def test_a_missed_run_is_capped_at_four_days():
    """A fortnight of this chat is a 500,000-token harvest, and four days is already more
    than one rewrite can absorb."""
    previous = {"window_end": "2026-08-01T05:00:00+00:00"}

    start, end = lore.pick_window(previous, "2026-07-01T00:00:00+00:00", NOW)

    assert start == (NOW - timedelta(days=lore.MAX_WINDOW_DAYS)).isoformat(timespec="seconds")
    assert end == NOW.isoformat(timespec="seconds")


def test_a_chat_with_nothing_stored_has_no_window():
    assert lore.pick_window(None, None, NOW) is None


def test_a_window_that_ends_before_it_starts_is_no_window():
    """A previous version written after a clock skew, or a re-run inside the same second."""
    previous = {"window_end": "2026-08-21T00:00:00+00:00"}

    assert lore.pick_window(previous, "2026-08-11T00:00:00+00:00", NOW) is None


async def test_the_harvest_returns_the_beats_it_was_given(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)
    client = FakeClient(beats_payload("посварилися через дистрибутиви"))

    beats = await lore.harvest(db, client, CHAT, messages, "m", thinking=-1)

    assert [b["what"] for b in beats] == ["посварилися через дистрибутиви"]


async def test_the_harvest_thinks_when_it_is_told_to(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)
    client = FakeClient(beats_payload("щось"))

    await lore.harvest(db, client, CHAT, messages, "m", thinking=-1)

    assert client.calls[0]["config"].thinking_config.thinking_budget == -1


async def test_no_more_than_eight_beats_survive_one_chunk(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)
    client = FakeClient(beats_payload(*[f"подія {n}" for n in range(20)]))

    beats = await lore.harvest(db, client, CHAT, messages, "m", thinking=-1)

    assert len(beats) == lore.MAX_BEATS


async def test_one_refused_chunk_costs_only_that_chunk(db):
    await store.upsert_user(db, chat_id=CHAT, user_id=1, display_name="Олег", alias="oleh")
    filler = int(lore.CHUNK_TOKENS * context.CHARS_PER_TOKEN / 6) + 50
    for n, text in enumerate(("перший " * filler, "другий " * filler, "третій " * filler)):
        await store.save_message(
            db, chat_id=CHAT, message_id=100 + n, user_id=1,
            ts=f"2026-08-18T0{n}:00:00+00:00", text=text, media_kind=None,
            file_id=None, reply_to=None, is_bot=False,
        )
    messages = await store.messages_between(db, CHAT, START, END)
    client = FakeClient(beats_payload("перша"), None, beats_payload("третя"))

    beats = await lore.harvest(db, client, CHAT, messages, "m", thinking=-1)

    assert [b["what"] for b in beats] == ["перша", "третя"]


async def test_a_harvest_where_every_chunk_refuses_is_a_failure_not_an_empty_list(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)

    assert await lore.harvest(db, FakeClient(None), CHAT, messages, "m", thinking=-1) is None


async def test_unparseable_output_does_not_raise(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)

    assert await lore.harvest(db, FakeClient("not json"), CHAT, messages, "m", thinking=-1) is None


async def test_the_harvest_records_what_it_spent_under_its_own_purpose(db):
    await seed_window(db)
    messages = await store.messages_between(db, CHAT, START, END)

    await lore.harvest(
        db, FakeClient(beats_payload("щось")), CHAT, messages, "gemini-3.7-flash", thinking=-1
    )

    async with db.execute("SELECT purpose, model, thought_tok, cost_usd FROM usage") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]
    assert rows[0][0] == "lore"
    assert rows[0][1] == "gemini-3.7-flash"
    assert rows[0][2] == 4000
    assert rows[0][3] > 0


def test_beats_render_with_their_quotes_intact():
    beats = [{"who": ["oleh", "maria"], "what": "посварилися", "quote": "ти дурень", "kind": "drama"}]

    rendered = lore.render_beats(beats)

    assert "oleh, maria" in rendered
    assert "посварилися" in rendered
    assert "ти дурень" in rendered
    assert "drama" in rendered


def test_a_beat_without_a_quote_renders_without_an_empty_one():
    rendered = lore.render_beats([{"who": ["oleh"], "what": "щось", "kind": "event"}])

    assert "«»" not in rendered


async def enabled(db):
    await admin.enable_chat(db, CHAT, "матсурі")


async def test_a_first_run_writes_version_one(db):
    await enabled(db)
    await seed_window(db)
    client = FakeClient(beats_payload("посварилися"), "# Лор\n\nТут щось сталося.")

    assert await lore.generate(db, client, CHAT, now=NOW) is True

    latest = await store.latest_lore(db, CHAT)
    assert latest["version"] == 1
    assert latest["text"] == "# Лор\n\nТут щось сталося."
    assert latest["window_end"] == NOW.isoformat(timespec="seconds")


async def test_the_rewrite_is_shown_the_current_document_the_beats_and_the_figures(db):
    await enabled(db)
    await seed_window(db)
    await store.replace_facts(db, CHAT, "2026-08-18", [(1, "з Тернополя")])
    await store.save_lore(
        db, chat_id=CHAT, text="СТАРИЙ ЛОР", model="m", tokens=2,
        window_start=BEFORE, window_end=START, created_at="2026-08-18T05:00:00+00:00",
    )
    client = FakeClient(beats_payload("посварилися через дистрибутиви"), "# новий")

    await lore.generate(db, client, CHAT, now=NOW, force=True)

    sent = client.calls[-1]["contents"]
    assert "СТАРИЙ ЛОР" in sent
    assert "посварилися через дистрибутиви" in sent
    assert "Повідомлень за період" in sent
    assert "з Тернополя" in sent
    assert "матсурі" in sent


async def test_the_document_is_clamped_to_the_configured_size(db):
    await enabled(db)
    await seed_window(db)
    await config.set(db, "lore_max_chars", "100", chat_id=CHAT)
    client = FakeClient(beats_payload("щось"), "я" * 5000)

    await lore.generate(db, client, CHAT, now=NOW)

    assert len((await store.latest_lore(db, CHAT))["text"]) <= 100


async def test_a_refused_rewrite_leaves_the_previous_version_standing(db):
    await enabled(db)
    await seed_window(db)
    await store.save_lore(
        db, chat_id=CHAT, text="ЦЕ МАЄ ВИЖИТИ", model="m", tokens=2,
        window_start=BEFORE, window_end=START, created_at="2026-08-18T05:00:00+00:00",
    )
    client = FakeClient(beats_payload("щось"), None)

    assert await lore.generate(db, client, CHAT, now=NOW, force=True) is False

    latest = await store.latest_lore(db, CHAT)
    assert latest["version"] == 1
    assert latest["text"] == "ЦЕ МАЄ ВИЖИТИ"


async def test_an_empty_rewrite_is_a_failure_not_an_empty_document(db):
    await enabled(db)
    await seed_window(db)
    client = FakeClient(beats_payload("щось"), "")

    assert await lore.generate(db, client, CHAT, now=NOW) is False
    assert await store.latest_lore(db, CHAT) is None


async def test_a_harvest_that_refuses_entirely_never_reaches_the_rewrite(db):
    await enabled(db)
    await seed_window(db)
    client = FakeClient(None)

    assert await lore.generate(db, client, CHAT, now=NOW) is False
    assert len(client.calls) == 1
    assert await store.latest_lore(db, CHAT) is None


async def test_a_chat_with_nothing_in_the_window_costs_nothing(db):
    await enabled(db)
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW) is False
    assert client.calls == []


async def test_the_interval_is_respected_without_spending_anything(db):
    await enabled(db)
    await seed_window(db)
    await store.save_lore(
        db, chat_id=CHAT, text="учорашній", model="m", tokens=2,
        window_start=BEFORE, window_end=START,
        created_at=(NOW - timedelta(hours=6)).isoformat(timespec="seconds"),
    )
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW) is False
    assert client.calls == []


async def test_the_interval_having_passed_lets_a_run_through(db):
    await enabled(db)
    await seed_window(db)
    await store.save_lore(
        db, chat_id=CHAT, text="позавчорашній", model="m", tokens=2,
        window_start=BEFORE, window_end=START,
        created_at=(NOW - timedelta(days=3)).isoformat(timespec="seconds"),
    )
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW) is True


async def test_the_button_bypasses_the_interval(db):
    """The timer paces the cost; the admin has already decided to pay it."""
    await enabled(db)
    await seed_window(db)
    await store.save_lore(
        db, chat_id=CHAT, text="щойно", model="m", tokens=2,
        window_start=BEFORE, window_end=START,
        created_at=(NOW - timedelta(hours=1)).isoformat(timespec="seconds"),
    )
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW, force=True) is True


async def test_a_chat_with_the_lore_switched_off_is_skipped(db):
    await enabled(db)
    await seed_window(db)
    await config.set(db, "lore_enabled", "0", chat_id=CHAT)
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW) is False
    assert client.calls == []


async def test_switching_it_off_does_not_block_the_button(db):
    await enabled(db)
    await seed_window(db)
    await config.set(db, "lore_enabled", "0", chat_id=CHAT)
    client = FakeClient(beats_payload("щось"), "# новий")

    assert await lore.generate(db, client, CHAT, now=NOW, force=True) is True


async def test_thinking_comes_from_the_menu_knob(db):
    await enabled(db)
    await seed_window(db)
    await config.set(db, "lore_thinking", "0", chat_id=CHAT)
    client = FakeClient(beats_payload("щось"), "# новий")

    await lore.generate(db, client, CHAT, now=NOW)

    assert all(c["config"].thinking_config.thinking_budget == 0 for c in client.calls)


async def test_both_stages_are_billed_to_the_lore(db):
    await enabled(db)
    await seed_window(db)
    client = FakeClient(beats_payload("щось"), "# новий")

    await lore.generate(db, client, CHAT, now=NOW)

    async with db.execute("SELECT COUNT(*), SUM(cost_usd) FROM usage WHERE purpose = 'lore'") as cur:
        calls, cost = await cur.fetchone()
    assert calls == 2
    assert cost > 0


async def test_a_run_covers_every_enabled_chat_and_nothing_else(db):
    await enabled(db)
    await seed_window(db)
    await db.execute("INSERT INTO chats (chat_id, enabled) VALUES (-200, 0)")
    await db.commit()
    client = FakeClient(beats_payload("щось"), "# новий")

    await lore.run(db, client, now=NOW)

    assert await store.latest_lore(db, CHAT) is not None
    assert await store.latest_lore(db, -200) is None


async def test_a_run_that_fails_in_one_chat_still_reaches_the_next(db):
    """One chat's refusal is not a reason for the other to go a week without a rewrite."""
    await enabled(db)
    await seed_window(db)
    await admin.enable_chat(db, -200, "інший")
    await store.save_message(
        db, chat_id=-200, message_id=1, user_id=3, ts="2026-08-19T10:00:00+00:00",
        text="привіт", media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )
    # `chats.chat_id` is an INTEGER PRIMARY KEY, so it is the rowid and -200 is visited
    # first. The refusal is queued for whoever goes first, and the point of the test is
    # that whoever goes second is still served.
    client = FakeClient(None, beats_payload("щось"), "# новий")

    await lore.run(db, client, now=NOW)

    assert (await store.latest_lore(db, -200)) is None
    assert (await store.latest_lore(db, CHAT)) is not None
