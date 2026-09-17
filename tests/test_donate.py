from datetime import datetime, timedelta, timezone

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from gryag import donate

JAR = "https://send.monobank.ua/jar/3KMKUPJ4TP"
CARD = "4874 1000 3199 9561"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("DONATE_JAR_URL", "DONATE_CARD", "DONATE_SITE_URL"):
        monkeypatch.delenv(name, raising=False)


def _configure(monkeypatch, jar=JAR, card=CARD, site=None):
    if jar is not None:
        monkeypatch.setenv("DONATE_JAR_URL", jar)
    if card is not None:
        monkeypatch.setenv("DONATE_CARD", card)
    if site is not None:
        monkeypatch.setenv("DONATE_SITE_URL", site)


def test_the_keyboard_is_the_jar_and_a_card_that_copies(monkeypatch):
    _configure(monkeypatch)

    (row,) = donate.donate_keyboard().inline_keyboard

    jar, card = row
    assert jar.text == "🫙 Підтримати бота"
    assert jar.url == JAR
    assert card.text == "💳 Картка"
    assert card.copy_text.text == CARD


def test_without_a_card_only_the_jar_is_offered(monkeypatch):
    _configure(monkeypatch, card=None)

    (row,) = donate.donate_keyboard().inline_keyboard

    assert [b.url for b in row] == [JAR]


def test_without_a_jar_only_the_card_is_offered(monkeypatch):
    _configure(monkeypatch, jar=None)

    (row,) = donate.donate_keyboard().inline_keyboard

    assert [b.copy_text.text for b in row] == [CARD]


def test_with_nothing_configured_there_is_no_keyboard():
    assert donate.donate_keyboard() is None


def test_blank_values_count_as_nothing(monkeypatch):
    _configure(monkeypatch, jar="  ", card="")

    assert donate.donate_keyboard() is None


def test_the_row_goes_under_existing_buttons_without_touching_them(monkeypatch):
    _configure(monkeypatch)
    game = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="гра", callback_data="g")]]
    )

    merged = donate.with_donate_row(game)

    assert merged.inline_keyboard[0][0].callback_data == "g"
    assert merged.inline_keyboard[1][0].url == JAR
    assert len(game.inline_keyboard) == 1


def test_with_nothing_configured_the_markup_is_returned_as_is():
    game = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="гра", callback_data="g")]]
    )

    assert donate.with_donate_row(game) is game
    assert donate.with_donate_row(None) is None


def test_the_text_carries_the_jar_the_card_and_the_site(monkeypatch):
    _configure(monkeypatch, site="https://dobrovolskyi.com.ua")

    text = donate.donate_text()

    assert JAR in text
    assert f"<code>{CARD}</code>" in text
    assert "https://dobrovolskyi.com.ua" in text


def test_the_text_leaves_the_site_out_when_there_is_none(monkeypatch):
    _configure(monkeypatch)

    assert "dobrovolskyi" not in donate.donate_text()


def test_the_text_escapes_what_it_is_given(monkeypatch):
    _configure(monkeypatch, card="<b>1</b>")

    assert "&lt;b&gt;1&lt;/b&gt;" in donate.donate_text()


def test_with_nothing_configured_there_is_no_text():
    assert donate.donate_text() is None


async def test_the_command_answers_with_the_details_and_the_buttons(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch, site="https://dobrovolskyi.com.ua")
    message = FakeMessage(text="/donate")

    await donate.show_command(message, db)

    assert CARD in message.replies[0]
    assert message.parse_modes[0] == "HTML"
    assert message.markups[0].inline_keyboard[0][0].url == JAR


async def test_the_command_says_so_when_nothing_is_configured(db):
    from tests.conftest import FakeMessage

    message = FakeMessage(text="/donate")

    await donate.show_command(message, db)

    assert message.replies == ["реквізитів поки немає"]


async def test_the_commands_answer_is_stored(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch)

    await donate.show_command(FakeMessage(text="/donate"), db)

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1", (-100,)
    ) as cur:
        assert (await cur.fetchone())[0] == 1


async def test_a_replayed_command_is_not_answered(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch)
    message = FakeMessage(text="/donate", date=datetime.now(timezone.utc) - timedelta(hours=3))

    await donate.show_command(message, db)

    assert message.replies == []
