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

WEEK_SUMMARY_TOKENS = 400
DAY_SUMMARY_TOKENS = 300
FACTS_TOKENS = 150

BOUNDARY = (
    "---\n"
    "Далі пишеш тільки свою наступну репліку. Без імені, без дужок, "
    "не продовжуй чужі рядки."
)

MEDIA_MARKERS = {
    "photo": "[фото]",
    # Animations and audio had no marker at all, so a GIF — 315 of them in this chat —
    # rendered as an empty line with a name in front of it.
    "animation": "[гіфка]",
    "audio": "[аудіо]",
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


PRETTY_NAME_MAX = 24
"""Long enough for «Vsevolod Dobrovolskyi», short enough to exclude the 63-character
display name one member of this chat actually has."""

_DECORATION = re.compile(r"[^\w\s'-]", re.UNICODE)
"""Emoji, flags, brackets and slashes. Replaced with a space rather than deleted, or
«артемопокалипсис/локшина» comes out as one welded word."""

_JUNK_TOKEN = re.compile(r"^[_'-]+$")


def pretty_name(display_name: str | None, alias: str | None) -> str:
    """A name fit for a document, as opposed to `alias_for`, which is fit for a prompt.

    `alias_for` takes the first word and cuts it at eight characters, which buys 13-18%
    of the context block and is the right trade there. In the lore it produced
    `Anonymou`, `андрійни` and `позорниц` — people's names cut mid-word in a page they
    read. This never cuts mid-word: it cleans the display name, falls back to its first
    word if that is too long, and to the alias when the display name is unusable.
    """
    words = _DECORATION.sub(" ", display_name or "").split()
    cleaned = " ".join(w for w in words if not _JUNK_TOKEN.match(w))
    if 0 < len(cleaned) <= PRETTY_NAME_MAX:
        return cleaned
    first = cleaned.split(" ")[0] if cleaned else ""
    if 0 < len(first) <= PRETTY_NAME_MAX:
        return first
    return (alias or "").strip() or "хтось"


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


def render_quote(quoted: str | None, author: str | None) -> str | None:
    """Telegram lets a person quote *part* of a message when replying.

    That selection is the whole point of the reply — someone quoting two words out of a
    long message is asking about those two words. Without this the model receives the
    entire parent message and has to guess which bit mattered.
    """
    if not quoted or not quoted.strip():
        return None
    who = f" з {author}" if author else ""
    return f"(цитує{who}: «{quoted.strip()}»)"


def build(
    messages: list[dict],
    chain: list[dict],
    trigger: dict,
    now: str,
    chat_title: str,
    quote: str | None = None,
    quote_author: str | None = None,
    week_summary: str | None = None,
    today_summary: str | None = None,
    facts: list[tuple[str, str]] | None = None,
) -> str:
    """Header, memory, then the reply chain, the recent window, and the boundary.

    Every block below carries a hard cap, checked here rather than trusted from upstream.
    Legacy degraded precisely because its summaries crept to 65% of the prompt, leaving
    665 tokens for the conversation actually happening.
    """
    header = f"Зараз {now}. Чат: {chat_title}."
    # `now` must already be local. Telegram timestamps are UTC, and handing those over
    # told the bot it was three hours earlier than everyone in the room — wrong for
    # "котра година", and wrong for knowing whether it is late at night.

    memory: list[str] = []
    if week_summary and week_summary.strip():
        memory.append("За тиждень: " + clamp(week_summary.strip(), WEEK_SUMMARY_TOKENS))
    if today_summary and today_summary.strip():
        memory.append("Сьогодні: " + clamp(today_summary.strip(), DAY_SUMMARY_TOKENS))
    if facts:
        rendered = "; ".join(f"{who} — {fact}" for who, fact in facts)
        memory.append("Про присутніх: " + clamp(rendered, FACTS_TOKENS))

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

    tail = [BOUNDARY]
    quoted = render_quote(quote, quote_author)
    if quoted is not None:
        tail.append(quoted)
    tail.append(render_line(trigger))
    return "\n".join([header, *memory, "", *lines, *tail])
