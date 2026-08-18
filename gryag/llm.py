"""The Gemini call.

Uses the native SDK deliberately. Measured on 2026-08-18, the OpenAI compatibility endpoint
served one implicit cache hit in 37 calls where the native endpoint served 46-93%, and it
does not report thinking tokens at all — which are billed at the output rate and, on 3.x
models, are the volatile part of the bill.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

HARM_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)

PRICES: dict[str, tuple[float, float, float]] = {
    # model: (input, output, cached input) in USD per 1M tokens.
    # Verified against Google's pricing page on 2026-08-18. The 3.x rates are
    # promotional and double on 2027-01-01.
    "gemini-flash-latest": (0.75, 3.75, 0.075),
    "gemini-3.7-flash": (0.75, 3.75, 0.075),
    "gemini-2.5-flash": (0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.025),
}


@dataclass(frozen=True)
class LlmResult:
    text: str
    searched: int
    prompt_tokens: int
    cached_tokens: int
    visible_tokens: int
    thought_tokens: int
    latency_ms: int
    cost_usd: float


SEARCH_FREE_PER_MONTH = 5000
"""Gemini 3.x allowance, shared across 3.x models; $14 per 1,000 after that. At this
chat's volume even searching on every reply stays inside it, but the panel counts anyway."""


def build_tools() -> list[types.Tool]:
    """Server-side tools: they cost nothing in the prompt, unlike a tool manifest in the
    persona, which is exactly why the 137-token manifest was cut from it."""
    return [
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(url_context=types.UrlContext()),
        types.Tool(code_execution=types.ToolCodeExecution()),
    ]


def cost_usd(
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    visible_tokens: int,
    thought_tokens: int,
) -> float:
    """Thinking tokens bill at the output rate even though they are never shown."""
    if model not in PRICES:
        log.warning("no price for model %s, reporting zero cost", model)
        return 0.0
    price_in, price_out, price_cached = PRICES[model]
    fresh = max(prompt_tokens - cached_tokens, 0)
    return (
        fresh * price_in
        + cached_tokens * price_cached
        + (visible_tokens + thought_tokens) * price_out
    ) / 1_000_000


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


async def generate(
    client: genai.Client,
    *,
    model: str,
    system: str,
    user: str,
    max_output_tokens: int,
    thinking_budget: int,
    media: tuple[bytes, str] | None = None,
    use_tools: bool = True,
) -> LlmResult | None:
    """Returns None on any failure or empty reply — silence is the correct behaviour.

    `media` is (bytes, mime_type) and is sent inline before the prompt, so the model sees
    the picture first and the conversation second — the same order a person would.
    """
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        safety_settings=[
            types.SafetySetting(category=category, threshold="BLOCK_NONE")
            for category in HARM_CATEGORIES
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tools=build_tools() if use_tools else None,
    )

    contents: object = user
    if media is not None:
        payload, mime_type = media
        contents = [types.Part.from_bytes(data=payload, mime_type=mime_type), user]

    started = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
    except Exception:
        log.exception("gemini call failed for model %s", model)
        return None
    latency_ms = int((time.monotonic() - started) * 1000)

    candidate = (response.candidates or [None])[0]
    grounding = getattr(candidate, "grounding_metadata", None)
    queries = list(getattr(grounding, "web_search_queries", None) or [])
    if queries:
        log.info("grounded on: %s", ", ".join(queries))

    text = (response.text or "").strip()
    usage = response.usage_metadata
    prompt_tokens = usage.prompt_token_count or 0
    cached_tokens = usage.cached_content_token_count or 0
    visible_tokens = usage.candidates_token_count or 0
    thought_tokens = usage.thoughts_token_count or 0

    if not text:
        log.warning(
            "empty reply from %s: %s thinking tokens consumed the budget",
            model,
            thought_tokens,
        )
        return None

    return LlmResult(
        text=text,
        searched=len(queries),
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        visible_tokens=visible_tokens,
        thought_tokens=thought_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd(
            model, prompt_tokens, cached_tokens, visible_tokens, thought_tokens
        ),
    )
