"""Image generation and editing, for a whitelist only.

Nano Banana 2 (`gemini-3.1-flash-image`) is a separate model call billed per image, not
per token, so unlike search and code execution it cannot be left open to a chat of 33
people. Access is a list of user ids the admin edits with a command.

Measured 2026-08-19: generation ~8s, editing ~7s, roughly 900 KB per JPEG. Nano Banana
Pro (`gemini-3-pro-image`) takes ~16s for no visible gain at this size; Lite manages
~3s and is the fallback worth trying if 8 seconds feels slow in the room.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from google.genai import types

from gryag import llm

log = logging.getLogger(__name__)

DRAW_WORDS = (
    "намалюй",
    "нарисуй",
    "згенеруй",
    "зґенеруй",
    "зроби картинку",
    "зроби фото",
    "перемалюй",
)

EDIT_WORDS = ("перемалюй", "додай", "прибери", "заміни", "зміни")


@dataclass(frozen=True)
class ImageResult:
    payload: bytes
    mime_type: str
    latency_ms: int
    prompt_tokens: int
    output_tokens: int


def wants_image(text: str) -> str | None:
    """The prompt to draw, or None. Plain code — no model call to decide."""
    lowered = (text or "").lower()
    for word in DRAW_WORDS:
        index = lowered.find(word)
        if index != -1:
            prompt = text[index + len(word) :].strip(" ,:.!?—-")
            return prompt or text.strip()
    return None


def wants_edit(text: str) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in EDIT_WORDS)


def is_allowed(user_id: int, whitelist: str) -> bool:
    return str(user_id) in {part.strip() for part in whitelist.split(",") if part.strip()}


def parse_whitelist(raw: str) -> list[int]:
    return [int(p) for p in re.findall(r"-?\d+", raw or "")]


def render_whitelist(ids: list[int]) -> str:
    return ",".join(str(i) for i in dict.fromkeys(ids))


async def generate(
    client,
    *,
    model: str,
    prompt: str,
    source: tuple[bytes, str] | None = None,
) -> ImageResult | None:
    """Draw, or redraw `source` according to `prompt`. None on any failure."""
    contents: object = prompt
    if source is not None:
        payload, mime_type = source
        contents = [types.Part.from_bytes(data=payload, mime_type=mime_type), prompt]

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        safety_settings=[
            types.SafetySetting(category=category, threshold="BLOCK_NONE")
            for category in llm.HARM_CATEGORIES
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    started = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
    except Exception:
        log.exception("image generation failed on %s", model)
        return None
    latency_ms = int((time.monotonic() - started) * 1000)

    if not response.candidates:
        feedback = getattr(response, "prompt_feedback", None)
        log.warning(
            "image request refused: %s", getattr(feedback, "block_reason", "no candidates")
        )
        return None

    images = [
        part.inline_data
        for part in (response.candidates[0].content.parts or [])
        if getattr(part, "inline_data", None)
    ]
    if not images:
        log.warning("image request produced no image on %s", model)
        return None

    usage = response.usage_metadata
    return ImageResult(
        payload=images[0].data,
        mime_type=images[0].mime_type,
        latency_ms=latency_ms,
        prompt_tokens=usage.prompt_token_count or 0,
        output_tokens=usage.candidates_token_count or 0,
    )
