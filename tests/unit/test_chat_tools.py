"""Unit tests for tool registry (Phase C).

Covers:
- build_tool_definitions toggling by settings
- build_tool_callbacks creation and usage tracking
- search_messages tool callback formatting and behavior
"""

import asyncio
import json
import pytest

from app.handlers.chat_tools import (
    build_tool_definitions,
    build_tool_callbacks,
)


class _DummyStore:
    def __init__(self):
        self.calls = []

    async def semantic_search(self, chat_id, thread_id, query_embedding, limit):
        # Record call for assertions
        self.calls.append(
            {
                "chat_id": chat_id,
                "thread_id": thread_id,
                "embedding_len": len(query_embedding) if query_embedding else 0,
                "limit": limit,
            }
        )
        # Return two mock results
        return [
            {
                "score": 0.9,
                "text": "First result text",
                "metadata": {"message_id": "1001", "user_id": "42"},
                "role": "user",
                "message_id": 1,
            },
            {
                "score": 0.8,
                "text": "Second result text",
                "metadata": {"message_id": "1002", "user_id": "99"},
                "role": "model",
                "message_id": 2,
            },
        ]


class _DummyGemini:
    def __init__(self):
        self.embed_calls = []

    async def embed_text(self, text: str):
        self.embed_calls.append(text)
        return [0.1, 0.2, 0.3]


class _DummyProfileStore:
    pass


def _names_from_defs(defs: list[dict]) -> list[str]:
    names = []
    for d in defs:
        for f in d.get("function_declarations", []):
            if f.get("name"):
                names.append(f["name"])
    return sorted(names)


class _DummySettings:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.mark.asyncio
async def test_build_tool_definitions_flags():
    s = _DummySettings(
        enable_search_grounding=True,
        enable_tool_based_memory=True,
        enable_image_generation=False,
    )
    defs = build_tool_definitions(s)
    names = _names_from_defs(defs)

    # Always present
    assert "search_messages" in names
    assert "calculator" in names
    assert "weather" in names
    assert "currency" in names
    assert "polls" in names

    # Flags
    assert "search_web" in names, "search_web should be included when enabled"
    assert "remember_memory" in names, "memory tools should be included"
    assert "recall_memories" in names
    assert "forget_memory" in names
    assert "forget_all_memories" in names
    assert "set_pronouns" in names
    assert "generate_image" not in names
    assert "edit_image" not in names

    # Enable image tools
    s2 = _DummySettings(
        enable_search_grounding=False,
        enable_tool_based_memory=False,
        enable_image_generation=True,
    )
    defs2 = build_tool_definitions(s2)
    names2 = _names_from_defs(defs2)

    assert "generate_image" in names2
    assert "edit_image" in names2
    assert "search_web" not in names2
    assert "remember_memory" not in names2


@pytest.mark.asyncio
async def test_search_messages_callback_tracks_usage_and_formats_output():
    s = _DummySettings(
        enable_search_grounding=False,
        enable_tool_based_memory=False,
        enable_image_generation=False,
    )
    store = _DummyStore()
    gemini = _DummyGemini()
    profile_store = _DummyProfileStore()
    memory_repo = None  # Mock memory repo
    tools_used: list[str] = []

    callbacks = build_tool_callbacks(
        settings=s,
        store=store,
        gemini_client=gemini,
        profile_store=profile_store,
        memory_repo=memory_repo,
        chat_id=123,
        thread_id=456,
        message_id=999,
        tools_used_tracker=tools_used,
    )

    assert "search_messages" in callbacks, "search_messages callback should be present"

    payload_raw = await callbacks["search_messages"]({"query": "hello", "limit": 2})
    payload = json.loads(payload_raw)

    # Usage tracker records the tool
    assert tools_used == ["search_messages"], tools_used

    # Validate results structure and formatting
    assert "results" in payload and len(payload["results"]) == 2
    first = payload["results"][0]
    assert first["role"] == "user"
    assert first["message_id"] == 1
    assert "metadata" in first and isinstance(first["metadata"], dict)
    assert "metadata_text" in first and first["metadata_text"].startswith("[meta]")

    # Ensure embed_text was called
    assert gemini.embed_calls == ["hello"], gemini.embed_calls
