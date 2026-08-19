"""The killboard is never called from a test. This payload is a real one, captured from
https://sbs-group.army/api/public/statistics/… on 2026-08-19 and trimmed to five target
classes; the shape is exactly what the API returns."""

from gryag import pidrahuika

PAYLOAD = {
    "personnel": {"killed": 168, "wounded": 182},
    "flights": {"strike": 3822, "recon": 2904},
    "status": "completed",
    "lastUpdated": "2026-08-19T16:41:00.022Z",
    "totalTargetsHit": 1575,
    "totalTargetsDestroyed": 630,
    "targetsByType": [
        {"targetClassId": 1, "targetClass": "Танки", "hit": 0, "destroyed": 0},
        {"targetClassId": 15, "targetClass": "ОС РОВ", "hit": 350, "destroyed": 168},
        {"targetClassId": 21, "targetClass": "Укриття", "hit": 406, "destroyed": 17},
        {"targetClassId": 25, "targetClass": "Ворожі крила", "hit": 206, "destroyed": 202},
        {"targetClassId": 30, "targetClass": "Шахеди", "hit": 7, "destroyed": 7},
    ],
}


def test_parsing_pulls_out_the_headline_numbers():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert report.killed == 168
    assert report.wounded == 182
    assert report.hit == 1575
    assert report.destroyed == 630
    assert report.strike == 3822
    assert report.collected is True


def test_the_top_is_ordered_by_what_was_destroyed():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert report.top[0] == ("Ворожі крила", 206, 202)
    assert report.top[1] == ("ОС РОВ", 350, 168)


def test_categories_with_nothing_in_them_are_left_out():
    report = pidrahuika.parse(PAYLOAD, "2026-08-19")

    assert all(name != "Танки" for name, _hit, _dead in report.top)


def test_totals_are_summed_when_the_api_omits_them():
    payload = {k: v for k, v in PAYLOAD.items() if not k.startswith("total")}

    report = pidrahuika.parse(payload, "2026-08-19")

    assert report.hit == 969
    assert report.destroyed == 394


def test_a_day_the_board_has_not_counted_yet_is_marked_uncollected():
    report = pidrahuika.parse({**PAYLOAD, "status": "not_collected"}, "2026-08-19")

    assert report.collected is False


def test_a_payload_missing_everything_does_not_explode():
    report = pidrahuika.parse({}, "2026-08-19")

    assert report.killed == 0
    assert report.top == ()
    assert report.collected is False


def test_rendering_names_the_day_in_ukrainian():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "нормальна робота")

    assert "19 серпня" in text


def test_rendering_carries_the_numbers_and_the_comment():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "нормальна робота")

    assert "168" in text
    assert "1575" in text
    assert "Ворожі крила" in text
    assert "нормальна робота" in text


def test_rendering_shows_the_change_against_the_day_before():
    today = pidrahuika.parse(PAYLOAD, "2026-08-19")
    yesterday = pidrahuika.parse({**PAYLOAD, "totalTargetsDestroyed": 500}, "2026-08-18")

    text = pidrahuika.render(today, yesterday, "нормальна робота")

    assert "+130" in text


def test_rendering_without_a_previous_day_says_nothing_about_change():
    text = pidrahuika.render(pidrahuika.parse(PAYLOAD, "2026-08-19"), None, "x")

    assert "+" not in text.split("Вильоти")[0]


def test_only_the_top_n_categories_are_shown():
    many = {
        **PAYLOAD,
        "targetsByType": [
            {"targetClassId": i, "targetClass": f"клас {i}", "hit": i, "destroyed": i}
            for i in range(1, 20)
        ],
    }

    report = pidrahuika.parse(many, "2026-08-19")

    assert len(report.top) == pidrahuika.TOP_N
