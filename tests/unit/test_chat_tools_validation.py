"""Validation tests for the centralized tool registry.

Ensures:
- No duplicate function names in tool definitions
- Reasonable parameter schema exists for each tool
- Callback registry exposes callbacks for all defined tools when enabled
"""

import pytest
import types

from app.handlers.chat_tools import build_tool_definitions, build_tool_callbacks


class _DummySettings:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _DummyBot:
    async def send_photo(self, *args, **kwargs):
        return None


class _DummyImageService:
    async def generate_image(self, **kwargs):
        return b"IMG"

    async def get_usage_stats(self, user_id, chat_id):
        return {"remaining": 0, "daily_limit": 1, "is_admin": False}


class _DummyMessage:
    reply_to_message = None


class _DummyProfileStore:
    pass


class _DummyGemini:
    async def embed_text(self, text: str):
        return [0.1, 0.2, 0.3]


def _names_from_defs(defs: list[dict]) -> list[str]:
    names = []
    for d in defs:
        for f in d.get("function_declarations", []):
            n = f.get("name")
            if isinstance(n, str):
                names.append(n)
    return names


@pytest.mark.asyncio
async def test_tool_definitions_unique_and_have_parameters():
    settings = _DummySettings(
        enable_search_grounding=True,
        enable_tool_based_memory=True,
        enable_image_generation=True,
    )

    defs = build_tool_definitions(settings)
    names = _names_from_defs(defs)

    # No duplicates
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    # All have parameter schemas with type object and properties mapping
    for d in defs:
        for f in d.get("function_declarations", []):
            params = f.get("parameters")
            assert isinstance(params, dict), f"Missing parameters for {f.get('name')}"
            assert params.get("type") == "object", f"parameters.type must be object for {f.get('name')}"
            props = params.get("properties")
            assert isinstance(props, dict), f"parameters.properties must be object for {f.get('name')}"


@pytest.mark.asyncio
async def test_registry_callbacks_include_defined_tools_when_enabled(monkeypatch):
    settings = _DummySettings(
        enable_search_grounding=True,
        enable_tool_based_memory=True,
        enable_image_generation=True,
    )

    defs = build_tool_definitions(settings)
    names = set(_names_from_defs(defs))

    # Build callbacks with all runtime deps
    callbacks = build_tool_callbacks(
        settings=settings,
        store=types.SimpleNamespace(),
        gemini_client=_DummyGemini(),
        profile_store=_DummyProfileStore(),
        chat_id=111,
        thread_id=222,
        message_id=333,
        tools_used_tracker=[],
        user_id=444,
        bot=_DummyBot(),
        message=_DummyMessage(),
        image_gen_service=_DummyImageService(),
    )

    # Ensure every defined tool name has a callback
    missing = names.difference(set(callbacks.keys()))
    assert not missing, f"Missing callbacks for: {sorted(missing)}"

