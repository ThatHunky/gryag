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

EDIT_WORDS = ("перемалюй", "додай", "прибери", "заміни", "зміни", "переробі", "зроби з")


@dataclass(frozen=True)
class ImageResult:
    payload: bytes
    mime_type: str
    latency_ms: int
    prompt_tokens: int
    output_tokens: int


def wants_image(text: str) -> str | None:
    """The prompt to draw, or None. Plain code — no model call to decide.

    Returns an empty string when a draw verb was used with nothing after it — "гряг
    намалюй" in reply to something. That is a request to draw *that*, and the subject has
    to be found elsewhere; returning the message text would have the model draw the words
    "гряг намалюй", which is exactly what it did.
    """
    lowered = (text or "").lower()
    for word in DRAW_WORDS:
        index = lowered.find(word)
        if index != -1:
            return text[index + len(word) :].strip(" ,:.!?—-\n")
    return None


def subject_from(prompt: str, quoted: str | None, parent: str | None, recent: str | None) -> str | None:
    """What to draw, in order of how directly it was asked for.

    An explicit prompt wins. Failing that, a quoted fragment — somebody selecting two
    words and saying "намалюй" means those two words. Then the whole message being
    replied to. Only then the conversation, which is a guess but a better one than
    drawing the instruction itself.
    """
    for candidate in (prompt, quoted, parent, recent):
        text = (candidate or "").strip()
        if len(text) >= 3:
            return text
    return None


PARENT_INSTRUCTION = (
    "Намалюй ілюстрацію до цього повідомлення з групового чату. "
    "Не пиши текст на зображенні, якщо про це не просили окремо.\n\n"
)

EDIT_INSTRUCTION = "Переробіть це зображення так: "


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
