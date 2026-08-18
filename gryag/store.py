"""SQLite persistence. All SQL in the project lives here.

Two processes share this file — the bot and, from phase 2, the digest job — so the
connection runs in WAL mode with a busy timeout and transactions stay short.
"""

from __future__ import annotations

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id  INTEGER PRIMARY KEY,
    title    TEXT,
    enabled  INTEGER NOT NULL DEFAULT 0,
    added_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    chat_id      INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    display_name TEXT,
    alias        TEXT,
    pronouns     TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id    INTEGER,
    ts         TEXT NOT NULL,
    text       TEXT,
    media_kind TEXT,
    file_id    TEXT,
    reply_to   INTEGER,
    is_bot     INTEGER NOT NULL DEFAULT 0,
    sender_is_bot INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages (chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_reply   ON messages (chat_id, reply_to);

CREATE TABLE IF NOT EXISTS facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    source_day TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    chat_id      INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    text         TEXT NOT NULL,
    tokens       INTEGER,
    PRIMARY KEY (chat_id, kind, period_start)
);

CREATE TABLE IF NOT EXISTS config (
    scope   TEXT NOT NULL,
    chat_id INTEGER NOT NULL DEFAULT 0,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (scope, chat_id, key)
);

CREATE TABLE IF NOT EXISTS usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (datetime('now')),
    chat_id     INTEGER,
    purpose     TEXT NOT NULL,
    model       TEXT NOT NULL,
    prompt_tok  INTEGER NOT NULL,
    cached_tok  INTEGER NOT NULL,
    visible_tok INTEGER NOT NULL,
    thought_tok INTEGER NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cost_usd    REAL NOT NULL,
    searched    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id         INTEGER PRIMARY KEY,
    last_spoke_ts   TEXT,
    last_ambient_ts TEXT,
    muted_until     TEXT
);
"""

MESSAGE_COLUMNS = """
    m.message_id, m.user_id, m.ts, m.text, m.media_kind, m.file_id,
    m.reply_to, m.is_bot, m.sender_is_bot, u.alias, u.display_name
"""

MIGRATIONS = (
    # `is_bot` means "gryag said this" and drives the reply caps. Messages from *other*
    # bots need their own flag, or the loop guard cannot see them.
    "ALTER TABLE messages ADD COLUMN sender_is_bot INTEGER NOT NULL DEFAULT 0",
    # Google Search grounding is free for the first 5,000 requests a month and $14 per
    # 1,000 after, so the panel needs to be able to count them.
    "ALTER TABLE usage ADD COLUMN searched INTEGER NOT NULL DEFAULT 0",
)


async def _migrate(db: aiosqlite.Connection) -> None:
    for statement in MIGRATIONS:
        try:
            await db.execute(statement)
        except aiosqlite.OperationalError:
            pass  # already applied
    await db.commit()


async def connect(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.executescript(SCHEMA)
    await db.commit()
    await _migrate(db)
    return db


async def upsert_user(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    user_id: int,
    display_name: str,
    alias: str,
) -> None:
    await db.execute(
        """
        INSERT INTO users (chat_id, user_id, display_name, alias)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET display_name = excluded.display_name
        """,
        (chat_id, user_id, display_name, alias),
    )
    await db.commit()


async def save_message(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    message_id: int,
    user_id: int | None,
    ts: str,
    text: str,
    media_kind: str | None,
    file_id: str | None,
    reply_to: int | None,
    is_bot: bool,
    sender_is_bot: bool = False,
) -> None:
    await db.execute(
        """
        INSERT INTO messages
            (chat_id, message_id, user_id, ts, text, media_kind, file_id, reply_to,
             is_bot, sender_is_bot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """,
        (
            chat_id,
            message_id,
            user_id,
            ts,
            text,
            media_kind,
            file_id,
            reply_to,
            int(is_bot),
            int(sender_is_bot or is_bot),
        ),
    )
    await db.commit()


async def recent_messages(
    db: aiosqlite.Connection, chat_id: int, limit: int
) -> list[dict]:
    """The last `limit` messages, returned oldest first."""
    async with db.execute(
        f"""
        SELECT {MESSAGE_COLUMNS} FROM messages m
        LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
        WHERE m.chat_id = ?
        ORDER BY m.ts DESC, m.message_id DESC
        LIMIT ?
        """,
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in reversed(rows)]


async def reply_chain(
    db: aiosqlite.Connection, chat_id: int, message_id: int, max_depth: int = 20
) -> list[dict]:
    """The message and its ancestors, oldest first. Stops at a missing parent."""
    chain: list[dict] = []
    current: int | None = message_id
    seen: set[int] = set()
    while current is not None and len(chain) < max_depth and current not in seen:
        seen.add(current)
        async with db.execute(
            f"""
            SELECT {MESSAGE_COLUMNS} FROM messages m
            LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
            WHERE m.chat_id = ? AND m.message_id = ?
            """,
            (chat_id, current),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            break
        chain.append(dict(row))
        current = row["reply_to"]
    return list(reversed(chain))


async def count_replies_since(
    db: aiosqlite.Connection, chat_id: int, since_ts: str
) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1 AND ts >= ?",
        (chat_id, since_ts),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def bot_streak(db: aiosqlite.Connection, chat_id: int) -> int:
    """How many bot messages have piled up since a human last said something.

    This is the loop guard's only input. Two bots left alone drive it up until the gate
    stops answering; the first human line drops it back to zero.
    """
    async with db.execute(
        """
        SELECT COUNT(*) FROM messages
        WHERE chat_id = ? AND sender_is_bot = 1 AND ts > COALESCE(
            (SELECT MAX(ts) FROM messages WHERE chat_id = ? AND sender_is_bot = 0), ''
        )
        """,
        (chat_id, chat_id),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def replies_to_user(
    db: aiosqlite.Connection, chat_id: int, user_id: int, since_ts: str
) -> tuple[int, str | None]:
    """(how many times gryag answered this person recently, when it last did).

    Joins the bot's replies back to the messages they quote, which is possible only
    because every reply is sent with `message.reply`.
    """
    async with db.execute(
        """
        SELECT COUNT(*), MAX(b.ts)
        FROM messages b
        JOIN messages t ON t.chat_id = b.chat_id AND t.message_id = b.reply_to
        WHERE b.chat_id = ? AND b.is_bot = 1 AND t.user_id = ? AND b.ts >= ?
        """,
        (chat_id, user_id, since_ts),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]), row[1]


async def record_usage(
    db: aiosqlite.Connection,
    *,
    chat_id: int | None,
    purpose: str,
    model: str,
    prompt_tok: int,
    cached_tok: int,
    visible_tok: int,
    thought_tok: int,
    latency_ms: int,
    cost_usd: float,
    searched: int = 0,
) -> None:
    await db.execute(
        """
        INSERT INTO usage
            (chat_id, purpose, model, prompt_tok, cached_tok,
             visible_tok, thought_tok, latency_ms, cost_usd, searched)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            purpose,
            model,
            prompt_tok,
            cached_tok,
            visible_tok,
            thought_tok,
            latency_ms,
            cost_usd,
            searched,
        ),
    )
    await db.commit()
