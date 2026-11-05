from gryag import context, handlers, llm, proactive, store, vocabulary
from tests.conftest import FakeMessage


def box(*phrases):
    return {"text": "persona", "phrases": phrases}


def test_load_skips_blanks_and_duplicates(tmp_path):
    path = tmp_path / "phrases.txt"
    path.write_text("ну да і чо\n\n  дем  \nну да і чо\n", encoding="utf-8")

    assert vocabulary.load(path) == ("ну да і чо", "дем")


def test_no_path_means_no_dictionary():
    assert vocabulary.load(None) == ()
    assert vocabulary.load("") == ()


async def test_nothing_repeats_until_the_dictionary_runs_out(db):
    pool = tuple(f"фраза {i}" for i in range(20))

    seen = []
    for _ in range(5):
        seen += await vocabulary.draw(db, -100, box(*pool), count=4)

    assert sorted(seen) == sorted(pool)


async def test_starts_over_when_it_runs_out_without_a_duplicate_in_one_draw(db):
    pool = tuple(f"фраза {i}" for i in range(5))
    await vocabulary.draw(db, -100, box(*pool), count=4)

    second = await vocabulary.draw(db, -100, box(*pool), count=4)

    assert len(second) == len(set(second)) == 4


async def test_a_dictionary_smaller_than_the_draw_gives_all_of_it(db):
    assert sorted(await vocabulary.draw(db, -100, box("а", "б"), count=8)) == ["а", "б"]
    assert sorted(await vocabulary.draw(db, -100, box("а", "б"), count=8)) == ["а", "б"]


async def test_each_chat_has_its_own_history(db):
    await vocabulary.draw(db, -100, box("а"), count=1)

    assert await store.used_phrases(db, -200) == set()
    assert await vocabulary.draw(db, -200, box("а"), count=1) == ["а"]


async def test_a_persona_without_a_dictionary_draws_nothing(db):
    assert await vocabulary.draw(db, -100, "plain persona") == []
    assert await vocabulary.draw(db, -100, {"text": "persona"}) == []


def _build(**kwargs):
    return context.build(
        messages=[],
        chain=[],
        trigger={"text": "привіт", "alias": "Олег", "is_bot": False, "message_id": 1},
        now="зараз",
        chat_title="чат",
        **kwargs,
    )


def test_phrases_go_above_the_boundary():
    prompt = _build(phrases=["ну да і чо", "дем"])

    assert context.PHRASES_INTRO in prompt
    assert prompt.index("ну да і чо") < prompt.index("---")


def test_without_phrases_the_prompt_is_unchanged():
    assert _build() == _build(phrases=[])
    assert context.PHRASES_INTRO not in _build()


class FakeLlm:
    def __init__(self):
        self.prompts = []

    async def generate(self, client, **kwargs):
        self.prompts.append(kwargs["user"])
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


async def test_a_reply_is_handed_phrases_it_has_not_seen(db, monkeypatch):
    await db.execute("INSERT INTO chats (chat_id, title, enabled) VALUES (-100, 'ч', 1)")
    await db.commit()
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    persona = box("перша фраза", "друга фраза")

    await handlers.handle_message(
        FakeMessage(text="гряг привіт"), db, client=None, persona=persona, bot_id=77
    )

    assert "перша фраза" in fake.prompts[0]
    assert await store.used_phrases(db, -100) == {"перша фраза", "друга фраза"}


async def test_a_message_the_bot_ignores_uses_up_no_phrases(db, monkeypatch):
    await db.execute("INSERT INTO chats (chat_id, title, enabled) VALUES (-100, 'ч', 1)")
    await db.commit()
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)

    await handlers.handle_message(
        FakeMessage(text="балачки"), db, client=None, persona=box("фраза"), bot_id=77
    )

    assert await store.used_phrases(db, -100) == set()


async def test_proactive_speech_uses_the_dictionary_too(db, monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(proactive.llm, "generate", fake.generate)

    class Bot:
        async def send_message(self, chat_id, text):
            return FakeMessage(text=text, message_id=9000, chat_id=chat_id, is_bot=True)

    from datetime import datetime, timezone

    await proactive._speak_into(
        db, None, Bot(), box("тиха фраза"), -100, datetime.now(timezone.utc)
    )

    assert "тиха фраза" in fake.prompts[0]
    assert fake.prompts[0].rstrip().endswith(proactive.PROMPT_SUFFIX.rstrip())
