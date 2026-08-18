# Gryag V3 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working Telegram bot that replies in persona when directly addressed in one
chat, records what every call cost, and lets the admin switch models from a button.

**Architecture:** One `aiogram` process behind a Caddy-terminated webhook. Every incoming
message is written to SQLite before any decision is made. A pure function decides whether
to speak. If it says yes, a prompt is assembled from the compressed persona plus a window
of recent messages, sent to Gemini through the native `google-genai` SDK with thinking
disabled, and the reply is posted. Every call writes a `usage` row.

**Tech Stack:** Python 3.13, aiogram 3.30, google-genai 2.18, aiosqlite 0.22, pytest 9 +
pytest-asyncio 1.4. SQLite in WAL mode. systemd + Caddy.

## Global Constraints

- Source spec: `docs/superpowers/specs/2026-08-19-gryag-v3-design.md`. Where this plan and
  the spec disagree, the spec wins.
- Working directory: `/home/thathunky/bots/gryag-v2`. Python is `.venv/bin/python`; there is
  no activate step.
- **Speaking model default:** `gemini-flash-latest`, `thinking_budget=0`,
  `max_output_tokens=1500`.
- **Safety settings must be `BLOCK_NONE`** on all four harm categories. The persona is
  deliberately offensive; default thresholds will block it.
- **`usage.cached_content_token_count` arrives as `None`, not `0`.** Every read of a usage
  field coerces with `or 0`.
- **The bot never posts an error into the chat.** Any failure means silence.
- **Messages are persisted before the gate runs**, always, including when the bot stays
  silent.
- Prices, verified against Google on 2026-08-18, USD per 1M tokens
  (input / output / cached input):
  `gemini-flash-latest` and `gemini-3.7-flash` = 0.75 / 3.75 / 0.075;
  `gemini-2.5-flash` = 0.30 / 2.50 / 0.03; `gemini-2.5-flash-lite` = 0.10 / 0.40 / 0.025.
- Token estimation without a tokenizer uses **2.5 characters per token**, measured on
  142,773 characters of this chat's real Ukrainian text.
- Never commit `chat_exports/`, `eval/reference/`, `eval/out/`, `.env`.

## Scope

Phase 1 only: direct address, telemetry, model switch. The digest job, summaries, facts,
ambient and proactive triggers, the full admin menu and on-demand media each get their own
plan, because each is independently shippable and phase 1 must be judged in the chat before
they are built.

## File Structure

| path | responsibility |
|---|---|
| `gryag/__init__.py` | package marker, version |
| `gryag/config.py` | typed access to the `config` table, defaults, secrets from env |
| `gryag/store.py` | schema, connection, all SQL |
| `gryag/gate.py` | pure decision function — no I/O, no network |
| `gryag/context.py` | prompt assembly and rendering |
| `gryag/llm.py` | Gemini call, usage capture, cost arithmetic |
| `gryag/handlers.py` | aiogram routers, wiring |
| `gryag/admin.py` | model/effort switch, cost panel |
| `gryag/__main__.py` | entrypoint: app, webhook, startup |
| `tests/conftest.py` | fixtures: temp database |
| `tests/test_*.py` | one per module |

---

### Task 1: Project skeleton

**Files:**
- Create: `gryag/__init__.py`, `tests/__init__.py`, `pytest.ini`
- Modify: `requirements.txt`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: the `gryag` package importable as `gryag`, `gryag.__version__` as `str`

- [ ] **Step 1: Initialise the repository**

```bash
cd /home/thathunky/bots/gryag-v2
git init
git add .gitignore
git commit -m "chore: initial commit with ignore rules"
```

- [ ] **Step 2: Confirm nothing sensitive is staged**

```bash
git status --porcelain --ignored | grep -E "chat_exports|eval/reference|eval/out|\.env$"
```

Expected: every listed path is prefixed `!!` (ignored). If any shows `??` or `A`, stop and
fix `.gitignore` before continuing.

- [ ] **Step 3: Write the failing smoke test**

Create `tests/test_smoke.py`:

```python
def test_package_imports():
    import gryag

    assert isinstance(gryag.__version__, str)
```

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag'`

- [ ] **Step 5: Create the package**

Create `gryag/__init__.py`:

```python
"""gryag V3 — a Telegram group-chat bot with a fixed persona."""

__version__ = "3.0.0"
```

Create `tests/__init__.py` as an empty file.

Create `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = -q
```

- [ ] **Step 6: Replace requirements.txt**

```
aiogram>=3.30
google-genai>=2.18
aiosqlite>=0.22
python-dotenv>=1.0
pyyaml>=6.0
pytest>=9.0
pytest-asyncio>=1.4
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add gryag tests pytest.ini requirements.txt
git commit -m "feat: package skeleton and test harness"
```

---

### Task 2: Store — schema and message persistence

**Files:**
- Create: `gryag/store.py`, `tests/conftest.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `async def connect(path: str) -> aiosqlite.Connection` — opens, applies schema, sets WAL
  - `async def save_message(db, *, chat_id: int, message_id: int, user_id: int, ts: str, text: str, media_kind: str | None, file_id: str | None, reply_to: int | None, is_bot: bool) -> None`
  - `async def upsert_user(db, *, chat_id: int, user_id: int, display_name: str, alias: str) -> None`
  - `async def recent_messages(db, chat_id: int, limit: int) -> list[dict]` — oldest first
  - `async def reply_chain(db, chat_id: int, message_id: int, max_depth: int = 20) -> list[dict]` — oldest first
  - `async def count_replies_since(db, chat_id: int, since_ts: str) -> int`
  - `async def record_usage(db, *, chat_id: int, purpose: str, model: str, prompt_tok: int, cached_tok: int, visible_tok: int, thought_tok: int, latency_ms: int, cost_usd: float) -> None`
  - Each message dict has keys: `message_id`, `user_id`, `ts`, `text`, `media_kind`, `file_id`, `reply_to`, `is_bot`, `alias`, `display_name`

- [ ] **Step 1: Write the failing tests**

Create `tests/conftest.py`:

```python
import pytest_asyncio

from gryag import store


@pytest_asyncio.fixture
async def db(tmp_path):
    conn = await store.connect(str(tmp_path / "test.db"))
    yield conn
    await conn.close()
```

Create `tests/test_store.py`:

```python
from gryag import store


async def _seed_user(db, user_id=1, alias="oleh"):
    await store.upsert_user(
        db, chat_id=-100, user_id=user_id, display_name=f"User {user_id}", alias=alias
    )


async def test_saves_and_reads_back_in_chronological_order(db):
    await _seed_user(db)
    for n in range(3):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=10)

    assert [r["text"] for r in rows] == ["msg 0", "msg 1", "msg 2"]
    assert rows[0]["alias"] == "oleh"


async def test_recent_messages_returns_the_newest_but_still_oldest_first(db):
    await _seed_user(db)
    for n in range(5):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=2)

    assert [r["text"] for r in rows] == ["msg 3", "msg 4"]


async def test_saving_the_same_message_twice_does_not_duplicate(db):
    await _seed_user(db)
    for _ in range(2):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=7,
            user_id=1,
            ts="2026-08-19T10:00:00",
            text="once",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=False,
        )

    rows = await store.recent_messages(db, -100, limit=10)

    assert len(rows) == 1


async def test_reply_chain_walks_back_to_the_root(db):
    await _seed_user(db)
    parents = [None, 1, 2]
    for n, parent in enumerate(parents, start=1):
        await store.save_message(
            db,
            chat_id=-100,
            message_id=n,
            user_id=1,
            ts=f"2026-08-19T10:0{n}:00",
            text=f"msg {n}",
            media_kind=None,
            file_id=None,
            reply_to=parent,
            is_bot=False,
        )

    chain = await store.reply_chain(db, -100, message_id=3)

    assert [r["message_id"] for r in chain] == [1, 2, 3]


async def test_reply_chain_survives_a_missing_parent(db):
    await _seed_user(db)
    await store.save_message(
        db,
        chat_id=-100,
        message_id=9,
        user_id=1,
        ts="2026-08-19T10:00:00",
        text="orphan",
        media_kind=None,
        file_id=None,
        reply_to=4242,
        is_bot=False,
    )

    chain = await store.reply_chain(db, -100, message_id=9)

    assert [r["message_id"] for r in chain] == [9]


async def test_counts_only_this_chats_bot_replies_after_the_cutoff(db):
    await _seed_user(db)
    rows = [
        (1, "2026-08-19T09:00:00", True, -100),
        (2, "2026-08-19T11:00:00", True, -100),
        (3, "2026-08-19T11:30:00", False, -100),
        (4, "2026-08-19T11:40:00", True, -200),
    ]
    for message_id, ts, is_bot, chat_id in rows:
        await store.save_message(
            db,
            chat_id=chat_id,
            message_id=message_id,
            user_id=1,
            ts=ts,
            text="x",
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=is_bot,
        )

    count = await store.count_replies_since(db, -100, "2026-08-19T10:00:00")

    assert count == 1


async def test_usage_rows_are_recorded(db):
    await store.record_usage(
        db,
        chat_id=-100,
        purpose="reply",
        model="gemini-flash-latest",
        prompt_tok=1800,
        cached_tok=0,
        visible_tok=20,
        thought_tok=150,
        latency_ms=2100,
        cost_usd=0.0019,
    )

    async with db.execute("SELECT model, thought_tok FROM usage") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]

    assert rows == [("gemini-flash-latest", 150)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL with `ImportError: cannot import name 'store' from 'gryag'`

- [ ] **Step 3: Implement the store**

Create `gryag/store.py`:

```python
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
    cost_usd    REAL NOT NULL
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
    m.reply_to, m.is_bot, u.alias, u.display_name
"""


async def connect(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.executescript(SCHEMA)
    await db.commit()
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
) -> None:
    await db.execute(
        """
        INSERT INTO messages
            (chat_id, message_id, user_id, ts, text, media_kind, file_id, reply_to, is_bot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """,
        (chat_id, message_id, user_id, ts, text, media_kind, file_id, reply_to, int(is_bot)),
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
) -> None:
    await db.execute(
        """
        INSERT INTO usage
            (chat_id, purpose, model, prompt_tok, cached_tok,
             visible_tok, thought_tok, latency_ms, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    await db.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add gryag/store.py tests/conftest.py tests/test_store.py
git commit -m "feat: sqlite store with messages, users and usage telemetry"
```

---

### Task 3: Config with database-backed overrides

**Files:**
- Create: `gryag/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `gryag.store.connect`
- Produces:
  - `DEFAULTS: dict[str, str]` — every configurable key with its default, values are strings
  - `async def get(db, key: str, chat_id: int | None = None) -> str`
  - `async def get_int(db, key: str, chat_id: int | None = None) -> int`
  - `async def set(db, key: str, value: str, chat_id: int | None = None) -> None`
  - `async def all_for_chat(db, chat_id: int) -> dict[str, str]`
  - `def secrets() -> Secrets` where `Secrets` has `.bot_token`, `.gemini_api_key`,
    `.webhook_secret`, `.webhook_base`, `.admin_ids: tuple[int, ...]`, `.db_path`

Resolution order is chat override, then global override, then `DEFAULTS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
import pytest

from gryag import config


async def test_returns_the_default_when_nothing_is_set(db):
    assert await config.get(db, "speak_model") == "gemini-flash-latest"


async def test_global_override_wins_over_the_default(db):
    await config.set(db, "speak_model", "gemini-2.5-flash")

    assert await config.get(db, "speak_model") == "gemini-2.5-flash"


async def test_chat_override_wins_over_the_global_one(db):
    await config.set(db, "speak_model", "gemini-2.5-flash")
    await config.set(db, "speak_model", "gemini-3.7-flash", chat_id=-100)

    assert await config.get(db, "speak_model", chat_id=-100) == "gemini-3.7-flash"
    assert await config.get(db, "speak_model", chat_id=-200) == "gemini-2.5-flash"


async def test_setting_a_value_twice_updates_it(db):
    await config.set(db, "speak_model", "a")
    await config.set(db, "speak_model", "b")

    assert await config.get(db, "speak_model") == "b"


async def test_get_int_parses_numeric_settings(db):
    await config.set(db, "context_messages", "12")

    assert await config.get_int(db, "context_messages") == 12


async def test_unknown_key_is_a_programming_error(db):
    with pytest.raises(KeyError):
        await config.get(db, "no_such_key")


async def test_all_for_chat_merges_every_layer(db):
    await config.set(db, "daily_reply_cap", "99")
    await config.set(db, "speak_model", "gemini-2.5-flash", chat_id=-100)

    merged = await config.all_for_chat(db, -100)

    assert merged["daily_reply_cap"] == "99"
    assert merged["speak_model"] == "gemini-2.5-flash"
    assert merged["thinking_budget"] == "0"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'config' from 'gryag'`

- [ ] **Step 3: Implement config**

Create `gryag/config.py`:

```python
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
```

The `ORDER BY scope DESC` puts `'global'` before `'chat'`, so chat rows overwrite global
ones as the loop proceeds.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add gryag/config.py tests/test_config.py
git commit -m "feat: layered config with per-chat overrides"
```

---

### Task 4: The gate

**Files:**
- Create: `gryag/gate.py`, `tests/test_gate.py`

**Interfaces:**
- Consumes: nothing — this module imports no I/O of any kind
- Produces:
  - `@dataclass(frozen=True) class GateInput` with fields `text: str`, `is_bot: bool`,
    `chat_enabled: bool`, `mentions_bot: bool`, `replies_to_bot: bool`,
    `keywords: tuple[str, ...]`, `replies_today: int`, `replies_this_hour: int`,
    `daily_cap: int`, `hourly_cap: int`
  - `@dataclass(frozen=True) class GateDecision` with `speak: bool`, `reason: str`
  - `def should_speak(g: GateInput) -> GateDecision`
  - `def mentions_keyword(text: str, keywords: tuple[str, ...]) -> bool`

`reason` is a stable machine-readable slug, used in logs and later in the admin panel.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate.py`:

```python
import pytest

from gryag.gate import GateInput, mentions_keyword, should_speak


def make(**overrides) -> GateInput:
    base = dict(
        text="просто повідомлення",
        is_bot=False,
        chat_enabled=True,
        mentions_bot=False,
        replies_to_bot=False,
        keywords=("гряг",),
        replies_today=0,
        replies_this_hour=0,
        daily_cap=60,
        hourly_cap=10,
    )
    base.update(overrides)
    return GateInput(**base)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("гряг привіт", True),
        ("Гряг, шо там", True),
        ("а гряга нема", True),
        ("дай грягу спокій", True),
        ("грягом клянуся", True),
        ("привіт усім", False),
        ("аргумент", False),
        ("шпаргалка", False),
    ],
)
def test_keyword_matching_covers_inflections_but_not_substrings(text, expected):
    assert mentions_keyword(text, ("гряг",)) is expected


def test_speaks_when_the_bot_is_mentioned():
    assert should_speak(make(mentions_bot=True)).speak is True


def test_speaks_when_someone_replies_to_the_bot():
    assert should_speak(make(replies_to_bot=True)).speak is True


def test_speaks_when_a_keyword_appears():
    decision = should_speak(make(text="гряг шо скажеш"))

    assert decision.speak is True
    assert decision.reason == "keyword"


def test_stays_silent_without_any_address():
    decision = should_speak(make())

    assert decision.speak is False
    assert decision.reason == "not_addressed"


def test_never_answers_another_bot_even_when_addressed():
    decision = should_speak(make(is_bot=True, mentions_bot=True))

    assert decision.speak is False
    assert decision.reason == "sender_is_bot"


def test_stays_silent_in_a_disabled_chat():
    decision = should_speak(make(chat_enabled=False, mentions_bot=True))

    assert decision.speak is False
    assert decision.reason == "chat_disabled"


def test_daily_cap_stops_even_a_direct_address():
    decision = should_speak(make(mentions_bot=True, replies_today=60, daily_cap=60))

    assert decision.speak is False
    assert decision.reason == "daily_cap"


def test_hourly_cap_stops_even_a_direct_address():
    decision = should_speak(make(mentions_bot=True, replies_this_hour=10, hourly_cap=10))

    assert decision.speak is False
    assert decision.reason == "hourly_cap"


def test_disabled_chat_is_checked_before_the_sender():
    decision = should_speak(make(chat_enabled=False, is_bot=True, mentions_bot=True))

    assert decision.reason == "chat_disabled"


def test_empty_text_with_a_reply_to_the_bot_still_speaks():
    assert should_speak(make(text="", replies_to_bot=True)).speak is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag.gate'`

- [ ] **Step 3: Implement the gate**

Create `gryag/gate.py`:

```python
"""The decision to speak.

Deliberately pure: no database, no network, no clock. Everything it needs is passed in, so
the whole of the bot's behaviour can be tested without spending a cent. This is the
structural difference from the legacy bot, where deciding whether to answer cost money.

Phase 1 implements direct address only. Ambient interjection and proactive speech arrive in
phase 3 and will extend GateInput rather than replace it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GateInput:
    text: str
    is_bot: bool
    chat_enabled: bool
    mentions_bot: bool
    replies_to_bot: bool
    keywords: tuple[str, ...]
    replies_today: int
    replies_this_hour: int
    daily_cap: int
    hourly_cap: int


@dataclass(frozen=True)
class GateDecision:
    speak: bool
    reason: str


def mentions_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """True when a keyword starts a word.

    Matching on a word boundary followed by the keyword catches Ukrainian inflections
    (гряг, гряга, грягу, грягом) with a single configured stem, while refusing to fire on
    words that merely contain it, like `шпаргалка`.
    """
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}", text, re.IGNORECASE):
            return True
    return False


def should_speak(g: GateInput) -> GateDecision:
    if not g.chat_enabled:
        return GateDecision(False, "chat_disabled")
    if g.is_bot:
        return GateDecision(False, "sender_is_bot")
    if g.replies_today >= g.daily_cap:
        return GateDecision(False, "daily_cap")
    if g.replies_this_hour >= g.hourly_cap:
        return GateDecision(False, "hourly_cap")

    if g.mentions_bot:
        return GateDecision(True, "mention")
    if g.replies_to_bot:
        return GateDecision(True, "reply_to_bot")
    if mentions_keyword(g.text, g.keywords):
        return GateDecision(True, "keyword")

    return GateDecision(False, "not_addressed")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gate.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add gryag/gate.py tests/test_gate.py
git commit -m "feat: pure trigger gate for direct address"
```

---

### Task 5: Context assembly

**Files:**
- Create: `gryag/context.py`, `tests/test_context.py`

**Interfaces:**
- Consumes: message dicts as returned by `gryag.store.recent_messages`
- Produces:
  - `CHARS_PER_TOKEN: float = 2.5`
  - `BOUNDARY: str` — the marker that separates the log from the bot's answer slot
  - `def estimate_tokens(text: str) -> int`
  - `def clamp(text: str, max_tokens: int) -> str`
  - `def alias_for(display_name: str) -> str`
  - `def render_line(msg: dict) -> str`
  - `def is_context_worthy(msg: dict) -> bool`
  - `def build(messages: list[dict], chain: list[dict], trigger: dict, now: str, chat_title: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_context.py`:

```python
from gryag import context


def msg(**overrides) -> dict:
    base = dict(
        message_id=1,
        user_id=1,
        ts="2026-08-19T10:00:00",
        text="привіт",
        media_kind=None,
        file_id=None,
        reply_to=None,
        is_bot=False,
        alias="oleh",
        display_name="Олег",
    )
    base.update(overrides)
    return base


def test_alias_shortens_a_long_display_name():
    assert context.alias_for("Vsevolod Dobrovolskyi") == "Vsevolod"


def test_alias_falls_back_when_the_name_is_unusable():
    assert context.alias_for("٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.") != ""
    assert len(context.alias_for("٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.")) <= 8


def test_renders_a_plain_message():
    assert context.render_line(msg()) == "oleh: привіт"


def test_renders_media_as_a_marker():
    line = context.render_line(msg(text="", media_kind="photo"))

    assert line == "oleh: [фото]"


def test_media_with_a_caption_keeps_both():
    line = context.render_line(msg(text="гляньте", media_kind="photo"))

    assert line == "oleh: [фото] гляньте"


def test_bot_messages_are_labelled_as_the_bot():
    assert context.render_line(msg(is_bot=True, text="ага")).startswith("гряг:")


def test_drops_messages_from_other_bots():
    assert context.is_context_worthy(msg(alias="Пісюнбот", is_bot=False, text="")) is False


def test_keeps_a_media_message_that_has_a_kind():
    assert context.is_context_worthy(msg(text="", media_kind="photo")) is True


def test_drops_an_empty_message_with_no_media():
    assert context.is_context_worthy(msg(text="", media_kind=None)) is False


def test_estimate_tokens_uses_the_measured_ratio():
    assert context.estimate_tokens("a" * 250) == 100


def test_clamp_leaves_short_text_alone():
    assert context.clamp("короткий", 100) == "короткий"


def test_clamp_cuts_long_text_to_the_budget():
    clamped = context.clamp("я" * 1000, 10)

    assert len(clamped) <= 25


def test_build_ends_with_the_boundary_and_the_trigger():
    prompt = context.build(
        messages=[msg(message_id=1, text="перше"), msg(message_id=2, text="друге")],
        chain=[],
        trigger=msg(message_id=3, text="гряг шо"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert "перше" in prompt
    assert prompt.index("перше") < prompt.index("друге")
    assert context.BOUNDARY in prompt
    assert prompt.strip().endswith("oleh: гряг шо")


def test_build_puts_the_reply_chain_before_the_window_without_duplicating():
    prompt = context.build(
        messages=[msg(message_id=5, text="вікно")],
        chain=[msg(message_id=1, text="корінь"), msg(message_id=5, text="вікно")],
        trigger=msg(message_id=6, text="гряг шо"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert prompt.count("вікно") == 1
    assert prompt.index("корінь") < prompt.index("вікно")


def test_build_includes_the_header():
    prompt = context.build(
        messages=[],
        chain=[],
        trigger=msg(text="гряг"),
        now="2026-08-19 10:00, середа",
        chat_title="матсурі",
    )

    assert "2026-08-19 10:00, середа" in prompt
    assert "матсурі" in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag.context'`

- [ ] **Step 3: Implement context assembly**

Create `gryag/context.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_context.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add gryag/context.py tests/test_context.py
git commit -m "feat: context assembly with aliases, media markers and answer boundary"
```

---

### Task 6: The Gemini call

**Files:**
- Create: `gryag/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `PRICES: dict[str, tuple[float, float, float]]` — model → (input, output, cached input)
  - `@dataclass(frozen=True) class LlmResult` with `text: str`, `prompt_tokens: int`,
    `cached_tokens: int`, `visible_tokens: int`, `thought_tokens: int`, `latency_ms: int`,
    `cost_usd: float`
  - `def cost_usd(model: str, prompt_tokens: int, cached_tokens: int, visible_tokens: int, thought_tokens: int) -> float`
  - `def build_client(api_key: str) -> genai.Client`
  - `async def generate(client, *, model: str, system: str, user: str, max_output_tokens: int, thinking_budget: int) -> LlmResult | None`

`generate` returns `None` on any failure or empty reply, because silence is the correct
behaviour and the caller must never post an error into the chat.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm.py`:

```python
import types as pytypes

import pytest

from gryag import llm


class FakeUsage:
    def __init__(self, prompt=1000, cached=None, visible=20, thoughts=None):
        self.prompt_token_count = prompt
        self.cached_content_token_count = cached
        self.candidates_token_count = visible
        self.thoughts_token_count = thoughts


class FakeResponse:
    def __init__(self, text="ага", usage=None):
        self.text = text
        self.usage_metadata = usage or FakeUsage()


class FakeClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []
        self.aio = pytypes.SimpleNamespace(models=self)

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error is not None:
            raise self._error
        return self._response


def test_cost_uses_the_cached_rate_for_cached_tokens():
    cost = llm.cost_usd(
        "gemini-2.5-flash",
        prompt_tokens=1_000_000,
        cached_tokens=1_000_000,
        visible_tokens=0,
        thought_tokens=0,
    )

    assert cost == pytest.approx(0.03)


def test_cost_bills_thinking_tokens_at_the_output_rate():
    cost = llm.cost_usd(
        "gemini-2.5-flash",
        prompt_tokens=0,
        cached_tokens=0,
        visible_tokens=500_000,
        thought_tokens=500_000,
    )

    assert cost == pytest.approx(2.50)


def test_unknown_model_costs_nothing_rather_than_crashing():
    assert llm.cost_usd("some-new-model", 1000, 0, 10, 10) == 0.0


async def test_returns_the_text_and_usage():
    client = FakeClient(FakeResponse("ага", FakeUsage(prompt=1800, visible=16, thoughts=150)))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result.text == "ага"
    assert result.prompt_tokens == 1800
    assert result.thought_tokens == 150
    assert result.latency_ms >= 0
    assert result.cost_usd > 0


async def test_treats_a_missing_cached_count_as_zero():
    client = FakeClient(FakeResponse("ага", FakeUsage(cached=None)))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result.cached_tokens == 0


async def test_empty_reply_becomes_silence():
    client = FakeClient(FakeResponse(""))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_none_reply_becomes_silence():
    client = FakeClient(FakeResponse(None))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_an_api_failure_becomes_silence_not_an_exception():
    client = FakeClient(error=RuntimeError("boom"))

    result = await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    assert result is None


async def test_safety_is_disabled_on_every_category():
    client = FakeClient(FakeResponse())

    await llm.generate(
        client,
        model="gemini-flash-latest",
        system="persona",
        user="привіт",
        max_output_tokens=1500,
        thinking_budget=0,
    )

    settings = client.calls[0]["config"].safety_settings
    assert len(settings) == 4
    assert all(s.threshold == "BLOCK_NONE" for s in settings)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag.llm'`

- [ ] **Step 3: Implement the LLM layer**

Create `gryag/llm.py`:

```python
"""The Gemini call.

Uses the native SDK deliberately. Measured on 2026-08-18, the OpenAI compatibility endpoint
served one implicit cache hit in 37 calls where the native endpoint served 46-93%, and it
does not report thinking tokens at all — which are billed at the output rate and, on 3.x
models, are the volatile part of the bill.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

HARM_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)

PRICES: dict[str, tuple[float, float, float]] = {
    # model: (input, output, cached input) in USD per 1M tokens.
    # Verified against Google's pricing page on 2026-08-18. The 3.x rates are
    # promotional and double on 2027-01-01.
    "gemini-flash-latest": (0.75, 3.75, 0.075),
    "gemini-3.7-flash": (0.75, 3.75, 0.075),
    "gemini-2.5-flash": (0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.025),
}


@dataclass(frozen=True)
class LlmResult:
    text: str
    prompt_tokens: int
    cached_tokens: int
    visible_tokens: int
    thought_tokens: int
    latency_ms: int
    cost_usd: float


def cost_usd(
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    visible_tokens: int,
    thought_tokens: int,
) -> float:
    """Thinking tokens bill at the output rate even though they are never shown."""
    if model not in PRICES:
        log.warning("no price for model %s, reporting zero cost", model)
        return 0.0
    price_in, price_out, price_cached = PRICES[model]
    fresh = max(prompt_tokens - cached_tokens, 0)
    return (
        fresh * price_in
        + cached_tokens * price_cached
        + (visible_tokens + thought_tokens) * price_out
    ) / 1_000_000


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


async def generate(
    client: genai.Client,
    *,
    model: str,
    system: str,
    user: str,
    max_output_tokens: int,
    thinking_budget: int,
) -> LlmResult | None:
    """Returns None on any failure or empty reply — silence is the correct behaviour."""
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        safety_settings=[
            types.SafetySetting(category=category, threshold="BLOCK_NONE")
            for category in HARM_CATEGORIES
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    started = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model, contents=user, config=config
        )
    except Exception:
        log.exception("gemini call failed for model %s", model)
        return None
    latency_ms = int((time.monotonic() - started) * 1000)

    text = (response.text or "").strip()
    usage = response.usage_metadata
    prompt_tokens = usage.prompt_token_count or 0
    cached_tokens = usage.cached_content_token_count or 0
    visible_tokens = usage.candidates_token_count or 0
    thought_tokens = usage.thoughts_token_count or 0

    if not text:
        log.warning(
            "empty reply from %s: %s thinking tokens consumed the budget",
            model,
            thought_tokens,
        )
        return None

    return LlmResult(
        text=text,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        visible_tokens=visible_tokens,
        thought_tokens=thought_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd(
            model, prompt_tokens, cached_tokens, visible_tokens, thought_tokens
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Verify against the real API once, by hand**

```bash
cd /home/thathunky/bots/gryag-v2
set -a && . ./.env && set +a && .venv/bin/python -c "
import asyncio, os
from gryag import llm
async def main():
    c = llm.build_client(os.environ['GEMINI_API_KEY'])
    r = await llm.generate(c, model='gemini-flash-latest',
        system=open('eval/persona-v3.txt').read(),
        user='oleh: гряг шо там по лінуксу\n---\nпиши тільки свою репліку',
        max_output_tokens=1500, thinking_budget=0)
    print(r)
asyncio.run(main())
"
```

Expected: an `LlmResult` with non-empty Ukrainian text, `prompt_tokens` near 600, and
`cost_usd` on the order of 0.0005. If `text` is empty, the safety settings or the thinking
budget are wrong — do not proceed.

- [ ] **Step 6: Commit**

```bash
git add gryag/llm.py tests/test_llm.py
git commit -m "feat: native gemini client with usage capture and cost arithmetic"
```

---

### Task 7: Handlers

**Files:**
- Create: `gryag/handlers.py`, `tests/test_handlers.py`

**Interfaces:**
- Consumes: `store`, `config`, `gate`, `context`, `llm`
- Produces:
  - `def media_kind_and_file_id(message) -> tuple[str | None, str | None]`
  - `async def persist(db, message, *, is_bot: bool = False) -> None`
  - `async def handle_message(message, db, client, persona: str, bot_id: int) -> str | None` —
    returns the reply text it sent, or `None` when it stayed silent. Answers with
    `message.reply`, so every reply quotes what triggered it, and holds a `typing…`
    action for the ~2 seconds generation takes
  - `def build_router() -> aiogram.Router`

`handle_message` is written to take its dependencies as arguments so it can be tested
without a live bot.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers.py`:

```python
import types as pytypes
from datetime import datetime

from gryag import config, handlers, llm, store


class FakeMessage:
    def __init__(
        self,
        *,
        text="привіт",
        message_id=1,
        chat_id=-100,
        user_id=1,
        full_name="Олег",
        is_bot=False,
        reply_to=None,
        entities=None,
    ):
        self.message_id = message_id
        self.date = datetime(2026, 8, 19, 10, 0, 0)
        self.text = text
        self.caption = None
        self.chat = pytypes.SimpleNamespace(id=chat_id, title="матсурі")
        self.from_user = pytypes.SimpleNamespace(
            id=user_id, full_name=full_name, is_bot=is_bot
        )
        self.reply_to_message = reply_to
        self.entities = entities or []
        self.photo = self.voice = self.video = None
        self.video_note = self.sticker = self.document = None
        self.answers: list[str] = []

    async def answer(self, text):
        self.answers.append(text)
        return FakeMessage(text=text, message_id=self.message_id + 1000, is_bot=True)


class FakeLlm:
    def __init__(self, text="ага"):
        self.text = text
        self.calls: list[dict] = []

    async def generate(self, client, **kwargs):
        self.calls.append(kwargs)
        return llm.LlmResult(
            text=self.text,
            prompt_tokens=600,
            cached_tokens=0,
            visible_tokens=10,
            thought_tokens=100,
            latency_ms=1200,
            cost_usd=0.0005,
        )


async def enable_chat(db, chat_id=-100):
    await db.execute(
        "INSERT OR REPLACE INTO chats (chat_id, title, enabled) VALUES (?, ?, 1)",
        (chat_id, "матсурі"),
    )
    await db.commit()


async def test_persists_even_when_it_stays_silent(db, monkeypatch):
    await enable_chat(db)
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="балачки без звертання")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert fake.calls == []
    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["балачки без звертання"]


async def test_answers_when_a_keyword_is_used(db, monkeypatch):
    await enable_chat(db)
    fake = FakeLlm("та лінух то діагноз")
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply == "та лінух то діагноз"
    assert message.answers == ["та лінух то діагноз"]


async def test_stays_silent_in_a_chat_that_was_never_enabled(db, monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(handlers.llm, "generate", fake.generate)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert fake.calls == []


async def test_records_usage_for_every_reply(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm().generate)
    message = FakeMessage(text="гряг шо там")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    async with db.execute("SELECT purpose, cost_usd FROM usage") as cur:
        rows = await cur.fetchall()
    assert rows[0][0] == "reply"
    assert rows[0][1] > 0


async def test_stores_its_own_reply_so_the_next_context_contains_it(db, monkeypatch):
    await enable_chat(db)
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm("моя репліка").generate)
    message = FakeMessage(text="гряг шо там")

    await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    rows = await store.recent_messages(db, -100, limit=10)
    assert [r["text"] for r in rows] == ["гряг шо там", "моя репліка"]
    assert rows[1]["is_bot"] == 1


async def test_a_failed_generation_posts_nothing(db, monkeypatch):
    await enable_chat(db)

    async def failing(client, **kwargs):
        return None

    monkeypatch.setattr(handlers.llm, "generate", failing)
    message = FakeMessage(text="гряг шо там")

    reply = await handlers.handle_message(message, db, client=None, persona="p", bot_id=77)

    assert reply is None
    assert message.answers == []


async def test_the_daily_cap_silences_the_bot(db, monkeypatch):
    await enable_chat(db)
    await config.set(db, "daily_reply_cap", "1")
    monkeypatch.setattr(handlers.llm, "generate", FakeLlm().generate)

    first = FakeMessage(text="гряг раз", message_id=1)
    await handlers.handle_message(first, db, client=None, persona="p", bot_id=77)
    second = FakeMessage(text="гряг два", message_id=2)
    reply = await handlers.handle_message(second, db, client=None, persona="p", bot_id=77)

    assert reply is None


async def test_media_kind_is_detected():
    message = FakeMessage(text="")
    message.photo = [pytypes.SimpleNamespace(file_id="abc")]

    kind, file_id = handlers.media_kind_and_file_id(message)

    assert (kind, file_id) == ("photo", "abc")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_handlers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag.handlers'`

- [ ] **Step 3: Implement the handlers**

Create `gryag/handlers.py`:

```python
"""aiogram wiring.

The message is written to the database before the gate decides anything. If it were written
afterwards, history would have holes exactly where the bot stayed quiet, and the digest job
would summarise an incomplete day.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import aiosqlite
from aiogram import F, Router
from aiogram.types import Message

from gryag import config, context, gate, llm, store

log = logging.getLogger(__name__)


def media_kind_and_file_id(message) -> tuple[str | None, str | None]:
    if getattr(message, "photo", None):
        return "photo", message.photo[-1].file_id
    for kind in ("voice", "video_note", "video", "sticker", "document"):
        item = getattr(message, kind, None)
        if item is not None:
            return kind, item.file_id
    return None, None


async def persist(db: aiosqlite.Connection, message, *, is_bot: bool = False) -> None:
    kind, file_id = media_kind_and_file_id(message)
    user = message.from_user
    if user is not None:
        await store.upsert_user(
            db,
            chat_id=message.chat.id,
            user_id=user.id,
            display_name=user.full_name,
            alias=context.alias_for(user.full_name),
        )
    await store.save_message(
        db,
        chat_id=message.chat.id,
        message_id=message.message_id,
        user_id=user.id if user else None,
        ts=message.date.isoformat(timespec="seconds"),
        text=(message.text or message.caption or ""),
        media_kind=kind,
        file_id=file_id,
        reply_to=(
            message.reply_to_message.message_id if message.reply_to_message else None
        ),
        is_bot=is_bot,
    )


async def _chat_enabled(db: aiosqlite.Connection, chat_id: int) -> bool:
    async with db.execute(
        "SELECT enabled FROM chats WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


async def handle_message(
    message: Message,
    db: aiosqlite.Connection,
    client,
    persona: str,
    bot_id: int,
) -> str | None:
    chat_id = message.chat.id
    await persist(db, message)

    now = message.date
    replies_today = await store.count_replies_since(
        db, chat_id, now.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    )
    replies_this_hour = await store.count_replies_since(
        db, chat_id, (now - timedelta(hours=1)).isoformat(timespec="seconds")
    )

    text = message.text or message.caption or ""
    replied = message.reply_to_message
    decision = gate.should_speak(
        gate.GateInput(
            text=text,
            is_bot=bool(message.from_user and message.from_user.is_bot),
            chat_enabled=await _chat_enabled(db, chat_id),
            mentions_bot=any(
                text[e.offset : e.offset + e.length].lstrip("@").lower().endswith("gryag_bot")
                for e in (message.entities or [])
                if e.type == "mention"
            ),
            replies_to_bot=bool(
                replied and replied.from_user and replied.from_user.id == bot_id
            ),
            keywords=tuple(
                k.strip()
                for k in (await config.get(db, "keywords", chat_id)).split(",")
                if k.strip()
            ),
            replies_today=replies_today,
            replies_this_hour=replies_this_hour,
            daily_cap=await config.get_int(db, "daily_reply_cap", chat_id),
            hourly_cap=await config.get_int(db, "hourly_reply_cap", chat_id),
        )
    )
    if not decision.speak:
        log.debug("silent in %s: %s", chat_id, decision.reason)
        return None

    window = await config.get_int(db, "context_messages", chat_id)
    messages = await store.recent_messages(db, chat_id, limit=window)
    chain = (
        await store.reply_chain(db, chat_id, replied.message_id) if replied else []
    )
    trigger = {
        "message_id": message.message_id,
        "text": text,
        "media_kind": media_kind_and_file_id(message)[0],
        "is_bot": False,
        "alias": context.alias_for(message.from_user.full_name),
    }
    prompt = context.build(
        messages=messages,
        chain=chain,
        trigger=trigger,
        now=now.strftime("%Y-%m-%d %H:%M"),
        chat_title=message.chat.title or "",
    )

    model = await config.get(db, "speak_model", chat_id)
    result = await llm.generate(
        client,
        model=model,
        system=persona,
        user=prompt,
        max_output_tokens=await config.get_int(db, "max_output_tokens", chat_id),
        thinking_budget=await config.get_int(db, "thinking_budget", chat_id),
    )
    if result is None:
        return None

    await store.record_usage(
        db,
        chat_id=chat_id,
        purpose="reply",
        model=model,
        prompt_tok=result.prompt_tokens,
        cached_tok=result.cached_tokens,
        visible_tok=result.visible_tokens,
        thought_tok=result.thought_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )

    sent = await message.reply(result.text)
    await persist(db, sent, is_bot=True)
    return result.text


def build_router() -> Router:
    router = Router(name="chat")

    @router.message(F.text | F.caption | F.photo | F.voice | F.video | F.sticker)
    async def on_message(message: Message, db, client, persona, bot_id) -> None:
        await handle_message(message, db, client, persona, bot_id)

    return router
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_handlers.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS, 66 tests

- [ ] **Step 6: Commit**

```bash
git add gryag/handlers.py tests/test_handlers.py
git commit -m "feat: message handler wiring persistence, gate, context and reply"
```

---

### Task 8: Admin — model switch and cost panel

**Files:**
- Create: `gryag/admin.py`, `tests/test_admin.py`

**Interfaces:**
- Consumes: `store`, `config`, `llm.PRICES`
- Produces:
  - `MODEL_CHOICES: tuple[str, ...]`
  - `async def spend_report(db, chat_id: int | None = None) -> str` — plain-text panel
  - `async def enable_chat(db, chat_id: int, title: str) -> None`
  - `def build_router(admin_ids: tuple[int, ...]) -> aiogram.Router` — `/gryag` opens the
    menu, callbacks `model:<name>`, `think:<n>`, `chat:on`, `chat:off`, `panel`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin.py`:

```python
from gryag import admin, config, store


async def test_spend_report_says_so_when_there_is_nothing_yet(db):
    report = await admin.spend_report(db)

    assert "поки нічого" in report


async def test_spend_report_totals_cost_and_tokens(db):
    for _ in range(2):
        await store.record_usage(
            db,
            chat_id=-100,
            purpose="reply",
            model="gemini-flash-latest",
            prompt_tok=600,
            cached_tok=0,
            visible_tok=20,
            thought_tok=150,
            latency_ms=2000,
            cost_usd=0.001,
        )

    report = await admin.spend_report(db)

    assert "0.0020" in report
    assert "gemini-flash-latest" in report
    assert "2" in report


async def test_enabling_a_chat_makes_it_enabled(db):
    await admin.enable_chat(db, -100, "матсурі")

    async with db.execute("SELECT enabled, title FROM chats WHERE chat_id = ?", (-100,)) as cur:
        row = await cur.fetchone()

    assert row[0] == 1
    assert row[1] == "матсурі"


async def test_every_offered_model_has_a_price(db):
    from gryag import llm

    assert all(model in llm.PRICES for model in admin.MODEL_CHOICES)


async def test_switching_the_model_is_readable_afterwards(db):
    await config.set(db, "speak_model", "gemini-2.5-flash", chat_id=-100)

    assert await config.get(db, "speak_model", chat_id=-100) == "gemini-2.5-flash"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gryag.admin'`

- [ ] **Step 3: Implement admin**

Create `gryag/admin.py`:

```python
"""The phase-1 admin surface: switch the model, read what it costs.

These two exist in phase 1 rather than with the rest of the menu because quality is judged
live (see spec §10.2). A live comparison is only real if swapping the model is a button
press, and only measurable if every call was recorded.
"""

from __future__ import annotations

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from gryag import config

MODEL_CHOICES = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite")


async def enable_chat(db: aiosqlite.Connection, chat_id: int, title: str) -> None:
    await db.execute(
        """
        INSERT INTO chats (chat_id, title, enabled, added_at)
        VALUES (?, ?, 1, datetime('now'))
        ON CONFLICT (chat_id) DO UPDATE SET enabled = 1, title = excluded.title
        """,
        (chat_id, title),
    )
    await db.commit()


async def disable_chat(db: aiosqlite.Connection, chat_id: int) -> None:
    await db.execute("UPDATE chats SET enabled = 0 WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def spend_report(db: aiosqlite.Connection, chat_id: int | None = None) -> str:
    where, params = "", []
    if chat_id is not None:
        where, params = "WHERE chat_id = ?", [chat_id]
    async with db.execute(
        f"""
        SELECT model,
               COUNT(*),
               SUM(cost_usd),
               AVG(prompt_tok),
               AVG(visible_tok),
               AVG(thought_tok),
               AVG(latency_ms),
               SUM(cached_tok) * 1.0 / NULLIF(SUM(prompt_tok), 0)
        FROM usage {where}
        GROUP BY model
        """,
        params,
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "Витрат поки нічого немає."

    lines = ["Витрати:"]
    total = 0.0
    for model, calls, cost, prompt, visible, thoughts, latency, cache in rows:
        total += cost or 0.0
        lines.append(
            f"{model}\n"
            f"  викликів: {calls}, разом ${cost:.4f}\n"
            f"  промпт {prompt:.0f}, видимих {visible:.0f}, думання {thoughts:.0f}\n"
            f"  латентність {latency:.0f} мс, кеш {100 * (cache or 0):.1f}%"
        )
    lines.append(f"Разом: ${total:.4f}")
    return "\n".join(lines)


def _menu(current_model: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("• " if model == current_model else "") + model,
                callback_data=f"model:{model}",
            )
        ]
        for model in MODEL_CHOICES
    ]
    rows.append(
        [
            InlineKeyboardButton(text="думання: 0", callback_data="think:0"),
            InlineKeyboardButton(text="думання: авто", callback_data="think:-1"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="увімкнути чат", callback_data="chat:on"),
            InlineKeyboardButton(text="вимкнути", callback_data="chat:off"),
        ]
    )
    rows.append([InlineKeyboardButton(text="витрати", callback_data="panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_router(admin_ids: tuple[int, ...]) -> Router:
    router = Router(name="admin")
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))

    @router.message(Command("gryag"))
    async def open_menu(message: Message, db) -> None:
        current = await config.get(db, "speak_model", message.chat.id)
        await message.answer(f"Модель: {current}", reply_markup=_menu(current))

    @router.callback_query(F.data.startswith("model:"))
    async def switch_model(query: CallbackQuery, db) -> None:
        model = query.data.split(":", 1)[1]
        await config.set(db, "speak_model", model, chat_id=query.message.chat.id)
        await query.message.edit_text(f"Модель: {model}", reply_markup=_menu(model))
        await query.answer("готово")

    @router.callback_query(F.data.startswith("think:"))
    async def switch_thinking(query: CallbackQuery, db) -> None:
        budget = query.data.split(":", 1)[1]
        await config.set(db, "thinking_budget", budget, chat_id=query.message.chat.id)
        await query.answer(f"думання: {budget}")

    @router.callback_query(F.data == "chat:on")
    async def turn_on(query: CallbackQuery, db) -> None:
        await enable_chat(db, query.message.chat.id, query.message.chat.title or "")
        await query.answer("чат увімкнено")

    @router.callback_query(F.data == "chat:off")
    async def turn_off(query: CallbackQuery, db) -> None:
        await disable_chat(db, query.message.chat.id)
        await query.answer("чат вимкнено")

    @router.callback_query(F.data == "panel")
    async def show_panel(query: CallbackQuery, db) -> None:
        await query.message.answer(await spend_report(db, query.message.chat.id))
        await query.answer()

    return router
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add gryag/admin.py tests/test_admin.py
git commit -m "feat: admin model switch and spend panel"
```

---

### Task 9: Entrypoint and deployment

**Files:**
- Create: `gryag/__main__.py`, `deploy/gryag-bot.service`, `deploy/Caddyfile.snippet`,
  `.env.example`
- Test: manual, described below

**Interfaces:**
- Consumes: everything above
- Produces: a runnable `python -m gryag`

- [ ] **Step 1: Write the entrypoint**

Create `gryag/__main__.py`:

```python
"""Entrypoint. Webhook mode behind Caddy."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from gryag import admin, config, handlers, llm, store

WEBHOOK_PATH = "/webhook"
PERSONA_PATH = Path(__file__).resolve().parent.parent / "eval" / "persona-v3.txt"


async def build_app() -> web.Application:
    """Everything is constructed inside the running loop.

    The database connection, the aiohttp app and the bot session must all belong to the
    same event loop. Building the app with `asyncio.run` and then handing it to
    `web.run_app` would create them in a loop that is closed before the server starts.
    """
    secrets = config.secrets()
    logging.basicConfig(level=logging.INFO)

    db = await store.connect(secrets.db_path)
    client = llm.build_client(secrets.gemini_api_key)
    persona = PERSONA_PATH.read_text()

    bot = Bot(secrets.bot_token, default=DefaultBotProperties(parse_mode=None))
    me = await bot.get_me()

    dispatcher = Dispatcher(db=db, client=client, persona=persona, bot_id=me.id)
    dispatcher.include_router(admin.build_router(secrets.admin_ids))
    dispatcher.include_router(handlers.build_router())

    await bot.set_webhook(
        f"{secrets.webhook_base}{WEBHOOK_PATH}",
        secret_token=secrets.webhook_secret,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=secrets.webhook_secret
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    return app


async def serve() -> None:
    app = await build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=8081)
    await site.start()
    logging.info("listening on 127.0.0.1:8081")
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
```

Note: the persona is read once at startup. Hot reload arrives with the full menu in phase 4;
until then a persona edit needs `systemctl restart gryag-bot`.

- [ ] **Step 2: Write `.env.example`**

```
TELEGRAM_BOT_TOKEN=
GEMINI_API_KEY=
WEBHOOK_SECRET=
WEBHOOK_BASE=https://gryag.dobrovolskyi.com.ua
ADMIN_IDS=392817811
DB_PATH=/home/thathunky/bots/gryag-v2/gryag.db
```

- [ ] **Step 3: Fill in the real `.env`**

```bash
cd /home/thathunky/bots/gryag-v2
python3 -c "import secrets; print('WEBHOOK_SECRET=' + secrets.token_urlsafe(32))" >> .env
```

Then add `TELEGRAM_BOT_TOKEN`, `WEBHOOK_BASE`, `ADMIN_IDS` and `DB_PATH` by hand.
`GEMINI_API_KEY` is already there.

- [ ] **Step 4: Write the systemd unit**

Create `deploy/gryag-bot.service`:

```ini
[Unit]
Description=gryag V3 telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=thathunky
WorkingDirectory=/home/thathunky/bots/gryag-v2
ExecStart=/home/thathunky/bots/gryag-v2/.venv/bin/python -m gryag
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Write the Caddy snippet**

Create `deploy/Caddyfile.snippet`:

```
gryag.dobrovolskyi.com.ua {
    reverse_proxy 127.0.0.1:8081
}
```

- [ ] **Step 6: Install and start**

```bash
sudo cp deploy/gryag-bot.service /etc/systemd/system/gryag-bot.service
cat deploy/Caddyfile.snippet | sudo tee -a /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl daemon-reload
sudo systemctl enable --now gryag-bot
sudo systemctl status gryag-bot --no-pager
```

Expected: `active (running)`. Before appending to the Caddyfile, back it up —
`sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.pre-gryag` — the directory shows this
is the established habit on this machine.

- [ ] **Step 7: Verify the webhook is registered**

```bash
set -a && . ./.env && set +a
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo" | python3 -m json.tool
```

Expected: `"url"` matches `WEBHOOK_BASE`, `"pending_update_count": 0`, and no
`last_error_message`.

- [ ] **Step 8: Live smoke test in the chat**

1. Add the bot to the target chat.
2. Send `/gryag` and press **увімкнути чат**.
3. Send `гряг привіт`.
4. Expect one in-character Ukrainian reply, plain text, short.
5. Press **витрати** and confirm a row appeared with a non-zero cost and a sane latency.

```bash
journalctl -u gryag-bot -n 50 --no-pager
```

Expected: no tracebacks. Silent messages log at debug level with a `reason` slug.

- [ ] **Step 9: Commit**

```bash
git add gryag/__main__.py deploy .env.example
git commit -m "feat: entrypoint, systemd unit and caddy config"
```

---

## Done when

- `.venv/bin/python -m pytest` passes, 71 tests.
- The bot answers `гряг ...` in the enabled chat, in character, in one message.
- It stays silent for everything else, and `journalctl` shows why.
- `/gryag` switches the model, and the next reply's `usage` row records the new one.
- The spend panel shows cost, tokens, thinking tokens, latency and cache share per model.
- Phase 1's numbers can be compared against spec §14: ~1,890-token prompts and roughly
  $0.002 per reply on `flash-latest`.

## Not in this plan

Digest job and summaries, facts extraction, ambient and proactive triggers, the rest of the
admin menu, on-demand media, persona hot reload. Each gets its own plan once phase 1 has
been judged in the chat.
