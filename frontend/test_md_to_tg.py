"""Tests for the Markdown → Telegram HTML converter."""

from md_to_tg import md_to_telegram_html


def test_bold():
    assert md_to_telegram_html("**hello**") == "<b>hello</b>"
    assert md_to_telegram_html("__hello__") == "<b>hello</b>"


def test_italic():
    assert md_to_telegram_html("*hello*") == "<i>hello</i>"
    assert md_to_telegram_html("_hello_") == "<i>hello</i>"


def test_bold_italic():
    assert md_to_telegram_html("***hello***") == "<b><i>hello</i></b>"


def test_strikethrough():
    assert md_to_telegram_html("~~hello~~") == "<s>hello</s>"


def test_inline_code():
    assert md_to_telegram_html("`print('hi')`") == "<code>print(&#x27;hi&#x27;)</code>"


def test_code_block():
    md = "```python\nprint('hi')\n```"
    result = md_to_telegram_html(md)
    assert '<pre><code class="language-python">' in result
    assert "print(&#x27;hi&#x27;)" in result


def test_code_block_no_language():
    md = "```\nhello world\n```"
    result = md_to_telegram_html(md)
    assert "<pre>hello world</pre>" in result


def test_link():
    assert md_to_telegram_html("[click](https://example.com)") == '<a href="https://example.com">click</a>'


def test_header_to_bold():
    assert md_to_telegram_html("# Title") == "<b>Title</b>"
    assert md_to_telegram_html("### Sub") == "<b>Sub</b>"


def test_bullet_points():
    md = "- item one\n- item two"
    result = md_to_telegram_html(md)
    assert "• item one" in result
    assert "• item two" in result


def test_html_escaping():
    assert md_to_telegram_html("1 < 2 & 3 > 1") == "1 &lt; 2 &amp; 3 &gt; 1"


def test_code_block_not_parsed():
    """Code blocks should NOT have inner markdown converted."""
    md = "```\n**not bold** *not italic*\n```"
    result = md_to_telegram_html(md)
    assert "<b>" not in result
    assert "<i>" not in result


def test_underscore_in_words():
    """Underscores inside words like variable_name should NOT be converted."""
    assert md_to_telegram_html("some_variable_name") == "some_variable_name"


def test_mixed():
    md = "**Bold** and *italic* with `code` and [link](http://x.com)"
    result = md_to_telegram_html(md)
    assert "<b>Bold</b>" in result
    assert "<i>italic</i>" in result
    assert "<code>code</code>" in result
    assert '<a href="http://x.com">link</a>' in result


def test_empty():
    assert md_to_telegram_html("") == ""
    assert md_to_telegram_html(None) is None


def test_no_markdown():
    assert md_to_telegram_html("just plain text") == "just plain text"
