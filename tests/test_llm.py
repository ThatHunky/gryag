import types as pytypes

import pytest

from gryag import llm


class FakeUsage:
    def __init__(self, prompt=1000, cached=None, visible=20, thoughts=None):
        self.prompt_token_count = prompt
        self.cached_content_token_count = cached
        self.candidates_token_count = visible
        self.thoughts_token_count = thoughts


class FakeResponse:
    def __init__(self, text="ага", usage=None):
        self.text = text
        self.usage_metadata = usage or FakeUsage()


class FakeClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []
        self.aio = pytypes.SimpleNamespace(models=self)

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error is not None:
            raise self._error
        return self._response


def test_cost_uses_the_cached_rate_for_cached_tokens():
    cost = llm.cost_usd(
        "gemini-2.5-flash",
        prompt_tokens=1_000_000,
        cached_tokens=1_000_000,
        visible_tokens=0,
        thought_tokens=0,
    )

    assert cost == pytest.approx(0.03)


def test_cost_bills_thinking_tokens_at_the_output_rate():
    cost = llm.cost_usd(
        "gemini-2.5-flash",
        prompt_tokens=0,
        cached_tokens=0,
        visible_tokens=500_000,
        thought_tokens=500_000,
    )

    assert cost == pytest.approx(2.50)


def test_unknown_model_costs_nothing_rather_than_crashing():
    assert llm.cost_usd("some-new-model", 1000, 0, 10, 10) == 0.0


async def test_returns_the_text_and_usage():
    client = FakeClient(FakeResponse("ага", FakeUsage(prompt=1800, visible=16, thoughts=150)))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result.text == "ага"
    assert result.prompt_tokens == 1800
    assert result.thought_tokens == 150
    assert result.latency_ms >= 0
    assert result.cost_usd > 0


async def test_treats_a_missing_cached_count_as_zero():
    client = FakeClient(FakeResponse("ага", FakeUsage(cached=None)))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result.cached_tokens == 0


async def test_empty_reply_becomes_silence():
    client = FakeClient(FakeResponse(""))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_none_reply_becomes_silence():
    client = FakeClient(FakeResponse(None))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_an_api_failure_becomes_silence_not_an_exception():
    client = FakeClient(error=RuntimeError("boom"))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_safety_is_disabled_on_every_category():
    client = FakeClient(FakeResponse())

    await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    settings = client.calls[0]["config"].safety_settings
    assert len(settings) == 4
    assert all(s.threshold == "BLOCK_NONE" for s in settings)
