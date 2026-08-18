from gryag import config, menu


def test_every_setting_points_at_a_real_config_key():
    for _title, settings in menu.SECTIONS.values():
        for setting in settings:
            assert setting.key in config.DEFAULTS, setting.key


def test_every_default_is_one_of_the_offered_choices():
    """A default the menu cannot display would show as a raw value and cycle oddly."""
    for _title, settings in menu.SECTIONS.values():
        for setting in settings:
            assert config.DEFAULTS[setting.key] in [c.value for c in setting.choices]


def test_cycling_walks_the_ring_and_wraps():
    setting = menu.SECTIONS["model"][1][2]

    assert menu.cycle(setting, "0") == "-1"
    assert menu.cycle(setting, "-1") == "0"


def test_cycling_from_an_unknown_value_starts_over():
    setting = menu.SECTIONS["model"][1][2]

    assert menu.cycle(setting, "512") == "0"


def test_labels_fall_back_to_the_raw_value():
    setting = menu.SECTIONS["model"][1][0]

    assert setting.label_for("gemini-2.5-flash") == "2.5 flash"
    assert setting.label_for("gemini-9") == "gemini-9"


def test_button_labels_stay_short_enough_not_to_be_truncated():
    """Telegram ellipsises anything much past eight characters when several buttons share
    a row, which is how "замовкни 1 год" became "замовкни …" three times over."""
    for choice in menu.MUTE_CHOICES:
        assert len(choice.label) <= 8, choice.label


def test_setting_titles_and_values_fit_on_one_button():
    for _title, settings in menu.SECTIONS.values():
        for setting in settings:
            for choice in setting.choices:
                assert len(f"{setting.title}: {choice.label}") <= 34
