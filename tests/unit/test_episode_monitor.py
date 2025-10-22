"""
Tests for Episode Monitor.

Phase 4.2: Tests for automatic episode creation and monitoring.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.config import Settings
from app.services.context.episode_boundary_detector import (
    BoundarySignal,
    EpisodeBoundaryDetector,
)
from app.services.context.episode_monitor import ConversationWindow, EpisodeMonitor
from app.services.context.episodic_memory import EpisodicMemoryStore


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock(spec=Settings)
    settings.auto_create_episodes = True
    settings.episode_min_messages = 5
    settings.episode_min_importance = 0.6
    settings.episode_window_timeout = 1800  # 30 minutes
    settings.episode_window_max_messages = 50
    settings.episode_monitor_interval = 300  # 5 minutes
    return settings


@pytest.fixture
def mock_gemini():
    """Create mock Gemini client."""
    return AsyncMock()


@pytest.fixture
def mock_episodic_memory():
    """Create mock episodic memory store."""
    memory = AsyncMock(spec=EpisodicMemoryStore)
    memory.create_episode.return_value = 123  # Mock episode ID
    return memory


@pytest.fixture
def mock_boundary_detector():
    """Create mock boundary detector."""
    detector = AsyncMock(spec=EpisodeBoundaryDetector)
    # Default: no boundary detected
    detector.detect_boundaries.return_value = []
    detector.should_create_boundary.return_value = (False, 0.3, [])
    return detector


@pytest_asyncio.fixture
async def monitor(
    tmp_path, mock_settings, mock_gemini, mock_episodic_memory, mock_boundary_detector
):
    """Create episode monitor instance."""
    db_path = tmp_path / "test.db"
    monitor = EpisodeMonitor(
        db_path,
        mock_settings,
        mock_gemini,
        mock_episodic_memory,
        mock_boundary_detector,
    )
    return monitor


def create_message(
    msg_id: int, user_id: int, text: str, timestamp: int | None = None
) -> dict:
    """Create a test message."""
    if timestamp is None:
        timestamp = int(time.time())

    return {
        "id": msg_id,
        "user_id": user_id,
        "text": text,
        "timestamp": timestamp,
        "chat_id": 1,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ConversationWindow Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_conversation_window_creation():
    """Test conversation window creation."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    assert window.chat_id == 1
    assert window.thread_id is None
    assert len(window.messages) == 0
    assert len(window.participant_ids) == 0


def test_conversation_window_add_message():
    """Test adding messages to window."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    msg1 = create_message(1, 100, "Hello")
    msg2 = create_message(2, 200, "Hi there")

    window.add_message(msg1)
    window.add_message(msg2)

    assert len(window.messages) == 2
    assert 100 in window.participant_ids
    assert 200 in window.participant_ids


def test_conversation_window_expiration():
    """Test window expiration check."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Fresh window should not be expired
    assert not window.is_expired(timeout=1800)

    # Set last_activity to past
    window.last_activity = int(time.time()) - 2000

    # Now should be expired (timeout 1800 = 30 minutes)
    assert window.is_expired(timeout=1800)


def test_conversation_window_minimum_messages():
    """Test minimum message count check."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Not enough messages
    assert not window.has_minimum_messages(5)

    # Add messages
    for i in range(5):
        window.add_message(create_message(i, 100, f"Message {i}"))

    # Now has minimum
    assert window.has_minimum_messages(5)


def test_conversation_window_to_sequence():
    """Test conversion to MessageSequence."""
    window = ConversationWindow(chat_id=1, thread_id=42)

    msg1 = create_message(1, 100, "First", timestamp=1000)
    msg2 = create_message(2, 100, "Second", timestamp=2000)

    window.add_message(msg1)
    window.add_message(msg2)

    sequence = window.to_message_sequence()

    assert sequence.chat_id == 1
    assert sequence.thread_id == 42
    assert len(sequence.messages) == 2
    assert sequence.start_timestamp == 1000
    assert sequence.end_timestamp == 2000


# ═══════════════════════════════════════════════════════════════════════════
# EpisodeMonitor - Basic Operations
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_monitor_initialization(monitor):
    """Test monitor initialization."""
    assert monitor.windows == {}
    assert not monitor._running
    assert monitor.window_timeout == 1800
    assert monitor.min_messages_for_episode == 5


@pytest.mark.asyncio
async def test_monitor_start_stop(monitor):
    """Test starting and stopping monitor."""
    # Start
    await monitor.start()
    assert monitor._running is True
    assert monitor._monitor_task is not None

    # Give it a moment to start
    await asyncio.sleep(0.1)

    # Stop
    await monitor.stop()
    assert monitor._running is False


@pytest.mark.asyncio
async def test_monitor_track_message_creates_window(monitor):
    """Test that tracking a message creates a new window."""
    msg = create_message(1, 100, "Hello")

    await monitor.track_message(chat_id=1, thread_id=None, message=msg)

    # Should have created a window
    assert len(monitor.windows) == 1
    key = (1, None)
    assert key in monitor.windows

    window = monitor.windows[key]
    assert len(window.messages) == 1
    assert 100 in window.participant_ids


@pytest.mark.asyncio
async def test_monitor_track_message_adds_to_existing_window(monitor):
    """Test that tracking multiple messages adds to same window."""
    msg1 = create_message(1, 100, "Hello")
    msg2 = create_message(2, 200, "Hi")

    await monitor.track_message(chat_id=1, thread_id=None, message=msg1)
    await monitor.track_message(chat_id=1, thread_id=None, message=msg2)

    # Should still have one window
    assert len(monitor.windows) == 1

    window = monitor.windows[(1, None)]
    assert len(window.messages) == 2
    assert 100 in window.participant_ids
    assert 200 in window.participant_ids


@pytest.mark.asyncio
async def test_monitor_track_message_separate_threads(monitor):
    """Test that different threads create separate windows."""
    msg1 = create_message(1, 100, "Hello")
    msg2 = create_message(2, 100, "Hi")

    await monitor.track_message(chat_id=1, thread_id=None, message=msg1)
    await monitor.track_message(chat_id=1, thread_id=42, message=msg2)

    # Should have two windows
    assert len(monitor.windows) == 2
    assert (1, None) in monitor.windows
    assert (1, 42) in monitor.windows


@pytest.mark.asyncio
async def test_monitor_disabled_when_auto_create_off(monitor, mock_settings):
    """Test that monitor doesn't track when auto_create_episodes is False."""
    mock_settings.auto_create_episodes = False

    msg = create_message(1, 100, "Hello")
    await monitor.track_message(chat_id=1, thread_id=None, message=msg)

    # Should not have created a window
    assert len(monitor.windows) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Episode Creation Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_episode_from_window(monitor, mock_episodic_memory):
    """Test creating an episode from a window."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add enough messages (start from ID 1, not 0)
    for i in range(1, 6):
        window.add_message(
            create_message(i, 100 + i, f"Message {i}", timestamp=1000 + i)
        )

    episode_id = await monitor._create_episode_from_window(window, "test")

    # Should have created episode
    assert episode_id == 123
    mock_episodic_memory.create_episode.assert_called_once()

    # Check call arguments
    call_args = mock_episodic_memory.create_episode.call_args
    assert call_args.kwargs["chat_id"] == 1
    assert call_args.kwargs["thread_id"] is None
    assert len(call_args.kwargs["messages"]) == 5
    assert len(call_args.kwargs["user_ids"]) == 5


@pytest.mark.asyncio
async def test_create_episode_skips_if_too_few_messages(monitor, mock_episodic_memory):
    """Test that episode creation is skipped if not enough messages."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add only 3 messages (need 5)
    for i in range(3):
        window.add_message(create_message(i, 100, f"Message {i}"))

    episode_id = await monitor._create_episode_from_window(window, "test")

    # Should not have created episode
    assert episode_id is None
    mock_episodic_memory.create_episode.assert_not_called()


@pytest.mark.asyncio
async def test_calculate_importance_message_count(monitor):
    """Test importance calculation based on message count."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # 5 messages
    for i in range(5):
        window.add_message(create_message(i, 100, f"Msg {i}", timestamp=1000 + i))

    importance = monitor._calculate_importance(window)

    # Should have base importance from message count
    assert importance >= 0.2


@pytest.mark.asyncio
async def test_calculate_importance_participants(monitor):
    """Test importance calculation based on participant count."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # 5 messages from 3 different users
    for i in range(5):
        user_id = 100 + (i % 3)  # Rotate through 3 users
        window.add_message(create_message(i, user_id, f"Msg {i}", timestamp=1000 + i))

    importance = monitor._calculate_importance(window)

    # Should have importance from participants
    assert importance >= 0.3


@pytest.mark.asyncio
async def test_calculate_importance_duration(monitor):
    """Test importance calculation based on conversation duration."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # 5 messages over 40 minutes
    for i in range(5):
        timestamp = 1000 + (i * 600)  # 10 minute intervals = 40 min total
        window.add_message(create_message(i, 100, f"Msg {i}", timestamp=timestamp))

    importance = monitor._calculate_importance(window)

    # Should have importance from duration
    assert importance >= 0.3


# ═══════════════════════════════════════════════════════════════════════════
# Boundary Detection Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_check_window_boundary_no_boundary(monitor, mock_boundary_detector):
    """Test checking window when no boundary detected."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add enough messages
    for i in range(5):
        window.add_message(create_message(i, 100, f"Msg {i}"))

    # No boundary detected
    mock_boundary_detector.should_create_boundary.return_value = (False, 0.3, [])

    # Add to monitor
    monitor.windows[(1, None)] = window

    await monitor._check_window_boundary((1, None), window, auto_close=True)

    # Window should still exist (not closed)
    assert (1, None) in monitor.windows


@pytest.mark.asyncio
async def test_check_window_boundary_boundary_detected(
    monitor, mock_boundary_detector, mock_episodic_memory
):
    """Test checking window when boundary is detected."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add enough messages
    for i in range(5):
        window.add_message(create_message(i, 100, f"Msg {i}", timestamp=1000 + i))

    # Boundary detected
    signal = BoundarySignal(
        message_id=4, timestamp=1004, signal_type="temporal", strength=1.0, reason="Gap"
    )
    mock_boundary_detector.detect_boundaries.return_value = [signal]
    mock_boundary_detector.should_create_boundary.return_value = (True, 0.8, [signal])

    # Add to monitor
    monitor.windows[(1, None)] = window

    await monitor._check_window_boundary((1, None), window, auto_close=True)

    # Episode should have been created
    mock_episodic_memory.create_episode.assert_called_once()

    # Window should be closed
    assert (1, None) not in monitor.windows


@pytest.mark.asyncio
async def test_check_window_boundary_auto_close_false(
    monitor, mock_boundary_detector, mock_episodic_memory
):
    """Test that auto_close=False doesn't close window."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add enough messages
    for i in range(5):
        window.add_message(create_message(i, 100, f"Msg {i}"))

    # Boundary detected
    signal = BoundarySignal(
        message_id=4, timestamp=1004, signal_type="temporal", strength=1.0, reason="Gap"
    )
    mock_boundary_detector.should_create_boundary.return_value = (True, 0.8, [signal])

    # Add to monitor
    monitor.windows[(1, None)] = window

    await monitor._check_window_boundary((1, None), window, auto_close=False)

    # Episode should NOT be created
    mock_episodic_memory.create_episode.assert_not_called()

    # Window should still exist
    assert (1, None) in monitor.windows


# ═══════════════════════════════════════════════════════════════════════════
# Window Management Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_active_windows(monitor):
    """Test getting list of active windows."""
    # Create some windows
    window1 = ConversationWindow(chat_id=1, thread_id=None)
    window2 = ConversationWindow(chat_id=2, thread_id=42)

    monitor.windows[(1, None)] = window1
    monitor.windows[(2, 42)] = window2

    active = await monitor.get_active_windows()

    assert len(active) == 2
    assert window1 in active
    assert window2 in active


@pytest.mark.asyncio
async def test_get_window_count(monitor):
    """Test getting window count."""
    assert await monitor.get_window_count() == 0

    # Add windows
    monitor.windows[(1, None)] = ConversationWindow(chat_id=1, thread_id=None)
    monitor.windows[(2, None)] = ConversationWindow(chat_id=2, thread_id=None)

    assert await monitor.get_window_count() == 2


@pytest.mark.asyncio
async def test_clear_window(monitor):
    """Test manually clearing a window."""
    window = ConversationWindow(chat_id=1, thread_id=None)
    monitor.windows[(1, None)] = window

    # Clear window
    cleared = await monitor.clear_window(chat_id=1, thread_id=None)

    assert cleared is True
    assert (1, None) not in monitor.windows


@pytest.mark.asyncio
async def test_clear_nonexistent_window(monitor):
    """Test clearing a window that doesn't exist."""
    cleared = await monitor.clear_window(chat_id=999, thread_id=None)

    assert cleared is False


# ═══════════════════════════════════════════════════════════════════════════
# Max Messages Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_track_message_triggers_boundary_check_at_max(
    monitor, mock_boundary_detector, mock_episodic_memory
):
    """Test that reaching max messages triggers boundary check."""
    # Set low max for testing
    monitor.max_messages_per_window = 5

    # Boundary will be detected
    signal = BoundarySignal(
        message_id=4, timestamp=1004, signal_type="temporal", strength=1.0, reason="Gap"
    )
    mock_boundary_detector.should_create_boundary.return_value = (True, 0.8, [signal])

    # Add messages up to max
    for i in range(5):
        msg = create_message(i, 100, f"Msg {i}", timestamp=1000 + i)
        await monitor.track_message(chat_id=1, thread_id=None, message=msg)

    # Episode should have been created
    mock_episodic_memory.create_episode.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# Topic and Summary Generation Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_generate_topic(monitor):
    """Test topic generation from window."""
    window = ConversationWindow(chat_id=1, thread_id=None)
    window.add_message(create_message(1, 100, "This is a test message about Python"))

    topic = await monitor._generate_topic(window)

    # Should use first message
    assert "This is a test message about Python" in topic


@pytest.mark.asyncio
async def test_generate_topic_truncates_long_messages(monitor):
    """Test that long messages are truncated for topic."""
    window = ConversationWindow(chat_id=1, thread_id=None)
    long_text = "A" * 100
    window.add_message(create_message(1, 100, long_text))

    topic = await monitor._generate_topic(window)

    # Should be truncated
    assert len(topic) <= 53  # 50 chars + "..."
    assert "..." in topic


@pytest.mark.asyncio
async def test_generate_summary(monitor):
    """Test summary generation from window."""
    window = ConversationWindow(chat_id=1, thread_id=None)

    # Add 5 messages from 3 users
    for i in range(5):
        user_id = 100 + (i % 3)
        window.add_message(create_message(i, user_id, f"Msg {i}"))

    summary = await monitor._generate_summary(window)

    # Should mention participants and message count
    assert "3 participant" in summary
    assert "5 message" in summary
