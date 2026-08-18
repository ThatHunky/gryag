"""Prompt assembly.

The measured chat has a median message of 19 characters, so a speaker's display name can
cost more tokens than what they said: `٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.` is 16 tokens on its own. Short
aliases cut the whole context block by 13-18%.

Phase 1 assembles the header and the live window. Summaries and facts slot in above the
window in phase 2, under the caps recorded in the spec.
"""

from __future__ import annotations

import re

CHARS_PER_TOKEN = 2.5
"""Measured on 142,773 characters of this chat's Ukrainian text (57,109 tokens)."""

BOT_ALIAS = "гряг"

BOUNDARY = (
    "---\n"
    "Далі пишеш тільки свою наступну репліку. Без імені, без дужок, "
    "не продовжуй чужі рядки."
)

MEDIA_MARKERS = {
    "photo": "[фото]",
    "voice": "[голосове]",
    "video": "[відео]",
    "video_note": "[кружок]",
    "sticker": "[стікер]",
    "document": "[файл]",
}

OTHER_BOT_ALIASES = {"Пісюнбот", "Mafia UA Bot", "TikArchive | TikTok Downloader"}


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def clamp(text: str, max_tokens: int) -> str:
    """Cut text to a token budget. Caps are never allowed to be exceeded silently."""
    limit = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text
    # The ellipsis counts against the budget: a cap that can be exceeded by a
    # character is a cap nobody checks.
    return text[: limit - 1].rstrip() + "…"


def alias_for(display_name: str) -> str:
    """A short, stable name for use in the rendered log."""
    first = (display_name or "").split()
    candidate = first[0] if first else ""
    candidate = re.sub(r"[^\w'-]", "", candidate, flags=re.UNICODE)[:8]
    return candidate or "хтось"


def render_line(msg: dict) -> str:
    name = BOT_ALIAS if msg.get("is_bot") else (msg.get("alias") or "хтось")
    marker = MEDIA_MARKERS.get(msg.get("media_kind") or "", "")
    text = (msg.get("text") or "").strip()
    body = f"{marker} {text}".strip() if marker else text
    return f"{name}: {body}"


def is_context_worthy(msg: dict) -> bool:
    """Filters that cost nothing and remove most of the noise.

    Other bots produce 6% of this chat's traffic and 17% of messages carry no text at all.
    A media message still earns its place — it keeps the conversation from looking torn —
    but an empty message with no media is pure noise.
    """
    if (msg.get("alias") or "") in OTHER_BOT_ALIASES:
        return False
    if (msg.get("text") or "").strip():
        return True
    return bool(msg.get("media_kind"))


def build(
    messages: list[dict],
    chain: list[dict],
    trigger: dict,
    now: str,
    chat_title: str,
) -> str:
    """Header, then the reply chain, then the recent window, then the boundary."""
    header = f"Зараз {now}. Чат: {chat_title}."

    seen: set[int] = set()
    lines: list[str] = []
    for msg in [*chain, *messages]:
        message_id = msg.get("message_id")
        if message_id in seen or message_id == trigger.get("message_id"):
            continue
        if not is_context_worthy(msg):
            continue
        seen.add(message_id)
        lines.append(render_line(msg))

    return "\n".join([header, "", *lines, BOUNDARY, render_line(trigger)])
