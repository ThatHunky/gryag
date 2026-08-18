from gryag import admin, config, store


async def test_spend_report_says_so_when_there_is_nothing_yet(db):
    report = await admin.spend_report(db)

    assert "поки нічого" in report


async def test_spend_report_totals_cost_and_tokens(db):
    for _ in range(2):
        await store.record_usage(
            db,
            chat_id=-100,
            purpose="reply",
            model="gemini-flash-latest",
            prompt_tok=600,
            cached_tok=0,
            visible_tok=20,
            thought_tok=150,
            latency_ms=2000,
            cost_usd=0.001,
        )

    report = await admin.spend_report(db)

    assert "0.0020" in report
    assert "gemini-flash-latest" in report
    assert "2" in report


async def test_enabling_a_chat_makes_it_enabled(db):
    await admin.enable_chat(db, -100, "матсурі")

    async with db.execute("SELECT enabled, title FROM chats WHERE chat_id = ?", (-100,)) as cur:
        row = await cur.fetchone()

    assert row[0] == 1
    assert row[1] == "матсурі"


async def test_every_offered_model_has_a_price(db):
    from gryag import llm

    assert all(model in llm.PRICES for model in admin.MODEL_CHOICES)


async def test_switching_the_model_is_readable_afterwards(db):
    await config.set(db, "speak_model", "gemini-2.5-flash", chat_id=-100)

    assert await config.get(db, "speak_model", chat_id=-100) == "gemini-2.5-flash"
