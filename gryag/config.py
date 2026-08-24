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
    # was still being approached within an hour of raising it, and 120 was hit outright
    # on the first evening people spent playing with it. A runaway gate fires hundreds a
    # MINUTE — these are sized against that, not against enthusiasm. The per-person
    # throttle is what paces normal use; this is only the wall behind it.
    # At roughly $0.0014 a reply, 300/hour is about $0.42 in the worst hour.
    "daily_reply_cap": "1500",
    "hourly_reply_cap": "300",
    # How many bot messages may pile up before gryag stops answering other bots.
    # Any human line resets the count, so this only ever bites a bot-to-bot loop.
    "bot_exchange_limit": "3",
    # Seconds. Older messages are still stored, just never answered — this is what makes
    # replaying the restart backlog safe.
    "max_reply_age": "300",
    # When somebody addresses the bot while it is already answering, that message is
    # dropped — which from inside the chat reads as being ignored. It is remembered and
    # sometimes answered afterwards. Sometimes, not always: a bot that always circles
    # back is a queue, and this one is supposed to be a person who missed something.
    "deferred_chance": "40",
    "deferred_max_age": "60",
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
    # Ambient interjection: speaking without being spoken to.
    "ambient_enabled": "0",
    "ambient_per_day": "10",
    "ambient_cooldown": "1200",
    # Proactive: speaking into a silence. Measured, this fires almost only in the
    # morning — two days of this chat held just 18 gaps longer than fifteen minutes.
    "proactive_enabled": "0",
    "proactive_silence": "10800",
    "proactive_cooldown": "21600",
    # Підарас дня. A joke, but the pool is real people, so the window governs who counts
    # as present: somebody who left the chat a month ago should not keep winning.
    "pidor_enabled": "1",
    "pidor_window_days": "30",
    "pidor_min_players": "3",
    # Kyiv hour at which the bot rolls on its own if nobody has asked. -1 never does.
    "pidor_announce_hour": "13",
    # Підрахуйка: the USF public killboard. Off until a chat asks for it.
    "pidrahuika_enabled": "0",
    "pidrahuika_hour": "9",
    # Лор: one living page per chat, rewritten from the raw transcript on a timer.
    "lore_enabled": "1",
    # The pinned model, not `gemini-flash-latest`. That alias is repointed with no notice
    # and no API signal, and a document whose voice is quietly rewritten by a swapped
    # model is exactly the case nobody catches until it has happened three times.
    "lore_model": "gemini-3.7-flash",
    "lore_interval_days": "2",
    # Thinking is the single largest cost lever in this feature: it takes a run from about
    # $0.10 to an estimated $0.25-0.35. A knob rather than a constant, so a run that
    # thinks for a dollar can be turned down without a deploy.
    "lore_thinking": "-1",
    "lore_max_chars": "20000",
    # /lore is a database read and an upload, so it cannot be made expensive by being
    # spammed — but it can be made annoying. Seconds.
    "lore_cooldown": "600",
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
