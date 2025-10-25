"""Tests for Gemini free-tier key rotation."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from app.services import gemini as gemini_module
from app.services.gemini import GeminiClient, GeminiError


class DummyPart:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.function_call = None


class DummyCandidate:
    def __init__(self, text: str) -> None:
        self.finish_reason = "STOP"
        self.content = SimpleNamespace(parts=[DummyPart(text)], role="model")


class DummyResponse:
    def __init__(self, text: str) -> None:
        self.candidates = [DummyCandidate(text)]
        self.text = text


class DummyEmbedding:
    def __init__(self, values: list[float]) -> None:
        self.values = values


class DummyEmbedResponse:
    def __init__(self, values: list[float]) -> None:
        self.embeddings = [DummyEmbedding(values)]


@pytest.fixture
def patched_gemini(monkeypatch: pytest.MonkeyPatch):
    """Patch google SDK primitives to deterministic fakes."""

    random.seed(0)
    call_order: list[tuple[str, str]] = []
    response_map: dict[str, dict[str, object]] = {}

    class DummyModels:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def generate_content(self, *, model: str, contents, config):  # type: ignore[unused-argument]
            call_order.append(("generate", self.api_key))
            outcome = response_map[self.api_key]["generate"]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def embed_content(self, *, model: str, contents):  # type: ignore[unused-argument]
            call_order.append(("embed", self.api_key))
            outcome = response_map[self.api_key]["embed"]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class DummyClient:
        def __init__(self, api_key: str) -> None:
            self.aio = SimpleNamespace(models=DummyModels(api_key))

    monkeypatch.setattr(
        gemini_module,
        "genai",
        SimpleNamespace(Client=DummyClient),
    )
    monkeypatch.setattr(
        gemini_module,
        "types",
        SimpleNamespace(
            SafetySetting=lambda **_: None,
            HarmCategory=SimpleNamespace(
                HARM_CATEGORY_HARASSMENT="HARM_CATEGORY_HARASSMENT",
                HARM_CATEGORY_HATE_SPEECH="HARM_CATEGORY_HATE_SPEECH",
                HARM_CATEGORY_SEXUALLY_EXPLICIT="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                HARM_CATEGORY_DANGEROUS_CONTENT="HARM_CATEGORY_DANGEROUS_CONTENT",
            ),
            HarmBlockThreshold=SimpleNamespace(BLOCK_NONE="BLOCK_NONE"),
            Tool=lambda **_: None,
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
            ContentListUnionDict=list,
        ),
    )

    return call_order, response_map


@pytest.mark.asyncio
async def test_generate_rotates_on_quota(patched_gemini):
    call_order, response_map = patched_gemini
    response_map["key1"] = {
        "generate": RuntimeError("429 quota"),
        "embed": DummyEmbedResponse([0.1, 0.2]),
    }
    response_map["key2"] = {
        "generate": DummyResponse("Все працює"),
        "embed": DummyEmbedResponse([0.3, 0.4]),
    }

    client = GeminiClient(
        api_key="key1",
        model="gemini-2.5-flash",
        embed_model="models/text-embedding-004",
        free_tier_mode=True,
        api_keys=["key1", "key2"],
    )

    if client._key_pool:  # type: ignore[attr-defined]
        client._key_pool._index = 0  # type: ignore[attr-defined]

    result = await client.generate("", [], [{"text": "Привіт"}])

    assert "працює" in result.lower()
    assert call_order[0] == ("generate", "key1")
    assert call_order[1] == ("generate", "key2")


@pytest.mark.asyncio
async def test_generate_raises_after_all_keys_exhausted(patched_gemini):
    call_order, response_map = patched_gemini
    quota_error = RuntimeError("quota exceeded")
    response_map["key1"] = {"generate": quota_error, "embed": DummyEmbedResponse([0.1])}
    response_map["key2"] = {"generate": quota_error, "embed": DummyEmbedResponse([0.2])}

    client = GeminiClient(
        api_key="key1",
        model="gemini-2.5-flash",
        embed_model="models/text-embedding-004",
        free_tier_mode=True,
        api_keys=["key1", "key2"],
    )

    if client._key_pool:  # type: ignore[attr-defined]
        client._key_pool._index = 0  # type: ignore[attr-defined]

    with pytest.raises(GeminiError):
        await client.generate("", [], [{"text": "Привіт"}])

    assert call_order[:2] == [("generate", "key1"), ("generate", "key2")]


@pytest.mark.asyncio
async def test_embed_rotates_on_quota(patched_gemini):
    call_order, response_map = patched_gemini
    response_map["key1"] = {
        "generate": DummyResponse("Не використано"),
        "embed": RuntimeError("429 quota"),
    }
    response_map["key2"] = {
        "generate": DummyResponse("Не використано"),
        "embed": DummyEmbedResponse([0.9, 0.1]),
    }

    client = GeminiClient(
        api_key="key1",
        model="gemini-2.5-flash",
        embed_model="models/text-embedding-004",
        free_tier_mode=True,
        api_keys=["key1", "key2"],
    )

    if client._key_pool:  # type: ignore[attr-defined]
        client._key_pool._index = 0  # type: ignore[attr-defined]

    result = await client.embed_text("hello world")

    assert result == [0.9, 0.1]
    assert ("embed", "key1") in call_order
    assert ("embed", "key2") in call_order
