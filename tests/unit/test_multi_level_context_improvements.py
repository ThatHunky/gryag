"""
Tests for multi-level context improvements.
"""

from unittest.mock import Mock

import pytest

from app.services.context.multi_level_context import MultiLevelContextManager


class TestQueryTypeDetection:
    @pytest.fixture
    def mock_settings(self):
        """Create mock settings object."""
        settings = Mock()
        return settings

    @pytest.fixture
    def manager(self, mock_settings):
        """Create MultiLevelContextManager instance for testing."""
        return MultiLevelContextManager(
            db_path=":memory:",
            settings=mock_settings,
            context_store=Mock(),
        )

    def test_news_detection(self, manager):
        assert manager._detect_query_type("Що сталося сьогодні?") == "news"
        assert manager._detect_query_type("Latest news please") == "news"
        assert manager._detect_query_type("Останні новини") == "news"

    def test_factual_detection(self, manager):
        assert manager._detect_query_type("Що таке Python?") == "factual"
        assert manager._detect_query_type("Who is the president?") == "factual"
        assert manager._detect_query_type("Коли це сталося?") == "factual"

    def test_command_detection(self, manager):
        assert manager._detect_query_type("Зроби щось") == "command"
        assert manager._detect_query_type("Create a file") == "command"
        assert manager._detect_query_type("Напиши код") == "command"

    def test_conversational_detection(self, manager):
        assert manager._detect_query_type("Привіт") == "conversational"
        assert manager._detect_query_type("Hello") == "conversational"
        assert manager._detect_query_type("OK") == "conversational"  # Short query

    def test_general_fallback(self, manager):
        assert manager._detect_query_type("Just some regular text here") == "general"
        assert manager._detect_query_type("") == "general"
