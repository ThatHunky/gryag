"""Runtime configuration.

Secrets come from the environment. Everything the admin can change with a button lives in
the `config` table and is read at decision time, so the menu never needs a restart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

DEFAULTS: dict[str, str] = {
    # models
    "speak_model": "gemini-flash-latest",
    "thinking_budget": "0",
    "max_output_tokens": "1500",
    # trigger
    "keywords": "гряг",
    "context_messages": "30",
    # safety valves — these exist for bugs, not for money
    "daily_reply_cap": "60",
    "hourly_reply_cap": "10",
    # How many bot messages may pile up before gryag stops answering other bots.
    # Any human line resets the count, so this only ever bites a bot-to-bot loop.
    "bot_exchange_limit": "3",
    # Google Search grounding and URL fetching. Server-side, so they cost no prompt
    # tokens; search is free to 5,000/month, fetched pages bill as input tokens.
    "tools_enabled": "1",
}


@dataclass(frozen=True)
class Secrets:
    bot_token: str
    gemini_api_key: str
    webhook_secret: str
    webhook_base: str
    admin_ids: tuple[int, ...]
    db_path: str


def secrets() -> Secrets:
    raw_admins = os.environ.get("ADMIN_IDS", "392817811")
    return Secrets(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        webhook_secret=os.environ["WEBHOOK_SECRET"],
        webhook_base=os.environ["WEBHOOK_BASE"],
        admin_ids=tuple(int(x) for x in raw_admins.split(",") if x.strip()),
        db_path=os.environ.get("DB_PATH", "gryag.db"),
    )


async def get(db: aiosqlite.Connection, key: str, chat_id: int | None = None) -> str:
    if key not in DEFAULTS:
        raise KeyError(f"unknown config key: {key}")
    if chat_id is not None:
        async with db.execute(
            "SELECT value FROM config WHERE scope = 'chat' AND chat_id = ? AND key = ?",
            (chat_id, key),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            return row[0]
    async with db.execute(
        "SELECT value FROM config WHERE scope = 'global' AND key = ?", (key,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row is not None else DEFAULTS[key]


async def get_int(db: aiosqlite.Connection, key: str, chat_id: int | None = None) -> int:
    return int(await get(db, key, chat_id))


async def set(
    db: aiosqlite.Connection, key: str, value: str, chat_id: int | None = None
) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown config key: {key}")
    scope = "chat" if chat_id is not None else "global"
    await db.execute(
        """
        INSERT INTO config (scope, chat_id, key, value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (scope, chat_id, key) DO UPDATE SET value = excluded.value
        """,
        (scope, chat_id or 0, key, value),
    )
    await db.commit()


async def all_for_chat(db: aiosqlite.Connection, chat_id: int) -> dict[str, str]:
    merged = dict(DEFAULTS)
    async with db.execute(
        """
        SELECT key, value FROM config
        WHERE scope = 'global' OR (scope = 'chat' AND chat_id = ?)
        ORDER BY scope DESC
        """,
        (chat_id,),
    ) as cur:
        for key, value in await cur.fetchall():
            if key in merged:
                merged[key] = value
    return merged
