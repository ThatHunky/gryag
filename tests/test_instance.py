"""A second bot from the same code: its own identity, and no shared daily jobs."""

import types as pytypes
from datetime import datetime, timedelta, timezone

import pytest

from gryag import __main__ as entry
from gryag import config, context, handlers, llm, proactive, store
from tests.conftest import FakeMessage


def test_token_is_read_from_the_named_variable(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "main-bot-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_VAR", "SOME_PERSONA_TOKEN")
    monkeypatch.setenv("SOME_PERSONA_TOKEN", "persona-token")

    entry.apply_instance_env()

    assert config.os.environ["TELEGRAM_BOT_TOKEN"] == "persona-token"


def test_a_missing_token_never_falls_back_to_the_main_bot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "main-bot-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_VAR", "SOME_PERSONA_TOKEN")
    monkeypatch.delenv("SOME_PERSONA_TOKEN", raising=False)

    with pytest.raises(KeyError):
        entry.apply_instance_env()


def test_without_instance_settings_nothing_changes(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "main-bot-token")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_VAR", raising=False)
    monkeypatch.delenv("BOT_KEYWORDS", raising=False)

    entry.apply_instance_env()

    assert config.os.environ["TELEGRAM_BOT_TOKEN"] == "main-bot-token"
    assert config.DEFAULTS["keywords"] == "гряг"


def test_keywords_become_the_default(monkeypatch):
    monkeypatch.setitem(config.DEFAULTS, "keywords", "гряг")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_VAR", raising=False)
    monkeypatch.setenv("BOT_KEYWORDS", "андрійбот")

    entry.apply_instance_env()

    assert config.DEFAULTS["keywords"] == "андрійбот"


def test_the_copied_person_and_the_bot_read_as_different_speakers(monkeypatch):
    monkeypatch.setattr(context, "BOT_ALIAS", "андрій")

    own = context.render_line({"is_bot": True, "text": "дем"})
    human = context.render_line({"alias": "андрій", "username": "real", "text": "бля"})

    assert own == "андрій: дем"
    assert human == "андрій(@real): бля"


async def test_the_trigger_is_labelled_like_the_log(db, monkeypatch):
    """Regression: the real андрій showed as "андрій(@binihit)" in the window but as
    "андрій(не бот)" on the trigger line, and the bot answered him as somebody else."""
    monkeypatch.setattr(context, "BOT_ALIAS", "андрій")
    await _enable(db)
    prompts = []

    async def generate(client, **kwargs):
        prompts.append(kwargs["user"])
        return await Reply().generate(client, **kwargs)

    monkeypatch.setattr(handlers.llm, "generate", generate)
    message = FakeMessage(text="гряг чим же", full_name="андрій", user_id=5)
    message.from_user.username = "binihit"
    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert prompts[0].rstrip().endswith("андрій(@binihit): гряг чим же")


def test_another_bot_is_marked_so_it_is_not_taken_for_its_original():
    line = context.render_line({"alias": "андрій", "sender_is_bot": 1, "text": "ідк"})

    assert line == "андрій(бот): ідк"


def _mention(text):
    return pytypes.SimpleNamespace(type="mention", extract_from=lambda _: text)


class Reply:
    def __init__(self):
        self.calls = 0

    async def generate(self, client, **kwargs):
        self.calls += 1
        return llm.LlmResult(
            text="ага",
            searched=0,
            prompt_tokens=1,
            cached_tokens=0,
            visible_tokens=1,
            thought_tokens=0,
            latency_ms=1,
            cost_usd=0.0,
        )


async def _enable(db):
    await db.execute("INSERT INTO chats (chat_id, title, enabled) VALUES (-100, 'ч', 1)")
    await db.commit()


async def test_answers_a_mention_of_its_own_username_only(db, monkeypatch):
    await _enable(db)
    fake = Reply()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)

    other = FakeMessage(text="@gryag_bot йо", message_id=1, entities=[_mention("@gryag_bot")])
    await handlers.handle_message(
        other, db, client=None, persona="p", bot_id=77, bot_username="binihit_clone_bot"
    )
    assert fake.calls == 0

    mine = FakeMessage(
        text="@Binihit_Clone_Bot йо", message_id=2, entities=[_mention("@Binihit_Clone_Bot")]
    )
    await handlers.handle_message(
        mine, db, client=None, persona="p", bot_id=77, bot_username="binihit_clone_bot"
    )
    assert fake.calls == 1


async def test_two_instances_stop_arguing_and_a_human_restarts_them(tmp_path, monkeypatch):
    """Each instance counts the streak in its own database, so this is the real topology."""
    fake = Reply()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    bots = {
        77: await store.connect(str(tmp_path / "a.db")),
        88: await store.connect(str(tmp_path / "b.db")),
    }
    try:
        for db in bots.values():
            await _enable(db)
        start = datetime.now(timezone.utc) - timedelta(seconds=120)

        async def human(message_id, seconds):
            for db in bots.values():
                await handlers.persist(
                    db,
                    FakeMessage(
                        text="люди тут",
                        message_id=message_id,
                        user_id=1,
                        date=start + timedelta(seconds=seconds),
                    ),
                )

        async def exchange(first_id, seconds):
            """Bot 88 pokes bot 77, then each answers the other until one goes quiet."""
            spoken, sender, receiver = 0, 88, 77
            message_id = first_id
            for turn in range(12):
                moment = start + timedelta(seconds=seconds + turn + 1)
                incoming = FakeMessage(
                    text="йо",
                    message_id=message_id,
                    user_id=sender,
                    is_bot=True,
                    date=moment,
                    reply_to=FakeMessage(text="ага", message_id=message_id - 1, user_id=receiver),
                )
                await handlers.persist(bots[sender], incoming)
                # The sender's own copy is what its reply caps and streak read.
                reply = await handlers.handle_message(
                    incoming, bots[receiver], client=None, persona="p", bot_id=receiver
                )
                if reply is None:
                    return spoken
                spoken += 1
                message_id = incoming.message_id + 1000
                sender, receiver = receiver, sender
            raise AssertionError("the bots never stopped")

        await human(1, 0)
        first = await exchange(10, 1)
        assert 1 <= first <= 3

        await human(5000, 30)
        second = await exchange(6000, 31)
        assert second >= 1
    finally:
        for db in bots.values():
            await db.close()


async def test_a_persona_instance_skips_the_daily_posts(db, monkeypatch):
    called = []

    async def job(*_args, **_kwargs):
        called.append("job")

    monkeypatch.setattr(proactive.pidor, "announce_due", job)
    monkeypatch.setattr(proactive.pidrahuika, "post_due", job)

    await proactive.tick(db, None, None, "p", chat_only=True)
    assert called == []

    await proactive.tick(db, None, None, "p", chat_only=False)
    assert called == ["job", "job"]
