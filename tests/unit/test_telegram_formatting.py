"""Tests for Telegram HTML formatting utilities."""


def test_format_for_telegram_basic_text():
    """Test basic text without special characters."""
    from app.handlers.chat import _format_for_telegram

    text = "Привіт, як справи?"
    result = _format_for_telegram(text)
    assert result == "Привіт, як справи?"


def test_format_for_telegram_html_escaping():
    """Test HTML special characters are escaped."""
    from app.handlers.chat import _format_for_telegram

    text = "Text with <html> & special > characters"
    result = _format_for_telegram(text)
    assert result == "Text with &lt;html&gt; &amp; special &gt; characters"


def test_format_for_telegram_spoiler_single():
    """Test single spoiler tag conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "Оце по-пацанськи. Бачиш, і без ||цицьок|| можна день зробити."
    result = _format_for_telegram(text)
    expected = "Оце по-пацанськи. Бачиш, і без <tg-spoiler>цицьок</tg-spoiler> можна день зробити."
    assert result == expected


def test_format_for_telegram_spoiler_multiple():
    """Test multiple spoiler tags."""
    from app.handlers.chat import _format_for_telegram

    text = "Є ||секрет1|| і ще ||секрет2|| тут."
    result = _format_for_telegram(text)
    expected = (
        "Є <tg-spoiler>секрет1</tg-spoiler> і ще <tg-spoiler>секрет2</tg-spoiler> тут."
    )
    assert result == expected


def test_format_for_telegram_spoiler_with_html():
    """Test spoiler content is HTML-escaped."""
    from app.handlers.chat import _format_for_telegram

    text = "Secret: ||<script>alert('xss')</script>||"
    result = _format_for_telegram(text)
    expected = "Secret: <tg-spoiler>&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;</tg-spoiler>"
    assert result == expected


def test_format_for_telegram_mixed_content():
    """Test text with spoilers and HTML characters."""
    from app.handlers.chat import _format_for_telegram

    text = "Це <важливо> & ||секретно||!"
    result = _format_for_telegram(text)
    expected = "Це &lt;важливо&gt; &amp; <tg-spoiler>секретно</tg-spoiler>!"
    assert result == expected


def test_format_for_telegram_empty_spoiler():
    """Test empty spoiler tags."""
    from app.handlers.chat import _format_for_telegram

    text = "Text with ||||empty|| spoiler"
    result = _format_for_telegram(text)
    # First || creates empty spoiler, then "empty||" is left (not matched)
    expected = "Text with <tg-spoiler></tg-spoiler>empty|| spoiler"
    assert result == expected


def test_format_for_telegram_none():
    """Test None input."""
    from app.handlers.chat import _format_for_telegram

    result = _format_for_telegram(None)
    assert result is None


def test_format_for_telegram_empty_string():
    """Test empty string."""
    from app.handlers.chat import _format_for_telegram

    result = _format_for_telegram("")
    assert result == ""


def test_format_for_telegram_no_spoilers():
    """Test text without spoilers but with pipes."""
    from app.handlers.chat import _format_for_telegram

    # Single | are fine, || without closing || are literal
    text = "Text | with | pipes | but not || spoilers"
    result = _format_for_telegram(text)
    # || needs matching closing ||, otherwise stays literal
    expected = "Text | with | pipes | but not || spoilers"
    assert result == expected


def test_format_for_telegram_nested_spoilers():
    """Test that nested spoilers don't work (by design)."""
    from app.handlers.chat import _format_for_telegram

    text = "||outer ||inner|| text||"
    result = _format_for_telegram(text)
    # Regex is non-greedy, so it matches first || to first ||
    # Result: <tg-spoiler>outer </tg-spoiler>inner<tg-spoiler> text</tg-spoiler>
    assert "<tg-spoiler>" in result
    # Just check it doesn't crash and produces valid HTML
    assert result.count("<tg-spoiler>") == result.count("</tg-spoiler>")


def test_format_for_telegram_bold_double_asterisk():
    """Test **bold** conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "This is **bold** text"
    result = _format_for_telegram(text)
    assert result == "This is <b>bold</b> text"


def test_format_for_telegram_bold_double_underscore():
    """Test __bold__ conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "This is __bold__ text"
    result = _format_for_telegram(text)
    assert result == "This is <b>bold</b> text"


def test_format_for_telegram_italic_single_asterisk():
    """Test *italic* conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "This is *italic* text"
    result = _format_for_telegram(text)
    assert result == "This is <i>italic</i> text"


def test_format_for_telegram_italic_single_underscore():
    """Test _italic_ conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "This is _italic_ text"
    result = _format_for_telegram(text)
    assert result == "This is <i>italic</i> text"


def test_format_for_telegram_strikethrough():
    """Test ~~strikethrough~~ conversion."""
    from app.handlers.chat import _format_for_telegram

    text = "це ~~теплий~~ крижаний"
    result = _format_for_telegram(text)
    assert result == "це <s>теплий</s> крижаний"


def test_format_for_telegram_multiple_strikethrough():
    """Test multiple strikethrough sections."""
    from app.handlers.chat import _format_for_telegram

    text = "~~wrong~~ right ~~also wrong~~ correct"
    result = _format_for_telegram(text)
    assert result == "<s>wrong</s> right <s>also wrong</s> correct"


def test_format_for_telegram_mixed_formatting():
    """Test mixed bold and italic."""
    from app.handlers.chat import _format_for_telegram

    text = "Це **жирний** і *курсив* текст"
    result = _format_for_telegram(text)
    assert result == "Це <b>жирний</b> і <i>курсив</i> текст"


def test_format_for_telegram_real_bot_message():
    """Test real bot message from screenshot."""
    from app.handlers.chat import _format_for_telegram

    text = "а можна без **Гряга** Він, здається, там *материнською платою* захлинувся"
    result = _format_for_telegram(text)
    assert (
        result
        == "а можна без <b>Гряга</b> Він, здається, там <i>материнською платою</i> захлинувся"
    )


def test_format_for_telegram_multiple_bold():
    """Test multiple bold sections."""
    from app.handlers.chat import _format_for_telegram

    text = "**батько** **виконав** **факт**"
    result = _format_for_telegram(text)
    assert result == "<b>батько</b> <b>виконав</b> <b>факт</b>"


def test_format_for_telegram_bold_with_html_inside():
    """Test bold text with HTML characters inside."""
    from app.handlers.chat import _format_for_telegram

    text = "This is **<important>** text"
    result = _format_for_telegram(text)
    expected = "This is <b>&lt;important&gt;</b> text"
    assert result == expected


def test_format_for_telegram_all_formats_combined():
    """Test text with spoilers, bold, italic and HTML characters."""
    from app.handlers.chat import _format_for_telegram

    text = "Це **важливо** & ||секретно|| і *красиво*!"
    result = _format_for_telegram(text)
    expected = (
        "Це <b>важливо</b> &amp; <tg-spoiler>секретно</tg-spoiler> і <i>красиво</i>!"
    )
    assert result == expected


def test_format_for_telegram_protected_bug():
    """
    Test the specific bug from screenshot: **PROTECTED1** and **PROTECTED2** showing literally.

    This was caused by placeholder text (\x00PROTECTED0\x00) being HTML-escaped,
    which broke the placeholder replacement logic.
    """
    from app.handlers.chat import _format_for_telegram

    # Simulate the problematic text from Gemini
    text = "щоб дула була велика. Тримай свою е-гюрлу в панчохах. А ви тям, **PROTECTED2**, перестаньте один одному порно-гiфки та' нєцiкаві' &Бокі слати, лясьно-шоу. Порошенко, бляха. Хлопці."
    result = _format_for_telegram(text)

    # Should properly convert **PROTECTED2** to <b>PROTECTED2</b>
    assert "<b>PROTECTED2</b>" in result

    # Should NOT contain literal **PROTECTED (bug symptom)
    assert "**PROTECTED" not in result

    # Should properly escape HTML entities
    assert "&amp;" in result

    # Full expected result (single quotes are also escaped by html.escape)
    expected = "щоб дула була велика. Тримай свою е-гюрлу в панчохах. А ви тям, <b>PROTECTED2</b>, перестаньте один одному порно-гiфки та&#x27; нєцiкаві&#x27; &amp;Бокі слати, лясьно-шоу. Порошенко, бляха. Хлопці."
    assert result == expected


def test_format_for_telegram_username_underscores():
    """
    Test that underscores in Telegram usernames are preserved.

    Bug: @vsevolod_dobrovolskyi was being formatted as @vsevolod<i>dobrovolskyi</i>
    because the underscore was treated as italic markdown.
    """
    from app.handlers.chat import _format_for_telegram

    # Test various username patterns
    tests = [
        ("@vsevolod_dobrovolskyi", "@vsevolod_dobrovolskyi"),
        ("@test_user_name", "@test_user_name"),
        ("@Qyyya_nya", "@Qyyya_nya"),
        (
            "Привіт @vsevolod_dobrovolskyi, як справи?",
            "Привіт @vsevolod_dobrovolskyi, як справи?",
        ),
        (
            "@user_name та **bold** і *italic*",
            "@user_name та <b>bold</b> і <i>italic</i>",
        ),
        ("@user_name це _курсив_", "@user_name це <i>курсив</i>"),
    ]

    for input_text, expected in tests:
        result = _format_for_telegram(input_text)
        assert (
            result == expected
        ), f"Failed for: {input_text}\nExpected: {expected}\nGot: {result}"


def test_format_for_telegram_markdownv2_escapes():
    """
    Test that MarkdownV2 escape sequences are removed.

    Bug: Gemini sometimes generates text with MarkdownV2 escapes (backslashes before special chars)
    which are needed for MarkdownV2 parse mode but should be removed for HTML parse mode.
    """
    from app.handlers.chat import _format_for_telegram

    tests = [
        # Basic escapes
        (r"Текст з \- тире", "Текст з - тире"),
        (r"Крапка\. в кінці", "Крапка. в кінці"),
        (r"\~ тильда \~", "~ тильда ~"),
        (r"\[дужки\]", "[дужки]"),
        (r"\(скобки\)", "(скобки)"),
        (r"Знак \+ плюс", "Знак + плюс"),
        (r"Знак \= рівності", "Знак = рівності"),
        (r"Вертикальна \| риска", "Вертикальна | риска"),
        # Mixed with actual formatting
        (r"Це **жирний\. текст**", "Це <b>жирний. текст</b>"),
        (r"\- Пункт списку", "- Пункт списку"),
        (r"\- @vsevolod_dobrovolskyi", "- @vsevolod_dobrovolskyi"),
        # Real example from screenshot
        (r"Це\, блять\, дуже важливо\!", "Це, блять, дуже важливо!"),
    ]

    for input_text, expected in tests:
        result = _format_for_telegram(input_text)
        assert (
            result == expected
        ), f"Failed for: {input_text}\nExpected: {expected}\nGot: {result}"


# LaTeX conversion tests
def test_convert_latex_inline_math():
    """Test inline LaTeX math conversion: $...$"""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$17_b$ це $b + 7$"
    result = _convert_latex_to_plaintext(text)
    assert result == "17_b це b + 7"


def test_convert_latex_display_math():
    """Test display LaTeX math conversion: $$...$$"""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$$x + y = z$$"
    result = _convert_latex_to_plaintext(text)
    assert result == "x + y = z"


def test_convert_latex_mixed_inline_display():
    """Test mixed inline and display math."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Inline: $a$ and display: $$b + c$$"
    result = _convert_latex_to_plaintext(text)
    assert result == "Inline: a and display: b + c"


def test_convert_latex_multiple_expressions():
    """Test multiple LaTeX expressions in one text."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$17_b$ це $b + 7$. Також $9b + 7 = 9(b + 7) - 56$"
    result = _convert_latex_to_plaintext(text)
    assert result == "17_b це b + 7. Також 9b + 7 = 9(b + 7) - 56"


def test_convert_latex_with_subscripts():
    """Test LaTeX expressions with subscripts."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$b + 7$ та $9b + 7$"
    result = _convert_latex_to_plaintext(text)
    assert result == "b + 7 та 9b + 7"


def test_convert_latex_real_example():
    """Test real example from the screenshot."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$17_b$ це $b + 7$. $97_b$ це $9b + 7$. Нам треба, щоб $(b + 7)$ ділило $(9b + 7)$."
    result = _convert_latex_to_plaintext(text)
    expected = "17_b це b + 7. 97_b це 9b + 7. Нам треба, щоб (b + 7) ділило (9b + 7)."
    assert result == expected


def test_convert_latex_with_regular_text():
    """Test LaTeX expressions mixed with regular text."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Це ж тупа маніпуляція з основами. $17_b$ це $b + 7$. Розписуємо: $9b + 7 = 9(b + 7) - 56$."
    result = _convert_latex_to_plaintext(text)
    expected = "Це ж тупа маніпуляція з основами. 17_b це b + 7. Розписуємо: 9b + 7 = 9(b + 7) - 56."
    assert result == expected


def test_convert_latex_no_math():
    """Test text without LaTeX math expressions."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Привіт, як справи?"
    result = _convert_latex_to_plaintext(text)
    assert result == "Привіт, як справи?"


def test_convert_latex_empty_string():
    """Test empty string."""
    from app.handlers.chat import _convert_latex_to_plaintext

    result = _convert_latex_to_plaintext("")
    assert result == ""


def test_convert_latex_none():
    """Test None input."""
    from app.handlers.chat import _convert_latex_to_plaintext

    result = _convert_latex_to_plaintext(None)
    assert result is None


def test_convert_latex_unmatched_dollar():
    """Test unmatched dollar sign (edge case)."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Це $незакритий вираз"
    result = _convert_latex_to_plaintext(text)
    # Should leave unmatched dollar as-is
    assert "$" in result


def test_convert_latex_dollar_in_text():
    """Test dollar sign used as currency (not LaTeX)."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Ціна: $100"
    result = _convert_latex_to_plaintext(text)
    # Single dollar at end shouldn't be treated as LaTeX
    assert "$" in result or result == "Ціна: $100"


def test_convert_latex_display_before_inline():
    """Test display math $$ before inline $ to ensure order doesn't matter."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "Display: $$x$$ and inline: $y$"
    result = _convert_latex_to_plaintext(text)
    assert result == "Display: x and inline: y"


def test_convert_latex_complex_expression():
    """Test complex LaTeX expression with multiple operations."""
    from app.handlers.chat import _convert_latex_to_plaintext

    text = "$b + 7 = 28 \\implies b = 21$"
    result = _convert_latex_to_plaintext(text)
    assert result == "b + 7 = 28 \\implies b = 21"
