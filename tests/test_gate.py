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


def test_another_bots_command_is_ignored():
    """This chat runs three other bots; /slots is a person talking to Пісюнбот."""
    decision = should_speak(make(text="/slots 1.6", own_commands=("gryag", "nb")))

    assert decision.speak is False
    assert decision.reason == "foreign_command"


def test_a_foreign_command_is_ignored_even_when_it_names_the_bot():
    decision = should_speak(
        make(text="/slots гряг подивись", own_commands=("gryag", "nb"))
    )

    assert decision.speak is False
    assert decision.reason == "foreign_command"


def test_our_own_commands_fall_through_to_the_admin_router():
    from gryag.gate import foreign_command

    assert foreign_command("/gryag", ("gryag", "nb")) is False
    assert foreign_command("/nb@gryag_bot", ("gryag", "nb")) is False
    assert foreign_command("/slots@pisunbot 1", ("gryag", "nb")) is True


def test_a_slash_in_the_middle_is_not_a_command():
    from gryag.gate import foreign_command

    assert foreign_command("це 50/50", ("gryag",)) is False


# ── ambient interjection ────────────────────────────────────────────────────────

def ambient(**overrides):
    base = dict(
        text="досить довге повідомлення про щось конкретне і цікаве",
        ambient_enabled=True,
        ambient_roll=0.0,
        ambient_probability=0.01,
        seconds_since_bot_spoke=9999,
        local_hour=14,
    )
    base.update(overrides)
    return make(**base)


def test_ambient_fires_when_the_dice_land():
    decision = should_speak(ambient())

    assert decision.speak is True
    assert decision.reason == "ambient"


def test_ambient_stays_off_until_it_is_enabled():
    assert should_speak(ambient(ambient_enabled=False)).reason == "not_addressed"


def test_ambient_respects_the_dice():
    assert should_speak(ambient(ambient_roll=0.9)).speak is False


def test_ambient_is_silent_during_quiet_hours():
    decision = should_speak(ambient(local_hour=4))

    assert decision.reason == "quiet_hours"


def test_ambient_waits_out_its_cooldown():
    decision = should_speak(ambient(seconds_since_bot_spoke=60))

    assert decision.reason == "ambient_cooldown"


def test_ambient_skips_short_messages():
    """Median message here is 19 characters; rolling on those spends interjections on 'ага'."""
    assert should_speak(ambient(text="ага")).reason == "not_worth_it"


def test_ambient_skips_media_with_no_words():
    assert should_speak(ambient(text="", media_only=True)).reason == "not_worth_it"


def test_ambient_does_not_butt_into_a_two_person_exchange():
    assert should_speak(ambient(is_reply_to_other=True)).reason == "not_worth_it"


def test_being_addressed_still_wins_over_every_ambient_rule():
    decision = should_speak(ambient(mentions_bot=True, local_hour=4, text="ага"))

    assert decision.speak is True
    assert decision.reason == "mention"


def test_quiet_hours_wrap_around_midnight():
    from gryag.gate import in_quiet_hours

    assert in_quiet_hours(23, 22, 6) is True
    assert in_quiet_hours(3, 22, 6) is True
    assert in_quiet_hours(12, 22, 6) is False
    assert in_quiet_hours(4, 2, 8) is True
    assert in_quiet_hours(9, 2, 8) is False


def test_quiet_hours_can_be_switched_off_by_equal_bounds():
    from gryag.gate import in_quiet_hours

    assert in_quiet_hours(3, 0, 0) is False


# ── proactive ───────────────────────────────────────────────────────────────────

def proactive(**overrides):
    from gryag.gate import ProactiveInput

    base = dict(
        chat_enabled=True,
        chat_muted=False,
        local_hour=10,
        quiet_from=2,
        quiet_to=8,
        silent_seconds=4 * 3600,
        silence_needed=3 * 3600,
        seconds_since_proactive=99999,
        proactive_cooldown=6 * 3600,
        has_context=True,
    )
    base.update(overrides)
    return ProactiveInput(**base)


def test_speaks_into_a_long_silence():
    from gryag.gate import should_start_talking

    decision = should_start_talking(proactive())

    assert decision.speak is True
    assert decision.reason == "proactive"


def test_does_not_speak_into_a_short_pause():
    from gryag.gate import should_start_talking

    assert should_start_talking(proactive(silent_seconds=600)).reason == "not_silent_enough"


def test_does_not_wake_the_chat_at_night():
    from gryag.gate import should_start_talking

    assert should_start_talking(proactive(local_hour=4)).reason == "quiet_hours"


def test_does_not_speak_twice_in_a_row():
    from gryag.gate import should_start_talking

    decision = should_start_talking(proactive(seconds_since_proactive=600))

    assert decision.reason == "proactive_cooldown"


def test_says_nothing_into_an_empty_chat():
    from gryag.gate import should_start_talking

    assert should_start_talking(proactive(has_context=False)).reason == "nothing_to_talk_about"


def test_a_muted_chat_is_left_alone():
    from gryag.gate import should_start_talking

    assert should_start_talking(proactive(chat_muted=True)).reason == "chat_muted"
