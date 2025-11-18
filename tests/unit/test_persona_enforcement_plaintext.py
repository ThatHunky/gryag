from app.handlers.chat import _enforce_plaintext_ukrainian


def test_enforce_plaintext_strips_markdown_and_code():
    text = "Ось код:\n```python\nprint('hi')\n```\nА тут `inline` і **жирний** та _курсив_."
    cleaned = _enforce_plaintext_ukrainian(text)
    assert "```" not in cleaned
    assert "`" not in cleaned
    assert "**" not in cleaned
    assert "_" not in cleaned
    # preserves Ukrainian content
    assert "Ось код:" in cleaned
    assert "А тут inline і жирний та курсив." in cleaned


def test_enforce_plaintext_strips_html():
    text = "<b>Привіт</b>, <i>світ</i>!"
    cleaned = _enforce_plaintext_ukrainian(text)
    assert "<b>" not in cleaned and "<i>" not in cleaned
    assert "Привіт, світ!" in cleaned
