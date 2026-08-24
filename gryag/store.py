"""SQLite persistence. All SQL in the project lives here.

Two processes share this file — the bot and, from phase 2, the digest job — so the
connection runs in WAL mode with a busy timeout and transactions stay short.
"""

from __future__ import annotations

import json

import aiosqlite

from gryag import context

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
    username     TEXT,
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

CREATE TABLE IF NOT EXISTS bans (
    chat_id  INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    until_ts TEXT NOT NULL,
    reason   TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS pidor_days (
    chat_id   INTEGER NOT NULL,
    day       TEXT    NOT NULL,
    user_id   INTEGER NOT NULL,
    chosen_at TEXT    NOT NULL,
    PRIMARY KEY (chat_id, day)
);

CREATE TABLE IF NOT EXISTS pidrahuika_days (
    day        TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pidrahuika_posts (
    chat_id INTEGER NOT NULL,
    day     TEXT    NOT NULL,
    PRIMARY KEY (chat_id, day)
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id         INTEGER PRIMARY KEY,
    last_spoke_ts   TEXT,
    last_ambient_ts TEXT,
    muted_until     TEXT
);

CREATE TABLE IF NOT EXISTS reactions (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji      TEXT    NOT NULL,
    count      INTEGER NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (chat_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS events (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    ts         TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    actor_id   INTEGER,
    payload    TEXT,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS lore (
    chat_id      INTEGER NOT NULL,
    version      INTEGER NOT NULL,
    text         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    model        TEXT,
    tokens       INTEGER,
    window_start TEXT,
    window_end   TEXT,
    PRIMARY KEY (chat_id, version)
);

CREATE INDEX IF NOT EXISTS idx_reactions_chat ON reactions (chat_id, count DESC);
CREATE INDEX IF NOT EXISTS idx_events_chat_ts ON events (chat_id, ts);
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
    # A mention needs @username, and until the game arrived nothing ever needed one.
    "ALTER TABLE users ADD COLUMN username TEXT",
    # The lore's stats block names an edit champion, and nothing has ever counted an
    # edit: update_message_text overwrote the text and left no trace it had happened.
    "ALTER TABLE messages ADD COLUMN edits INTEGER NOT NULL DEFAULT 0",
    # /lore is open to the whole chat, so its cooldown has to outlive a restart. In
    # memory every deploy is a fresh spam window.
    "ALTER TABLE chat_state ADD COLUMN last_lore_ts TEXT",
)


async def _migrate(db: aiosqlite.Connection) -> None:
    for statement in MIGRATIONS:
        try:
            await db.execute(statement)
        except aiosqlite.OperationalError as exc:
            # "duplicate column name" means it ran before. "database is locked" means it
            # did NOT, and swallowing that records a migration as applied against a schema
            # that never got the column — surfacing hours later as a mystery INSERT error.
            if "duplicate column" not in str(exc).lower():
                raise
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
    username: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO users (chat_id, user_id, display_name, alias, username)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET
            display_name = excluded.display_name,
            -- Telegram omits the field for people who have no username, and an update
            -- that omits it must not erase one recorded earlier.
            username = COALESCE(excluded.username, users.username)
        """,
        (chat_id, user_id, display_name, alias, username),
    )
    await db.commit()


async def user_names(
    db: aiosqlite.Connection, chat_id: int, user_ids: list[int]
) -> dict[int, tuple[str | None, str]]:
    """{user_id: (username, display_name)} for building mentions."""
    if not user_ids:
        return {}
    marks = ",".join("?" * len(user_ids))
    async with db.execute(
        f"""
        SELECT user_id, username, COALESCE(display_name, alias, CAST(user_id AS TEXT))
        FROM users WHERE chat_id = ? AND user_id IN ({marks})
        """,
        (chat_id, *user_ids),
    ) as cur:
        return {r[0]: (r[1], r[2]) for r in await cur.fetchall()}


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


async def update_message_text(
    db: aiosqlite.Connection, chat_id: int, message_id: int, text: str
) -> bool:
    """Apply an edit to a message already stored.

    Telegram sends `edited_message` updates, so an edit can be followed. It sends nothing
    at all when a message is deleted — the Bot API has no such update for ordinary bots —
    so a deleted message stays in the transcript. Nothing here can change that.
    """
    cur = await db.execute(
        "UPDATE messages SET text = ?, edits = edits + 1 WHERE chat_id = ? AND message_id = ?",
        (text, chat_id, message_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def apply_reaction(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    message_id: int,
    added: list[str],
    removed: list[str],
    ts: str,
) -> None:
    """Move the stored counts by one person's change of mind.

    Counts drift low across downtime and that is accepted: Telegram replays pending
    *messages* for 24 hours but never replays reaction updates, so anything reacted to
    while the bot is down is lost for good. Good enough for "which message made the chat
    laugh"; not good enough for anything that must be exact, and nothing here is.
    """
    for emoji in added:
        await db.execute(
            """
            INSERT INTO reactions (chat_id, message_id, emoji, count, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT (chat_id, message_id, emoji) DO UPDATE SET
                count = count + 1, updated_at = excluded.updated_at
            """,
            (chat_id, message_id, emoji, ts),
        )
    for emoji in removed:
        # A removal for something never seen added is the normal shape of a restart, not
        # an error, so this touches nothing rather than writing a negative count.
        await db.execute(
            """
            UPDATE reactions SET count = count - 1, updated_at = ?
            WHERE chat_id = ? AND message_id = ? AND emoji = ?
            """,
            (ts, chat_id, message_id, emoji),
        )
    await db.execute(
        "DELETE FROM reactions WHERE chat_id = ? AND message_id = ? AND count <= 0",
        (chat_id, message_id),
    )
    await db.commit()


async def set_reaction_count(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    message_id: int,
    emoji: str,
    count: int,
    ts: str,
) -> None:
    """The importer's path: an export states the total, it does not describe a change."""
    await db.execute(
        """
        INSERT INTO reactions (chat_id, message_id, emoji, count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id, emoji) DO UPDATE SET
            count = excluded.count, updated_at = excluded.updated_at
        """,
        (chat_id, message_id, emoji, count, ts),
    )
    await db.commit()


async def reactions_for(
    db: aiosqlite.Connection, chat_id: int, message_id: int
) -> list[tuple[str, int]]:
    """(emoji, count), most reacted first."""
    async with db.execute(
        """
        SELECT emoji, count FROM reactions
        WHERE chat_id = ? AND message_id = ?
        ORDER BY count DESC, emoji
        """,
        (chat_id, message_id),
    ) as cur:
        return [(r[0], r[1]) for r in await cur.fetchall()]


async def save_event(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    message_id: int,
    ts: str,
    action: str,
    actor_id: int | None,
    payload: dict,
) -> None:
    """A join, a leave, a pin, a rename. Never recoverable later — the Bot API does not
    let anybody go back for them — so a duplicate is cheaper than a miss."""
    await db.execute(
        """
        INSERT INTO events (chat_id, message_id, ts, action, actor_id, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """,
        (chat_id, message_id, ts, action, actor_id, json.dumps(payload, ensure_ascii=False)),
    )
    await db.commit()


async def events_between(
    db: aiosqlite.Connection, chat_id: int, start: str, end: str
) -> list[dict]:
    """Every event in the window, oldest first, with the actor's alias and parsed payload."""
    async with db.execute(
        """
        SELECT e.message_id, e.ts, e.action, e.actor_id, e.payload,
               u.display_name, u.alias
        FROM events e
        LEFT JOIN users u ON u.chat_id = e.chat_id AND u.user_id = e.actor_id
        WHERE e.chat_id = ? AND e.ts >= ? AND e.ts < ?
        ORDER BY e.ts, e.message_id
        """,
        (chat_id, start, end),
    ) as cur:
        rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        row["payload"] = json.loads(row["payload"]) if row["payload"] else {}
        row["alias"] = context.pretty_name(row.pop("display_name"), row.pop("alias"))
    return rows


async def save_lore(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    text: str,
    model: str,
    tokens: int,
    window_start: str,
    window_end: str,
    created_at: str,
) -> int:
    """Store a new version and return its number.

    Versions accumulate rather than overwrite. A document the model is free to amend is a
    document that can quietly lose a good line; keeping every version makes that
    recoverable for a few kilobytes a week.
    """
    await db.execute("BEGIN IMMEDIATE")
    async with db.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM lore WHERE chat_id = ?", (chat_id,)
    ) as cur:
        version = int((await cur.fetchone())[0])
    await db.execute(
        """
        INSERT INTO lore
            (chat_id, version, text, created_at, model, tokens, window_start, window_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (chat_id, version, text, created_at, model, tokens, window_start, window_end),
    )
    await db.commit()
    return version


async def latest_lore(db: aiosqlite.Connection, chat_id: int) -> dict | None:
    async with db.execute(
        "SELECT * FROM lore WHERE chat_id = ? ORDER BY version DESC LIMIT 1", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def lore_sent_at(db: aiosqlite.Connection, chat_id: int) -> str | None:
    async with db.execute(
        "SELECT last_lore_ts FROM chat_state WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def mark_lore_sent(db: aiosqlite.Connection, chat_id: int, ts: str) -> None:
    await db.execute(
        """
        INSERT INTO chat_state (chat_id, last_lore_ts) VALUES (?, ?)
        ON CONFLICT (chat_id) DO UPDATE SET last_lore_ts = excluded.last_lore_ts
        """,
        (chat_id, ts),
    )
    await db.commit()


async def messages_between(
    db: aiosqlite.Connection, chat_id: int, start: str, end: str
) -> list[dict]:
    """Everything said between two instants, oldest first. `end` is exclusive.

    `messages_for_day` is the digest's window and cannot serve this: a lore window is up
    to four days long and starts wherever the previous document stopped.
    """
    async with db.execute(
        f"""
        SELECT {MESSAGE_COLUMNS} FROM messages m
        LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
        WHERE m.chat_id = ? AND m.ts >= ? AND m.ts < ?
        ORDER BY m.ts, m.message_id
        """,
        (chat_id, start, end),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def oldest_message_ts(db: aiosqlite.Connection, chat_id: int) -> str | None:
    async with db.execute(
        "SELECT MIN(ts) FROM messages WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0]


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


async def messages_for_day(
    db: aiosqlite.Connection, chat_id: int, day: str
) -> list[dict]:
    """Everything said on one calendar day (UTC), oldest first."""
    async with db.execute(
        f"""
        SELECT {MESSAGE_COLUMNS} FROM messages m
        LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
        WHERE m.chat_id = ? AND m.ts >= ? AND m.ts < ?
        ORDER BY m.ts, m.message_id
        """,
        # Stored timestamps carry a +00:00 offset, so the upper bound needs a character
        # that sorts above it rather than relying on '+' < '.' by accident.
        (chat_id, f"{day}T00:00:00", f"{day}T24"),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def save_summary(
    db: aiosqlite.Connection,
    *,
    chat_id: int,
    kind: str,
    period_start: str,
    period_end: str,
    text: str,
    tokens: int,
) -> None:
    await db.execute(
        """
        INSERT INTO summaries (chat_id, kind, period_start, period_end, text, tokens)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, kind, period_start) DO UPDATE SET
            text = excluded.text, tokens = excluded.tokens, period_end = excluded.period_end
        """,
        (chat_id, kind, period_start, period_end, text, tokens),
    )
    await db.commit()


async def latest_summary(
    db: aiosqlite.Connection, chat_id: int, kind: str
) -> str | None:
    async with db.execute(
        """
        SELECT text FROM summaries WHERE chat_id = ? AND kind = ?
        ORDER BY period_start DESC LIMIT 1
        """,
        (chat_id, kind),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def recent_daily_summaries(
    db: aiosqlite.Connection, chat_id: int, limit: int = 7
) -> list[tuple[str, str]]:
    """(day, text) for the last `limit` days, oldest first."""
    async with db.execute(
        """
        SELECT period_start, text FROM summaries
        WHERE chat_id = ? AND kind = 'day'
        ORDER BY period_start DESC LIMIT ?
        """,
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [(r[0], r[1]) for r in reversed(rows)]


async def replace_facts(
    db: aiosqlite.Connection, chat_id: int, day: str, facts: list[tuple[int, str]]
) -> None:
    """Facts for one day, rewritten wholesale so a re-run cannot duplicate them."""
    # One transaction. Every other helper here commits on its own, and any of them
    # landing between the delete and the insert would commit the delete alone — losing
    # a day's facts if the insert then failed.
    await db.execute("BEGIN IMMEDIATE")
    await db.execute(
        "DELETE FROM facts WHERE chat_id = ? AND source_day = ?", (chat_id, day)
    )
    await db.executemany(
        """
        INSERT INTO facts (chat_id, user_id, text, source_day, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        [(chat_id, user_id, text, day) for user_id, text in facts],
    )
    await db.commit()


async def facts_for_users(
    db: aiosqlite.Connection, chat_id: int, user_ids: list[int], per_user: int = 4
) -> list[tuple[str, str]]:
    """(alias, fact) for the people currently in the window — nobody else.

    Addressing the facts to whoever is present is what keeps this block inside its
    150-token cap in a chat with 27 participants.
    """
    if not user_ids:
        return []
    marks = ",".join("?" * len(user_ids))
    async with db.execute(
        f"""
        SELECT u.alias, f.text, f.user_id,
               -- created_at is written by one executemany, so a whole day shares one
               -- second and ordering by it alone leaves the planner to break ties. The
               -- id makes "the most recent four" mean the same thing twice running.
               ROW_NUMBER() OVER (
                   PARTITION BY f.user_id ORDER BY f.created_at DESC, f.id DESC
               ) AS rn
        FROM facts f
        LEFT JOIN users u ON u.chat_id = f.chat_id AND u.user_id = f.user_id
        WHERE f.chat_id = ? AND f.user_id IN ({marks})
        """,
        (chat_id, *user_ids),
    ) as cur:
        rows = await cur.fetchall()
    return [(r[0] or "хтось", r[1]) for r in rows if r[3] <= per_user]


async def lore_stats(
    db: aiosqlite.Connection,
    chat_id: int,
    start: str,
    end: str,
    previous_start: str,
) -> dict:
    """Everything the lore is told rather than asked to work out.

    The model is bad at counting three thousand messages and good at being funny about a
    number handed to it, so every figure in the document comes from here.
    """
    window = (chat_id, start, end)

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND ts >= ? AND ts < ?", window
    ) as cur:
        total = int((await cur.fetchone())[0])

    async def per_person(since: str, until: str) -> dict[str, int]:
        # Grouped by user rather than by alias: the readable name is built in Python by
        # `context.pretty_name`, which SQL cannot call.
        async with db.execute(
            """
            SELECT u.display_name, u.alias, COUNT(*) AS n
            FROM messages m
            LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
            WHERE m.chat_id = ? AND m.ts >= ? AND m.ts < ?
              AND m.is_bot = 0 AND m.sender_is_bot = 0
            GROUP BY m.user_id
            """,
            (chat_id, since, until),
        ) as cur:
            # Summed rather than assigned: SQL groups by user and the key is a name, so
            # two people whose display names clean to the same string would otherwise
            # overwrite each other and one of them would vanish from the block.
            counts: dict[str, int] = {}
            for display_name, alias, number in await cur.fetchall():
                who = context.pretty_name(display_name, alias)
                counts[who] = counts.get(who, 0) + int(number)
            return counts

    now_counts = await per_person(start, end)
    then_counts = await per_person(previous_start, start)
    ranked = sorted(now_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]

    async with db.execute(
        """
        SELECT r.message_id, u.display_name, u.alias, COALESCE(m.text, ''),
               m.media_kind, SUM(r.count) AS total
        FROM reactions r
        JOIN messages m ON m.chat_id = r.chat_id AND m.message_id = r.message_id
        LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
        WHERE r.chat_id = ? AND m.ts >= ? AND m.ts < ?
        GROUP BY r.message_id
        ORDER BY total DESC, r.message_id
        LIMIT 3
        """,
        window,
    ) as cur:
        reacted = [tuple(r) for r in await cur.fetchall()]
    top_reacted = [
        (
            context.pretty_name(display_name, alias),
            text,
            media_kind,
            message_id,
            int(count),
            await reactions_for(db, chat_id, message_id),
        )
        for message_id, display_name, alias, text, media_kind, count in reacted
    ]

    async with db.execute(
        """
        SELECT substr(ts, 1, 13) AS bucket, COUNT(*) FROM messages
        WHERE chat_id = ? AND ts >= ? AND ts < ?
        GROUP BY bucket
        """,
        window,
    ) as cur:
        hours = [(r[0], int(r[1])) for r in await cur.fetchall()]

    async with db.execute(
        """
        SELECT prev, ts, (julianday(ts) - julianday(prev)) * 86400 AS gap FROM (
            SELECT ts, LAG(ts) OVER (ORDER BY ts, message_id) AS prev FROM messages
            WHERE chat_id = ? AND ts >= ? AND ts < ?
        )
        WHERE prev IS NOT NULL
        ORDER BY gap DESC LIMIT 1
        """,
        window,
    ) as cur:
        row = await cur.fetchone()
    # julianday is a float, so a clean twelve hours comes back as 43199.99998.
    longest_silence = (round(row[2]), row[0], row[1]) if row else None

    async def champion(clause: str, expression: str) -> tuple[str, int] | None:
        # Bots are excluded here for the same reason `per_person` excludes them. Without
        # it the first real run crowned Пісюнбот "головний редактор реальності" for
        # editing its own 58 messages, which is a bot's behaviour, not a person's habit.
        async with db.execute(
            f"""
            SELECT u.display_name, u.alias, {expression} AS n
            FROM messages m
            LEFT JOIN users u ON u.chat_id = m.chat_id AND u.user_id = m.user_id
            WHERE m.chat_id = ? AND m.ts >= ? AND m.ts < ?
              AND m.is_bot = 0 AND m.sender_is_bot = 0 AND {clause}
            GROUP BY m.user_id ORDER BY n DESC, u.alias LIMIT 1
            """,
            window,
        ) as cur:
            found = await cur.fetchone()
        return (
            (context.pretty_name(found[0], found[1]), int(found[2]))
            if found and found[2]
            else None
        )

    return {
        "total": total,
        "per_person": [
            (who, count, count - then_counts.get(who, 0)) for who, count in ranked
        ],
        "top_reacted": top_reacted,
        "hours": hours,
        "longest_silence": longest_silence,
        "events": await events_between(db, chat_id, start, end),
        "stickers": await champion("m.media_kind = 'sticker'", "COUNT(*)"),
        "edits": await champion("m.edits > 0", "SUM(m.edits)"),
    }


async def forget_chat(db: aiosqlite.Connection, chat_id: int) -> dict[str, int]:
    """Erase everything recorded about one chat.

    Used to clean up chats that were recorded before the whitelist governed storage as
    well as speech, and available for any chat the bot should never have been in.
    """
    removed: dict[str, int] = {}
    for table in (
        "messages", "users", "facts", "summaries", "usage", "bans", "chat_state",
        "reactions", "events", "lore",
        # pidrahuika_days is deliberately absent: the killboard's figures are not this
        # chat's data. They are the same for everybody, and dropping them here would
        # break tomorrow's delta in every other chat.
        "pidor_days", "pidrahuika_posts",
    ):
        cur = await db.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
        removed[table] = cur.rowcount
    await db.commit()
    return {k: v for k, v in removed.items() if v}


async def ensure_chat(db: aiosqlite.Connection, chat_id: int, title: str) -> None:
    """Record that the chat exists, without switching it on.

    An importer that enabled a chat would be an importer that starts the bot talking in
    it. Whether gryag speaks anywhere is the admin's decision and only the admin's.
    """
    await db.execute(
        """
        INSERT INTO chats (chat_id, title, enabled, added_at)
        VALUES (?, ?, 0, datetime('now'))
        ON CONFLICT (chat_id) DO NOTHING
        """,
        (chat_id, title),
    )
    await db.commit()


async def bulk_insert_messages(db: aiosqlite.Connection, rows: list[tuple]) -> int:
    """`save_message` for tens of thousands of rows at once, returning how many landed.

    One transaction rather than one per row: the real export is 43,147 messages, and a
    commit each is minutes of WAL churn. Columns, in order: chat_id, message_id, user_id,
    ts, text, media_kind, file_id, reply_to, is_bot, sender_is_bot, edits.
    """
    if not rows:
        return 0
    before = db.total_changes
    await db.execute("BEGIN IMMEDIATE")
    await db.executemany(
        """
        INSERT INTO messages
            (chat_id, message_id, user_id, ts, text, media_kind, file_id, reply_to,
             is_bot, sender_is_bot, edits)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """,
        rows,
    )
    await db.commit()
    return db.total_changes - before


async def bulk_set_reactions(db: aiosqlite.Connection, rows: list[tuple]) -> int:
    """(chat_id, message_id, emoji, count, updated_at), counts set absolutely."""
    if not rows:
        return 0
    await db.execute("BEGIN IMMEDIATE")
    await db.executemany(
        """
        INSERT INTO reactions (chat_id, message_id, emoji, count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id, emoji) DO UPDATE SET
            count = excluded.count, updated_at = excluded.updated_at
        """,
        rows,
    )
    await db.commit()
    return len(rows)


async def bulk_insert_events(db: aiosqlite.Connection, rows: list[tuple]) -> int:
    """(chat_id, message_id, ts, action, actor_id, payload_json)."""
    if not rows:
        return 0
    before = db.total_changes
    await db.execute("BEGIN IMMEDIATE")
    await db.executemany(
        """
        INSERT INTO events (chat_id, message_id, ts, action, actor_id, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """,
        rows,
    )
    await db.commit()
    return db.total_changes - before


async def chat_title(db: aiosqlite.Connection, chat_id: int) -> str:
    async with db.execute("SELECT title FROM chats WHERE chat_id = ?", (chat_id,)) as cur:
        row = await cur.fetchone()
    return row[0] if row and row[0] else str(chat_id)


async def enabled_chats(db: aiosqlite.Connection) -> list[int]:
    async with db.execute("SELECT chat_id FROM chats WHERE enabled = 1") as cur:
        return [r[0] for r in await cur.fetchall()]


async def ban_user(
    db: aiosqlite.Connection, chat_id: int, user_id: int, until_ts: str, reason: str
) -> None:
    await db.execute(
        """
        INSERT INTO bans (chat_id, user_id, until_ts, reason) VALUES (?, ?, ?, ?)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET
            until_ts = excluded.until_ts, reason = excluded.reason
        """,
        (chat_id, user_id, until_ts, reason),
    )
    await db.commit()


async def unban_user(db: aiosqlite.Connection, chat_id: int, user_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    )
    await db.commit()
    return cur.rowcount > 0


async def ban_until(
    db: aiosqlite.Connection, chat_id: int, user_id: int, now_ts: str
) -> str | None:
    """When this person's ban expires, or None if they are free.

    A ban only stops gryag answering. Their messages are stored and stay in the context
    window exactly as before — being ignored is not the same as being erased.
    """
    async with db.execute(
        "SELECT until_ts FROM bans WHERE chat_id = ? AND user_id = ? AND until_ts > ?",
        (chat_id, user_id, now_ts),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def active_bans(
    db: aiosqlite.Connection, chat_id: int, now_ts: str
) -> list[tuple[str, str, str]]:
    async with db.execute(
        """
        SELECT COALESCE(u.alias, CAST(b.user_id AS TEXT)), b.until_ts, COALESCE(b.reason, '')
        FROM bans b LEFT JOIN users u ON u.chat_id = b.chat_id AND u.user_id = b.user_id
        WHERE b.chat_id = ? AND b.until_ts > ? ORDER BY b.until_ts
        """,
        (chat_id, now_ts),
    ) as cur:
        return [tuple(r) for r in await cur.fetchall()]


async def set_mute(db: aiosqlite.Connection, chat_id: int, until_ts: str | None) -> None:
    await db.execute(
        """
        INSERT INTO chat_state (chat_id, muted_until) VALUES (?, ?)
        ON CONFLICT (chat_id) DO UPDATE SET muted_until = excluded.muted_until
        """,
        (chat_id, until_ts),
    )
    await db.commit()


async def muted_until(
    db: aiosqlite.Connection, chat_id: int, now_ts: str
) -> str | None:
    async with db.execute(
        "SELECT muted_until FROM chat_state WHERE chat_id = ? AND muted_until > ?",
        (chat_id, now_ts),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def last_message_ts(
    db: aiosqlite.Connection, chat_id: int, *, from_bot: bool | None = None
) -> str | None:
    clause = "" if from_bot is None else f" AND is_bot = {int(from_bot)}"
    async with db.execute(
        f"SELECT MAX(ts) FROM messages WHERE chat_id = ?{clause}", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0]


async def ambient_candidates_per_day(db: aiosqlite.Connection, chat_id: int) -> int:
    """How many messages a day would even be worth interrupting over.

    The interjection probability is derived from this rather than pinned to a constant,
    so a quiet chat is not left silent and a loud one is not swamped. Spec §16 left this
    open precisely because it cannot be guessed in advance.
    """
    async with db.execute(
        """
        SELECT COUNT(*) FROM messages
        WHERE chat_id = ? AND is_bot = 0 AND sender_is_bot = 0
          -- Messages are stored ISO-8601 with a 'T'; SQLite's datetime() uses a space,
          -- and 'T' > ' ', so comparing against datetime('now','-1 day') let anything
          -- sharing that calendar date through — a 35-hour-old message counted as
          -- "today", inflating the divisor and halving the ambient rate.
          AND ts >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 day')
          AND LENGTH(COALESCE(text, '')) >= 30
          AND reply_to IS NULL
        """,
        (chat_id,),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def last_proactive_ts(db: aiosqlite.Connection, chat_id: int) -> str | None:
    async with db.execute(
        "SELECT last_ambient_ts FROM chat_state WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def mark_proactive(db: aiosqlite.Connection, chat_id: int, ts: str) -> None:
    await db.execute(
        """
        INSERT INTO chat_state (chat_id, last_ambient_ts) VALUES (?, ?)
        ON CONFLICT (chat_id) DO UPDATE SET last_ambient_ts = excluded.last_ambient_ts
        """,
        (chat_id, ts),
    )
    await db.commit()


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


async def active_user_ids(
    db: aiosqlite.Connection, chat_id: int, since_ts: str
) -> list[int]:
    """Everybody who has said something since `since_ts`, bots excluded.

    This is the only list of chat members available: the Bot API cannot enumerate a
    group, so "who is here" means "who has spoken here recently".
    """
    async with db.execute(
        """
        SELECT DISTINCT user_id FROM messages
        WHERE chat_id = ? AND ts >= ? AND user_id IS NOT NULL
          AND sender_is_bot = 0 AND is_bot = 0
          -- Anybody ever seen as a bot here is out, not merely anybody whose messages in
          -- this window say so. `sender_is_bot` arrived by migration with DEFAULT 0, so
          -- every message sent before it landed reads as human — ten such rows for гряг
          -- itself were enough to put the bot in its own draw.
          AND user_id NOT IN (
              SELECT user_id FROM messages
              WHERE chat_id = ? AND (sender_is_bot = 1 OR is_bot = 1)
                -- NOT IN over a set containing NULL is NULL for every row, so without
                -- this the bot's own messages — stored with no user_id — excluded the
                -- entire chat rather than just the bots.
                AND user_id IS NOT NULL
          )
        ORDER BY user_id
        """,
        (chat_id, since_ts, chat_id),
    ) as cur:
        return [r[0] for r in await cur.fetchall()]


async def pidor_winner(db: aiosqlite.Connection, chat_id: int, day: str) -> int | None:
    async with db.execute(
        "SELECT user_id FROM pidor_days WHERE chat_id = ? AND day = ?", (chat_id, day)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def pidor_record(
    db: aiosqlite.Connection, chat_id: int, day: str, user_id: int, chosen_at: str
) -> int:
    """Claim the day, and return whoever actually holds it.

    Insert-then-read rather than a lock: two people typing the command in the same second
    both write, one loses on the primary key, and both then read the same winner. The same
    reasoning as `_claim` in handlers — the cheapest race is the one you let happen.
    """
    await db.execute(
        """
        INSERT INTO pidor_days (chat_id, day, user_id, chosen_at) VALUES (?, ?, ?, ?)
        ON CONFLICT (chat_id, day) DO NOTHING
        """,
        (chat_id, day, user_id, chosen_at),
    )
    await db.commit()
    held = await pidor_winner(db, chat_id, day)
    assert held is not None  # just inserted, or already there
    return held


async def pidor_counts(
    db: aiosqlite.Connection, chat_id: int, since_day: str | None = None
) -> list[tuple[int, int]]:
    """(user_id, wins), most wins first."""
    clause, params = "", [chat_id]
    if since_day is not None:
        clause = " AND day >= ?"
        params.append(since_day)
    async with db.execute(
        f"""
        SELECT user_id, COUNT(*) AS wins FROM pidor_days
        WHERE chat_id = ?{clause}
        GROUP BY user_id ORDER BY wins DESC, user_id
        """,
        params,
    ) as cur:
        return [(r[0], r[1]) for r in await cur.fetchall()]


async def pidrahuika_save(
    db: aiosqlite.Connection, day: str, fetched_at: str, payload: dict
) -> None:
    """The raw payload, not the rendered text: a change to the rendering should be able to
    go back over days already collected."""
    await db.execute(
        """
        INSERT INTO pidrahuika_days (day, fetched_at, payload) VALUES (?, ?, ?)
        ON CONFLICT (day) DO UPDATE SET
            fetched_at = excluded.fetched_at, payload = excluded.payload
        """,
        (day, fetched_at, json.dumps(payload, ensure_ascii=False)),
    )
    await db.commit()


async def pidrahuika_payload(db: aiosqlite.Connection, day: str) -> dict | None:
    async with db.execute(
        "SELECT payload FROM pidrahuika_days WHERE day = ?", (day,)
    ) as cur:
        row = await cur.fetchone()
    return json.loads(row[0]) if row else None


async def pidrahuika_posted(db: aiosqlite.Connection, chat_id: int, day: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM pidrahuika_posts WHERE chat_id = ? AND day = ?", (chat_id, day)
    ) as cur:
        return await cur.fetchone() is not None


async def pidrahuika_mark(db: aiosqlite.Connection, chat_id: int, day: str) -> None:
    await db.execute(
        """
        INSERT INTO pidrahuika_posts (chat_id, day) VALUES (?, ?)
        ON CONFLICT (chat_id, day) DO NOTHING
        """,
        (chat_id, day),
    )
    await db.commit()
