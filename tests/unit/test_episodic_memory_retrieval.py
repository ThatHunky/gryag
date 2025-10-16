from types import SimpleNamespace

import pytest

from app.services.context.episodic_memory import EpisodicMemoryStore


@pytest.mark.asyncio
async def test_retrieve_relevant_episodes_exact_participant_match(
    test_db, mock_gemini_client
):
    settings = SimpleNamespace(episode_min_importance=0.0)
    store = EpisodicMemoryStore(test_db, settings, mock_gemini_client)
    await store.init()

    mock_gemini_client.embed_text.return_value = [0.1, 0.2, 0.3]

    await store.create_episode(
        chat_id=1,
        thread_id=None,
        user_ids=[123],
        topic="Alpha topic",
        summary="Alpha summary",
        messages=[1],
        importance=0.9,
    )

    await store.create_episode(
        chat_id=1,
        thread_id=None,
        user_ids=[23],
        topic="Beta topic",
        summary="Beta summary",
        messages=[2],
        importance=0.8,
    )

    episodes = await store.retrieve_relevant_episodes(
        chat_id=1,
        user_id=23,
        query="Beta",
        limit=5,
    )

    assert len(episodes) == 1
    assert episodes[0].participant_ids == [23]
