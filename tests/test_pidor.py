from datetime import datetime, timezone

from gryag import pidor


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
