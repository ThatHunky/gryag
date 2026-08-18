from gryag import images


def test_a_draw_verb_becomes_the_prompt():
    assert images.wants_image("гряг намалюй кота у вишиванці") == "кота у вишиванці"


def test_other_draw_verbs_are_recognised():
    assert images.wants_image("згенеруй мем про лінукс") == "мем про лінукс"
    assert images.wants_image("нарисуй, будь ласка, собаку") == "будь ласка, собаку"


def test_an_ordinary_message_is_not_a_draw_request():
    assert images.wants_image("гряг шо там по лінуксу") is None


def test_a_bare_verb_asks_for_nothing_in_particular():
    """It used to return the whole message, so the model drew the words "гряг намалюй"."""
    assert images.wants_image("гряг намалюй") == ""


def test_the_subject_prefers_what_was_actually_asked_for():
    assert images.subject_from("кота", "цитата", "батьківське", "розмова") == "кота"


def test_a_bare_request_falls_back_to_the_quoted_fragment():
    assert images.subject_from("", "два слова", "усе повідомлення", "розмова") == "два слова"


def test_then_to_the_message_being_replied_to():
    assert images.subject_from("", None, "усе повідомлення", "розмова") == "усе повідомлення"


def test_and_only_then_to_the_conversation():
    assert images.subject_from("", None, "", "про що говорили") == "про що говорили"


def test_nothing_to_draw_is_reported_as_such():
    assert images.subject_from("", None, "", None) is None
    assert images.subject_from("", None, "", "ок") is None


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
