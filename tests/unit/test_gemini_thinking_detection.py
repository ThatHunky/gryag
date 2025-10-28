"""Test Gemini thinking mode detection logic."""

import pytest

from app.services.gemini import GeminiClient


class TestThinkingDetection:
    """Test thinking support detection for various Gemini models."""

    @pytest.mark.parametrize(
        "model_name,expected",
        [
            # Gemini 2.5 series - ALL support thinking
            ("gemini-2.5-flash", True),
            ("models/gemini-2.5-flash", True),
            ("gemini-2.5-pro", True),
            ("models/gemini-2.5-pro", True),
            ("gemini-2.5-flash-lite", True),
            ("models/gemini-2.5-flash-lite", True),
            ("gemini-2-5-flash", True),  # Alternative naming
            # -latest variants (map to 2.5 as of Oct 2025)
            ("gemini-flash-latest", True),
            ("gemini-pro-latest", True),
            ("models/gemini-flash-latest", True),
            ("models/gemini-pro-latest", True),
            # Experimental thinking models
            ("gemini-2.0-flash-thinking-exp", True),
            ("gemini-exp-1206", True),
            # Models without thinking support
            ("gemini-1.5-flash", False),
            ("gemini-1.5-pro", False),
            ("models/gemma-3-27b-it", False),
            ("models/gemma-3-4b-it", False),
        ],
    )
    def test_thinking_support_detection(self, model_name: str, expected: bool) -> None:
        """Test that thinking support is correctly detected for various models."""
        result = GeminiClient._detect_thinking_support(model_name)
        assert result == expected, (
            f"Model {model_name} should {'support' if expected else 'not support'} thinking, "
            f"but got {result}"
        )

    def test_gemini_25_flash_supports_thinking(self) -> None:
        """Specific test for the main use case: Gemini 2.5 Flash.

        Per official Google documentation:
        https://ai.google.dev/gemini-api/docs/thinking

        "Thinking features are supported on all the 2.5 series models"
        """
        assert GeminiClient._detect_thinking_support("gemini-2.5-flash") is True
        assert GeminiClient._detect_thinking_support("models/gemini-2.5-flash") is True
