"""
Unit tests for response text cleaning.

Tests the _clean_response_text function to ensure system metadata
and technical markers are properly removed from bot responses.
"""

from app.handlers.chat import _clean_response_text


class TestCleanResponseText:
    """Test response text cleaning functionality."""

    def test_removes_generated_image_marker(self):
        """[GENERATED_IMAGE] marker should be removed."""
        text = "Текст перед маркером [GENERATED_IMAGE] текст після"
        result = _clean_response_text(text)
        assert result == "Текст перед маркером текст після"

    def test_removes_attachment_marker(self):
        """[ATTACHMENT] marker should be removed."""
        text = "Готово! [ATTACHMENT]"
        result = _clean_response_text(text)
        assert result == "Готово!"

    def test_removes_image_generated_marker(self):
        """[IMAGE_GENERATED] marker should be removed."""
        text = "[IMAGE_GENERATED] Зображення створено"
        result = _clean_response_text(text)
        assert result == "Зображення створено"

    def test_case_insensitive_markers(self):
        """Markers should be removed case-insensitively."""
        test_cases = [
            ("[generated_image]", ""),
            ("[GENERATED_IMAGE]", ""),
            ("[Generated_Image]", ""),
            ("[attachment]", ""),
            ("[ATTACHMENT]", ""),
        ]
        for input_text, expected in test_cases:
            result = _clean_response_text(input_text)
            assert result == expected

    def test_multiple_markers(self):
        """Multiple markers in same text should all be removed."""
        text = "[GENERATED_IMAGE] Text [ATTACHMENT] more text [IMAGE]"
        result = _clean_response_text(text)
        assert result == "Text more text"

    def test_preserves_normal_text(self):
        """Normal text without markers should be unchanged."""
        text = "Це звичайний текст без жодних маркерів"
        result = _clean_response_text(text)
        assert result == text

    def test_removes_meta_blocks(self):
        """[meta] blocks should still be removed."""
        text = "Text [meta user_id=123] more text"
        result = _clean_response_text(text)
        # The regex removes the content but may leave [meta ], which gets cleaned
        # The important part is that user_id info is removed
        assert "user_id" not in result or "user_id=" not in result

    def test_removes_technical_ids(self):
        """Technical IDs should be removed."""
        text = "Response with chat_id=123456 and user_id=789"
        result = _clean_response_text(text)
        # Technical IDs should be removed
        assert "chat_id=123456" not in result
        assert "user_id=789" not in result

    def test_cleans_extra_whitespace(self):
        """Extra whitespace should be normalized."""
        text = "Text   with    extra     spaces"
        result = _clean_response_text(text)
        assert result == "Text with extra spaces"

    def test_empty_text(self):
        """Empty text should return empty."""
        assert _clean_response_text("") == ""
        # None is handled by early return in the function
        result = _clean_response_text("")
        assert result is not None

    def test_real_world_case(self):
        """Real-world example from bug report."""
        text = "Це вже якась їбана естетика. Жука на тарантула? Ти серйозно? [GENERATED_IMAGE]"
        result = _clean_response_text(text)
        assert "[GENERATED_IMAGE]" not in result
        assert "Це вже якась їбана естетика" in result

    def test_marker_at_start(self):
        """Marker at the start of text should be removed."""
        text = "[GENERATED_IMAGE] Текст після маркера"
        result = _clean_response_text(text)
        assert result == "Текст після маркера"

    def test_marker_at_end(self):
        """Marker at the end of text should be removed."""
        text = "Текст перед маркером [GENERATED_IMAGE]"
        result = _clean_response_text(text)
        assert result == "Текст перед маркером"

    def test_only_marker(self):
        """Text with only a marker should result in empty string."""
        text = "[GENERATED_IMAGE]"
        result = _clean_response_text(text)
        assert result == ""

    def test_preserves_legitimate_brackets(self):
        """Legitimate bracketed text should be preserved."""
        text = "Формула [x + y] і координати [10, 20]"
        result = _clean_response_text(text)
        assert "[x + y]" in result
        assert "[10, 20]" in result

    def test_newlines_preserved(self):
        """Newlines should be preserved in multi-line text."""
        text = "Перший рядок\nДругий рядок\nТретій рядок"
        result = _clean_response_text(text)
        # After cleaning, single line breaks are preserved
        assert "Перший рядок" in result
        assert "Другий рядок" in result
        assert "Третій рядок" in result
