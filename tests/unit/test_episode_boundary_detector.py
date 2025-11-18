"""
Tests for Episode Boundary Detector.

Phase 4.1: Tests for automatic episode boundary detection.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.config import Settings
from app.services.context.episode_boundary_detector import (
    BoundarySignal,
    EpisodeBoundaryDetector,
    MessageSequence,
)


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock(spec=Settings)
    settings.enable_episodic_memory = True
    settings.episode_min_messages = 5
    settings.episode_min_importance = 0.6
    return settings


@pytest.fixture
def mock_gemini():
    """Create mock Gemini client."""
    client = AsyncMock()
    # Default: return similar embeddings
    client.embed_text.side_effect = lambda text: [0.5] * 768
    return client


@pytest_asyncio.fixture
async def detector(tmp_path, mock_settings, mock_gemini):
    """Create boundary detector instance."""
    db_path = tmp_path / "test.db"
    detector = EpisodeBoundaryDetector(db_path, mock_settings, mock_gemini)
    await detector.init()
    return detector


def create_message(msg_id: int, text: str, timestamp: int, user_id: int = 123) -> dict:
    """Create a test message."""
    return {
        "id": msg_id,
        "text": text,
        "timestamp": timestamp,
        "user_id": user_id,
        "chat_id": 1,
    }


def create_sequence(messages: list[dict]) -> MessageSequence:
    """Create a message sequence from messages."""
    return MessageSequence(
        messages=messages,
        chat_id=1,
        thread_id=None,
        start_timestamp=messages[0]["timestamp"] if messages else 0,
        end_timestamp=messages[-1]["timestamp"] if messages else 0,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Temporal Boundary Detection Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_temporal_boundary_short_gap(detector):
    """Test detection of short time gap (weak signal)."""
    msg_a = create_message(1, "Hello", 1000)
    msg_b = create_message(2, "Hi there", 1130)  # 130 seconds = 2m 10s

    signal = await detector._detect_temporal_boundary(msg_a, msg_b)

    assert signal is not None
    assert signal.signal_type == "temporal"
    assert signal.strength == 0.4  # Short gap = weak signal
    assert signal.message_id == 2


@pytest.mark.asyncio
async def test_temporal_boundary_medium_gap(detector):
    """Test detection of medium time gap (moderate signal)."""
    msg_a = create_message(1, "Hello", 1000)
    msg_b = create_message(2, "Hi there", 2000)  # 1000 seconds = 16m 40s

    signal = await detector._detect_temporal_boundary(msg_a, msg_b)

    assert signal is not None
    assert signal.signal_type == "temporal"
    assert signal.strength == 0.7  # Medium gap = moderate signal
    assert "Medium gap" in signal.reason


@pytest.mark.asyncio
async def test_temporal_boundary_long_gap(detector):
    """Test detection of long time gap (strong signal)."""
    msg_a = create_message(1, "Hello", 1000)
    msg_b = create_message(2, "Hi there", 5000)  # 4000 seconds = 66m 40s

    signal = await detector._detect_temporal_boundary(msg_a, msg_b)

    assert signal is not None
    assert signal.signal_type == "temporal"
    assert signal.strength == 1.0  # Long gap = strong signal
    assert "Long gap" in signal.reason


@pytest.mark.asyncio
async def test_temporal_boundary_no_gap(detector):
    """Test that very short gaps don't trigger boundary."""
    msg_a = create_message(1, "Hello", 1000)
    msg_b = create_message(2, "Hi there", 1050)  # 50 seconds

    signal = await detector._detect_temporal_boundary(msg_a, msg_b)

    assert signal is None  # Too short to be a boundary


# ═══════════════════════════════════════════════════════════════════════════
# Topic Marker Detection Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_topic_marker_ukrainian(detector):
    """Test detection of Ukrainian topic markers."""
    test_cases = [
        "Давайте поговорим про щось інше",
        "Кстаті, я хотів спитати...",
        "Змінімо тему, окей?",
        "Тепер про іншу річ",
        "А зараз щодо іншого питання",
    ]

    for i, text in enumerate(test_cases):
        msg = create_message(i, text, 1000 + i)
        signal = await detector._detect_topic_marker(msg)

        assert signal is not None, f"Failed to detect marker in: {text}"
        assert signal.signal_type == "topic_marker"
        assert signal.strength == 0.8
        assert signal.message_id == i


@pytest.mark.asyncio
async def test_topic_marker_english(detector):
    """Test detection of English topic markers."""
    test_cases = [
        "Let's talk about something else",
        "By the way, I wanted to ask...",
        "Changing the subject, have you seen...",
        "Speaking of which...",
        "On another note, did you hear...",
    ]

    for i, text in enumerate(test_cases):
        msg = create_message(i, text, 1000 + i)
        signal = await detector._detect_topic_marker(msg)

        assert signal is not None, f"Failed to detect marker in: {text}"
        assert signal.signal_type == "topic_marker"
        assert signal.strength == 0.8


@pytest.mark.asyncio
async def test_topic_marker_none(detector):
    """Test that normal messages don't trigger topic markers."""
    msg = create_message(1, "This is just a normal message about nothing special", 1000)

    signal = await detector._detect_topic_marker(msg)

    assert signal is None


@pytest.mark.asyncio
async def test_topic_marker_case_insensitive(detector):
    """Test that topic markers are case-insensitive."""
    msg = create_message(1, "LET'S TALK ABOUT THIS", 1000)

    signal = await detector._detect_topic_marker(msg)

    assert signal is not None
    assert signal.signal_type == "topic_marker"


# ═══════════════════════════════════════════════════════════════════════════
# Semantic Boundary Detection Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_semantic_boundary_low_similarity(detector, mock_gemini):
    """Test detection of low semantic similarity (topic shift)."""
    # Return very different embeddings
    embeddings = [[1.0] * 768, [0.0] * 768]
    mock_gemini.embed_text.side_effect = lambda text: embeddings.pop(0)

    msg_a = create_message(1, "I love pizza with cheese and pepperoni", 1000)
    msg_b = create_message(2, "Quantum physics is fascinating", 1010)

    signal = await detector._detect_semantic_boundary(msg_a, msg_b)

    assert signal is not None
    assert signal.signal_type == "semantic"
    # Low similarity = high strength (inverted)
    assert signal.strength > 0.5
    assert "Low semantic similarity" in signal.reason


@pytest.mark.asyncio
async def test_semantic_boundary_high_similarity(detector, mock_gemini):
    """Test that high similarity doesn't trigger boundary."""
    # Return very similar embeddings
    mock_gemini.embed_text.return_value = [0.8] * 768

    msg_a = create_message(1, "I love pizza", 1000)
    msg_b = create_message(2, "Pizza is my favorite food", 1010)

    signal = await detector._detect_semantic_boundary(msg_a, msg_b)

    # High similarity = no boundary
    assert signal is None


@pytest.mark.asyncio
async def test_semantic_boundary_short_messages(detector, mock_gemini):
    """Test that short messages are skipped."""
    msg_a = create_message(1, "Hi", 1000)
    msg_b = create_message(2, "Hello", 1010)

    signal = await detector._detect_semantic_boundary(msg_a, msg_b)

    # Too short to analyze
    assert signal is None
    # Should not have called embedding
    mock_gemini.embed_text.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_boundary_uses_cached_embedding(detector, mock_gemini):
    """Test that cached embeddings are reused."""
    # Use very different embeddings to ensure low similarity
    embedding_a = [1.0] * 768
    embedding_b = [0.0] * 768  # Completely different = similarity ~0.0

    # Message with cached embedding
    msg_a = create_message(1, "Test message one", 1000)
    msg_a["embedding"] = json.dumps(embedding_a)

    msg_b = create_message(2, "Different test message two", 1010)
    msg_b["embedding"] = json.dumps(embedding_b)

    signal = await detector._detect_semantic_boundary(msg_a, msg_b)

    # Should use cached embeddings, not call API
    mock_gemini.embed_text.assert_not_called()
    assert signal is not None  # Very different embeddings should trigger boundary
    assert signal.signal_type == "semantic"


# ═══════════════════════════════════════════════════════════════════════════
# Signal Clustering Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_cluster_signals_single_cluster(detector):
    """Test clustering of signals close together."""
    signals = [
        BoundarySignal(1, 1000, "temporal", 0.8, "Gap"),
        BoundarySignal(1, 1020, "topic_marker", 0.8, "Marker"),
        BoundarySignal(1, 1040, "semantic", 0.7, "Shift"),
    ]

    clusters = detector._cluster_signals(signals, time_window=60)

    assert len(clusters) == 1
    assert len(clusters[0]) == 3  # All in one cluster


def test_cluster_signals_multiple_clusters(detector):
    """Test clustering with distant signals."""
    signals = [
        BoundarySignal(1, 1000, "temporal", 0.8, "Gap 1"),
        BoundarySignal(1, 1020, "topic_marker", 0.8, "Marker 1"),
        BoundarySignal(2, 2000, "temporal", 0.9, "Gap 2"),  # Far away
        BoundarySignal(2, 2030, "semantic", 0.7, "Shift 2"),
    ]

    clusters = detector._cluster_signals(signals, time_window=60)

    assert len(clusters) == 2
    assert len(clusters[0]) == 2  # First cluster
    assert len(clusters[1]) == 2  # Second cluster


def test_cluster_signals_empty(detector):
    """Test clustering with no signals."""
    clusters = detector._cluster_signals([], time_window=60)

    assert len(clusters) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Signal Scoring Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_score_single_signal_type(detector):
    """Test scoring with single signal type."""
    signals = [BoundarySignal(1, 1000, "temporal", 0.8, "Gap")]

    score = detector._score_signal_cluster(signals)

    # Just temporal weight * strength
    expected = 0.8 * detector.TEMPORAL_WEIGHT
    assert abs(score - expected) < 0.01


def test_score_multiple_signal_types(detector):
    """Test scoring with multiple signal types (bonus)."""
    signals = [
        BoundarySignal(1, 1000, "temporal", 0.8, "Gap"),
        BoundarySignal(1, 1020, "topic_marker", 0.8, "Marker"),
    ]

    score = detector._score_signal_cluster(signals)

    # Weighted sum + 20% bonus for 2 types
    base = 0.8 * detector.TEMPORAL_WEIGHT + 0.8 * detector.TOPIC_MARKER_WEIGHT
    expected = base * 1.2
    assert abs(score - expected) < 0.01


def test_score_all_signal_types(detector):
    """Test scoring with all three signal types (maximum bonus)."""
    signals = [
        BoundarySignal(1, 1000, "temporal", 1.0, "Gap"),
        BoundarySignal(1, 1020, "topic_marker", 0.8, "Marker"),
        BoundarySignal(1, 1040, "semantic", 0.9, "Shift"),
    ]

    score = detector._score_signal_cluster(signals)

    # Weighted sum + 20% for 2 types + 10% for 3 types
    base = (
        1.0 * detector.TEMPORAL_WEIGHT
        + 0.8 * detector.TOPIC_MARKER_WEIGHT
        + 0.9 * detector.SEMANTIC_WEIGHT
    )
    expected = min(base * 1.2 * 1.1, 1.0)  # Cap at 1.0
    assert abs(score - expected) < 0.01


def test_score_empty_signals(detector):
    """Test scoring with no signals."""
    score = detector._score_signal_cluster([])

    assert score == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Boundary Decision Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_should_create_boundary_strong_signals(detector):
    """Test boundary creation with strong signals."""
    messages = [
        create_message(1, "Test 1", 1000),
        create_message(2, "Test 2", 1020),
    ]
    sequence = create_sequence(messages)

    # Strong signals
    signals = [
        BoundarySignal(2, 1020, "temporal", 1.0, "Long gap"),
        BoundarySignal(2, 1020, "topic_marker", 0.8, "Marker"),
        BoundarySignal(2, 1020, "semantic", 0.9, "Shift"),
    ]

    should_create, score, contributing = await detector.should_create_boundary(
        sequence, signals
    )

    assert should_create is True
    assert score >= detector.boundary_threshold
    assert len(contributing) > 0


@pytest.mark.asyncio
async def test_should_create_boundary_weak_signals(detector):
    """Test boundary decision with weak signals."""
    messages = [
        create_message(1, "Test 1", 1000),
        create_message(2, "Test 2", 1020),
    ]
    sequence = create_sequence(messages)

    # Weak signals
    signals = [
        BoundarySignal(2, 1020, "temporal", 0.3, "Short gap"),
    ]

    should_create, score, contributing = await detector.should_create_boundary(
        sequence, signals
    )

    assert should_create is False
    assert score < detector.boundary_threshold


@pytest.mark.asyncio
async def test_should_create_boundary_no_signals(detector):
    """Test boundary decision with no signals."""
    messages = [
        create_message(1, "Test 1", 1000),
        create_message(2, "Test 2", 1020),
    ]
    sequence = create_sequence(messages)

    should_create, score, contributing = await detector.should_create_boundary(
        sequence, []
    )

    assert should_create is False
    assert score == 0.0
    assert len(contributing) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_detect_boundaries_full_sequence(detector, mock_gemini):
    """Test full boundary detection on message sequence."""
    # Create conversation with clear topic shift
    messages = [
        create_message(1, "I love programming in Python very much indeed", 1000),
        create_message(2, "Yeah Python is great for data science tasks", 1010),
        create_message(3, "Totally agree pandas is amazing for analysis", 1020),
        # Long gap + topic shift
        create_message(4, "By the way what about the weather today outside", 5000),
        create_message(5, "It's quite rainy I think unfortunately today", 5010),
    ]

    # Mock embeddings for semantic comparison
    # Each semantic boundary check needs 2 embeddings (for pair of messages)
    # Order: For each pair (i, i+1), we get embedding for msg[i] then msg[i+1]
    # Pairs: (1,2), (2,3), (3,4), (4,5)
    embeddings_queue = [
        [1.0] + [0.0] * 767,  # msg 1
        [0.95] + [0.0] * 767,  # msg 2 (similar to msg 1)
        [0.95] + [0.0] * 767,  # msg 2
        [0.9] + [0.0] * 767,  # msg 3 (similar to msg 2)
        [0.9] + [0.0] * 767,  # msg 3
        [0.0] + [1.0] * 767,  # msg 4 (VERY DIFFERENT - weather topic!)
        [0.0] + [1.0] * 767,  # msg 4
        [0.0] + [0.95] * 767,  # msg 5 (similar to msg 4)
    ]

    call_count = [0]

    def get_embedding(text):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(embeddings_queue):
            return embeddings_queue[idx]
        return [0.5] * 768  # Fallback

    mock_gemini.embed_text.side_effect = get_embedding

    sequence = create_sequence(messages)
    signals = await detector.detect_boundaries(sequence)

    # Should detect multiple signals around message 4
    assert len(signals) > 0

    # Should have temporal signal (large gap)
    temporal_signals = [s for s in signals if s.signal_type == "temporal"]
    assert len(temporal_signals) > 0
    assert any(s.strength == 1.0 for s in temporal_signals)

    # Should have topic marker ("by the way")
    marker_signals = [s for s in signals if s.signal_type == "topic_marker"]
    assert len(marker_signals) > 0

    # Should have semantic signal (topic shift between msg 3 and 4)
    semantic_signals = [s for s in signals if s.signal_type == "semantic"]
    assert len(semantic_signals) > 0


@pytest.mark.asyncio
async def test_detect_boundaries_no_boundaries(detector, mock_gemini):
    """Test detection on coherent conversation (no boundaries)."""
    # All messages close together, same topic, high similarity
    messages = [
        create_message(1, "I love pizza", 1000),
        create_message(2, "Me too, especially with cheese", 1010),
        create_message(3, "Yeah cheese pizza is the best", 1020),
    ]

    # Similar embeddings
    mock_gemini.embed_text.return_value = [0.9] * 768

    sequence = create_sequence(messages)
    signals = await detector.detect_boundaries(sequence)

    # Should have minimal or no strong signals
    strong_signals = [s for s in signals if s.strength >= 0.7]
    assert len(strong_signals) == 0
