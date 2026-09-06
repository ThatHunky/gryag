"""The killboard is never called from a test. This payload is a real one, captured from
https://sbs-group.army/api/public/statistics/… on 2026-08-19 and trimmed to five target
classes; the shape is exactly what the API returns."""

from datetime import datetime, timezone

import pytest

from gryag import admin, config, pidrahuika, store

PAYLOAD = {
    "personnel": {"killed": 168, "wounded": 182},
    "flights": {"strike": 3822, "recon": 2904},
    "status": "completed",
    "lastUpdated": "2026-08-19T16:41:00.022Z",
    "totalTargetsHit": 1575,
    "totalTargetsDestroyed": 630,
    "targetsByType": [
        {"targetClassId": 1, "targetClass": "Танки", "hit": 0, "destroyed": 0},
        {"targetClassId": 15, "targetClass": "ОС РОВ", "hit": 350, "destroyed": 168},
        {"targetClassId": 21, "targetClass": "Укриття", "hit": 406, "destroyed": 17},
        {"targetClassId": 25, "targetClass": "Ворожі крила", "hit": 206, "destroyed": 202},
        {"targetClassId": 30, "targetClass": "Шахеди", "hit": 7, "destroyed": 7},
    ],
}


def test_parsing_pulls_out_the_headline_numbers():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert report.killed == 168
    assert report.wounded == 182
    assert report.hit == 1575
    assert report.destroyed == 630
    assert report.strike == 3822
    assert report.collected is True


def test_the_top_is_ordered_by_what_was_destroyed():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert report.top[0] == ("Ворожі крила", 206, 202)
    assert report.top[1] == ("ОС РОВ", 350, 168)


def test_categories_with_nothing_in_them_are_left_out():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert all(name != "Танки" for name, _hit, _dead in report.top)


def test_totals_are_summed_when_the_api_omits_them():
    payload = {k: v for k, v in PAYLOAD.items() if not k.startswith("total")}

    report = pidrahuika.parse(payload, "2026-08-19")

    assert report.hit == 969
    assert report.destroyed == 394


def test_a_day_the_board_has_not_counted_yet_is_marked_uncollected():
    report = pidrahuika.parse({**PAYLOAD, "status": "not_collected"}, "2026-08-19")

    assert report.collected is False


def test_a_payload_missing_everything_does_not_explode():
    report = pidrahuika.parse({}, "2026-08-19")

    assert report.killed == 0
    assert report.top == ()
    assert report.collected is False


def test_rendering_names_the_day_in_ukrainian():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "нормальна робота")

    assert "19 серпня" in text


def test_rendering_carries_the_numbers_and_the_comment():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "нормальна робота")

    assert "168" in text
    assert "1575" in text
    assert "Ворожі крила" in text
    assert "нормальна робота" in text


def test_rendering_shows_the_change_against_the_day_before():
    today = pidrahuika.parse(PAYLOAD, "2026-08-19")
    yesterday = pidrahuika.parse({**PAYLOAD, "totalTargetsDestroyed": 500}, "2026-08-18")

    text = pidrahuika.render(today, yesterday, "нормальна робота")

    assert "+130" in text


def test_rendering_without_a_previous_day_says_nothing_about_change():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "x")

    assert "+" not in text.split("Вильоти")[0]


def test_only_the_top_n_categories_are_shown():
    many = {
        **PAYLOAD,
        "targetsByType": [
            {"targetClassId": i, "targetClass": f"клас {i}", "hit": i, "destroyed": i}
            for i in range(1, 20)
        ],
    }

    report = pidrahuika.parse(many, "2026-08-19")

    assert len(report.top) == pidrahuika.TOP_N


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class Sent:
            message_id = 1000 + len(self.sent)

        return Sent()


@pytest.fixture
def _board(monkeypatch):
    """The killboard is never called from a test."""
    calls: list[str] = []

    async def fake_fetch(period_type, now=None):
        calls.append(period_type)
        return pidrahuika.parse(PAYLOAD, "2026-08-18"), PAYLOAD

    monkeypatch.setattr(pidrahuika, "fetch_report", fake_fetch)
    return calls


async def test_the_digest_reads_the_previous_day_and_stores_it(db, _board):
    text = await pidrahuika.digest_text(
        db, "prev_day", datetime(2026, 8, 19, 6, tzinfo=timezone.utc)
    )

    assert "Підрахуйка" in text
    assert _board == ["prev_day"]
    assert await store.pidrahuika_payload(db, "2026-08-18") is not None


async def test_a_board_that_does_not_answer_yields_nothing(db, monkeypatch):
    async def no_answer(period_type, now=None):
        return None

    monkeypatch.setattr(pidrahuika, "fetch_report", no_answer)

    assert (
        await pidrahuika.digest_text(db, "prev_day", datetime(2026, 8, 19, tzinfo=timezone.utc))
        is None
    )


async def test_figures_that_are_not_collected_yet_say_so(db, monkeypatch):
    async def uncollected(period_type, now=None):
        return pidrahuika.parse({**PAYLOAD, "status": "not_collected"}, "2026-08-18"), PAYLOAD

    monkeypatch.setattr(pidrahuika, "fetch_report", uncollected)

    text = await pidrahuika.digest_text(db, "daily", datetime(2026, 8, 19, tzinfo=timezone.utc))

    assert "ще не порахували" in text


async def test_the_morning_post_lands_once(db, _board):
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)
    bot = FakeBot()
    # 09:30 Kyiv is 06:30 UTC in summer.
    morning = datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)

    assert await pidrahuika.post_due(db, bot, morning) == 1
    assert await pidrahuika.post_due(db, bot, morning) == 0
    assert len(bot.sent) == 1


async def test_nothing_is_posted_before_the_hour(db, _board):
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)
    bot = FakeBot()

    assert await pidrahuika.post_due(db, bot, datetime(2026, 8, 19, 3, tzinfo=timezone.utc)) == 0


async def test_a_chat_that_did_not_ask_for_it_gets_nothing(db, _board):
    await admin.enable_chat(db, -100, "матсурі")
    bot = FakeBot()

    assert (
        await pidrahuika.post_due(db, bot, datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)) == 0
    )


async def test_a_muted_chat_gets_nothing(db, _board):
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)
    await store.set_mute(db, -100, "2126-01-01T00:00:00+00:00")
    bot = FakeBot()

    assert (
        await pidrahuika.post_due(db, bot, datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)) == 0
    )


async def test_a_failed_fetch_leaves_the_day_unmarked_so_the_next_tick_retries(db, monkeypatch):
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)

    async def no_answer(period_type, now=None):
        return None

    monkeypatch.setattr(pidrahuika, "fetch_report", no_answer)
    bot = FakeBot()
    morning = datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)

    assert await pidrahuika.post_due(db, bot, morning) == 0
    assert await store.pidrahuika_posted(db, -100, "2026-08-19") is False


async def test_the_command_answers_even_when_the_morning_post_is_off(db, _board):
    """A command somebody typed is not ambient speech.

    Silence here is indistinguishable from a broken bot, which is exactly how this was
    first reported: "не працює команда підрахуйки взагалі". The flag governs the
    unprompted morning post; reading a public board on request costs nothing.
    """
    from tests.conftest import FakeMessage

    await admin.enable_chat(db, -100, "матсурі")
    message = FakeMessage(text="/pidrahuika")

    await pidrahuika.show_command(message, db)

    assert message.replies
    assert "Підрахуйка" in message.replies[0]


async def test_the_command_is_answered_even_in_a_chat_that_was_never_switched_on(db, _board):
    from tests.conftest import FakeMessage

    message = FakeMessage(text="/pidrahuika")

    await pidrahuika.show_command(message, db)

    assert message.replies
    assert "Підрахуйка" in message.replies[0]


async def test_the_commands_answer_is_stored_like_anything_else_the_bot_says(db, _board):
    from tests.conftest import FakeMessage

    await admin.enable_chat(db, -100, "матсурі")

    await pidrahuika.show_command(FakeMessage(text="/pidrahuika"), db)

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1", (-100,)
    ) as cur:
        assert (await cur.fetchone())[0] == 1


async def test_an_unfinished_day_is_not_snapshotted(db, _board):
    """A day in progress is not comparable to a finished one, in either direction, and
    storing it makes it tomorrow's baseline."""
    await pidrahuika.digest_text(db, "daily", datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert await store.pidrahuika_payload(db, "2026-08-18") is None


async def test_the_live_report_carries_no_delta(db, _board):
    await store.pidrahuika_save(db, "2026-08-17", "2026-08-18T09:00:00+00:00", PAYLOAD)

    text = await pidrahuika.digest_text(
        db, "daily", datetime(2026, 8, 19, 12, tzinfo=timezone.utc)
    )

    assert "(" not in text.split("Вильоти")[0].split("Особовий")[1]


async def test_the_morning_post_does_not_talk_over_a_reply(db, _board):
    from gryag import handlers

    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)
    bot = FakeBot()
    handlers._claim(-100)
    try:
        posted = await pidrahuika.post_due(
            db, bot, datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)
        )
    finally:
        handlers._release(-100)

    assert posted == 0
    assert bot.sent == []
