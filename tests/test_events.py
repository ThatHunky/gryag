import types as pytypes

from gryag import events


def _message(**fields):
    """A Message with every service field absent unless named."""
    blank = {
        "new_chat_members": None,
        "left_chat_member": None,
        "pinned_message": None,
        "new_chat_title": None,
        "migrate_from_chat_id": None,
        "boost_added": None,
        "forum_topic_created": None,
        "forum_topic_edited": None,
        "text": None,
        "caption": None,
    }
    return pytypes.SimpleNamespace(**{**blank, **fields})


def test_an_ordinary_message_is_not_an_event():
    assert events.detect(_message(text="привіт")) is None


def test_somebody_joining():
    action, payload = events.detect(
        _message(new_chat_members=[pytypes.SimpleNamespace(id=7, full_name="Олег")])
    )

    assert action == "join"
    assert payload == {"members": ["Олег"], "member_ids": [7]}


def test_somebody_leaving():
    action, payload = events.detect(
        _message(left_chat_member=pytypes.SimpleNamespace(id=7, full_name="Олег"))
    )

    assert action == "leave"
    assert payload == {"members": ["Олег"], "member_ids": [7]}


def test_a_pin_records_what_was_pinned():
    action, payload = events.detect(
        _message(pinned_message=pytypes.SimpleNamespace(message_id=42, text="читайте правила"))
    )

    assert action == "pin"
    assert payload == {"message_id": 42, "text": "читайте правила"}


def test_a_rename_records_the_new_title():
    action, payload = events.detect(_message(new_chat_title="чат матсурі"))

    assert action == "title"
    assert payload == {"title": "чат матсурі"}


def test_a_migration_records_where_it_came_from():
    action, payload = events.detect(_message(migrate_from_chat_id=-100123))

    assert action == "migrate"
    assert payload == {"from_chat_id": -100123}


def test_a_boost():
    action, payload = events.detect(
        _message(boost_added=pytypes.SimpleNamespace(boost_count=2))
    )

    assert action == "boost"
    assert payload == {"boosts": 2}


def test_a_topic_being_created():
    action, payload = events.detect(
        _message(forum_topic_created=pytypes.SimpleNamespace(name="мафія"))
    )

    assert action == "topic"
    assert payload == {"title": "мафія"}


def test_a_topic_being_renamed():
    action, payload = events.detect(
        _message(forum_topic_edited=pytypes.SimpleNamespace(name="сєкрєтний чат"))
    )

    assert action == "topic"
    assert payload == {"title": "сєкрєтний чат"}


def test_every_action_the_detector_can_return_is_declared():
    """The importer maps a different vocabulary onto the same names. One list, or the
    stats block reads half a history."""
    for message in (
        _message(new_chat_title="x"),
        _message(migrate_from_chat_id=-1),
        _message(left_chat_member=pytypes.SimpleNamespace(id=1, full_name="a")),
    ):
        assert events.detect(message)[0] in events.ACTIONS
