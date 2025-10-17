from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Iterable
import math

import aiosqlite


# Determine the location of the project root dynamically.
# context_store.py lives at: <project_root>/app/services/context_store.py
# We need the schema at: <project_root>/db/schema.sql
# The previous implementation only went up two parents (…/app/app/db) which does not exist
# inside the container (mounted at /app). We correct this by going up three levels to the
# project root (parents[2]) and include a fallback to the old (incorrect) path just in case
# someone has copied the schema elsewhere.
def _resolve_schema_path() -> Path:
    candidates: list[Path] = [
        Path(__file__).resolve().parents[2]
        / "db"
        / "schema.sql",  # /app/db/schema.sql (expected)
        Path(__file__).resolve().parent.parent
        / "db"
        / "schema.sql",  # legacy incorrect location
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback: return first expected path even if missing; init() will raise clearer error
    return candidates[0]


SCHEMA_PATH: Path = _resolve_schema_path()


META_KEY_ORDER = [
    "chat_id",
    "thread_id",
    "message_id",
    "user_id",  # User ID FIRST - most reliable identifier
    "username",  # Username second
    "name",  # Display name last (can be truncated/ambiguous)
    "reply_to_message_id",
    "reply_to_user_id",  # Reply user ID before name for same reason
    "reply_to_username",
    "reply_to_name",
    "reply_excerpt",
]


def format_metadata(meta: dict[str, Any]) -> str:
    """
    Format metadata dict into a compact text snippet for Gemini.

    Optimized for token efficiency:
    - Only includes non-empty values
    - Drops optional fields when null/empty
    - Truncates long values aggressively
    - Uses shortest possible format
    """
    if not meta:
        return ""  # Drop empty metadata block entirely

    pieces: list[str] = []
    for key in META_KEY_ORDER:
        if key not in meta:
            continue
        value = meta[key]

        # Skip None, empty strings, and zero values for optional fields
        if value is None or value == "":
            continue
        if (
            key in ("thread_id", "reply_to_message_id", "reply_to_user_id")
            and value == 0
        ):
            continue

        if isinstance(value, str):
            # Aggressive sanitization and truncation
            sanitized = (
                value.replace("\n", " ")
                .replace('"', '\\"')
                .replace("[", "")
                .replace("]", "")
                .strip()
            )
            # Truncate usernames and names to preserve distinguishing info
            # Increased from 30 to 60 to avoid cutting off name suffixes that help identify users
            max_len = (
                60
                if key in ("name", "username", "reply_to_name", "reply_to_username")
                else 80
            )
            if len(sanitized) > max_len:
                sanitized = sanitized[: max_len - 2] + ".."

            if sanitized:  # Only add if non-empty after sanitization
                pieces.append(f'{key}="{sanitized}"')
        else:
            pieces.append(f"{key}={value}")

    # Return compact format or empty string
    if pieces:
        return "[meta] " + " ".join(pieces)
    else:
        return ""  # No metadata to include


def _chunked(seq: list[int], size: int) -> Iterable[list[int]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class ContextStore:
    """SQLite-backed storage for chat history and per-user quotas."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._prune_lock = asyncio.Lock()
        self._last_prune_ts = 0
        self._prune_interval = 900  # seconds between automatic pruning tasks

    async def init(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            if not SCHEMA_PATH.exists():  # early clear error
                raise FileNotFoundError(
                    f"SQLite schema file not found at {SCHEMA_PATH}. Ensure 'db/schema.sql' exists in project root and is mounted into the container."
                )
            async with aiosqlite.connect(self._db_path) as db:
                with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
                    await db.executescript(fh.read())
                try:
                    await db.execute("ALTER TABLE messages ADD COLUMN embedding TEXT")
                except aiosqlite.OperationalError:
                    pass
                await db.commit()
            self._initialized = True

    async def add_turn(
        self,
        chat_id: int,
        thread_id: int | None,
        user_id: int | None,
        role: str,
        text: str | None,
        media: Iterable[dict[str, Any]] | None,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        retention_days: int | None = None,
    ) -> None:
        await self.init()
        ts = int(time.time())
        payload: dict[str, Any] = {
            "media": list(media) if media else [],
            "meta": metadata or {},
        }
        media_json = json.dumps(payload)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO messages (chat_id, thread_id, user_id, role, text, media, embedding, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    thread_id,
                    user_id,
                    role,
                    text,
                    media_json,
                    json.dumps(embedding) if embedding else None,
                    ts,
                ),
            )
            await db.commit()
        if retention_days:
            await self._maybe_prune(retention_days)

    async def _maybe_prune(self, retention_days: int) -> None:
        now = int(time.time())
        if self._prune_interval <= 0:
            await self.prune_old(retention_days)
            return
        if now - self._last_prune_ts < self._prune_interval:
            return
        async with self._prune_lock:
            if now - self._last_prune_ts < self._prune_interval:
                return
            await self.prune_old(retention_days)
            self._last_prune_ts = int(time.time())

    async def ban_user(self, chat_id: int, user_id: int) -> None:
        await self.init()
        ts = int(time.time())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO bans (chat_id, user_id, ts) VALUES (?, ?, ?)",
                (chat_id, user_id, ts),
            )
            await db.commit()

    async def delete_user_messages(self, chat_id: int, user_id: int) -> int:
        """Remove all stored messages for a user within a chat."""
        await self.init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM messages WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            rows = await cursor.fetchall()
            message_ids = [row[0] for row in rows]

            if not message_ids:
                return 0

            for chunk in _chunked(message_ids, 500):
                placeholders = ",".join("?" * len(chunk))
                await db.execute(
                    f"DELETE FROM message_metadata WHERE message_id IN ({placeholders})",
                    chunk,
                )
                await db.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    chunk,
                )

            # Clear derived aggregates that may still reference removed messages
            await db.execute(
                "DELETE FROM conversation_windows WHERE chat_id = ?", (chat_id,)
            )
            await db.execute(
                "DELETE FROM proactive_events WHERE chat_id = ?", (chat_id,)
            )
            await db.commit()

        return len(message_ids)

    async def delete_message_by_external_id(
        self, chat_id: int, external_message_id: int
    ) -> bool:
        """Remove a stored message by its original Telegram message ID."""
        await self.init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT id FROM messages 
                WHERE chat_id = ? AND json_extract(media, '$.meta.message_id') = ?
                """,
                (chat_id, external_message_id),
            )
            row = await cursor.fetchone()
            if not row:
                return False

            internal_id = row[0]
            await db.execute(
                "DELETE FROM message_metadata WHERE message_id = ?",
                (internal_id,),
            )
            await db.execute("DELETE FROM messages WHERE id = ?", (internal_id,))
            await db.commit()
            return True

    async def unban_user(self, chat_id: int, user_id: int) -> None:
        await self.init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM bans WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            await db.commit()

    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        await self.init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM bans WHERE chat_id = ? AND user_id = ? LIMIT 1",
                (chat_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def recent(
        self,
        chat_id: int,
        thread_id: int | None,
        max_turns: int,
    ) -> list[dict[str, Any]]:
        await self.init()
        # Each turn = 1 user message + 1 bot response = 2 messages
        # So we need to fetch max_turns * 2 to get the full conversation history
        message_limit = max_turns * 2

        if thread_id is None:
            query = (
                "SELECT role, text, media FROM messages "
                "WHERE chat_id = ? AND thread_id IS NULL "
                "ORDER BY id DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (chat_id, message_limit)
        else:
            query = (
                "SELECT role, text, media FROM messages "
                "WHERE chat_id = ? AND thread_id = ? "
                "ORDER BY id DESC LIMIT ?"
            )
            params = (chat_id, thread_id, message_limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = list(await cursor.fetchall())  # list for reversed()

        history: list[dict[str, Any]] = []
        for row in reversed(rows):
            parts: list[dict[str, Any]] = []
            text = row["text"]
            media_json = row["media"]
            stored_media: list[dict[str, Any]] = []
            stored_meta: dict[str, Any] = {}
            if media_json:
                try:
                    payload = json.loads(media_json)
                    if isinstance(payload, dict):
                        stored_media = [
                            part
                            for part in payload.get("media", [])
                            if isinstance(part, dict)
                        ]
                        meta = payload.get("meta", {})
                        if isinstance(meta, dict):
                            stored_meta = meta
                    elif isinstance(payload, list):
                        stored_media = [
                            part for part in payload if isinstance(part, dict)
                        ]
                except json.JSONDecodeError:
                    pass

            if stored_meta:
                meta_text = format_metadata(stored_meta)
                if meta_text:  # Only add if format_metadata returned non-empty
                    parts.append({"text": meta_text})
            if text:
                parts.append({"text": text})
            if stored_media:
                parts.extend(stored_media)
            history.append({"role": row["role"], "parts": parts or [{"text": ""}]})
        return history

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def semantic_search(
        self,
        chat_id: int,
        thread_id: int | None,
        query_embedding: list[float],
        limit: int = 5,
        max_candidates: int = 500,
    ) -> list[dict[str, Any]]:
        await self.init()
        if not query_embedding:
            return []

        candidate_cap = max(1, max_candidates)
        if thread_id is None:
            query = (
                "SELECT id, role, text, media, embedding FROM messages "
                "WHERE chat_id = ? AND embedding IS NOT NULL "
                "ORDER BY id DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (chat_id, candidate_cap)
        else:
            query = (
                "SELECT id, role, text, media, embedding FROM messages "
                "WHERE chat_id = ? AND thread_id = ? AND embedding IS NOT NULL "
                "ORDER BY id DESC LIMIT ?"
            )
            params = (chat_id, thread_id, candidate_cap)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        scored: list[tuple[float, aiosqlite.Row]] = []
        for row in rows:
            embedding_json = row["embedding"]
            if not embedding_json:
                continue
            try:
                stored_embedding = json.loads(embedding_json)
                if not isinstance(stored_embedding, list):
                    continue
                similarity = self._cosine_similarity(query_embedding, stored_embedding)
            except (json.JSONDecodeError, TypeError):
                continue
            if similarity <= 0:
                continue
            scored.append((similarity, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: max(1, min(limit, 10))]

        results: list[dict[str, Any]] = []
        for score, row in top:
            meta: dict[str, Any] = {}
            media_json = row["media"]
            if media_json:
                try:
                    payload = json.loads(media_json)
                    if isinstance(payload, dict):
                        meta_obj = payload.get("meta", {})
                        if isinstance(meta_obj, dict):
                            meta = meta_obj
                except json.JSONDecodeError:
                    pass
            results.append(
                {
                    "score": float(score),
                    "text": row["text"] or "",
                    "metadata": meta,
                    "role": row["role"],
                    "message_id": row["id"],
                }
            )
        return results

    async def prune_old(self, retention_days: int) -> None:
        await self.init()
        cutoff = int(time.time()) - retention_days * 86400
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
            await db.execute("DELETE FROM bans WHERE ts < ?", (cutoff,))
            await db.commit()
        self._last_prune_ts = int(time.time())
