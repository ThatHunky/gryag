import asyncio
import types as pytypes
from datetime import datetime, timedelta, timezone

from gryag import admin, config, handlers, llm, store
from tests.conftest import FakeMessage


class FakeLlm:
    def __init__(self, text="ага"):
        self.text = text
        self.calls: list[dict] = []

    async def generate(self, client, **kwargs):
        self.calls.append(kwargs)
        return llm.LlmResult(
            text=self.text,
            searched=0,
            prompt_tokens=600,
            cached_tokens=0,
            visible_tokens=10,
            thought_tokens=100,
            latency_ms=1200,
            cost_usd=0.0005,
        )


async def enable_chat(db, chat_id=-100):
    await db.execute(
        "INSERT OR REPLACE INTO chats (chat_id, title, enabled) VALUES (?, ?, 1)",
        (chat_id, "матсурі"),
    )
    await db.commit()


async def test_persists_even_when_it_stays_silent(db, monkeypatch):
    await enable_chat(db)
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="балачки без звертання")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert fake.calls == []
    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["балачки без звертання"]


async def test_answers_when_a_keyword_is_used(db, monkeypatch):
    await enable_chat(db)
    fake = FakeLlm("та лінух то діагноз")
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply == "та лінух то діагноз"
    assert message.replies == ["та лінух то діагноз"]


async def test_stays_silent_in_a_chat_that_was_never_enabled(db, monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert fake.calls == []


async def test_records_usage_for_every_reply(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm().generate)
    message = FakeMessage(text="гряг шо там")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    async with db.execute("SELECT purpose, cost_usd FROM usage") as cur:
        rows = await cur.fetchall()
    assert rows[0][0] == "reply"
    assert rows[0][1] > 0


async def test_stores_its_own_reply_so_the_next_context_contains_it(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm("моя репліка").generate)
    message = FakeMessage(text="гряг шо там")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["гряг шо там", "моя репліка"]
    assert rows[1]["is_bot"] == 1


async def test_a_failed_generation_posts_nothing(db, monkeypatch):
    await enable_chat(db)

    async def failing(client, **kwargs):
        return None

    monkeypatch.setattr(handlers.llm, "generate", failing)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert message.replies == []


async def test_the_daily_cap_silences_the_bot(db, monkeypatch):
    await enable_chat(db)
    await config.set(db, "daily_reply_cap", "1")
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm().generate)

    first = FakeMessage(text="гряг раз", message_id=1)
    await handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    second = FakeMessage(text="гряг два", message_id=2)
    reply = await handlers.handle_message(second, db, client=None, persona="p", bot_id=77)

    assert reply is None


async def test_media_kind_is_detected():
    message = FakeMessage(text="")
    message.photo = [pytypes.SimpleNamespace(file_id="abc")]

    kind, file_id = handlers.media_kind_and_file_id(message)

    assert (kind, file_id) == ("photo", "abc")


async def test_the_reply_quotes_the_message_that_triggered_it(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm("ага").generate)
    message = FakeMessage(text="гряг шо там", message_id=42)

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    rows = await store.recent_messages(db, -100, limit=10)
    bot_row = [r for r in rows if r["is_bot"]][0]
    assert bot_row["reply_to"] == 42


async def test_a_partial_quote_reaches_the_prompt(db, monkeypatch):
    await enable_chat(db)
    fake = FakeLlm("ага")
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    parent = FakeMessage(text="Нікос качався і слухав соні", message_id=1, user_id=77)
    parent.from_user.id = 77
    message = FakeMessage(text="гряг NixOS?", message_id=2, reply_to=parent)
    message.quote = pytypes.SimpleNamespace(text="Нікос")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert "«Нікос»" in fake.calls[0]["user"]


async def test_a_message_from_the_backlog_is_stored_but_not_answered(db, monkeypatch):
    """After downtime Telegram replays up to 24 hours of updates. They must land in the
    database — that hole was a quarter of the chat — without the bot answering an
    argument that ended an hour ago."""
    await enable_chat(db)
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    stale = FakeMessage(
        text="гряг шо там",
        date=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    reply = await handlers.handle_message(stale, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert fake.calls == []
    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["гряг шо там"]


async def test_a_second_message_is_ignored_while_the_first_is_being_answered(db, monkeypatch):
    """Generation takes ~2s; in this chat three people can address the bot inside that
    window. Answering all of them replies to a conversation that has already moved on."""
    await enable_chat(db)
    from gryag import config as cfg

    # Pin the deferral off: this test is about the claim, not about coming back later.
    await cfg.set(db, "deferred_chance", "0", chat_id=-100)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(client, **kwargs):
        started.set()
        await release.wait()
        return llm.LlmResult("повільна", 0, 600, 0, 10, 100, 1200, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", slow)
    first = FakeMessage(text="гряг раз", message_id=1)
    task = asyncio.create_task(
        handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    )
    await started.wait()

    second = FakeMessage(text="гряг два", message_id=2)
    ignored = await handlers.handle_message(second, db, client=None, persona="p", bot_id=77)

    release.set()
    assert await task == "повільна"
    assert ignored is None
    assert second.replies == []


async def test_an_edit_is_followed_but_never_answered(db, monkeypatch):
    """Answering edits would let anyone re-trigger the bot by editing an old message."""
    await enable_chat(db)
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    original = FakeMessage(text="просто балачки", message_id=7)
    await handlers.handle_message(original, db, client=None, persona="p", bot_id=77)

    edited = FakeMessage(text="гряг тепер я тебе кличу", message_id=7)
    applied = await handlers.handle_edit(edited, db)

    assert applied is True
    assert fake.calls == []
    rows = await store.recent_messages(db, -100, limit=5)
    assert rows[0]["text"] == "гряг тепер я тебе кличу"


async def test_a_whitelisted_person_gets_a_picture_instead_of_a_reply(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg, images

    await cfg.set(db, "image_whitelist", "1", chat_id=-100)
    drew: list[dict] = []

    async def fake_draw(client, *, model, prompt, source=None):
        drew.append({"model": model, "prompt": prompt, "source": source})
        return images.ImageResult(b"jpegbytes", "image/jpeg", 8000, 20, 1200)

    monkeypatch.setattr(handlers.images, "generate", fake_draw)
    text_llm = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", text_llm.generate)
    message = FakeMessage(text="гряг намалюй кота у вишиванці", user_id=1)

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert drew[0]["prompt"] == "кота у вишиванці"
    assert text_llm.calls == []
    assert message.photos == [b"jpegbytes"]


async def test_someone_not_on_the_list_gets_words_not_pictures(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg

    await cfg.set(db, "image_whitelist", "999", chat_id=-100)

    async def fake_draw(client, **kwargs):
        raise AssertionError("must not be called")

    monkeypatch.setattr(handlers.images, "generate", fake_draw)
    text_llm = FakeLlm("малюй сам")
    monkeypatch.setattr(handlers.llm, "generate", text_llm.generate)
    message = FakeMessage(text="гряг намалюй кота", user_id=1)

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply == "малюй сам"


async def test_the_bot_can_ban_someone_and_then_ignores_them(db, monkeypatch):
    await enable_chat(db)

    async def generate_with_ban(client, **kwargs):
        await kwargs["tool_handler"]("ban_user", {"minutes": 60, "reason": "спам"})
        return llm.LlmResult("годину тебе не чую", 0, 600, 0, 10, 100, 1200, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", generate_with_ban)
    first = FakeMessage(text="гряг здохни", message_id=1, user_id=5)
    assert await handlers.handle_message(first, db, client=None, persona="p", bot_id=77)

    quiet = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", quiet.generate)
    second = FakeMessage(text="гряг ну шо ти", message_id=2, user_id=5)
    reply = await handlers.handle_message(second, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert quiet.calls == []


async def test_a_banned_person_still_appears_in_the_context(db, monkeypatch):
    """Being ignored is not being erased — the conversation must still read correctly."""
    await enable_chat(db)

    async def generate_with_ban(client, **kwargs):
        await kwargs["tool_handler"]("ban_user", {"minutes": 60, "reason": "спам"})
        return llm.LlmResult("тихо", 0, 600, 0, 10, 100, 1200, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", generate_with_ban)
    await handlers.handle_message(
        FakeMessage(text="гряг здохни", message_id=1, user_id=5), db,
        client=None, persona="p", bot_id=77,
    )
    await handlers.handle_message(
        FakeMessage(text="я все одно пишу", message_id=2, user_id=5), db,
        client=None, persona="p", bot_id=77,
    )

    rows = await store.recent_messages(db, -100, limit=10)
    assert "я все одно пишу" in [r["text"] for r in rows]


async def test_a_ban_is_capped_at_two_days(db):
    from datetime import datetime, timezone

    sender = pytypes.SimpleNamespace(id=5)
    handler = handlers._ban_handler(db, -100, sender)

    await handler("ban_user", {"minutes": 999999})

    until = await store.ban_until(db, -100, 5, datetime.now(timezone.utc).isoformat())
    days = (datetime.fromisoformat(until) - datetime.now(timezone.utc)).days
    assert days <= 2


async def test_a_whole_batch_arriving_at_once_produces_one_reply(db, monkeypatch):
    """Regression: a restart replays the backlog, every message evaluated `busy` as false
    at the same moment, and five replies landed in the same second."""
    await enable_chat(db)
    from gryag import config as cfg

    await cfg.set(db, "deferred_chance", "0", chat_id=-100)
    calls = 0

    async def slow(client, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return llm.LlmResult("одна відповідь", 0, 600, 0, 10, 100, 50, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", slow)
    batch = [FakeMessage(text=f"гряг {n}", message_id=n) for n in range(5)]

    results = await asyncio.gather(*[
        handlers.handle_message(m, db, client=None, persona="p", bot_id=77) for m in batch
    ])

    assert calls == 1
    assert [r for r in results if r] == ["одна відповідь"]


async def test_a_muted_chat_stays_silent_but_keeps_listening(db, monkeypatch):
    await enable_chat(db)
    from datetime import datetime, timedelta, timezone

    await store.set_mute(
        db, -100, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    )
    quiet = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", quiet.generate)

    reply = await handlers.handle_message(
        FakeMessage(text="гряг агов"), db, client=None, persona="p", bot_id=77
    )

    assert reply is None
    assert quiet.calls == []
    rows = await store.recent_messages(db, -100, limit=5)
    assert [r["text"] for r in rows] == ["гряг агов"]


async def test_the_mute_expires(db, monkeypatch):
    await enable_chat(db)
    from datetime import datetime, timedelta, timezone

    await store.set_mute(
        db, -100, (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    )
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm("знову тут").generate)

    reply = await handlers.handle_message(
        FakeMessage(text="гряг агов"), db, client=None, persona="p", bot_id=77
    )

    assert reply == "знову тут"


async def test_the_persona_can_be_swapped_without_a_restart(db, monkeypatch):
    await enable_chat(db)
    seen = []

    async def capture(client, **kwargs):
        seen.append(kwargs["system"])
        return llm.LlmResult("ага", 0, 100, 0, 5, 10, 100, 0.0001)

    monkeypatch.setattr(handlers.llm, "generate", capture)
    box = {"text": "перша версія"}

    await handlers.handle_message(
        FakeMessage(text="гряг раз", message_id=1), db, client=None, persona=box, bot_id=77
    )
    box["text"] = "друга версія"
    await handlers.handle_message(
        FakeMessage(text="гряг два", message_id=2), db, client=None, persona=box, bot_id=77
    )

    assert seen == ["перша версія", "друга версія"]


async def test_nothing_is_recorded_about_a_chat_nobody_switched_on(db, monkeypatch):
    """Being added to a group is not consent to record it. The whitelist governs storage,
    not only speech."""
    quiet = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", quiet.generate)

    reply = await handlers.handle_message(
        FakeMessage(text="гряг привіт", chat_id=-777), db,
        client=None, persona="p", bot_id=77,
    )

    assert reply is None
    assert quiet.calls == []
    assert await store.recent_messages(db, -777, limit=10) == []


async def test_an_enabled_chat_is_still_recorded_even_when_the_bot_says_nothing(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm().generate)

    await handlers.handle_message(
        FakeMessage(text="балачки без звертання"), db, client=None, persona="p", bot_id=77
    )

    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["балачки без звертання"]


async def test_a_direct_address_lost_to_the_race_is_sometimes_answered_afterwards(db, monkeypatch):
    """Being skipped while the bot answers somebody else reads, from inside the chat, as
    being ignored — which is what prompted this. It comes back sometimes, not always."""
    await enable_chat(db)
    from gryag import config as cfg

    await cfg.set(db, "deferred_chance", "100", chat_id=-100)
    answered: list[str] = []

    async def slow(client, **kwargs):
        await asyncio.sleep(0.05)
        answered.append(kwargs["user"])
        return llm.LlmResult("ага", 0, 600, 0, 10, 100, 50, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", slow)
    first = FakeMessage(text="гряг раз", message_id=1)
    second = FakeMessage(text="гряг два", message_id=2, user_id=9)

    task = asyncio.create_task(
        handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    )
    await asyncio.sleep(0.01)
    assert await handlers.handle_message(second, db, client=None, persona="p", bot_id=77) is None
    await task
    # The deferred reply is spawned rather than awaited, so the webhook request is not
    # held open for two generations. Drain it here.
    await asyncio.gather(*handlers._tasks)

    assert second.replies == ["ага"]


async def test_it_does_not_always_come_back(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg

    await cfg.set(db, "deferred_chance", "0", chat_id=-100)

    async def slow(client, **kwargs):
        await asyncio.sleep(0.05)
        return llm.LlmResult("ага", 0, 600, 0, 10, 100, 50, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", slow)
    first = FakeMessage(text="гряг раз", message_id=1)
    second = FakeMessage(text="гряг два", message_id=2, user_id=9)

    task = asyncio.create_task(
        handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    )
    await asyncio.sleep(0.01)
    await handlers.handle_message(second, db, client=None, persona="p", bot_id=77)
    await task
    await asyncio.gather(*handlers._tasks)

    assert second.replies == []


async def test_an_ambient_message_that_lost_the_race_is_not_worth_returning_to(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg

    await cfg.set(db, "deferred_chance", "100", chat_id=-100)

    async def slow(client, **kwargs):
        await asyncio.sleep(0.05)
        return llm.LlmResult("ага", 0, 600, 0, 10, 100, 50, 0.0005)

    monkeypatch.setattr(handlers.llm, "generate", slow)
    first = FakeMessage(text="гряг раз", message_id=1)
    passerby = FakeMessage(text="просто балачки без звертання", message_id=2, user_id=9)

    task = asyncio.create_task(
        handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    )
    await asyncio.sleep(0.01)
    await handlers.handle_message(passerby, db, client=None, persona="p", bot_id=77)
    await task
    await asyncio.gather(*handlers._tasks)

    assert passerby.replies == []


async def test_a_stale_missed_message_is_dropped(db, monkeypatch):
    await enable_chat(db)
    from datetime import timedelta

    from gryag import config as cfg

    await cfg.set(db, "deferred_chance", "100", chat_id=-100)
    stale = FakeMessage(text="гряг агов", message_id=5)
    handlers._pending[-100] = (stale, handlers._utcnow() - timedelta(minutes=5))

    assert handlers._take_missed(-100, 60) is None


def test_the_bot_is_told_the_time_the_room_is_living_in():
    """Telegram timestamps are UTC. Handing those over told the bot it was three hours
    earlier than everybody in the chat."""
    from datetime import datetime, timezone

    rendered = handlers._render_now(datetime(2026, 8, 18, 23, 35, tzinfo=timezone.utc))

    assert rendered.startswith("2026-08-19 02:35")
    assert "середа" in rendered


async def test_a_bare_draw_request_draws_what_it_replies_to(db, monkeypatch):
    """"гряг намалюй" in reply to something means draw that. It used to hand the model
    the words "гряг намалюй" and get exactly that back."""
    await enable_chat(db)
    from gryag import config as cfg, images

    await cfg.set(db, "image_whitelist", "1", chat_id=-100)
    asked: list[str] = []

    async def fake_draw(client, *, model, prompt, source=None):
        asked.append(prompt)
        return images.ImageResult(b"jpeg", "image/jpeg", 8000, 20, 1200)

    monkeypatch.setattr(handlers.images, "generate", fake_draw)
    parent = FakeMessage(text="кіт у вишиванці компілює ядро", message_id=1, user_id=2)
    message = FakeMessage(text="гряг намалюй", message_id=2, user_id=1, reply_to=parent)

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert "кіт у вишиванці компілює ядро" in asked[0]
    assert "намалюй" not in asked[0]


async def test_a_quoted_fragment_wins_over_the_whole_parent(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg, images

    await cfg.set(db, "image_whitelist", "1", chat_id=-100)
    asked: list[str] = []

    async def fake_draw(client, *, model, prompt, source=None):
        asked.append(prompt)
        return images.ImageResult(b"jpeg", "image/jpeg", 8000, 20, 1200)

    monkeypatch.setattr(handlers.images, "generate", fake_draw)
    parent = FakeMessage(text="довге повідомлення про все на світі", message_id=1, user_id=2)
    message = FakeMessage(text="гряг намалюй", message_id=2, user_id=1, reply_to=parent)
    message.quote = pytypes.SimpleNamespace(text="все на світі")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert "все на світі" in asked[0]


async def test_an_explicit_prompt_still_wins(db, monkeypatch):
    await enable_chat(db)
    from gryag import config as cfg, images

    await cfg.set(db, "image_whitelist", "1", chat_id=-100)
    asked: list[str] = []

    async def fake_draw(client, *, model, prompt, source=None):
        asked.append(prompt)
        return images.ImageResult(b"jpeg", "image/jpeg", 8000, 20, 1200)

    monkeypatch.setattr(handlers.images, "generate", fake_draw)
    parent = FakeMessage(text="щось інше", message_id=1, user_id=2)
    message = FakeMessage(
        text="гряг намалюй пінгвіна на скейті", message_id=2, user_id=1, reply_to=parent
    )

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert asked[0] == "пінгвіна на скейті"


def test_local_time_follows_daylight_saving():
    """A fixed +3 offset was right in August and an hour wrong from late October, which
    would have shifted quiet hours with nothing failing visibly."""
    from datetime import datetime, timezone

    summer = handlers._render_now(datetime(2026, 8, 18, 23, 35, tzinfo=timezone.utc))
    winter = handlers._render_now(datetime(2026, 12, 18, 23, 35, tzinfo=timezone.utc))

    assert summer.startswith("2026-08-19 02:35")
    assert winter.startswith("2026-12-19 01:35")


class FakeReaction:
    """`ReactionTypeEmoji` in the shape the handler reads it."""

    def __init__(self, emoji=None, custom_emoji_id=None):
        self.type = "emoji" if emoji else "custom_emoji"
        self.emoji = emoji
        self.custom_emoji_id = custom_emoji_id


class FakeReactionUpdate:
    def __init__(self, *, message_id=1, chat_id=-100, old=(), new=(), date=None):
        self.message_id = message_id
        self.chat = pytypes.SimpleNamespace(id=chat_id, title="матсурі")
        self.old_reaction = list(old)
        self.new_reaction = list(new)
        self.date = date or datetime.now(timezone.utc)
        self.user = pytypes.SimpleNamespace(id=1, full_name="Олег", is_bot=False)


def test_the_delta_between_two_reaction_lists():
    added, removed = handlers.reaction_delta(
        [FakeReaction("😁"), FakeReaction("❤")], [FakeReaction("❤"), FakeReaction("🔥")]
    )

    assert added == ["🔥"]
    assert removed == ["😁"]


def test_custom_emoji_are_not_counted():
    """A custom emoji has no unicode character to put in the document, and the lore is a
    Markdown file people read."""
    added, removed = handlers.reaction_delta([], [FakeReaction(custom_emoji_id="55")])

    assert added == []
    assert removed == []


async def test_a_reaction_in_an_enabled_chat_is_stored(db):
    await admin.enable_chat(db, -100, "матсурі")

    assert await handlers.handle_reaction(FakeReactionUpdate(new=[FakeReaction("😁")]), db) is True
    assert await store.reactions_for(db, -100, 1) == [("😁", 1)]


async def test_a_reaction_in_a_chat_that_is_not_whitelisted_is_ignored(db):
    """The whitelist governs storage, not just speech. Being added to a group is not
    consent to have it recorded."""
    assert await handlers.handle_reaction(FakeReactionUpdate(new=[FakeReaction("😁")]), db) is False
    assert await store.reactions_for(db, -100, 1) == []


async def test_removing_a_reaction_lowers_the_count(db):
    await admin.enable_chat(db, -100, "матсурі")
    await handlers.handle_reaction(FakeReactionUpdate(new=[FakeReaction("😁")]), db)

    await handlers.handle_reaction(FakeReactionUpdate(old=[FakeReaction("😁")], new=[]), db)

    assert await store.reactions_for(db, -100, 1) == []
