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


def test_every_screen_has_a_unique_key_and_a_short_title():
    keys = [s.key for s in menu.SCREENS]

    assert len(keys) == len(set(keys))
    for screen in menu.SCREENS:
        assert len(screen.title) <= 14, screen.title


def test_every_tab_a_screen_names_is_a_real_section():
    for screen in menu.SCREENS:
        for tab in screen.tabs:
            assert tab in menu.SECTIONS, (screen.key, tab)


def test_every_section_is_reachable_from_some_screen():
    """A section nobody can navigate to is a setting nobody can change."""
    reachable = {tab for screen in menu.SCREENS for tab in screen.tabs}

    assert reachable == set(menu.SECTIONS)


def test_looking_up_a_screen_by_key():
    assert menu.screen("game").title == "Гра"


def test_looking_up_a_screen_that_does_not_exist_falls_back_to_the_first():
    """Callback data outlives deploys: a button from yesterday's layout must not raise."""
    assert menu.screen("nope") is menu.SCREENS[0]


def test_the_lore_section_exists_and_names_every_knob_the_spec_lists():
    keys = [s.key for s in menu.SECTIONS["lore"][1]]

    assert keys == [
        "lore_enabled", "lore_model", "lore_interval_days",
        "lore_thinking", "lore_max_chars",
    ]


def test_every_model_the_lore_offers_has_a_price():
    from gryag import llm

    setting = next(s for s in menu.SECTIONS["lore"][1] if s.key == "lore_model")
    assert all(choice.value in llm.PRICES for choice in setting.choices)


def test_the_lore_has_a_screen_of_its_own():
    assert menu.screen("lore").title == "Лор"
