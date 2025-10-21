"""Unit tests for memory tools: recall_facts semantic ranking.

Covers semantic ranking path when embeddings are available via fact repository.
"""

import json
import pytest
import pytest_asyncio

from app.services.tools.memory_tools import recall_facts_tool


class _DummyGemini:
    async def embed_text(self, text: str):
        # Return a simple 2-D embedding; test uses [1,0] as query
        return [1.0, 0.0]


class _DummyFactRepo:
    def __init__(self, facts):
        self._facts = facts

    async def get_facts(self, entity_id, chat_context=None, categories=None, limit=100):
        facts = self._facts
        if categories:
            facts = [f for f in facts if f.get("fact_category") in categories]
        return facts[:limit]


class _DummyProfileStore:
    def __init__(self, fact_repo):
        # Expose fact repository via expected attribute for resolution
        self.fact_repository = fact_repo


@pytest.mark.asyncio
async def test_recall_facts_semantic_ranking_prefers_higher_similarity():
    # Two candidate facts with embeddings; first should win with query [1,0]
    facts = [
        {
            "id": 1,
            "fact_category": "preference",
            "fact_key": "favorite_animal",
            "fact_value": "cats",
            "confidence": 0.9,
            "created_at": 1000,
            "embedding": [1.0, 0.0],
        },
        {
            "id": 2,
            "fact_category": "preference",
            "fact_key": "favorite_animal",
            "fact_value": "dogs",
            "confidence": 0.9,
            "created_at": 1001,
            "embedding": [0.0, 1.0],
        },
    ]

    repo = _DummyFactRepo(facts)
    profile_store = _DummyProfileStore(repo)

    payload = await recall_facts_tool(
        user_id=123,
        fact_types=["preference"],
        search_query="cats",
        limit=1,
        chat_id=456,
        profile_store=profile_store,
        fact_repo=repo,
        gemini_client=_DummyGemini(),
    )

    data = json.loads(payload)
    assert data.get("status") == "success"
    assert data.get("count") == 1
    assert data.get("facts")[0]["fact_id"] == 1
