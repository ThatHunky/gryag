"""
Test that media is properly included in multi-level context.

This test verifies the fix for the bug where media parts were being
ignored during token estimation, causing them to be excluded from context.
"""

import pytest
from unittest.mock import MagicMock
from app.services.context.multi_level_context import MultiLevelContextManager


def test_estimate_tokens_includes_media():
    """Test that _estimate_tokens counts media parts correctly."""
    # Create minimal mock settings
    mock_settings = MagicMock()
    mock_settings.immediate_context_size = 5
    mock_settings.recent_context_size = 30

    manager = MultiLevelContextManager(
        db_path=":memory:",
        settings=mock_settings,
        context_store=None,
    )

    # Test with text only
    text_only = [
        {
            "role": "user",
            "parts": [{"text": "Hello world"}],  # 2 words * 1.3 = 2.6 ≈ 2 tokens
        }
    ]
    tokens = manager._estimate_tokens(text_only)
    assert tokens == 2, f"Expected ~2 tokens for text-only, got {tokens}"

    # Test with inline_data (image/video/audio)
    with_inline_media = [
        {
            "role": "user",
            "parts": [
                {"text": "Check this out"},  # 3 words * 1.3 = 3.9 ≈ 3 tokens
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": "base64data...",
                    }
                },  # 258 tokens
            ],
        }
    ]
    tokens = manager._estimate_tokens(with_inline_media)
    assert tokens == 261, f"Expected 261 tokens (3 text + 258 media), got {tokens}"

    # Test with file_data (YouTube URL)
    with_file_data = [
        {
            "role": "user",
            "parts": [
                {"text": "Watch this"},  # 2 words * 1.3 = 2.6 ≈ 2 tokens
                {
                    "file_data": {
                        "mime_type": "video/youtube",
                        "file_uri": "https://youtube.com/watch?v=...",
                    }
                },  # 100 tokens
            ],
        }
    ]
    tokens = manager._estimate_tokens(with_file_data)
    assert tokens == 102, f"Expected 102 tokens (2 text + 100 media), got {tokens}"

    # Test with multiple media items
    multiple_media = [
        {
            "role": "user",
            "parts": [
                {"text": "Look"},  # 1 word * 1.3 = 1.3 ≈ 1 token
                {"inline_data": {"mime_type": "image/jpeg", "data": "..."}},  # 258
                {"inline_data": {"mime_type": "image/png", "data": "..."}},  # 258
            ],
        }
    ]
    tokens = manager._estimate_tokens(multiple_media)
    assert tokens == 517, f"Expected 517 tokens (1 text + 516 media), got {tokens}"


def test_estimate_tokens_backward_compatible():
    """Test that text-only messages still work as before."""
    mock_settings = MagicMock()
    mock_settings.immediate_context_size = 5
    mock_settings.recent_context_size = 30

    manager = MultiLevelContextManager(
        db_path=":memory:",
        settings=mock_settings,
        context_store=None,
    )

    # Old format without media should still work
    messages = [
        {"role": "user", "parts": [{"text": "Hello"}]},
        {"role": "model", "parts": [{"text": "Hi there"}]},
        {"role": "user", "parts": [{"text": "How are you"}]},
    ]

    tokens = manager._estimate_tokens(messages)
    # "Hello" = 1 word = 1.3 tokens ≈ 1
    # "Hi there" = 2 words = 2.6 tokens ≈ 2
    # "How are you" = 3 words = 3.9 tokens ≈ 3
    # Total ≈ 6 tokens
    assert (
        5 <= tokens <= 8
    ), f"Expected ~6 tokens for text-only conversation, got {tokens}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
