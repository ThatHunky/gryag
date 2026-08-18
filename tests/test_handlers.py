import types as pytypes
from datetime import datetime, timedelta, timezone

from gryag import config, handlers, llm, store


class FakeMessage:
    def __init__(
        self,
        *,
        text="привіт",
        message_id=1,
        chat_id=-100,
        user_id=1,
        full_name="Олег",
        is_bot=False,
        reply_to=None,
        entities=None,
        date=None,
    ):
        self.message_id = message_id
        # Telegram always sends tz-aware timestamps; the staleness guard subtracts
        # them from utcnow, so a naive datetime here would not exercise the real path.
        self.date = date or datetime.now(timezone.utc)
        self.text = text
        self.caption = None
        self.chat = pytypes.SimpleNamespace(id=chat_id, title="матсурі")
        self.from_user = pytypes.SimpleNamespace(
            id=user_id, full_name=full_name, is_bot=is_bot
        )
        self.reply_to_message = reply_to
        self.entities = entities or []
        self.photo = self.voice = self.video = None
        self.video_note = self.sticker = self.document = None
        self.bot = None  # disables the typing indicator; see handlers._typing
        self.replies: list[str] = []

    async def reply(self, text):
        """The bot always answers as a Telegram reply, quoting what triggered it."""
        self.replies.append(text)
        sent = FakeMessage(text=text, message_id=self.message_id + 1000, is_bot=True)
        sent.reply_to_message = self
        return sent


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
