import pytest

from gryag.gate import GateInput, mentions_keyword, should_speak


def make(**overrides) -> GateInput:
    base = dict(
        text="просто повідомлення",
        is_bot=False,
        chat_enabled=True,
        mentions_bot=False,
        replies_to_bot=False,
        keywords=("гряг",),
        replies_today=0,
        replies_this_hour=0,
        daily_cap=60,
        hourly_cap=10,
    )
    base.update(overrides)
    return GateInput(**base)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("гряг привіт", True),
        ("Гряг, шо там", True),
        ("а гряга нема", True),
        ("дай грягу спокій", True),
        ("грягом клянуся", True),
        ("привіт усім", False),
        ("аргумент", False),
        ("шпаргалка", False),
    ],
)
def test_keyword_matching_covers_inflections_but_not_substrings(text, expected):
    assert mentions_keyword(text, ("гряг",)) is expected


def test_speaks_when_the_bot_is_mentioned():
    assert should_speak(make(mentions_bot=True)).speak is True


def test_speaks_when_someone_replies_to_the_bot():
    assert should_speak(make(replies_to_bot=True)).speak is True


def test_speaks_when_a_keyword_appears():
    decision = should_speak(make(text="гряг шо скажеш"))

    assert decision.speak is True
    assert decision.reason == "keyword"


def test_stays_silent_without_any_address():
    decision = should_speak(make())

    assert decision.speak is False
    assert decision.reason == "not_addressed"


def test_never_answers_another_bot_even_when_addressed():
    decision = should_speak(make(is_bot=True, mentions_bot=True))

    assert decision.speak is False
    assert decision.reason == "sender_is_bot"


def test_stays_silent_in_a_disabled_chat():
    decision = should_speak(make(chat_enabled=False, mentions_bot=True))

    assert decision.speak is False
    assert decision.reason == "chat_disabled"


def test_daily_cap_stops_even_a_direct_address():
    decision = should_speak(make(mentions_bot=True, replies_today=60, daily_cap=60))

    assert decision.speak is False
    assert decision.reason == "daily_cap"


def test_hourly_cap_stops_even_a_direct_address():
    decision = should_speak(make(mentions_bot=True, replies_this_hour=10, hourly_cap=10))

    assert decision.speak is False
    assert decision.reason == "hourly_cap"


def test_disabled_chat_is_checked_before_the_sender():
    decision = should_speak(make(chat_enabled=False, is_bot=True, mentions_bot=True))

    assert decision.reason == "chat_disabled"


def test_empty_text_with_a_reply_to_the_bot_still_speaks():
    assert should_speak(make(text="", replies_to_bot=True)).speak is True
