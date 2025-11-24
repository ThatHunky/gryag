from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

from app.infrastructure.db_utils import get_db_connection
from app.infrastructure.query_converter import convert_query_to_postgres
from app.services.context_cache import ContextCache
from app.services.redis_types import RedisLike

logger = logging.getLogger(__name__)


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
class MessageSender:
    """Sender information for a message (replaces old TurnSender)."""

    role: str | None = None
    name: str | None = None
    username: str | None = None
    is_bot: bool | None = None


# Backward compatibility alias
TurnSender = MessageSender


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
    """PostgreSQL-backed storage for chat history and per-user quotas."""

    def __init__(self, database_url: str, redis_client: RedisLike | None = None) -> None:
        """
        Initialize context store.

        Args:
            database_url: PostgreSQL connection string
            redis_client: Optional Redis client for caching
        """
        self._database_url = str(database_url)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._prune_lock = asyncio.Lock()
        self._last_prune_ts = 0
        self._prune_interval = 900  # seconds between automatic pruning tasks
        self._context_cache = (
            ContextCache(redis_client, ttl_seconds=60) if redis_client else None
        )
        self._redis = redis_client  # Store for ban caching



    async def init(self) -> None:
        """Initialize database connection."""
        async with self._init_lock:
            if self._initialized:
                return

            # Verify connection works
            async with get_db_connection(self._database_url) as conn:
                await conn.execute("SELECT 1")

            self._initialized = True
            logger.info("ContextStore initialized with PostgreSQL")

    async def add_message(
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
        sender: MessageSender | None = None,
    ) -> int:
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

        from app.infrastructure.db_utils import execute_with_retry, get_db_connection

        message_id = 0

        async def insert_message():
            nonlocal message_id
            async with get_db_connection(self._database_url) as conn:
                query = """
                    INSERT INTO messages (
                        chat_id, thread_id, user_id, role, text, media, embedding, ts,
                        external_message_id, external_user_id, reply_to_external_message_id, reply_to_external_user_id,
                        sender_role, sender_name, sender_username, sender_is_bot
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    RETURNING id
                """
                params = (
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
                )

                row = await conn.fetchrow(query, *params)

                row = await conn.fetchrow(query, *params)
                message_id = row["id"] if row else 0

        await execute_with_retry(
            insert_message, max_retries=5, operation_name="add_message (insert_message)"
        )
        # NOTE: Retention pruning moved to background task in main.py to avoid blocking message processing
        # Previously: if retention_days: await self._maybe_prune(retention_days)

        # Invalidate cache when new message is added
        if self._context_cache is not None:
            await self._context_cache.invalidate(chat_id, thread_id)

        return int(message_id)

    async def update_message_embedding(
        self, message_id: int, embedding: list[float] | None
    ) -> None:
        """Update the embedding for an existing message row.

        Args:
            message_id: Primary key of the message in `messages` table
            embedding: Vector to store (JSON) or None to clear
        """
        query = "UPDATE messages SET embedding = $1 WHERE id = $2"
        params = (json.dumps(embedding) if embedding else None, message_id)

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(query, *params)

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
        query = """
            INSERT INTO bans (chat_id, user_id, ts, last_notice_time)
            VALUES ($1, $2, $3, NULL)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET ts = $4
        """
        params = (chat_id, user_id, ts, ts)

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(query, *params)

        # Invalidate cache
        if self._redis is not None:
            try:
                cache_key = f"ban:chat:{chat_id}:user:{user_id}"
                await self._redis.delete(cache_key)
            except Exception as exc:
                logger.warning(f"Redis ban cache invalidate failed: {exc}")

    async def delete_user_messages(self, chat_id: int, user_id: int) -> int:
        """Remove all stored messages for a user within a chat."""
        await self.init()
        async with get_db_connection(self._database_url) as conn:
            query = "SELECT id FROM messages WHERE chat_id = $1 AND user_id = $2"
            params = (chat_id, user_id)

            rows = await conn.fetch(query, *params)
            message_ids = [row["id"] for row in rows]

            if not message_ids:
                return 0

            # Delete metadata first (foreign key constraint)
            # Use ANY($1) for array parameter in Postgres
            q1 = "DELETE FROM message_metadata WHERE message_id = ANY($1::bigint[])"
            p1 = (message_ids,)
            await conn.execute(q1, *p1)

            q2 = "DELETE FROM messages WHERE id = ANY($1::bigint[])"
            p2 = (message_ids,)
            await conn.execute(q2, *p2)

            # Clear derived aggregates that may still reference removed messages
            q3 = "DELETE FROM conversation_windows WHERE chat_id = $1"
            p3 = (chat_id,)
            await conn.execute(q3, *p3)

            q4 = "DELETE FROM proactive_events WHERE chat_id = $1"
            p4 = (chat_id,)
            await conn.execute(q4, *p4)

        return len(message_ids)

    async def delete_message_by_external_id(
        self, chat_id: int, external_message_id: int
    ) -> bool:
        """Remove a stored message by its original Telegram message ID."""
        await self.init()
        async with get_db_connection(self._database_url) as conn:
            # Try matching dedicated external column first (stringified)
            query = "SELECT id FROM messages WHERE chat_id = $1 AND external_message_id = $2 LIMIT 1"
            params = (chat_id, str(external_message_id))

            row = await conn.fetchrow(query, *params)
            if not row:
                # Fallback to legacy JSON meta lookup
                query = """
                    SELECT id FROM messages
                    WHERE chat_id = $1
                      AND media IS NOT NULL
                      AND media != ''
                      AND (media::jsonb->'meta'->>'message_id') = $2
                    LIMIT 1
                """
                params = (chat_id, str(external_message_id))

                row = await conn.fetchrow(query, *params)
            if not row:
                return False

            internal_id = row["id"]

            q1 = "DELETE FROM message_metadata WHERE message_id = $1"
            p1 = (internal_id,)
            await conn.execute(q1, *p1)

            q2 = "DELETE FROM messages WHERE id = $1"
            p2 = (internal_id,)
            await conn.execute(q2, *p2)
            return True

    async def unban_user(self, chat_id: int, user_id: int) -> None:
        await self.init()
        query = "DELETE FROM bans WHERE chat_id = $1 AND user_id = $2"
        params = (chat_id, user_id)

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(query, *params)

        # Invalidate cache
        if self._redis is not None:
            try:
                cache_key = f"ban:chat:{chat_id}:user:{user_id}"
                await self._redis.delete(cache_key)
            except Exception as exc:
                logger.warning(f"Redis ban cache invalidate failed: {exc}")

    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        await self.init()

        # Try Redis cache first
        if self._redis is not None:
            try:
                cache_key = f"ban:chat:{chat_id}:user:{user_id}"
                cached = await self._redis.get(cache_key)
                if cached is not None:
                    # Cache hit - return cached value
                    return cached == b"1" or cached == "1"
            except Exception as exc:
                logger.warning(f"Redis ban cache get failed: {exc}")

        # Query database
        query = "SELECT 1 FROM bans WHERE chat_id = $1 AND user_id = $2 LIMIT 1"
        params = (chat_id, user_id)

        async with get_db_connection(self._database_url) as conn:
            row = await conn.fetchrow(query, *params)
            is_banned = row is not None

            # Cache the result (TTL: 5 minutes)
            if self._redis is not None:
                try:
                    cache_key = f"ban:chat:{chat_id}:user:{user_id}"
                    await self._redis.set(cache_key, "1" if is_banned else "0", ex=300)
                except Exception as exc:
                    logger.warning(f"Redis ban cache set failed: {exc}")

            return is_banned

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

        async with get_db_connection(self._database_url) as conn:
            # Check last ban notice time
            query = "SELECT last_notice_time FROM bans WHERE chat_id = $1 AND user_id = $2"
            params = (chat_id, user_id)

            row = await conn.fetchrow(query, *params)

            if row is None:
                # Not banned
                return False

            last_notice = row["last_notice_time"]
            if last_notice is None:
                # First time - send notice and update timestamp
                q2 = "UPDATE bans SET last_notice_time = $1 WHERE chat_id = $2 AND user_id = $3"
                p2 = (current_time, chat_id, user_id)
                await conn.execute(q2, *p2)
                return True

            # Check if cooldown has passed
            if current_time - last_notice >= cooldown_seconds:
                # Update timestamp
                q3 = "UPDATE bans SET last_notice_time = $1 WHERE chat_id = $2 AND user_id = $3"
                p3 = (current_time, chat_id, user_id)
                await conn.execute(q3, *p3)
                return True

            return False

    async def recent(
        self,
        chat_id: int,
        thread_id: int | None,
        max_messages: int,
        exclude_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        await self.init()

        # Try Redis cache first
        if self._context_cache is not None:
            cached_context = await self._context_cache.get(
                chat_id, thread_id, max_messages
            )
            if cached_context is not None:
                # Return cached data (already limited to max_messages)
                return (
                    cached_context[:max_messages]
                    if len(cached_context) > max_messages
                    else cached_context
                )

        # Use max_messages directly (no multiplication needed)
        message_limit = max_messages

        if thread_id is None:
            if exclude_message_id is not None:
                query = (
                    "SELECT role, text, media, external_user_id, user_id, ts, "
                    "sender_role, sender_name, sender_username, sender_is_bot "
                    "FROM messages "
                    "WHERE chat_id = $1 AND thread_id IS NULL "
                    "AND (external_message_id IS NULL OR external_message_id != $2) "
                    "ORDER BY id DESC LIMIT $3"
                )
                params: tuple[Any, ...] = (
                    chat_id,
                    str(exclude_message_id),
                    message_limit,
                )
            else:
                query = (
                    "SELECT role, text, media, external_user_id, user_id, ts, "
                    "sender_role, sender_name, sender_username, sender_is_bot "
                    "FROM messages "
                    "WHERE chat_id = $1 AND thread_id IS NULL "
                    "ORDER BY id DESC LIMIT $2"
                )
                params: tuple[Any, ...] = (chat_id, message_limit)
        else:
            if exclude_message_id is not None:
                query = (
                    "SELECT role, text, media, external_user_id, user_id, ts, "
                    "sender_role, sender_name, sender_username, sender_is_bot "
                    "FROM messages "
                    "WHERE chat_id = $1 AND thread_id = $2 "
                    "AND (external_message_id IS NULL OR external_message_id != $3) "
                    "ORDER BY id DESC LIMIT $4"
                )
                params = (chat_id, thread_id, str(exclude_message_id), message_limit)
            else:
                query = (
                    "SELECT role, text, media, external_user_id, user_id, ts, "
                    "sender_role, sender_name, sender_username, sender_is_bot "
                    "FROM messages "
                    "WHERE chat_id = $1 AND thread_id = $2 "
                    "ORDER BY id DESC LIMIT $3"
                )
                params = (chat_id, thread_id, message_limit)

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(query, *params)

        history: list[dict[str, Any]] = []
        for row in reversed(rows):
            parts: list[dict[str, Any]] = []
            text = row["text"]
            media_json = row["media"]
            stored_meta: dict[str, Any] = {}
            if media_json:
                try:
                    payload = json.loads(media_json)
                    if isinstance(payload, dict):
                        [
                            part
                            for part in payload.get("media", [])
                            if isinstance(part, dict)
                        ]
                        meta = payload.get("meta", {})
                        if isinstance(meta, dict):
                            stored_meta = meta
                    elif isinstance(payload, list):
                        [part for part in payload if isinstance(part, dict)]
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
            # Media from recent context is disabled - only current message and replied-to message include media
            # if stored_media:
            #     parts.extend(stored_media)
            msg_dict = {"role": row["role"], "parts": parts or [{"text": ""}]}
            # Include timestamp if available
            if row.get("ts") is not None:
                msg_dict["ts"] = row["ts"]
            history.append(msg_dict)

        # Cache the result for future requests
        if self._context_cache is not None:
            await self._context_cache.set(chat_id, thread_id, history)

        return history

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
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
                "WHERE chat_id = $1 AND embedding IS NOT NULL "
                "ORDER BY id DESC LIMIT $2"
            )
            params: tuple[Any, ...] = (chat_id, candidate_cap)
        else:
            query = (
                "SELECT id, role, text, media, embedding FROM messages "
                "WHERE chat_id = $1 AND thread_id = $2 AND embedding IS NOT NULL "
                "ORDER BY id DESC LIMIT $3"
            )
            params = (chat_id, thread_id, candidate_cap)

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(query, *params)

        scored: list[tuple[float, asyncpg.Record]] = []
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
        - Adds delays between chunks to allow other operations
        """
        await self.init()
        cutoff = int(time.time()) - int(retention_days) * 86400

        deleted_total = 0
        async with get_db_connection(self._database_url) as conn:
            # Build list of candidate message ids that are older than cutoff
            # and are NOT referenced by episodes or protected by message_importance
            query = """
            SELECT id FROM messages m
            WHERE m.ts < $1
              AND NOT EXISTS (
                SELECT 1 FROM episodes e, jsonb_array_elements_text(e.message_ids::jsonb) je
                WHERE je::bigint = m.id LIMIT 1
              )
              AND NOT EXISTS (
                SELECT 1 FROM message_importance mi
                WHERE mi.message_id = m.id AND (mi.retention_days IS NOT NULL AND mi.retention_days > 0)
              )
            ORDER BY id ASC
            """
            params = (cutoff,)

            rows = await conn.fetch(query, *params)
            candidate_ids = [row["id"] for row in rows]

            if not candidate_ids:
                self._last_prune_ts = int(time.time())
                return 0

            # Delete in smaller chunks (100 instead of 500) with delays between chunks
            # to avoid blocking other database operations
            chunk_size = 100
            for chunk_idx, chunk in enumerate(_chunked(candidate_ids, chunk_size)):
                try:
                    placeholders = ",".join(f"${i+1}" for i in range(len(chunk)))

                    queries = [
                        f"DELETE FROM message_metadata WHERE message_id IN ({placeholders})",
                        f"DELETE FROM message_importance WHERE message_id IN ({placeholders})",
                        f"DELETE FROM messages WHERE id IN ({placeholders})"
                    ]

                    for q in queries:
                        await conn.execute(q, *chunk)

                    deleted_total += len(chunk)

                    # Add small delay between chunks to allow other operations to proceed
                    # Only delay if there are more chunks to process
                    if (
                        chunk_idx
                        < (len(candidate_ids) + chunk_size - 1) // chunk_size - 1
                    ):
                        await asyncio.sleep(0.05)  # 50ms delay between chunks
                except Exception as e:
                    logger.warning(
                        f"Pruning operation hit database lock or error, continuing with remaining chunks: {e}",
                        extra={"deleted_so_far": deleted_total},
                    )
                    # Continue with next chunk rather than failing completely
                    continue

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

        async with get_db_connection(self._database_url) as conn:
            # Drop very old windows (older than previous hour) to keep table small
            query, params = convert_query_to_postgres(
                "DELETE FROM rate_limits WHERE window_start < $1",
                (window_start - window_seconds,),
            )
            await conn.execute(query, *params)

            # Upsert current window counter
            query, params = convert_query_to_postgres(
                """
                SELECT request_count FROM rate_limits
                WHERE user_id = $1 AND window_start = $2
                """,
                (user_id, window_start),
            )
            row = await conn.fetchrow(query, *params)

            if row:
                query, params = convert_query_to_postgres(
                    """
                    UPDATE rate_limits
                    SET request_count = request_count + 1, last_seen = $1
                    WHERE user_id = $2 AND window_start = $3
                    """,
                    (current_ts, user_id, window_start),
                )
                await conn.execute(query, *params)
            else:
                query, params = convert_query_to_postgres(
                    """
                    INSERT INTO rate_limits (user_id, window_start, request_count, last_seen)
                    VALUES ($1, $2, 1, $3)
                    """,
                    (user_id, window_start, current_ts),
                )
                await conn.execute(query, *params)

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

        async with get_db_connection(self._database_url) as conn:
            query = """
                SELECT COALESCE(SUM(request_count), 0) as total
                FROM rate_limits
                WHERE user_id = $1 AND window_start >= $2
                """
            params = (user_id, cutoff - (cutoff % window_seconds))
            row = await conn.fetchrow(query, *params)
            if not row or row["total"] is None:
                return 0
            return int(row["total"])

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
        async with get_db_connection(self._database_url) as conn:
            result = await conn.execute("DELETE FROM rate_limits")
            deleted = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
            return deleted


async def run_retention_pruning_task(
    store: ContextStore,
    retention_days: int,
    prune_interval_seconds: int,
) -> None:
    """Background task for pruning old messages based on retention policy.

    This task runs periodically to remove messages older than the configured
    retention period. Includes CPU-aware throttling to avoid impacting performance.

    Args:
        store: The ContextStore instance to use for pruning
        retention_days: Number of days to retain messages
        prune_interval_seconds: Interval between pruning runs in seconds
    """
    logger = logging.getLogger(__name__)
    import psutil

    while True:
        try:
            # Check CPU usage before running
            try:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                if cpu_percent > 80:
                    logger.info(
                        f"Retention pruning: skipping run due to high CPU ({cpu_percent:.1f}%)"
                    )
                    await asyncio.sleep(prune_interval_seconds)
                    continue
            except Exception:
                # psutil not available or failed, continue anyway
                pass

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
