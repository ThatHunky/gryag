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
