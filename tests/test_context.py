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


def test_summaries_and_facts_appear_above_the_conversation():
    prompt = context.build(
        messages=[msg(text="привіт")],
        chain=[],
        trigger=msg(message_id=99, text="гряг шо"),
        now="n", chat_title="c",
        week_summary="тиждень про лінукс",
        today_summary="сьогодні сварилися",
        facts=[("oleh", "з Тернополя")],
    )

    assert prompt.index("тиждень про лінукс") < prompt.index("привіт")
    assert "Сьогодні: сьогодні сварилися" in prompt
    assert "Про присутніх: oleh — з Тернополя" in prompt


def test_each_memory_block_is_capped_here_not_upstream():
    """Caps are enforced where the prompt is built, not trusted from whatever wrote the
    summary. Legacy degraded exactly by letting these blocks creep."""
    prompt = context.build(
        messages=[], chain=[], trigger=msg(text="."), now="n", chat_title="c",
        week_summary="w" * 9000,
        today_summary="d" * 9000,
        facts=[("oleh", "f" * 9000)],
    )
    blocks = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1]
        for line in prompt.splitlines()
        if line.startswith(("За тиждень: ", "Сьогодні: ", "Про присутніх: "))
    }

    assert context.estimate_tokens(blocks["За тиждень"]) <= context.WEEK_SUMMARY_TOKENS
    assert context.estimate_tokens(blocks["Сьогодні"]) <= context.DAY_SUMMARY_TOKENS
    assert context.estimate_tokens(blocks["Про присутніх"]) <= context.FACTS_TOKENS


def test_absent_memory_adds_nothing():
    with_none = context.build(messages=[], chain=[], trigger=msg(text="г"), now="n", chat_title="c")
    with_empty = context.build(messages=[], chain=[], trigger=msg(text="г"), now="n",
                               chat_title="c", week_summary="", today_summary=None, facts=[])

    assert with_none == with_empty


def test_a_pretty_name_is_never_cut_mid_word():
    """`alias_for` truncates at eight characters to save prompt tokens, which is right for
    the live context and wrong for a document people read: it produced `Anonymou`,
    `андрійни` and `позорниц` in the first lore."""
    assert context.pretty_name("Anonymous", "Anonymou") == "Anonymous"
    assert context.pretty_name("андрійний колайдер", "андрійни") == "андрійний колайдер"
    assert context.pretty_name("DarkBlossom", "DarkBlos") == "DarkBlossom"


def test_a_pretty_name_drops_decoration():
    assert context.pretty_name("позорниця🇺🇦", "позорниц") == "позорниця"
    assert context.pretty_name("Markinim ^_^", "Markinim") == "Markinim"


def test_a_long_name_falls_back_to_its_first_word():
    assert (
        context.pretty_name("артемопокалипсис/локшина малинова", "артемопо")
        == "артемопокалипсис"
    )
    assert context.pretty_name("TikArchive | TikTok Downloader", "TikArchi") == "TikArchive"


def test_an_unusable_display_name_falls_back_to_the_alias():
    """One member's display name is 63 characters of keyboard mash, and their alias is
    the only readable name anybody has."""
    mash = "bshdhdhdhgehdifidhsvdjfofushsvdhjdiduegdjducudvehejsexicudhsvshz undefined"

    assert context.pretty_name(mash, "блеб") == "блеб"


def test_a_pretty_name_with_nothing_to_work_from():
    assert context.pretty_name("", "") == "хтось"
    assert context.pretty_name(None, None) == "хтось"


def test_gifs_and_audio_get_a_marker_like_every_other_kind():
    """Without one they render as an empty line, which is what `[без тексту]` came from."""
    assert context.render_line({"media_kind": "animation", "text": "", "alias": "o"}) == "o: [гіфка]"
    assert context.render_line({"media_kind": "audio", "text": "", "alias": "o"}) == "o: [аудіо]"


def test_a_person_who_shares_the_bots_name_is_told_apart_by_username():
    """@gria_g is a human whose display name is «гряг». Rendered plainly, the model sees
    two speakers with one name and cannot tell its own lines from theirs."""
    line = context.render_line(
        {"alias": "гряг", "display_name": "гряг", "username": "gria_g", "text": "я не бот"}
    )

    assert line == "гряг(@gria_g): я не бот"


def test_the_bot_itself_keeps_the_bare_name():
    line = context.render_line({"is_bot": True, "text": "я бот"})

    assert line == "гряг: я бот"


def test_a_namesake_with_no_username_is_still_told_apart():
    line = context.render_line({"alias": "гряг", "display_name": "гряг", "text": "теж я"})

    assert line == "гряг(не бот): теж я"


def test_everybody_else_is_untouched():
    assert context.render_line({"alias": "oleh", "username": "oleh", "text": "привіт"}) == "oleh: привіт"
