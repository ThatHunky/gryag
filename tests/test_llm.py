import types as pytypes

import pytest

from gryag import llm


class FakeUsage:
    def __init__(self, prompt=1000, cached=None, visible=20, thoughts=None):
        self.prompt_token_count = prompt
        self.cached_content_token_count = cached
        self.candidates_token_count = visible
        self.thoughts_token_count = thoughts


class FakeCandidate:
    def __init__(self, queries=()):
        self.grounding_metadata = (
            pytypes.SimpleNamespace(web_search_queries=list(queries)) if queries else None
        )


class FakeResponse:
    def __init__(self, text="ага", usage=None, queries=()):
        self.text = text
        self.usage_metadata = usage or FakeUsage()
        self.candidates = [FakeCandidate(queries)]


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


async def test_reports_how_many_searches_were_grounded():
    client = FakeClient(FakeResponse("курс 44.7", queries=["usd uah kurs"]))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="гряг курс долара",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result.searched == 1


async def test_search_and_url_tools_are_offered_by_default():
    client = FakeClient(FakeResponse())

    await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    tools = client.calls[0]["config"].tools
    assert any(t.google_search is not None for t in tools)
    assert any(t.url_context is not None for t in tools)


async def test_tools_can_be_turned_off():
    client = FakeClient(FakeResponse())

    await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
        use_tools=False,
    )

    assert client.calls[0]["config"].tools is None


async def test_media_is_sent_before_the_prompt():
    client = FakeClient(FakeResponse())

    await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="гряг як тобі",
        max_output_tokens=1500,
        thinking_budget=0,
        media=(b"gifbytes", "video/mp4"),
    )

    contents = client.calls[0]["contents"]
    assert isinstance(contents, list)
    assert contents[0].inline_data.mime_type == "video/mp4"
    assert contents[1] == "гряг як тобі"
