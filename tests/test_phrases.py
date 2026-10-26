import re

from gryag import phrases


def test_no_pool_is_empty():
    for name in ("WARMUP", "VERDICT", "ALREADY", "DIGEST"):
        assert len(getattr(phrases, name)) >= 20, name


def test_every_verdict_names_exactly_one_person():
    """A template with two {who} formats fine and reads like a bug; one with none formats
    fine and never names anybody."""
    for line in phrases.VERDICT + phrases.ALREADY:
        assert line.count("{who}") == 1, line


def test_every_verdict_formats():
    for line in phrases.VERDICT + phrases.ALREADY:
        assert "гряг" in line.format(who="гряг")


def test_warmup_and_digest_carry_no_placeholders():
    for line in phrases.WARMUP + phrases.DIGEST:
        assert "{" not in line, line


def test_nothing_repeats():
    for name in ("WARMUP", "VERDICT", "ALREADY", "DIGEST"):
        pool = getattr(phrases, name)
        assert len(set(pool)) == len(pool), name


def test_picking_is_stable_for_the_same_seed():
    assert phrases.pick(phrases.WARMUP, 7) == phrases.pick(phrases.WARMUP, 7)


def test_picking_spreads_across_the_pool():
    seen = {phrases.pick(phrases.WARMUP, seed) for seed in range(200)}

    assert len(seen) > 10


def test_the_by_the_white_idiom_names_the_language_the_bot_speaks():
    """«русским по белому» is an idiom about the language the speaker just spoke. Carrying
    the frame into Ukrainian but leaving the language word alone had гряг insisting, in a
    Ukrainian sentence, that it had said it in Russian."""
    for name in ("WARMUP", "VERDICT", "ALREADY", "DIGEST"):
        for line in getattr(phrases, name):
            if "по білому" in line:
                assert "українською по білому" in line, line


# {who} is whoever won, women included, and a display name cannot be declined.
_WINNER_PAST_AFTER = re.compile(r"\{who\},?\s+(?:вже\s+|уже\s+|сьогодні\s+|знову\s+|і\s+)?\w+(?:в|вся)\b")
_WINNER_PAST_BEFORE = re.compile(r"\b\w+(?:ав|ив|ів|ов|вся|міг)\s+\{who\}")
_ADDRESSED_PAST = re.compile(r"\bти\s+(?:\w+\s+)?\w+(?:ав|ив|ів|ов|ався|ився)\b")
_PREPOSITION = re.compile(r"\b(?:до|для|від|у|в|на|руках|користувачу)\s+\{who\}", re.IGNORECASE)


def test_no_line_puts_the_winner_in_the_masculine():
    """«Vitalina, ти йшов до цього успіху» is what the draw produced for a woman."""
    for line in phrases.VERDICT + phrases.ALREADY:
        assert not _WINNER_PAST_AFTER.search(line), line
        assert not _WINNER_PAST_BEFORE.search(line), line
        assert not _ADDRESSED_PAST.search(line), line


def test_no_line_declines_the_winners_name():
    """«увага прикута до Надя»: the name lands where Ukrainian needs another case."""
    for line in phrases.VERDICT + phrases.ALREADY:
        assert not _PREPOSITION.search(line), line


def test_no_two_repeats_share_a_punchline():
    """Exact duplicates are caught above; this catches the same joke with a new opener."""
    for pool in (phrases.VERDICT, phrases.ALREADY):
        tails = [line.split("{who}", 1)[1].strip(" .,:—") for line in pool]
        tails = [t for t in tails if len(t) > 15]
        assert len(set(tails)) == len(tails)
