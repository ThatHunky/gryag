from gryag import images


def test_a_draw_verb_becomes_the_prompt():
    assert images.wants_image("гряг намалюй кота у вишиванці") == "кота у вишиванці"


def test_other_draw_verbs_are_recognised():
    assert images.wants_image("згенеруй мем про лінукс") == "мем про лінукс"
    assert images.wants_image("нарисуй, будь ласка, собаку") == "будь ласка, собаку"


def test_an_ordinary_message_is_not_a_draw_request():
    assert images.wants_image("гряг шо там по лінуксу") is None


def test_a_bare_verb_falls_back_to_the_whole_message():
    assert images.wants_image("намалюй") == "намалюй"


def test_edit_words_are_detected():
    assert images.wants_edit("додай йому окуляри") is True
    assert images.wants_edit("що це таке") is False


def test_the_whitelist_is_checked_exactly():
    assert images.is_allowed(392817811, "392817811") is True
    assert images.is_allowed(39281781, "392817811") is False
    assert images.is_allowed(111, "392817811, 111") is True
    assert images.is_allowed(111, "") is False


def test_whitelist_round_trips():
    assert images.parse_whitelist("392817811, 111") == [392817811, 111]
    assert images.render_whitelist([392817811, 111, 111]) == "392817811,111"
