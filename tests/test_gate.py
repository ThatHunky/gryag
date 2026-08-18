import pytest

from gryag.gate import GateInput, mentions_keyword, should_speak


def make(**overrides) -> GateInput:
    base = dict(
        text="просто повідомлення",
        is_bot=False,
        is_self=False,
        chat_enabled=True,
        mentions_bot=False,
        replies_to_bot=False,
        keywords=("гряг",),
        replies_today=0,
        replies_this_hour=0,
        daily_cap=60,
        hourly_cap=10,
        bot_streak=0,
        bot_exchange_limit=3,
        throttle_after=6,
        throttle_step=15,
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


def test_answers_another_bot_that_addresses_it():
    decision = should_speak(make(is_bot=True, mentions_bot=True))

    assert decision.speak is True


def test_ignores_a_bot_that_is_just_talking():
    decision = should_speak(make(is_bot=True, text="Живі гравці: 1. Неру 2. КЛ"))

    assert decision.speak is False
    assert decision.reason == "bot_not_addressed"


def test_bot_to_bot_exchange_dies_at_the_limit():
    decision = should_speak(make(is_bot=True, mentions_bot=True, bot_streak=3,
                                 bot_exchange_limit=3))

    assert decision.speak is False
    assert decision.reason == "bot_exchange_limit"


def test_bot_to_bot_exchange_is_allowed_below_the_limit():
    decision = should_speak(make(is_bot=True, mentions_bot=True, bot_streak=2,
                                 bot_exchange_limit=3))

    assert decision.speak is True


def test_the_streak_does_not_restrain_humans():
    decision = should_speak(make(mentions_bot=True, bot_streak=99, bot_exchange_limit=3))

    assert decision.speak is True


def test_never_answers_itself():
    decision = should_speak(make(is_self=True, is_bot=True, mentions_bot=True))

    assert decision.speak is False
    assert decision.reason == "sender_is_self"


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


def test_disabled_chat_is_checked_before_anything_else():
    decision = should_speak(make(chat_enabled=False, is_self=True, mentions_bot=True))

    assert decision.reason == "chat_disabled"


def test_empty_text_with_a_reply_to_the_bot_still_speaks():
    assert should_speak(make(text="", replies_to_bot=True)).speak is True


def test_a_stale_message_is_not_answered():
    decision = should_speak(make(mentions_bot=True, age_seconds=600, max_reply_age=300))

    assert decision.speak is False
    assert decision.reason == "too_old"


def test_a_fresh_message_is_answered():
    assert should_speak(make(mentions_bot=True, age_seconds=10)).speak is True


def test_staleness_is_checked_before_the_caps():
    decision = should_speak(
        make(mentions_bot=True, age_seconds=999, replies_today=999, daily_cap=1)
    )

    assert decision.reason == "too_old"


def test_says_nothing_while_it_is_already_writing():
    decision = should_speak(make(mentions_bot=True, busy=True))

    assert decision.speak is False
    assert decision.reason == "busy"


def test_the_first_few_replies_to_one_person_are_free():
    from gryag.gate import required_gap

    assert required_gap(0, 6, 15) == 0
    assert required_gap(5, 6, 15) == 0


def test_the_gap_grows_with_each_further_reply():
    from gryag.gate import required_gap

    assert required_gap(6, 6, 15) == 15
    assert required_gap(7, 6, 15) == 30
    assert required_gap(8, 6, 15) == 45


def test_an_active_conversation_is_not_throttled():
    """Regression: 3 free replies per 10 minutes silenced normal back-and-forth."""
    decision = should_speak(
        make(mentions_bot=True, user_recent_replies=5, seconds_since_user_reply=3)
    )

    assert decision.speak is True


def test_a_person_leaning_on_the_bot_is_slowed_down():
    decision = should_speak(
        make(mentions_bot=True, user_recent_replies=12, seconds_since_user_reply=10)
    )

    assert decision.speak is False
    assert decision.reason == "throttled"


def test_the_throttle_lets_them_through_once_they_wait():
    decision = should_speak(
        make(mentions_bot=True, user_recent_replies=12, seconds_since_user_reply=200)
    )

    assert decision.speak is True


def test_a_quiet_person_is_never_throttled():
    decision = should_speak(
        make(mentions_bot=True, user_recent_replies=1, seconds_since_user_reply=0)
    )

    assert decision.speak is True
