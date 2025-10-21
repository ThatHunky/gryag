"""Unit tests for image tools in the centralized registry.

Verifies that generate_image and edit_image callbacks are registered and work
when all runtime dependencies are provided to the registry.
"""

import json
import pytest
import types

from app.handlers.chat_tools import build_tool_callbacks


class _DummySettings:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, photo, caption=None, message_thread_id=None, reply_to_message_id=None):
        # Record call for assertions
        self.sent.append(
            {
                "chat_id": chat_id,
                "caption": caption,
                "thread_id": message_thread_id,
                "reply_to": reply_to_message_id,
                "filename": getattr(photo, "filename", None),
                "data_len": len(getattr(photo, "input_file", b"")),
            }
        )


class _DummyImageService:
    async def generate_image(self, prompt, aspect_ratio="1:1", user_id=None, chat_id=None, context_images=None):
        # Return fixed bytes to simulate an image
        return b"PNG_BYTES"

    async def get_usage_stats(self, user_id, chat_id):
        return {"remaining": 0, "daily_limit": 1, "is_admin": False}


class _DummyGemini:
    async def embed_text(self, text: str):
        return [0.1, 0.2]


class _DummyProfileStore:
    pass


class _DummyMessage:
    def __init__(self, reply_to_message=None):
        self.reply_to_message = reply_to_message


@pytest.mark.asyncio
async def test_generate_image_registry_callback(monkeypatch):
    settings = _DummySettings(enable_image_generation=True, enable_search_grounding=False, enable_tool_based_memory=False)
    bot = _DummyBot()
    image_service = _DummyImageService()
    profile_store = _DummyProfileStore()
    tools_used = []

    callbacks = build_tool_callbacks(
        settings=settings,
        store=types.SimpleNamespace(),  # not used by image tools
        gemini_client=_DummyGemini(),
        profile_store=profile_store,
        chat_id=123,
        thread_id=7,
        message_id=999,
        tools_used_tracker=tools_used,
        user_id=42,
        bot=bot,
        message=_DummyMessage(),
        image_gen_service=image_service,
    )

    assert "generate_image" in callbacks, "generate_image should be registered"
    raw = await callbacks["generate_image"]({"prompt": "draw cat", "aspect_ratio": "1:1"})
    data = json.loads(raw)
    assert data.get("success") is True
    assert tools_used == ["generate_image"]
    assert bot.sent and bot.sent[-1]["chat_id"] == 123
    assert bot.sent[-1]["reply_to"] == 999


@pytest.mark.asyncio
async def test_edit_image_registry_callback(monkeypatch):
    settings = _DummySettings(enable_image_generation=True, enable_search_grounding=False, enable_tool_based_memory=False)
    bot = _DummyBot()
    image_service = _DummyImageService()
    profile_store = _DummyProfileStore()
    tools_used = []

    # Patch collect_media_parts to return one image with bytes
    async def _fake_collect_media_parts(bot_obj, reply_msg):
        return [{"kind": "image", "bytes": b"IMG"}]

    from app import handlers as _h  # noqa: F401  # ensure package import
    import app.handlers.chat_tools as chat_tools_mod
    monkeypatch.setattr(chat_tools_mod, "collect_media_parts", _fake_collect_media_parts)

    reply = _DummyMessage()  # simple stub consumed by patched function
    message = _DummyMessage(reply_to_message=reply)

    callbacks = build_tool_callbacks(
        settings=settings,
        store=types.SimpleNamespace(),
        gemini_client=_DummyGemini(),
        profile_store=profile_store,
        chat_id=456,
        thread_id=11,
        message_id=1001,
        tools_used_tracker=tools_used,
        user_id=99,
        bot=bot,
        message=message,
        image_gen_service=image_service,
    )

    assert "edit_image" in callbacks, "edit_image should be registered"
    raw = await callbacks["edit_image"]({"prompt": "add text", "aspect_ratio": "1:1"})
    data = json.loads(raw)
    assert data.get("success") is True
    assert tools_used == ["edit_image"], tools_used
    assert bot.sent and bot.sent[-1]["chat_id"] == 456
    assert bot.sent[-1]["reply_to"] == 1001

