from gryag import admin, config, menu, store


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


async def test_rerunning_the_digest_reports_back_to_the_chat(db):
    ran: list[int] = []
    said: list[str] = []

    async def on_digest(conn, chat_id: int) -> None:
        ran.append(chat_id)

    class FakeChat:
        id = -100

        async def send_message(self, text: str) -> None:
            said.append(text)

    await admin._rerun_and_report(on_digest, db, FakeChat())

    assert ran == [-100]
    assert "самарі" in said[0]


async def test_a_failing_digest_says_so_instead_of_vanishing(db):
    said: list[str] = []

    async def on_digest(conn, chat_id: int) -> None:
        raise RuntimeError("quota")

    class FakeChat:
        id = -100

        async def send_message(self, text: str) -> None:
            said.append(text)

    await admin._rerun_and_report(on_digest, db, FakeChat())

    assert "не вийшло" in said[0]


async def test_the_root_text_says_whether_the_chat_is_on(db):
    await admin.enable_chat(db, -100, "матсурі")

    text = await admin.root_text(db, -100)

    assert "увімкнено" in text


async def test_the_root_text_names_the_model_in_use(db):
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "speak_model", "gemini-2.5-flash", chat_id=-100)

    text = await admin.root_text(db, -100)

    assert "gemini-2.5-flash" in text


async def test_the_root_text_shows_what_today_cost(db):
    await admin.enable_chat(db, -100, "матсурі")
    await store.record_usage(
        db,
        chat_id=-100,
        purpose="reply",
        model="gemini-flash-latest",
        prompt_tok=600,
        cached_tok=0,
        visible_tok=20,
        thought_tok=0,
        latency_ms=2000,
        cost_usd=0.0025,
    )

    text = await admin.root_text(db, -100)

    assert "0.0025" in text


async def test_the_people_screen_lists_who_may_draw(db):
    await config.set(db, "image_whitelist", "777", chat_id=-100)

    text = await admin.screen_text(db, -100, menu.screen("people"))

    assert "777" in text


async def test_the_people_screen_says_when_nobody_is_banned(db):
    text = await admin.screen_text(db, -100, menu.screen("people"))

    assert "ніхто" in text


async def test_spend_can_be_narrowed_to_the_last_day(db):
    await db.execute(
        """
        INSERT INTO usage (ts, chat_id, purpose, model, prompt_tok, cached_tok,
                           visible_tok, thought_tok, latency_ms, cost_usd)
        VALUES (datetime('now', '-3 days'), -100, 'reply', 'gemini-flash-latest',
                600, 0, 20, 0, 2000, 9.9999)
        """
    )
    await db.commit()
    await store.record_usage(
        db,
        chat_id=-100,
        purpose="reply",
        model="gemini-flash-latest",
        prompt_tok=600,
        cached_tok=0,
        visible_tok=20,
        thought_tok=0,
        latency_ms=2000,
        cost_usd=0.0011,
    )

    day = await admin.spend_report(db, -100, period="day")
    everything = await admin.spend_report(db, -100, period="all")

    assert "9.9999" not in day
    assert "0.0011" in day
    # "all" groups both calls into one row, so the old spend shows up in the total.
    assert "10.0010" in everything


async def test_rewriting_the_lore_reports_back_to_the_chat(db):
    ran: list[int] = []
    said: list[str] = []

    async def on_lore(conn, chat_id: int) -> bool:
        ran.append(chat_id)
        return True

    class FakeChat:
        id = -100

        async def send_message(self, text: str) -> None:
            said.append(text)

    await admin._lore_and_report(on_lore, db, FakeChat())

    assert ran == [-100]
    assert "лор" in said[0].lower()


async def test_a_lore_run_that_wrote_nothing_says_so(db):
    said: list[str] = []

    async def on_lore(conn, chat_id: int) -> bool:
        return False

    class FakeChat:
        id = -100

        async def send_message(self, text: str) -> None:
            said.append(text)

    await admin._lore_and_report(on_lore, db, FakeChat())

    assert "не" in said[0]


async def test_a_lore_run_that_raised_does_not_vanish(db):
    said: list[str] = []

    async def on_lore(conn, chat_id: int) -> bool:
        raise RuntimeError("quota")

    class FakeChat:
        id = -100

        async def send_message(self, text: str) -> None:
            said.append(text)

    await admin._lore_and_report(on_lore, db, FakeChat())

    assert said
