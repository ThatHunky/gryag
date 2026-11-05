"""An optional dictionary of a persona's own phrases.

The code picks them, not the model. A tool would add a second API call to every reply and
could simply go unused, and the model cannot promise not to repeat itself anyway. So each
reply is handed a handful of phrases this chat has not been shown yet, and the database
remembers which. Once the dictionary runs out it starts over.
"""

from __future__ import annotations

import random
from pathlib import Path

import aiosqlite

from gryag import store

PER_REPLY = 8


def load(path: str | Path | None) -> tuple[str, ...]:
    """One phrase a line. No path means no dictionary, which is how gryag itself runs."""
    if not path:
        return ()
    lines = (line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines())
    return tuple(dict.fromkeys(line for line in lines if line))


async def draw(
    db: aiosqlite.Connection, chat_id: int, persona, count: int = PER_REPLY
) -> list[str]:
    pool = persona.get("phrases", ()) if isinstance(persona, dict) else ()
    if not pool:
        return []
    used = await store.used_phrases(db, chat_id)
    fresh = [phrase for phrase in pool if phrase not in used]
    picked = random.sample(fresh, min(count, len(fresh)))
    if len(picked) < count:
        # Finish what was left, then start over. Topping up from the phrases that were
        # already used keeps one draw free of duplicates even on a tiny dictionary.
        await store.forget_used_phrases(db, chat_id)
        seen = [phrase for phrase in pool if phrase not in picked]
        picked += random.sample(seen, min(count - len(picked), len(seen)))
    await store.mark_phrases_used(db, chat_id, picked)
    return picked
