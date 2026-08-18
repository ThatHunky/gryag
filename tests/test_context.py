from gryag import context


def msg(**overrides) -> dict:
    base = dict(
        message_id=1,
        user_id=1,
        ts="2026-08-19T10:00:00",
        text="привіт",
        media_kind=None,
        file_id=None,
        reply_to=None,
        is_bot=False,
        alias="oleh",
        display_name="Олег",
    )
    base.update(overrides)
    return base


def test_alias_shortens_a_long_display_name():
    assert context.alias_for("Vsevolod Dobrovolskyi") == "Vsevolod"


def test_alias_falls_back_when_the_name_is_unusable():
    assert context.alias_for("٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.") != ""
    assert len(context.alias_for("٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.")) <= 8


def test_renders_a_plain_message():
    assert context.render_line(msg()) == "oleh: привіт"


def test_renders_media_as_a_marker():
    line = context.render_line(msg(text="", media_kind="photo"))

    assert line == "oleh: [фото]"


def test_media_with_a_caption_keeps_both():
    line = context.render_line(msg(text="гляньте", media_kind="photo"))

    assert line == "oleh: [фото] гляньте"


def test_bot_messages_are_labelled_as_the_bot():
    assert context.render_line(msg(is_bot=True, text="ага")).startswith("гряг:")


def test_drops_messages_from_other_bots():
    assert context.is_context_worthy(msg(alias="Пісюнбот", is_bot=False, text="")) is False


def test_keeps_a_media_message_that_has_a_kind():
    assert context.is_context_worthy(msg(text="", media_kind="photo")) is True


def test_drops_an_empty_message_with_no_media():
    assert context.is_context_worthy(msg(text="", media_kind=None)) is False


def test_estimate_tokens_uses_the_measured_ratio():
    assert context.estimate_tokens("a" * 250) == 100


def test_clamp_leaves_short_text_alone():
    assert context.clamp("короткий", 100) == "короткий"


def test_clamp_cuts_long_text_to_the_budget():
    clamped = context.clamp("я" * 1000, 10)

    assert len(clamped) <= 25


def test_build_ends_with_the_boundary_and_the_trigger():
    prompt = context.build(
        messages=[msg(message_id=1, text="перше"), msg(message_id=2, text="друге")],
        chain=[],
        trigger=msg(message_id=3, text="гряг шо"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert "перше" in prompt
    assert prompt.index("перше") < prompt.index("друге")
    assert context.BOUNDARY in prompt
    assert prompt.strip().endswith("oleh: гряг шо")


def test_build_puts_the_reply_chain_before_the_window_without_duplicating():
    prompt = context.build(
        messages=[msg(message_id=5, text="вікно")],
        chain=[msg(message_id=1, text="корінь"), msg(message_id=5, text="вікно")],
        trigger=msg(message_id=6, text="гряг шо"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert prompt.count("вікно") == 1
    assert prompt.index("корінь") < prompt.index("вікно")


def test_build_includes_the_header():
    prompt = context.build(
        messages=[],
        chain=[],
        trigger=msg(text="гряг"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert "2026-08-19 10:00, середа" in prompt
    assert "матсурі" in prompt


def test_a_partial_quote_is_shown_to_the_model():
    prompt = context.build(
        messages=[],
        chain=[],
        trigger=msg(text="NixOS?"),
        now="2026-08-19 01:05, середа",
        chat_title="матсурі",
        quote="Нікос",
        quote_author="гряг",
    )

    assert "цитує з гряг: «Нікос»" in prompt
    assert prompt.index("Нікос") < prompt.index("NixOS?")


def test_no_quote_changes_nothing():
    without = context.build(
        messages=[], chain=[], trigger=msg(text="NixOS?"),
        now="n", chat_title="c",
    )
    with_empty = context.build(
        messages=[], chain=[], trigger=msg(text="NixOS?"),
        now="n", chat_title="c", quote="   ",
    )

    assert without == with_empty


def test_quote_without_an_author_still_renders():
    assert context.render_quote("Нікос", None) == "(цитує: «Нікос»)"
