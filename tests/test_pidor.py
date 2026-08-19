from datetime import datetime, timezone

import pytest

from gryag import admin, config, pidor, store


def test_a_day_is_the_kyiv_day_not_the_utc_one():
    """22:30 UTC is already tomorrow in Kyiv. On UTC days the game would roll over at
    03:00 local, in the hours where nobody would see it happen."""
    late = datetime(2026, 8, 19, 22, 30, tzinfo=timezone.utc)

    assert pidor.kyiv_day(late) == "2026-08-20"


def test_an_ordinary_afternoon_is_its_own_day():
    assert pidor.kyiv_day(datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)) == "2026-08-19"


def test_too_few_candidates_means_nobody_is_chosen():
    assert pidor.choose([1, 2], previous=None, roll=0.5, min_players=3) is None


def test_the_roll_picks_across_the_whole_pool():
    pool = [10, 20, 30, 40]

    assert pidor.choose(pool, None, 0.0, 3) == 10
    assert pidor.choose(pool, None, 0.99, 3) == 40


def test_yesterdays_winner_is_left_out():
    pool = [10, 20, 30, 40]

    assert pidor.choose(pool, previous=10, roll=0.0, min_players=3) == 20


def test_yesterdays_winner_comes_back_when_dropping_them_empties_the_pool():
    """Three people and a repeat is chance. Three people and a refusal is a broken game."""
    pool = [10, 20, 30]

    assert pidor.choose(pool, previous=10, roll=0.0, min_players=3) == 10


def test_a_roll_of_exactly_one_stays_in_range():
    assert pidor.choose([10, 20, 30], None, 1.0, 3) == 30


def test_a_username_is_mentioned_by_handle():
    assert pidor.mention(7, "nailsad_eleos", "Віталій") == "@nailsad_eleos"


def test_somebody_without_a_username_gets_a_link():
    assert pidor.mention(7, None, "Віталій") == '<a href="tg://user?id=7">Віталій</a>'


def test_a_name_with_html_in_it_is_escaped():
    """A display name is user-controlled text going into a parse_mode="HTML" message."""
    assert pidor.mention(7, None, "<b>x</b>") == '<a href="tg://user?id=7">&lt;b&gt;x&lt;/b&gt;</a>'


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str, str | None]] = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.sent.append((chat_id, text, parse_mode))

        class Sent:
            # Well clear of the ids _populate hands the humans: save_message drops a
            # duplicate silently, and a collision would look like nothing being stored.
            message_id = 1000 + len(self.sent)

        return Sent()


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(pidor, "SHOW_DELAY", 0)


async def _populate(db, chat_id=-100, people=(1, 2, 3, 4)):
    await admin.enable_chat(db, chat_id, "матсурі")
    for user_id in people:
        await store.upsert_user(
            db,
            chat_id=chat_id,
            user_id=user_id,
            display_name=f"людина {user_id}",
            alias=f"людина{user_id}",
            username=f"user{user_id}",
        )
        await store.save_message(
            db,
            chat_id=chat_id,
            message_id=user_id,
            user_id=user_id,
            ts="2026-08-19T10:00:00+00:00",
            text="привіт",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )


async def test_rolling_picks_somebody_and_says_it_is_new(db):
    await _populate(db)

    result = await pidor.roll(db, -100, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert result is not None
    winner, is_new = result
    assert winner in (1, 2, 3, 4)
    assert is_new is True


async def test_rolling_twice_in_a_day_returns_the_same_person(db):
    await _populate(db)
    now = datetime(2026, 8, 19, 12, tzinfo=timezone.utc)

    first, _ = await pidor.roll(db, -100, now)
    second, is_new = await pidor.roll(db, -100, now)

    assert second == first
    assert is_new is False


async def test_an_empty_chat_cannot_be_rolled(db):
    await admin.enable_chat(db, -100, "матсурі")

    assert await pidor.roll(db, -100, datetime(2026, 8, 19, 12, tzinfo=timezone.utc)) is None


async def test_announcing_sends_the_show_and_mentions_the_winner(db):
    await _populate(db)
    bot = FakeBot()

    await pidor.announce(bot, db, -100, 3, True, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert len(bot.sent) == 3
    assert "@user3" in bot.sent[-1][1]
    assert bot.sent[-1][2] == "HTML"


async def test_announcing_an_old_winner_is_one_message(db):
    await _populate(db)
    bot = FakeBot()

    await pidor.announce(bot, db, -100, 3, False, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert len(bot.sent) == 1


async def test_the_announcement_is_stored_as_the_bots_own_message(db):
    await _populate(db)
    bot = FakeBot()

    await pidor.announce(bot, db, -100, 3, True, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1", (-100,)
    ) as cur:
        stored = (await cur.fetchone())[0]

    assert stored == 3


async def test_the_leaderboard_names_people_and_counts(db):
    await _populate(db)
    await store.pidor_record(db, -100, "2026-08-18", 2, "2026-08-18T09:00:00+00:00")
    await store.pidor_record(db, -100, "2026-08-19", 2, "2026-08-19T09:00:00+00:00")

    text = await pidor.leaderboard_text(db, -100, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert "людина 2" in text
    assert "2" in text


async def test_the_leaderboard_says_so_when_nobody_has_won_yet(db):
    await _populate(db)

    text = await pidor.leaderboard_text(db, -100, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert "ще нікого" in text


async def test_the_bot_rolls_by_itself_once_the_hour_has_passed(db):
    await _populate(db)
    bot = FakeBot()

    # 13:30 Kyiv is 10:30 UTC in summer, and the default announce hour is 13.
    spoken = await pidor.announce_due(db, bot, datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc))

    assert spoken == 1
    assert len(bot.sent) == 3


async def test_the_bot_stays_quiet_before_the_hour(db):
    await _populate(db)
    bot = FakeBot()

    spoken = await pidor.announce_due(db, bot, datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc))

    assert spoken == 0
    assert bot.sent == []


async def test_the_bot_does_not_announce_what_somebody_already_rolled(db):
    await _populate(db)
    now = datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc)
    await pidor.roll(db, -100, now)
    bot = FakeBot()

    assert await pidor.announce_due(db, bot, now) == 0


async def test_a_muted_chat_is_left_alone(db):
    await _populate(db)
    await store.set_mute(db, -100, "2126-01-01T00:00:00+00:00")
    bot = FakeBot()

    assert await pidor.announce_due(db, bot, datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc)) == 0


async def test_the_schedule_can_be_switched_off(db):
    await _populate(db)
    await config.set(db, "pidor_announce_hour", "-1", chat_id=-100)
    bot = FakeBot()

    assert await pidor.announce_due(db, bot, datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc)) == 0


async def test_a_disabled_game_is_not_announced(db):
    await _populate(db)
    await config.set(db, "pidor_enabled", "0", chat_id=-100)
    bot = FakeBot()

    assert await pidor.announce_due(db, bot, datetime(2026, 8, 19, 10, 30, tzinfo=timezone.utc)) == 0


async def test_a_switched_off_game_says_so_rather_than_going_quiet(db):
    """Same reasoning as the killboard command: silence reads as a broken bot."""
    from tests.conftest import FakeMessage

    await _populate(db)
    await config.set(db, "pidor_enabled", "0", chat_id=-100)
    message = FakeMessage(text="/pidor")

    await pidor.play_command(message, db)

    assert message.replies
    assert "вимкнен" in message.replies[0]


async def test_the_leaderboard_reply_is_stored(db):
    from tests.conftest import FakeMessage

    await _populate(db)

    await pidor.stats_command(FakeMessage(text="/pidorstats"), db)

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1", (-100,)
    ) as cur:
        assert (await cur.fetchone())[0] == 1
