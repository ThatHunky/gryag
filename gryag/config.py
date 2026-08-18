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
    # The digest has no voice requirement, so it runs on the cheapest tier. Flash-Lite is
    # ruled out for the persona, not for summarising: 0.86M tokens a month costs $0.09
    # here against $0.64 on the speaking model.
    "digest_model": "gemini-2.5-flash-lite",
    # trigger
    "keywords": "гряг",
    # 30 messages is only ~4.4 minutes of wall clock in a chat that runs at a median of
    # 6 seconds between messages. 60 buys ~14 minutes and 98% of reply targets, measured.
    "context_messages": "60",
    # Safety valves. These exist to stop a runaway gate, not to ration replies: a bug
    # fires hundreds a minute, while people poking a new bot in a chat that runs at
    # 3,000 messages a day comfortably pass twenty in an hour. The first values here
    # were 60/10 and the hourly one silenced the bot within the first evening; 30/hour
    # was still being approached within an hour of raising it. A runaway gate fires
    # hundreds a minute, so these stay a real backstop while never binding real use.
    "daily_reply_cap": "800",
    "hourly_reply_cap": "120",
    # How many bot messages may pile up before gryag stops answering other bots.
    # Any human line resets the count, so this only ever bites a bot-to-bot loop.
    "bot_exchange_limit": "3",
    # Seconds. Older messages are still stored, just never answered — this is what makes
    # replaying the restart backlog safe.
    "max_reply_age": "300",
    # Dynamic throttle, per person. Free for the first `throttle_after` replies inside
    # the window, then each further one demands a gap that grows by `throttle_step`.
    # First values were 3 free replies per 10 minutes with a 20s step, and they silenced
    # normal conversation within an evening: one person easily earns five replies in ten
    # minutes without being a nuisance. This only bites someone genuinely hammering it.
    "throttle_after": "6",
    "throttle_step": "15",
    "throttle_window": "300",
    # Google Search grounding and URL fetching. Server-side, so they cost no prompt
    # tokens; search is free to 5,000/month, fetched pages bill as input tokens.
    "tools_enabled": "1",
    # Nano Banana 2. Billed per image rather than per token, so it is whitelist-only.
    # The admin edits the list with /nb in reply to somebody.
    "image_model": "gemini-3.1-flash-image",
    "image_whitelist": "392817811",
    # Quiet hours, local time. They suppress ambient and proactive speech only — being
    # addressed directly works around the clock, because ignoring somebody who writes to
    # you at three in the morning is just broken.
    "quiet_from": "2",
    "quiet_to": "8",
}


@dataclass(frozen=True)
class Secrets:
    bot_token: str
    gemini_api_key: str
    webhook_secret: str
    webhook_base: str
    admin_ids: tuple[int, ...]
    db_path: str
    port: int


def secrets() -> Secrets:
    raw_admins = os.environ.get("ADMIN_IDS", "392817811")
    return Secrets(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        webhook_secret=os.environ["WEBHOOK_SECRET"],
        webhook_base=os.environ["WEBHOOK_BASE"],
        admin_ids=tuple(int(x) for x in raw_admins.split(",") if x.strip()),
        db_path=os.environ.get("DB_PATH", "gryag.db"),
        # 8080/8081 are taken by docker-proxy on this host; binding there fails and
        # Telegram sees a 302 from whatever container answers instead.
        port=int(os.environ.get("PORT", "8137")),
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
