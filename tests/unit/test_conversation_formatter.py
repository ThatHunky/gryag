"""
Unit tests for conversation_formatter module.

Tests compact plain text formatting for reduced token usage.
"""

import pytest
from app.services.conversation_formatter import (
    build_collision_map,
    describe_media,
    estimate_tokens,
    extract_metadata_from_parts,
    extract_text_from_parts,
    format_history_compact,
    format_message_compact,
    parse_user_id_short,
    sanitize_username,
)


class TestParseUserIdShort:
    """Test user ID short format extraction."""

    def test_basic_user_id(self):
        assert parse_user_id_short(123456789) == "456789"

    def test_short_user_id(self):
        assert parse_user_id_short(123) == "123"

    def test_negative_user_id(self):
        # Chat IDs can be negative
        assert parse_user_id_short(-987654321) == "654321"

    def test_none_user_id(self):
        assert parse_user_id_short(None) == ""

    def test_large_user_id(self):
        assert parse_user_id_short(999999999999) == "999999"


class TestBuildCollisionMap:
    """Test collision handling for duplicate short IDs."""

    def test_no_collisions(self):
        user_ids = [123456, 789012, 345678]
        result = build_collision_map(user_ids)
        assert result == {123456: "123456", 789012: "789012", 345678: "345678"}

    def test_with_collision(self):
        # Last 6 digits collision: 123456 and 999123456
        user_ids = [123456, 999123456]
        result = build_collision_map(user_ids)
        # Both have same last 6 digits, should get suffixes
        assert len(result) == 2
        assert result[123456].startswith("123456")
        assert result[999123456].startswith("123456")
        # One should have 'a', other 'b'
        values = set(result.values())
        assert "123456a" in values or "123456b" in values

    def test_empty_list(self):
        result = build_collision_map([])
        assert result == {}


class TestSanitizeUsername:
    """Test username sanitization."""

    def test_basic_name(self):
        assert sanitize_username("Alice") == "Alice"

    def test_name_with_problematic_chars(self):
        result = sanitize_username("Alice:Bob→Charlie[Test]")
        assert ":" not in result
        assert "→" not in result
        assert "[" not in result
        assert "]" not in result

    def test_name_with_newline(self):
        result = sanitize_username("Alice\nBob")
        assert "\n" not in result
        assert "Alice Bob" == result

    def test_long_name_truncation(self):
        long_name = "A" * 50
        result = sanitize_username(long_name, max_length=30)
        assert len(result) == 30
        assert result.endswith("..")

    def test_none_name(self):
        assert sanitize_username(None) == "Unknown"

    def test_empty_name(self):
        assert sanitize_username("") == "Unknown"

    def test_unicode_name(self):
        result = sanitize_username("Олександр 🎉")
        assert "Олександр" in result


class TestDescribeMedia:
    """Test media description formatting."""

    def test_empty_media(self):
        assert describe_media([]) == ""

    def test_single_image(self):
        media = [{"kind": "photo", "mime": "image/jpeg"}]
        assert describe_media(media) == "[Image]"

    def test_single_video(self):
        media = [{"kind": "video", "mime": "video/mp4"}]
        assert describe_media(media) == "[Video]"

    def test_audio(self):
        media = [{"kind": "audio", "mime": "audio/ogg"}]
        assert describe_media(media) == "[Audio]"

    def test_document(self):
        media = [{"kind": "document", "filename": "report.pdf"}]
        assert describe_media(media) == "[Document: report.pdf]"

    def test_long_filename_truncation(self):
        media = [
            {
                "kind": "document",
                "filename": "very_long_filename_that_needs_truncation.pdf",
            }
        ]
        result = describe_media(media)
        assert "..." in result
        assert len(result) < 30

    def test_multiple_media(self):
        media = [
            {"kind": "photo", "mime": "image/jpeg"},
            {"kind": "video", "mime": "video/mp4"},
        ]
        result = describe_media(media)
        assert "[Image]" in result
        assert "[Video]" in result


class TestExtractMetadataFromParts:
    """Test metadata extraction from message parts."""

    def test_basic_metadata(self):
        parts = [
            {"text": '[meta] chat_id=-123 user_id=456 name="Alice"'},
            {"text": "Hello world"},
        ]
        result = extract_metadata_from_parts(parts)
        assert result["chat_id"] == -123
        assert result["user_id"] == 456
        assert result["name"] == "Alice"

    def test_no_metadata(self):
        parts = [{"text": "Just regular text"}]
        result = extract_metadata_from_parts(parts)
        assert result == {}

    def test_metadata_with_quoted_values(self):
        parts = [{"text": '[meta] name="Alice Smith" username="alice_ua"'}]
        result = extract_metadata_from_parts(parts)
        assert result["name"] == "Alice Smith"
        assert result["username"] == "alice_ua"

    def test_metadata_with_unquoted_values(self):
        parts = [{"text": "[meta] user_id=123 message_id=456"}]
        result = extract_metadata_from_parts(parts)
        assert result["user_id"] == 123
        assert result["message_id"] == 456


class TestExtractTextFromParts:
    """Test text extraction from message parts."""

    def test_basic_text(self):
        parts = [{"text": "Hello world"}]
        assert extract_text_from_parts(parts) == "Hello world"

    def test_skip_metadata(self):
        parts = [
            {"text": "[meta] user_id=123"},
            {"text": "Hello world"},
        ]
        assert extract_text_from_parts(parts, skip_meta=True) == "Hello world"

    def test_include_metadata(self):
        parts = [
            {"text": "[meta] user_id=123"},
            {"text": "Hello world"},
        ]
        result = extract_text_from_parts(parts, skip_meta=False)
        assert "[meta]" in result
        assert "Hello world" in result

    def test_multiple_text_parts(self):
        parts = [
            {"text": "Hello"},
            {"text": "world"},
        ]
        assert extract_text_from_parts(parts) == "Hello world"

    def test_empty_parts(self):
        assert extract_text_from_parts([]) == ""


class TestFormatMessageCompact:
    """Test single message formatting."""

    def test_basic_user_message(self):
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Hello world",
        )
        assert result == "Alice#123456: Hello world"

    def test_bot_message(self):
        result = format_message_compact(
            user_id=None,
            username="gryag",
            text="Привіт",
            is_bot=True,
        )
        assert result == "gryag: Привіт"

    def test_message_with_media(self):
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Check this out",
            media_description="[Image]",
        )
        assert "[Image]" in result
        assert "Check this out" in result

    def test_reply_to_user(self):
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Thanks!",
            reply_to_user_id=789012,
            reply_to_username="Bob",
        )
        assert "Alice#123456 → Bob#789012: Thanks!" == result

    def test_reply_to_bot(self):
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Hey bot",
            reply_to_user_id=None,
            reply_to_username="gryag",
        )
        assert "Alice#123456 → gryag: Hey bot" == result

    def test_with_collision_map(self):
        user_id_map = {123456: "123456a", 789012: "123456b"}
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Hello",
            user_id_map=user_id_map,
        )
        assert "Alice#123456a: Hello" == result


class TestFormatHistoryCompact:
    """Test full conversation history formatting."""

    def test_basic_conversation(self):
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=123 name="Alice"'},
                    {"text": "Hello"},
                ],
            },
            {
                "role": "model",
                "parts": [
                    {"text": '[meta] name="gryag"'},
                    {"text": "Hi"},
                ],
            },
        ]
        result = format_history_compact(messages)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "Alice#000123: Hello" in lines[0]
        assert "gryag: Hi" in lines[1]

    def test_conversation_with_replies(self):
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=123 name="Alice"'},
                    {"text": "Hello"},
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "text": '[meta] user_id=456 name="Bob" reply_to_user_id=123 reply_to_name="Alice"'
                    },
                    {"text": "Hi Alice!"},
                ],
            },
        ]
        result = format_history_compact(messages)
        assert "→" in result  # Reply arrow

    def test_empty_history(self):
        assert format_history_compact([]) == ""

    def test_conversation_with_media(self):
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=123 name="Alice"'},
                    {"text": "Check this"},
                    {"inline_data": {"mime_type": "image/jpeg", "data": "..."}},
                ],
            },
        ]
        result = format_history_compact(messages)
        assert "[Media]" in result


class TestEstimateTokens:
    """Test token estimation."""

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_basic_text(self):
        # "Hello world" = 2 words * 1.3 = 2.6 ≈ 2 tokens
        tokens = estimate_tokens("Hello world")
        assert tokens > 0
        assert tokens < 10

    def test_long_text(self):
        text = "word " * 100  # 100 words
        tokens = estimate_tokens(text)
        assert tokens > 100  # Should be around 130
        assert tokens < 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
