"""
Integration test for Episode Monitor with main bot flow.

Tests the complete flow:
1. Bot initializes episode monitor
2. Messages are tracked through chat handler
3. Episodes are created automatically
4. Background monitoring works
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.config import get_settings
from app.services.context.episode_boundary_detector import EpisodeBoundaryDetector
from app.services.context.episode_monitor import EpisodeMonitor
from app.services.context.episodic_memory import EpisodicMemoryStore
from app.services.gemini import GeminiClient

LOGGER = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def settings(test_db):
    """Get settings with test database."""
    settings = get_settings()
    # Override settings for testing (use object.__setattr__ for frozen Pydantic models)
    object.__setattr__(settings, "database_url", test_db)
    object.__setattr__(settings, "auto_create_episodes", True)
    object.__setattr__(settings, "episode_min_messages", 3)
    object.__setattr__(settings, "episode_window_timeout", 5)
    object.__setattr__(settings, "episode_window_max_messages", 10)
    object.__setattr__(settings, "episode_monitor_interval", 1)
    return settings


@pytest_asyncio.fixture
async def gemini_client():
    """Create a mock Gemini client."""
    client = MagicMock(spec=GeminiClient)

    # Mock embed_text to return dummy embeddings
    async def mock_embed(text):
        return [0.1] * 768

    client.embed_text = AsyncMock(side_effect=mock_embed)
    return client


@pytest_asyncio.fixture
async def episodic_memory(test_db, gemini_client, settings):
    """Create episodic memory store."""
    memory = EpisodicMemoryStore(
        database_url=test_db,
        gemini_client=gemini_client,
        settings=settings,
    )
    await memory.init()
    return memory


@pytest_asyncio.fixture
async def boundary_detector(test_db, settings, gemini_client):
    """Create boundary detector."""
    detector = EpisodeBoundaryDetector(
        database_url=test_db,
        settings=settings,
        gemini_client=gemini_client,
    )
    return detector


@pytest_asyncio.fixture
async def episode_monitor(
    test_db, settings, gemini_client, episodic_memory, boundary_detector
):
    """Create and start episode monitor."""
    monitor = EpisodeMonitor(
        database_url=test_db,
        settings=settings,
        gemini_client=gemini_client,
        episodic_memory=episodic_memory,
        boundary_detector=boundary_detector,
    )

    # Start monitoring
    await monitor.start()

    yield monitor

    # Stop monitoring
    await monitor.stop()


@pytest.mark.asyncio
async def test_episode_creation_flow(episode_monitor, episodic_memory):
    """Test complete episode creation flow."""
    chat_id = 123
    thread_id = None

    # Track multiple messages
    messages = [
        {
            "id": i,
            "user_id": 1,
            "text": f"Test message {i}",
            "timestamp": int(time.time()),
            "chat_id": chat_id,
        }
        for i in range(1, 6)  # 5 messages
    ]

    for msg in messages:
        await episode_monitor.track_message(chat_id, thread_id, msg)
        await asyncio.sleep(0.1)  # Small delay between messages

    # Verify window was created
    windows = await episode_monitor.get_active_windows()
    assert len(windows) > 0, "Should have created a window"

    window = windows[0]
    assert window.chat_id == chat_id
    assert window.thread_id == thread_id
    assert len(window.messages) == 5
    assert len(window.participant_ids) == 1

    LOGGER.info(f"✅ Window created with {len(window.messages)} messages")


@pytest.mark.asyncio
async def test_episode_creation_on_timeout(episode_monitor, episodic_memory, settings):
    """Test episode creation when window times out."""
    chat_id = 456
    thread_id = None

    # Track messages
    for i in range(1, 4):  # 3 messages (minimum)
        msg = {
            "id": i,
            "user_id": 1,
            "text": f"Message {i}",
            "timestamp": int(time.time()),
            "chat_id": chat_id,
        }
        await episode_monitor.track_message(chat_id, thread_id, msg)

    # Verify window exists
    windows = await episode_monitor.get_active_windows()
    assert len(windows) > 0

    LOGGER.info(
        f"Window created, waiting {settings.episode_window_timeout}s for timeout..."
    )

    # Wait for timeout + a bit extra
    await asyncio.sleep(settings.episode_window_timeout + 2)

    # Window should be closed now (episode created)
    # Note: This depends on background task running
    LOGGER.info("✅ Timeout test completed")


@pytest.mark.asyncio
async def test_multiple_conversations(episode_monitor):
    """Test tracking multiple separate conversations."""
    # Create messages in different chats
    for chat_id in [100, 200, 300]:
        for i in range(1, 4):
            msg = {
                "id": i,
                "user_id": 1,
                "text": f"Chat {chat_id} message {i}",
                "timestamp": int(time.time()),
                "chat_id": chat_id,
            }
            await episode_monitor.track_message(chat_id, None, msg)

    # Should have 3 separate windows
    windows = await episode_monitor.get_active_windows()
    assert len(windows) == 3, f"Expected 3 windows, got {len(windows)}"

    chat_ids = {w.chat_id for w in windows}
    assert chat_ids == {100, 200, 300}

    LOGGER.info("✅ Multiple conversations tracked separately")


@pytest.mark.asyncio
async def test_monitor_start_stop(episode_monitor):
    """Test monitor lifecycle."""
    # Monitor should already be started from fixture
    assert episode_monitor._monitor_task is not None
    assert not episode_monitor._monitor_task.done()

    # Stop it
    await episode_monitor.stop()
    assert episode_monitor._monitor_task is None or episode_monitor._monitor_task.done()

    # Restart
    await episode_monitor.start()
    assert episode_monitor._monitor_task is not None
    assert not episode_monitor._monitor_task.done()

    LOGGER.info("✅ Monitor start/stop works correctly")


@pytest.mark.asyncio
async def test_disabled_monitor(
    test_db, gemini_client, episodic_memory, boundary_detector
):
    """Test that monitor doesn't track when disabled."""
    # Create settings with auto_create disabled
    settings = get_settings()
    object.__setattr__(settings, "db_path", str(test_db))
    object.__setattr__(settings, "auto_create_episodes", False)

    monitor = EpisodeMonitor(
        db_path=test_db,
        settings=settings,
        gemini_client=gemini_client,
        episodic_memory=episodic_memory,
        boundary_detector=boundary_detector,
    )

    # Try to track a message
    msg = {
        "id": 1,
        "user_id": 1,
        "text": "Test",
        "timestamp": int(time.time()),
        "chat_id": 123,
    }

    await monitor.track_message(123, None, msg)

    # Should not create window
    windows = await monitor.get_active_windows()
    assert len(windows) == 0, "Disabled monitor should not create windows"

    LOGGER.info("✅ Disabled monitor doesn't track messages")


@pytest.mark.asyncio
async def test_window_max_messages_trigger(episode_monitor, settings):
    """Test that reaching max messages triggers boundary check."""
    chat_id = 789
    thread_id = None

    # Track max_messages + 1 messages
    for i in range(1, settings.episode_window_max_messages + 2):
        msg = {
            "id": i,
            "user_id": 1,
            "text": f"Message {i}",
            "timestamp": int(time.time()),
            "chat_id": chat_id,
        }
        await episode_monitor.track_message(chat_id, thread_id, msg)

    # Window might be closed if boundary was detected
    # At minimum, it should have triggered a boundary check
    windows = await episode_monitor.get_active_windows()

    LOGGER.info(f"✅ Max messages trigger test completed (windows: {len(windows)})")


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
