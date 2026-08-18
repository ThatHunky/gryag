import types as pytypes

from gryag import digest, store


class FakeUsage:
    prompt_token_count = 5000
    cached_content_token_count = None
    candidates_token_count = 300
    thoughts_token_count = None


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
        self.calls.append({"model": model, "contents": contents})
        nxt = self._responses.pop(0) if self._responses else self._responses
        if nxt is None:
            return FakeResponse("", blocked=True)
        return FakeResponse(nxt)


async def seed_day(db, chat_id=-100, day="2026-08-18"):
    await store.upsert_user(db, chat_id=chat_id, user_id=1, display_name="Олег", alias="oleh")
    await store.upsert_user(db, chat_id=chat_id, user_id=2, display_name="Марія", alias="maria")
    for n, (user_id, text) in enumerate(
        [(1, "я з Тернополя"), (2, "а я на NixOS сиджу"), (1, "лінух це біль")]
    ):
        await store.save_message(
            db, chat_id=chat_id, message_id=n, user_id=user_id,
            ts=f"{day}T1{n}:00:00", text=text, media_kind=None, file_id=None,
            reply_to=None, is_bot=False,
        )


def day_payload(summary="Говорили про дистрибутиви", facts=None):
    import json
    return json.dumps({
        "summary": summary,
        "facts": facts if facts is not None else [
            {"who": "oleh", "fact": "з Тернополя"},
            {"who": "maria", "fact": "сидить на NixOS"},
        ],
    })


async def test_yesterday_is_the_day_before_today():
    import datetime
    assert digest.yesterday(datetime.date(2026, 8, 19)) == "2026-08-18"


async def test_summarising_a_day_stores_the_summary(db):
    await seed_day(db)
    client = FakeClient(day_payload())

    assert await digest.summarise_day(db, client, -100, "2026-08-18", "m") is True
    assert await store.latest_summary(db, -100, "day") == "Говорили про дистрибутиви"


async def test_facts_are_mapped_from_alias_back_to_user_id(db):
    await seed_day(db)

    await digest.summarise_day(db, FakeClient(day_payload()), -100, "2026-08-18", "m")

    facts = await store.facts_for_users(db, -100, [1, 2])
    assert sorted(facts) == [("maria", "сидить на NixOS"), ("oleh", "з Тернополя")]


async def test_facts_about_an_unknown_alias_are_dropped(db):
    await seed_day(db)
    payload = day_payload(facts=[{"who": "привид", "fact": "не існує"}])

    await digest.summarise_day(db, FakeClient(payload), -100, "2026-08-18", "m")

    assert await store.facts_for_users(db, -100, [1, 2]) == []


async def test_rerunning_a_day_does_not_duplicate_facts(db):
    await seed_day(db)
    for _ in range(2):
        await digest.summarise_day(db, FakeClient(day_payload()), -100, "2026-08-18", "m")

    assert len(await store.facts_for_users(db, -100, [1, 2])) == 2


async def test_an_empty_day_is_skipped(db):
    assert await digest.summarise_day(db, FakeClient(), -100, "2026-08-18", "m") is False


async def test_unparseable_output_fails_without_raising(db):
    await seed_day(db)

    assert await digest.summarise_day(db, FakeClient("not json"), -100, "2026-08-18", "m") is False


async def test_the_day_summary_is_capped(db):
    await seed_day(db)
    client = FakeClient(day_payload(summary="я" * 5000))

    await digest.summarise_day(db, client, -100, "2026-08-18", "m")

    summary = await store.latest_summary(db, -100, "day")
    assert len(summary) <= digest.DAY_SUMMARY_TOKENS * 2.5


async def test_the_week_is_built_from_daily_summaries_not_raw_messages(db):
    await seed_day(db)
    for day in ("2026-08-16", "2026-08-17", "2026-08-18"):
        await store.save_summary(db, chat_id=-100, kind="day", period_start=day,
                                 period_end=day, text=f"день {day}", tokens=5)
    client = FakeClient('{"summary": "тиждень про лінукс"}')

    assert await digest.rebuild_week(db, client, -100, "m") is True
    assert await store.latest_summary(db, -100, "week") == "тиждень про лінукс"
    sent = client.calls[0]["contents"]
    assert "день 2026-08-16" in sent
    assert "я з Тернополя" not in sent


async def test_the_digest_records_what_it_spent(db):
    await seed_day(db)

    await digest.summarise_day(db, FakeClient(day_payload()), -100, "2026-08-18", "gemini-2.5-flash-lite")

    async with db.execute("SELECT purpose, cost_usd FROM usage") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]
    assert rows[0][0] == "digest"
    assert rows[0][1] > 0


async def test_run_covers_every_enabled_chat(db):
    await seed_day(db)
    await db.execute("INSERT INTO chats (chat_id, enabled) VALUES (-100, 1)")
    await db.execute("INSERT INTO chats (chat_id, enabled) VALUES (-200, 0)")
    await db.commit()
    client = FakeClient(day_payload(), '{"summary": "тиждень"}')

    await digest.run(db, client, day="2026-08-18")

    assert await store.latest_summary(db, -100, "day") is not None
    assert await store.latest_summary(db, -200, "day") is None


async def test_a_day_is_split_into_chunks_that_never_break_a_message(db):
    messages = [
        {"text": "я" * 400, "media_kind": None, "is_bot": False, "alias": "oleh"}
        for _ in range(10)
    ]

    chunks = digest.chunk_transcript(messages, max_tokens=500)

    assert len(chunks) > 1
    assert all(digest.context.estimate_tokens(c) <= 700 for c in chunks)
    assert sum(c.count("oleh:") for c in chunks) == 10


async def test_one_refused_chunk_does_not_lose_the_whole_day(db):
    """Google refuses whole prompts with PROHIBITED_CONTENT and no candidates. That
    filter is not configurable, so a bad stretch must cost only that stretch."""
    await seed_day(db)
    # Each of these must exceed CHUNK_TOKENS on its own, so the day splits into exactly
    # three chunks and the middle one can be the refused stretch.
    filler = int(digest.CHUNK_TOKENS * digest.context.CHARS_PER_TOKEN / 6) + 50
    long_messages = [
        (1, "текст " * filler), (2, "інший " * filler), (1, "третій " * filler),
    ]
    for n, (user_id, text) in enumerate(long_messages, start=10):
        await store.save_message(
            db, chat_id=-100, message_id=n, user_id=user_id, ts=f"2026-08-18T2{n-10}:00:00",
            text=text, media_kind=None, file_id=None, reply_to=None, is_bot=False,
        )
    client = FakeClient(day_payload("перша частина"), None, day_payload("третя частина"))

    assert await digest.summarise_day(db, client, -100, "2026-08-18", "m") is True

    summary = await store.latest_summary(db, -100, "day")
    assert "перша частина" in summary
    assert "третя частина" in summary


async def test_a_day_refused_entirely_is_a_failure_not_an_empty_summary(db):
    await seed_day(db)
    client = FakeClient(None)

    assert await digest.summarise_day(db, client, -100, "2026-08-18", "m") is False
    assert await store.latest_summary(db, -100, "day") is None


async def test_an_empty_body_is_a_failure_not_a_blank_summary(db):
    """An empty body was being parsed as {} and stored, and the weekly pass then
    summarised the blank."""
    await seed_day(db)

    assert await digest.summarise_day(db, FakeClient(""), -100, "2026-08-18", "m") is False
    assert await store.latest_summary(db, -100, "day") is None


async def test_duplicate_facts_across_chunks_are_merged(db):
    await seed_day(db)
    same = day_payload(facts=[{"who": "oleh", "fact": "з Тернополя"}])
    client = FakeClient(same, same)

    await digest.summarise_day(db, client, -100, "2026-08-18", "m")

    assert await store.facts_for_users(db, -100, [1, 2]) == [("oleh", "з Тернополя")]
