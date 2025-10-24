"""
Unit tests for Markdown escaping in chat handlers.

Tests the _escape_markdown function to ensure MarkdownV2 special characters
are properly escaped for Telegram.
"""

import pytest
from app.handlers.chat import _escape_markdown


class TestEscapeMarkdown:
    """Test MarkdownV2 character escaping."""

    def test_basic_text_unchanged(self):
        """Plain text without special chars should pass through."""
        text = "Hello world"
        assert _escape_markdown(text) == "Hello world"

    def test_dash_escaping(self):
        """Dashes must be escaped in MarkdownV2."""
        text = "Test - with dashes"
        assert _escape_markdown(text) == r"Test \- with dashes"

    def test_multiple_dashes(self):
        """Multiple dashes should all be escaped."""
        text = "one-two-three"
        assert _escape_markdown(text) == r"one\-two\-three"

    def test_parentheses_escaping(self):
        """Parentheses must be escaped."""
        text = "Text (with parens)"
        assert _escape_markdown(text) == r"Text \(with parens\)"

    def test_brackets_escaping(self):
        """Brackets must be escaped."""
        text = "Text [with brackets]"
        assert _escape_markdown(text) == r"Text \[with brackets\]"

    def test_dots_and_exclamation(self):
        """Dots and exclamation marks must be escaped."""
        text = "Hello! How are you?"
        assert _escape_markdown(text) == r"Hello\! How are you?"

    def test_hash_and_plus(self):
        """Hash and plus signs must be escaped."""
        text = "User#123 + more"
        assert _escape_markdown(text) == r"User\#123 \+ more"

    def test_backticks_escaping(self):
        """Backticks must be escaped."""
        text = "Code: `example`"
        assert _escape_markdown(text) == r"Code: \`example\`"

    def test_asterisk_preserved(self):
        """Asterisks for bold should be preserved."""
        text = "This is *bold* text"
        # Asterisks are NOT escaped to allow MarkdownV2 formatting
        assert _escape_markdown(text) == r"This is *bold* text"

    def test_underscore_preserved(self):
        """Underscores for italic should be preserved."""
        text = "This is _italic_ text"
        # Underscores are NOT escaped to allow MarkdownV2 formatting
        assert _escape_markdown(text) == r"This is _italic_ text"

    def test_list_bullets_preserved(self):
        """List bullets should be preserved."""
        text = "* Item one\n* Item two"
        result = _escape_markdown(text)
        # Bullets should be preserved
        assert result.startswith("* Item")

    def test_mixed_special_characters(self):
        """Text with multiple special characters."""
        text = "Hello! Check (this) - #awesome"
        assert _escape_markdown(text) == r"Hello\! Check \(this\) \- \#awesome"

    def test_ukrainian_text_with_dash(self):
        """Ukrainian text with dash (real-world example)."""
        text = "гряг, живий?"
        # Question mark needs escaping, but Ukrainian letters don't
        assert _escape_markdown(text) == r"гряг, живий?"

    def test_empty_text(self):
        """Empty text should return as-is."""
        assert _escape_markdown("") == ""
        assert _escape_markdown(None) is None

    def test_backslash_escaping(self):
        """Backslashes must be escaped first."""
        text = "Text with \\ backslash"
        assert _escape_markdown(text) == r"Text with \\ backslash"

    def test_curly_braces_escaping(self):
        """Curly braces must be escaped."""
        text = "Object: {key: value}"
        assert _escape_markdown(text) == r"Object: \{key: value\}"

    def test_pipe_escaping(self):
        """Pipe character must be escaped."""
        text = "Column1 | Column2"
        assert _escape_markdown(text) == r"Column1 \| Column2"

    def test_angle_brackets_escaping(self):
        """Angle brackets must be escaped."""
        text = "Link: <https://example.com>"
        assert _escape_markdown(text) == r"Link: \<https://example\.com\>"

    def test_equals_escaping(self):
        """Equals sign must be escaped."""
        text = "A = B + C"
        assert _escape_markdown(text) == r"A \= B \+ C"

    def test_bold_with_special_chars_around(self):
        """Bold formatting with special characters around should work."""
        text = "**батько** (@username)"
        result = _escape_markdown(text)
        # Bold should be preserved, parentheses and @ should be escaped
        assert result == r"**батько** \(@username\)"

    def test_italic_with_special_chars(self):
        """Italic formatting with special characters around should work."""
        text = "_котошлюшки_ в панчохах."
        result = _escape_markdown(text)
        # Italic should be preserved, period should be escaped
        assert result == r"_котошлюшки_ в панчохах\."

    def test_mixed_bold_and_italic(self):
        """Mixed bold and italic formatting should both be preserved."""
        text = "This is **bold** and this is _italic_ text."
        result = _escape_markdown(text)
        assert result == r"This is **bold** and this is _italic_ text\."

    def test_nested_formatting(self):
        """Nested formatting should be handled."""
        text = "**bold with _italic_ inside**"
        result = _escape_markdown(text)
        # Both should be preserved
        assert result == "**bold with _italic_ inside**"

    def test_incomplete_formatting(self):
        """Incomplete formatting markers should be escaped."""
        text = "Text with single * and single _"
        result = _escape_markdown(text)
        # Single markers without closing should be escaped
        assert result == r"Text with single \* and single \_"

    def test_double_underscore_bold(self):
        """Double underscore for bold should be preserved."""
        text = "__bold text__ normal text"
        result = _escape_markdown(text)
        assert result == "__bold text__ normal text"
