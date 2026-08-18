import pytest

from gryag import config


async def test_returns_the_default_when_nothing_is_set(db):
    assert await config.get(db, "speak_model") == "gemini-flash-latest"


async def test_global_override_wins_over_the_default(db):
    await config.set(db, "speak_model", "gemini-2.5-flash")

    assert await config.get(db, "speak_model") == "gemini-2.5-flash"


async def test_chat_override_wins_over_the_global_one(db):
    await config.set(db, "speak_model", "gemini-2.5-flash")
    await config.set(db, "speak_model", "gemini-3.7-flash", chat_id=-100)

    assert await config.get(db, "speak_model", chat_id=-100) == "gemini-3.7-flash"
    assert await config.get(db, "speak_model", chat_id=-200) == "gemini-2.5-flash"


async def test_setting_a_value_twice_updates_it(db):
    await config.set(db, "speak_model", "a")
    await config.set(db, "speak_model", "b")

    assert await config.get(db, "speak_model") == "b"


async def test_get_int_parses_numeric_settings(db):
    await config.set(db, "context_messages", "12")

    assert await config.get_int(db, "context_messages") == 12


async def test_unknown_key_is_a_programming_error(db):
    with pytest.raises(KeyError):
        await config.get(db, "no_such_key")


async def test_all_for_chat_merges_every_layer(db):
    await config.set(db, "daily_reply_cap", "99")
    await config.set(db, "speak_model", "gemini-2.5-flash", chat_id=-100)

    merged = await config.all_for_chat(db, -100)

    assert merged["daily_reply_cap"] == "99"
    assert merged["speak_model"] == "gemini-2.5-flash"
    assert merged["thinking_budget"] == "0"


async def test_reply_caps_are_high_enough_for_a_busy_chat(db):
    """Regression: the first values, 60/day and 10/hour, silenced the bot within an
    evening of people trying it out. The valve is for runaway loops, not for rationing."""
    assert await config.get_int(db, "hourly_reply_cap") >= 300
    assert await config.get_int(db, "daily_reply_cap") >= 1500
