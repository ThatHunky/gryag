import types as pytypes
from datetime import datetime, timedelta, timezone

from gryag import config, llm, proactive, store


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return pytypes.SimpleNamespace(
            message_id=999,
            from_user=pytypes.SimpleNamespace(id=77),
            date=datetime.now(timezone.utc),
        )


async def seed_silent_chat(db, chat_id=-100, silent_hours=5):
    await db.execute("INSERT INTO chats (chat_id, enabled) VALUES (?, 1)", (chat_id,))
    await db.commit()
    await store.upsert_user(db, chat_id=chat_id, user_id=1, display_name="Олег", alias="oleh")
    old = datetime.now(timezone.utc) - timedelta(hours=silent_hours)
    await store.save_message(
        db, chat_id=chat_id, message_id=1, user_id=1,
        ts=old.isoformat(timespec="seconds"), text="останнє що тут казали про лінукс",
        media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )
    await config.set(db, "proactive_enabled", "1", chat_id=chat_id)
    await config.set(db, "quiet_from", "0", chat_id=chat_id)
    await config.set(db, "quiet_to", "0", chat_id=chat_id)


async def fake_generate(client, **kwargs):
    fake_generate.prompts.append(kwargs["user"])
    return llm.LlmResult("ну шо, всі повмирали?", 0, 500, 0, 12, 80, 900, 0.0006)


fake_generate.prompts = []


async def test_speaks_into_a_chat_that_has_gone_quiet(db, monkeypatch):
    await seed_silent_chat(db)
    fake_generate.prompts.clear()
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)
    bot = FakeBot()

    assert await proactive.run_once(db, None, bot, "persona") == 1
    assert bot.sent == [(-100, "ну шо, всі повмирали?")]


async def test_stays_out_of_a_chat_that_is_still_talking(db, monkeypatch):
    await seed_silent_chat(db, silent_hours=0)
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)
    bot = FakeBot()

    assert await proactive.run_once(db, None, bot, "persona") == 0
    assert bot.sent == []


async def test_does_nothing_until_it_is_switched_on(db, monkeypatch):
    await seed_silent_chat(db)
    await config.set(db, "proactive_enabled", "0", chat_id=-100)
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)
    bot = FakeBot()

    assert await proactive.run_once(db, None, bot, "persona") == 0


async def test_does_not_speak_twice_in_a_row(db, monkeypatch):
    await seed_silent_chat(db)
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)
    bot = FakeBot()

    await proactive.run_once(db, None, bot, "persona")
    second = await proactive.run_once(db, None, bot, "persona")

    assert second == 0


async def test_its_own_message_is_stored_so_the_chat_is_no_longer_silent(db, monkeypatch):
    await seed_silent_chat(db)
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)

    await proactive.run_once(db, None, FakeBot(), "persona")

    rows = await store.recent_messages(db, -100, limit=5)
    assert rows[-1]["is_bot"] == 1
    assert rows[-1]["text"] == "ну шо, всі повмирали?"


async def test_the_prompt_asks_it_to_start_rather_than_reply(db, monkeypatch):
    await seed_silent_chat(db)
    fake_generate.prompts.clear()
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)

    await proactive.run_once(db, None, FakeBot(), "persona")

    prompt = fake_generate.prompts[0]
    assert "Чат мовчить" in prompt
    assert "останнє що тут казали про лінукс" in prompt


async def test_a_muted_chat_is_left_in_peace(db, monkeypatch):
    await seed_silent_chat(db)
    await store.set_mute(
        db, -100,
        (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds"),
    )
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)

    assert await proactive.run_once(db, None, FakeBot(), "persona") == 0


async def test_the_usage_row_says_it_was_proactive(db, monkeypatch):
    await seed_silent_chat(db)
    monkeypatch.setattr(proactive.llm, "generate", fake_generate)

    await proactive.run_once(db, None, FakeBot(), "persona")

    async with db.execute("SELECT purpose FROM usage") as cur:
        assert [r[0] for r in await cur.fetchall()] == ["proactive"]
