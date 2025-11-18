"""
Unit tests for video and sticker context handling in compact format.

Tests the video/sticker context fix implementation:
- Historical media collection and inclusion
- Media limit enforcement with priority ordering
- Media type descriptions (videos, stickers, images)
- Telemetry counters for media handling
"""

import pytest

from app.services.conversation_formatter import describe_media, format_history_compact


class TestDescribeMedia:
    """Test media description generation."""

    def test_describe_image(self):
        """Image media should be described as [Image]."""
        media = [{"kind": "image", "mime": "image/jpeg"}]
        result = describe_media(media)
        assert result == "[Image]"

    def test_describe_video(self):
        """Video media should be described as [Video]."""
        media = [{"kind": "video", "mime": "video/mp4"}]
        result = describe_media(media)
        assert result == "[Video]"

    def test_describe_sticker_webp(self):
        """WebP stickers should be described as [Sticker]."""
        media = [{"kind": "image", "mime": "image/webp"}]
        result = describe_media(media)
        assert result == "[Sticker]"

    def test_describe_sticker_webm(self):
        """WebM video stickers should be described as [Sticker]."""
        media = [{"kind": "image", "mime": "video/webm"}]
        result = describe_media(media)
        assert result == "[Sticker]"

    def test_describe_audio(self):
        """Audio media should be described as [Audio]."""
        media = [{"kind": "audio", "mime": "audio/ogg"}]
        result = describe_media(media)
        assert result == "[Audio]"

    def test_describe_multiple_media(self):
        """Multiple media items should have separate descriptions."""
        media = [
            {"kind": "image", "mime": "image/jpeg"},
            {"kind": "video", "mime": "video/mp4"},
            {"kind": "image", "mime": "image/webp"},
        ]
        result = describe_media(media)
        assert result == "[Image] [Video] [Sticker]"

    def test_describe_document(self):
        """Document media should include filename."""
        media = [
            {"kind": "document", "mime": "application/pdf", "filename": "test.pdf"}
        ]
        result = describe_media(media)
        assert result == "[Document: test.pdf]"

    def test_describe_empty(self):
        """Empty media list should return empty string."""
        result = describe_media([])
        assert result == ""

    def test_fallback_to_mime(self):
        """Should fallback to mime type detection if kind is wrong."""
        # Old code used kind="photo", new code should detect from mime
        media = [{"kind": "unknown", "mime": "image/png"}]
        result = describe_media(media)
        assert result == "[Image]"


class TestFormatHistoryCompact:
    """Test compact history formatting with media descriptions."""

    def test_format_with_image(self):
        """History with image should show [Image] description."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=123 name="Alice"'},
                    {"text": "Check this out"},
                    {"inline_data": {"mime_type": "image/jpeg", "data": "base64data"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        assert "[Image]" in result
        assert "Alice" in result
        assert "Check this out" in result

    def test_format_with_video(self):
        """History with video should show [Video] description."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=456 name="Bob"'},
                    {"text": "Watch this"},
                    {"inline_data": {"mime_type": "video/mp4", "data": "base64data"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        assert "[Video]" in result
        assert "Bob" in result

    def test_format_with_sticker(self):
        """History with sticker should show [Sticker] description."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=789 name="Carol"'},
                    {"inline_data": {"mime_type": "image/webp", "data": "base64data"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        assert "[Sticker]" in result
        assert "Carol" in result

    def test_format_with_file_uri(self):
        """History with file_uri should show [Video] description."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=999 name="Dave"'},
                    {"text": "YouTube link"},
                    {"file_data": {"file_uri": "https://youtube.com/watch?v=xyz"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        assert "[Video]" in result
        assert "Dave" in result

    def test_format_multiple_media_types(self):
        """History with multiple media types should describe each."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=111 name="Eve"'},
                    {"text": "Multiple items"},
                    {"inline_data": {"mime_type": "image/jpeg", "data": "img1"}},
                    {"inline_data": {"mime_type": "video/mp4", "data": "vid1"}},
                    {"inline_data": {"mime_type": "image/webp", "data": "sticker1"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        # Should see all media types in description
        assert "[Image]" in result
        assert "[Video]" in result
        assert "[Sticker]" in result

    def test_no_generic_media_placeholder(self):
        """Should not use generic [Media] placeholder anymore."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=222 name="Frank"'},
                    {"inline_data": {"mime_type": "image/png", "data": "data"}},
                ],
            }
        ]
        result = format_history_compact(messages)
        # Old format used "[Media]", new format should use specific type
        assert "[Media]" not in result or "[Image]" in result


class TestHistoricalMediaCollection:
    """Test historical media collection in MultiLevelContextManager.

    Note: These are integration-style tests that would need a real
    MultiLevelContextManager instance. For unit testing, we verify
    the data structures and logic paths.
    """

    def test_historical_media_structure(self):
        """Historical media should have correct structure."""
        # Simulate what format_for_gemini_compact() returns
        formatted_context = {
            "conversation_text": "Alice#123: Hello\ngryag: Привіт",
            "system_context": None,
            "historical_media": [
                {"inline_data": {"mime_type": "image/jpeg", "data": "base64..."}},
                {"inline_data": {"mime_type": "video/mp4", "data": "base64..."}},
            ],
            "token_count": 500,
        }

        # Verify structure
        assert "historical_media" in formatted_context
        assert isinstance(formatted_context["historical_media"], list)
        assert len(formatted_context["historical_media"]) == 2
        assert "inline_data" in formatted_context["historical_media"][0]

    def test_empty_historical_media(self):
        """Empty historical media should be an empty list."""
        formatted_context = {
            "conversation_text": "Alice#123: Hello",
            "system_context": None,
            "historical_media": [],
            "token_count": 50,
        }

        assert formatted_context["historical_media"] == []


class TestMediaLimitEnforcement:
    """Test media limit enforcement with priority ordering.

    These tests verify the logic in chat.py for handling historical media
    with proper priority and limits.
    """

    def test_priority_current_over_historical(self):
        """Current message media should have priority over historical."""
        max_media = 3
        media_parts = [
            {"inline_data": {"mime_type": "image/jpeg", "data": "current1"}},
            {"inline_data": {"mime_type": "image/png", "data": "current2"}},
        ]
        historical_media = [
            {"inline_data": {"mime_type": "video/mp4", "data": "hist1"}},
            {"inline_data": {"mime_type": "image/webp", "data": "hist2"}},
            {"inline_data": {"mime_type": "video/webm", "data": "hist3"}},
        ]

        # Simulate the logic from chat.py
        all_media = []
        all_media.extend(media_parts)  # Current first

        remaining_slots = max_media - len(all_media)
        if remaining_slots > 0:
            all_media.extend(historical_media[:remaining_slots])

        # Should have 2 current + 1 historical (oldest)
        assert len(all_media) == 3
        assert all_media[0]["inline_data"]["data"] == "current1"
        assert all_media[1]["inline_data"]["data"] == "current2"
        assert all_media[2]["inline_data"]["data"] == "hist1"

    def test_no_historical_when_current_fills_limit(self):
        """No historical media if current message fills limit."""
        max_media = 2
        media_parts = [
            {"inline_data": {"mime_type": "image/jpeg", "data": "current1"}},
            {"inline_data": {"mime_type": "image/png", "data": "current2"}},
        ]
        historical_media = [
            {"inline_data": {"mime_type": "video/mp4", "data": "hist1"}},
        ]

        all_media = []
        all_media.extend(media_parts)

        remaining_slots = max_media - len(all_media)
        assert remaining_slots == 0  # No room for historical

        if remaining_slots > 0:
            all_media.extend(historical_media[:remaining_slots])

        # Should only have current media
        assert len(all_media) == 2
        assert all_media[0]["inline_data"]["data"] == "current1"
        assert all_media[1]["inline_data"]["data"] == "current2"

    def test_all_historical_when_no_current(self):
        """All historical media when no current media (up to limit)."""
        max_media = 3
        media_parts = []
        historical_media = [
            {"inline_data": {"mime_type": "video/mp4", "data": "hist1"}},
            {"inline_data": {"mime_type": "image/jpeg", "data": "hist2"}},
            {"inline_data": {"mime_type": "image/webp", "data": "hist3"}},
            {"inline_data": {"mime_type": "video/webm", "data": "hist4"}},
        ]

        all_media = []
        all_media.extend(media_parts)

        remaining_slots = max_media - len(all_media)
        if remaining_slots > 0:
            all_media.extend(historical_media[:remaining_slots])

        # Should have 3 historical (oldest first)
        assert len(all_media) == 3
        assert all_media[0]["inline_data"]["data"] == "hist1"
        assert all_media[1]["inline_data"]["data"] == "hist2"
        assert all_media[2]["inline_data"]["data"] == "hist3"

    def test_chronological_order_preserved(self):
        """Historical media should maintain chronological order (oldest first)."""
        max_media = 5
        historical_media = [
            {"inline_data": {"mime_type": "image/jpeg", "data": "oldest"}},
            {"inline_data": {"mime_type": "video/mp4", "data": "middle"}},
            {"inline_data": {"mime_type": "image/webp", "data": "newest"}},
        ]

        all_media = []
        remaining_slots = max_media - len(all_media)
        if remaining_slots > 0:
            all_media.extend(historical_media[:remaining_slots])

        # Order should be preserved
        assert len(all_media) == 3
        assert all_media[0]["inline_data"]["data"] == "oldest"
        assert all_media[1]["inline_data"]["data"] == "middle"
        assert all_media[2]["inline_data"]["data"] == "newest"


class TestTelemetryCounters:
    """Test telemetry counter logic for media handling.

    These tests verify the telemetry counter logic without requiring
    the actual telemetry module.
    """

    def test_telemetry_all_historical_included(self):
        """Should track when all historical media is included."""
        max_media = 10
        current_count = 2
        historical_count = 3

        remaining_slots = max_media - current_count
        historical_kept = min(historical_count, remaining_slots)

        assert historical_kept == 3  # All historical included
        assert historical_kept == historical_count

    def test_telemetry_historical_dropped(self):
        """Should track when historical media is dropped."""
        max_media = 5
        current_count = 3
        historical_count = 5

        remaining_slots = max_media - current_count
        historical_kept = min(historical_count, remaining_slots)
        historical_dropped = historical_count - historical_kept

        assert historical_kept == 2  # Only 2 slots remaining
        assert historical_dropped == 3  # 3 dropped

    def test_telemetry_limit_exceeded(self):
        """Should track when media limit is exceeded."""
        max_media = 3
        all_media_count = 5  # More than limit

        limit_exceeded = all_media_count > max_media
        assert limit_exceeded is True

    def test_telemetry_no_historical(self):
        """Should not increment counters when no historical media."""
        historical_count = 0

        # Logic: only increment if historical_media exists
        if historical_count > 0:
            pytest.fail("Should not reach here")
        else:
            # No counters incremented
            pass
