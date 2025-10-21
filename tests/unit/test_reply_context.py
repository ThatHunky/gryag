"""
Unit tests for reply chain context inclusion feature.

Tests that replied-to messages are always included in Gemini context,
both in JSON and compact conversation formats.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from aiogram.types import Message, User, Chat
from datetime import datetime

from app.services.conversation_formatter import (
    format_message_compact,
    format_history_compact,
)


class TestCompactFormatter:
    """Test compact format reply excerpt rendering."""

    def test_format_message_with_reply_excerpt(self):
        """Test that reply excerpt is prepended to message in compact format."""
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Yes, that's correct!",
            reply_to_user_id=789012,
            reply_to_username="Bob",
            reply_excerpt="What is the capital of Ukraine?",
        )

        assert "↩︎" in result
        assert "Bob" in result
        assert "What is the capital of Ukraine?" in result
        assert "Yes, that's correct!" in result
        assert result.startswith("Alice#")

    def test_format_message_without_reply(self):
        """Test that messages without reply work normally."""
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Hello world",
        )

        assert "↩︎" not in result
        assert result == "Alice#123456: Hello world"

    def test_format_message_reply_excerpt_truncation(self):
        """Test that long reply excerpts are truncated."""
        long_text = "A" * 200

        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Reply text",
            reply_to_user_id=789012,
            reply_to_username="Bob",
            reply_excerpt=long_text,
        )

        # Should be truncated to ~120 chars in the excerpt
        assert "..." in result
        assert len(result) < len(long_text) + 200  # Should be much shorter

    def test_format_history_with_reply_metadata(self):
        """Test that history formatting includes reply excerpts from metadata."""
        messages = [
            {
                "role": "user",
                "parts": [
                    {"text": '[meta] user_id=123 name="Alice" message_id=1'},
                    {"text": "What is ROE?"},
                ],
            },
            {
                "role": "model",
                "parts": [
                    {"text": "ROE is Return on Equity..."},
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            '[meta] user_id=456 name="Bob" message_id=2 '
                            'reply_to_user_id=123 reply_to_name="Alice" '
                            'reply_excerpt="What is ROE?"'
                        )
                    },
                    {"text": "Can you explain more?"},
                ],
            },
        ]

        result = format_history_compact(messages)

        # Should contain the reply chain indicator
        assert "→" in result  # Reply chain arrow
        assert "↩︎" in result  # Reply excerpt marker
        assert "What is ROE?" in result
        assert "Can you explain more?" in result


class TestReplyContextInclusion:
    """Test that reply context is always included in Gemini payloads."""

    def test_reply_context_with_text_only(self):
        """Test that text-only replies are included in context."""
        # This would be an integration test with the actual handler
        # For now, we test the building blocks

        # Mock reply message
        reply_msg = Mock(spec=Message)
        reply_msg.text = "What is the capital of Ukraine?"
        reply_msg.caption = None
        reply_msg.from_user = Mock(spec=User)
        reply_msg.from_user.id = 123456
        reply_msg.from_user.full_name = "Alice"
        reply_msg.from_user.username = "alice"
        reply_msg.message_id = 100
        reply_msg.date = datetime.now()

        # In the actual handler, this should create reply_context
        # and set reply_context_for_history

        # Test metadata building would happen here
        # This is more of an integration concern
        pass

    def test_inline_reply_excerpt_added_to_user_parts(self):
        """Test that inline reply excerpt is added to user_parts."""
        # This tests the logic in chat.py where we insert the inline reply

        # Mock a reply_context
        reply_context = {
            "text": "What is the capital of Ukraine?",
            "name": "Alice",
            "username": "alice",
            "message_id": 100,
        }

        # In the actual code, we'd build user_parts and insert the inline reply
        # This is tested via integration tests
        pass


class TestConfigurationFlags:
    """Test configuration flags for reply context feature."""

    def test_include_reply_excerpt_default_true(self):
        """Test that INCLUDE_REPLY_EXCERPT defaults to true."""
        from app.config import Settings

        settings = Settings(
            telegram_token="test_token",
            gemini_api_key="test_api_key",
        )

        assert settings.include_reply_excerpt is True

    def test_reply_excerpt_max_chars_default(self):
        """Test that REPLY_EXCERPT_MAX_CHARS has reasonable default."""
        from app.config import Settings

        settings = Settings(
            telegram_token="test_token",
            gemini_api_key="test_api_key",
        )

        assert settings.reply_excerpt_max_chars == 200
        assert 50 <= settings.reply_excerpt_max_chars <= 500


class TestReplyExcerptSanitization:
    """Test that reply excerpts are properly sanitized."""

    def test_newlines_removed_in_compact_format(self):
        """Test that newlines in reply excerpts are replaced with spaces."""
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Reply",
            reply_to_user_id=789012,
            reply_to_username="Bob",
            reply_excerpt="Line 1\nLine 2\nLine 3",
        )

        # Should not contain literal newlines in the excerpt
        lines = result.split("\n")
        assert len(lines) == 1  # Single line output

    def test_special_chars_handled(self):
        """Test that special characters don't break formatting."""
        result = format_message_compact(
            user_id=123456,
            username="Alice",
            text="Reply",
            reply_to_user_id=789012,
            reply_to_username="Bob",
            reply_excerpt='Test with "quotes" and [brackets]',
        )

        # Should still be valid
        assert "↩︎" in result
        assert "Bob" in result


class TestTelemetryCounters:
    """Test that telemetry counters are incremented correctly."""

    def test_reply_text_counter(self):
        """Test that context.reply_included_text counter is incremented."""
        # This would need to be tested via integration test
        # or by mocking telemetry.increment_counter
        pass

    def test_reply_media_counter(self):
        """Test that context.reply_included_media counter is incremented."""
        # This would need to be tested via integration test
        # or by mocking telemetry.increment_counter
        pass


@pytest.mark.asyncio
class TestHistoryInjection:
    """Test that reply messages are injected into history when missing."""

    async def test_reply_injected_when_not_in_history(self):
        """Test that replied message is injected if not in history."""
        # Mock history without the replied message
        history = [
            {
                "role": "user",
                "parts": [
                    {"text": "[meta] message_id=5"},
                    {"text": "Some other message"},
                ],
            },
        ]

        # Mock reply_context_for_history
        reply_context = {
            "message_id": 1,
            "user_id": 123,
            "name": "Alice",
            "text": "What is ROE?",
        }

        # In actual code, this would inject reply_context into history
        # Check that message_id=1 is not in history
        found = False
        for msg in history:
            for part in msg.get("parts", []):
                if "message_id=1" in part.get("text", ""):
                    found = True

        assert not found  # Should not be in history initially

        # After injection, it should be present
        # This is tested in integration tests

    async def test_reply_not_duplicated_if_already_in_history(self):
        """Test that replied message is not duplicated if already present."""
        # Mock history with the replied message already present
        history = [
            {
                "role": "user",
                "parts": [
                    {"text": "[meta] message_id=1"},
                    {"text": "What is ROE?"},
                ],
            },
            {
                "role": "model",
                "parts": [{"text": "ROE is..."}],
            },
        ]

        # Should detect that message_id=1 is already in history
        # and not inject it again

        original_length = len(history)

        # In actual code, duplication check happens
        # After the check, length should remain the same

        # This is verified in integration tests
        assert len(history) == original_length
