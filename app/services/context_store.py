from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
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


SPEAKER_ALLOWED_ROLES = {"user", "assistant", "system", "tool"}


@dataclass(slots=True)
class TurnSender:
    role: str | None = None
    name: str | None = None
    username: str | None = None
    is_bot: bool | None = None


def _sanitize_header_value(value: str) -> str:
    """Sanitize text for speaker header blocks."""
    cleaned = (
        value.replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
        .replace("[", "")
        .replace("]", "")
        .strip()
    )
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned


def format_speaker_header(
    role: str | None,
    sender_id: int | str | None,
    name: str | None,
    username: str | None,
    *,
    is_bot: bool | int | None = None,
) -> str:
    """Format speaker annotation for Gemini context messages."""
    pieces: list[str] = []

    normalized_role = (role or "user").lower()
    if normalized_role not in SPEAKER_ALLOWED_ROLES:
        if normalized_role == "model":
            normalized_role = "assistant"
        elif normalized_role == "agent":
            normalized_role = "assistant"
        else:
            normalized_role = "user"
    pieces.append(f"role={normalized_role}")

    if sender_id is not None:
        try:
            sender_id_str = str(int(sender_id))
        except (TypeError, ValueError):
            sender_id_str = str(sender_id)
        sender_id_str = sender_id_str.strip()
        if sender_id_str:
            pieces.append(f"id={sender_id_str}")

    if name:
        sanitized_name = _sanitize_header_value(str(name))
        if sanitized_name:
            pieces.append(f'name="{sanitized_name}"')

    if username:
        sanitized_username = _sanitize_header_value(str(username))
        if sanitized_username:
            pieces.append(f'username="{sanitized_username}"')

    if is_bot is not None:
        bot_value = 1 if bool(is_bot) else 0
        pieces.append(f"is_bot={bot_value}")

    if not pieces:
        return ""

    return "[speaker " + " ".join(pieces) + "]"


def format_metadata(meta: dict[str, Any], include_reply_chain: bool = True) -> str:
    """
    Format metadata dict into a compact text snippet for Gemini.

    Optimized for token efficiency:
    - Only includes non-empty values
    - Drops optional fields when null/empty
    - Truncates long values aggressively
    - Uses shortest possible format

    Args:
        meta: Metadata dictionary to format
        include_reply_chain: If False, excludes reply_to_* fields to simplify context.
                           Use False for historical context, True for immediate/trigger messages.
    """
    if not meta:
        return ""  # Drop empty metadata block entirely

    pieces: list[str] = []
    for key in META_KEY_ORDER:
        if key not in meta:
            continue

        # Skip reply chain fields if requested (for cleaner historical context)
        if not include_reply_chain and key.startswith("reply_to_"):
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
            # Increased from 30 to 60 (Oct 2025), now to 100 to preserve full distinguishing information
            # while still preventing excessive token usage
            max_len = (
                100
                if key in ("name", "username", "reply_to_name", "reply_to_username")
                else 120
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
                # Preflight migration for legacy DBs: ensure external_* columns exist
                try:
                    async with db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row:  # messages table exists, check columns
                        cols: set[str] = set()
                        async with db.execute("PRAGMA table_info(messages)") as cur2:
                            for r in await cur2.fetchall():
                                # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
                                cols.add(r[1])
                        # Add missing columns (idempotent)
                        if "embedding" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN embedding TEXT"
                            )
                        if "external_message_id" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN external_message_id TEXT"
                            )
                        if "external_user_id" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN external_user_id TEXT"
                            )
                        if "reply_to_external_message_id" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN reply_to_external_message_id TEXT"
                            )
                        if "reply_to_external_user_id" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN reply_to_external_user_id TEXT"
                            )
                        if "sender_role" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN sender_role TEXT"
                            )
                        if "sender_name" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN sender_name TEXT"
                            )
                        if "sender_username" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN sender_username TEXT"
                            )
                        if "sender_is_bot" not in cols:
                            await db.execute(
                                "ALTER TABLE messages ADD COLUMN sender_is_bot INTEGER DEFAULT 0"
                            )
                        await db.commit()
                except Exception:
                    # Best-effort; proceed to full schema application
                    pass

                # Apply (or re-apply) full schema — safe due to IF NOT EXISTS
                with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
                    await db.executescript(fh.read())
                try:
                    await db.execute("ALTER TABLE messages ADD COLUMN embedding TEXT")
                except aiosqlite.OperationalError:
                    pass
                # Ensure external ID text columns exist for robustness (idempotent)
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN external_message_id TEXT"
                    )
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN external_user_id TEXT"
                    )
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN reply_to_external_message_id TEXT"
                    )
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN reply_to_external_user_id TEXT"
                    )
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute("ALTER TABLE messages ADD COLUMN sender_role TEXT")
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute("ALTER TABLE messages ADD COLUMN sender_name TEXT")
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN sender_username TEXT"
                    )
                except aiosqlite.OperationalError:
                    pass
                try:
                    await db.execute(
                        "ALTER TABLE messages ADD COLUMN sender_is_bot INTEGER DEFAULT 0"
                    )
                except aiosqlite.OperationalError:
                    pass

                # Add last_notice_time column to bans table for throttled ban notices
                try:
                    await db.execute(
                        "ALTER TABLE bans ADD COLUMN last_notice_time INTEGER"
                    )
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
        *,
        sender: TurnSender | None = None,
    ) -> None:
        await self.init()
        ts = int(time.time())
        payload: dict[str, Any] = {
            "media": list(media) if media else [],
            "meta": metadata or {},
        }
        media_json = json.dumps(payload)
        # Ensure external IDs are available as strings to avoid precision loss
        ext_message_id: str | None = None
        ext_user_id: str | None = None
        reply_to_ext_message_id: str | None = None
        reply_to_ext_user_id: str | None = None
        if metadata:
            # Prefer explicit string versions when present, else stringify numbers
            if metadata.get("message_id") is not None:
                ext_message_id = str(metadata.get("message_id"))
            if metadata.get("user_id") is not None:
                ext_user_id = str(metadata.get("user_id"))
            if metadata.get("reply_to_message_id") is not None:
                reply_to_ext_message_id = str(metadata.get("reply_to_message_id"))
            if metadata.get("reply_to_user_id") is not None:
                reply_to_ext_user_id = str(metadata.get("reply_to_user_id"))
        sender_role: str | None = None
        sender_name: str | None = None
        sender_username: str | None = None
        sender_is_bot: int | None = None
        if sender:
            sender_role = sender.role
            sender_name = sender.name
            sender_username = sender.username
            if sender.is_bot is not None:
                sender_is_bot = 1 if sender.is_bot else 0
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO messages (
                    chat_id, thread_id, user_id, role, text, media, embedding, ts,
                    external_message_id, external_user_id, reply_to_external_message_id, reply_to_external_user_id,
                    sender_role, sender_name, sender_username, sender_is_bot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ext_message_id,
                    ext_user_id,
                    reply_to_ext_message_id,
                    reply_to_ext_user_id,
                    sender_role,
                    sender_name,
                    sender_username,
                    sender_is_bot,
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
                "INSERT OR REPLACE INTO bans (chat_id, user_id, ts, last_notice_time) VALUES (?, ?, ?, NULL)",
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
            # Try matching dedicated external column first (stringified)
            cursor = await db.execute(
                "SELECT id FROM messages WHERE chat_id = ? AND external_message_id = ? LIMIT 1",
                (chat_id, str(external_message_id)),
            )
            row = await cursor.fetchone()
            if not row:
                # Fallback to legacy JSON meta lookup (may be numeric or string)
                cursor = await db.execute(
                    """
                    SELECT id FROM messages 
                    WHERE chat_id = ? AND CAST(json_extract(media, '$.meta.message_id') AS TEXT) = ? LIMIT 1
                    """,
                    (chat_id, str(external_message_id)),
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

    async def should_send_ban_notice(
        self, chat_id: int, user_id: int, cooldown_seconds: int = 1800
    ) -> bool:
        """
        Check if we should send a ban notice to this user.
        Returns True if enough time has passed since last notice (or first time).
        Default cooldown: 30 minutes (1800 seconds)
        """
        await self.init()
        current_time = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            # Check last ban notice time
            async with db.execute(
                "SELECT last_notice_time FROM bans WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()

                if row is None:
                    # Not banned
                    return False

                last_notice = row[0]
                if last_notice is None:
                    # First time - send notice and update timestamp
                    await db.execute(
                        "UPDATE bans SET last_notice_time = ? WHERE chat_id = ? AND user_id = ?",
                        (current_time, chat_id, user_id),
                    )
                    await db.commit()
                    return True

                # Check if cooldown has passed
                if current_time - last_notice >= cooldown_seconds:
                    # Update timestamp
                    await db.execute(
                        "UPDATE bans SET last_notice_time = ? WHERE chat_id = ? AND user_id = ?",
                        (current_time, chat_id, user_id),
                    )
                    await db.commit()
                    return True

                return False

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
                "SELECT role, text, media, external_user_id, user_id, "
                "sender_role, sender_name, sender_username, sender_is_bot "
                "FROM messages "
                "WHERE chat_id = ? AND thread_id IS NULL "
                "ORDER BY id DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (chat_id, message_limit)
        else:
            query = (
                "SELECT role, text, media, external_user_id, user_id, "
                "sender_role, sender_name, sender_username, sender_is_bot "
                "FROM messages "
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

            stored_sender_role = row["sender_role"]
            stored_sender_name = row["sender_name"]
            stored_sender_username = row["sender_username"]
            stored_sender_is_bot = row["sender_is_bot"]
            external_sender_id = row["external_user_id"]
            internal_user_id = row["user_id"]

            sender_role_value = stored_sender_role or row["role"]
            sender_id_value: int | str | None = None
            if external_sender_id:
                sender_id_value = external_sender_id
            elif stored_meta and stored_meta.get("user_id") is not None:
                sender_id_value = stored_meta.get("user_id")
            elif internal_user_id is not None:
                sender_id_value = internal_user_id

            sender_name_value = stored_sender_name
            if not sender_name_value and stored_meta:
                sender_name_value = stored_meta.get("name")

            sender_username_value = stored_sender_username
            if not sender_username_value and stored_meta:
                sender_username_value = stored_meta.get("username")

            if stored_sender_is_bot is not None:
                sender_is_bot_value: bool | int | None = bool(stored_sender_is_bot)
            elif stored_meta:
                sender_is_bot_value = stored_meta.get("is_bot")
            else:
                sender_is_bot_value = None

            header = format_speaker_header(
                sender_role_value,
                sender_id_value,
                sender_name_value,
                sender_username_value,
                is_bot=sender_is_bot_value,
            )
            if header:
                parts.append({"text": header})
            if stored_meta:
                # For historical context, exclude reply chains to simplify and avoid confusion
                # This keeps user_id, name, username but removes reply_to_* fields
                meta_text = format_metadata(stored_meta, include_reply_chain=False)
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

    async def prune_old(self, retention_days: int) -> int:
        """Prune old messages and related data safely.

        Behavior:
        - Deletes messages older than cutoff (retention_days)
        - Skips messages referenced in `episodes.message_ids`
        - Skips messages with explicit `message_importance.retention_days` overrides
        - Deletes in chunks to avoid long locks
        """
        await self.init()
        cutoff = int(time.time()) - int(retention_days) * 86400

        deleted_total = 0
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # Build list of candidate message ids that are older than cutoff
            # and are NOT referenced by episodes or protected by message_importance
            query = """
            SELECT id FROM messages m
            WHERE m.ts < ?
              AND NOT EXISTS (
                SELECT 1 FROM episodes e, json_each(e.message_ids) je
                WHERE CAST(je.value AS INTEGER) = m.id LIMIT 1
              )
              AND NOT EXISTS (
                SELECT 1 FROM message_importance mi
                WHERE mi.message_id = m.id AND (mi.retention_days IS NOT NULL AND mi.retention_days > 0)
              )
            ORDER BY id ASC
            """

            cursor = await db.execute(query, (cutoff,))
            rows = await cursor.fetchall()
            candidate_ids = [row[0] for row in rows]

            if not candidate_ids:
                self._last_prune_ts = int(time.time())
                return 0

            # Delete in chunks of 500
            for chunk in _chunked(candidate_ids, 500):
                placeholders = ",".join("?" * len(chunk))
                # Remove metadata first
                await db.execute(
                    f"DELETE FROM message_metadata WHERE message_id IN ({placeholders})",
                    chunk,
                )
                # Remove any message_importance records referencing these messages
                await db.execute(
                    f"DELETE FROM message_importance WHERE message_id IN ({placeholders})",
                    chunk,
                )
                # Finally remove messages
                await db.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    chunk,
                )
                await db.commit()
                deleted_total += len(chunk)

        self._last_prune_ts = int(time.time())
        return deleted_total

    # =========================
    # Quota tracking utilities
    # =========================
    async def log_request(
        self, chat_id: int, user_id: int, now: int | None = None
    ) -> None:
        """
        Log a user request for hourly quota tracking.

        Note: Current implementation tracks per-user globally (no per-chat partition)
        to keep schema compatibility with existing 'rate_limits' table. The chat_id
        parameter is accepted for API compatibility and future partitioning but not used.

        Args:
            chat_id: Chat identifier (unused)
            user_id: User identifier
            now: Optional override for current timestamp (seconds)
        """
        await self.init()
        current_ts = int(now or time.time())
        window_seconds = 3600
        window_start = current_ts - (current_ts % window_seconds)

        async with aiosqlite.connect(self._db_path) as db:
            # Drop very old windows (older than previous hour) to keep table small
            await db.execute(
                "DELETE FROM rate_limits WHERE window_start < ?",
                (window_start - window_seconds,),
            )

            # Upsert current window counter
            async with db.execute(
                """
                SELECT request_count FROM rate_limits
                WHERE user_id = ? AND window_start = ?
                """,
                (user_id, window_start),
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                await db.execute(
                    """
                    UPDATE rate_limits
                    SET request_count = request_count + 1, last_seen = ?
                    WHERE user_id = ? AND window_start = ?
                    """,
                    (current_ts, user_id, window_start),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO rate_limits (user_id, window_start, request_count, last_seen)
                    VALUES (?, ?, 1, ?)
                    """,
                    (user_id, window_start, current_ts),
                )

            await db.commit()

    async def count_requests_last_hour(
        self, chat_id: int, user_id: int, now: int | None = None
    ) -> int:
        """
        Count how many requests this user made in the last 60 minutes.

        Args:
            chat_id: Chat identifier (unused)
            user_id: User identifier
            now: Optional override for current timestamp (seconds)

        Returns:
            Total requests observed in the trailing 60 minutes window
        """
        await self.init()
        current_ts = int(now or time.time())
        window_seconds = 3600
        cutoff = current_ts - window_seconds

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """
                SELECT COALESCE(SUM(request_count), 0)
                FROM rate_limits
                WHERE user_id = ? AND window_start >= ?
                """,
                (user_id, cutoff - (cutoff % window_seconds)),
            ) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] is None:
                    return 0
                return int(row[0])

    async def reset_quotas(self, chat_id: int) -> int:
        """
        Reset recorded request quotas.

        Current implementation resets all user windows (no per-chat partition).

        Args:
            chat_id: Chat identifier (unused)

        Returns:
            Number of rows deleted
        """
        await self.init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM rate_limits")
            await db.commit()
            return cursor.rowcount or 0


async def run_retention_pruning_task(
    store: ContextStore,
    retention_days: int,
    prune_interval_seconds: int,
) -> None:
    """Background task for pruning old messages based on retention policy.

    This task runs periodically to remove messages older than the configured
    retention period.

    Args:
        store: The ContextStore instance to use for pruning
        retention_days: Number of days to retain messages
        prune_interval_seconds: Interval between pruning runs in seconds
    """
    logger = logging.getLogger(__name__)

    while True:
        try:
            logger.info("Retention pruning: starting run")
            try:
                deleted = await store.prune_old(retention_days)
                logger.info(
                    "Retention pruning: completed",
                    extra={
                        "deleted_messages": deleted,
                        "retention_days": retention_days,
                    },
                )
            except Exception as e:
                logger.error(f"Retention pruning failed: {e}", exc_info=True)
        except Exception as exc:
            logger.error(f"Error in retention pruner: {exc}", exc_info=True)

        await asyncio.sleep(prune_interval_seconds)
