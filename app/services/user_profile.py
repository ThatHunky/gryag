"""User profiling system for learning about users over time."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import asyncpg

from app.infrastructure.db_utils import get_db_connection
from app.services import telemetry

LOGGER = logging.getLogger(__name__)


def _coerce_timestamp(value: Any) -> int | None:
    """Convert timestamp-like values to integer seconds."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _augment_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Ensure derived fields and normalized values on profile dict."""
    result = dict(profile)
    result["membership_status"] = result.get("membership_status") or "unknown"

    created_at = _coerce_timestamp(result.get("created_at"))
    if created_at is not None:
        result["created_at"] = created_at

    last_seen = _coerce_timestamp(result.get("last_seen"))
    if last_seen is not None:
        result["last_seen"] = last_seen

    # Provide backward-compatible alias for handlers
    result.setdefault("last_interaction_at", result.get("last_seen"))

    return result


FACT_EXTRACTION_PROMPT = """Analyze the following conversation and extract facts about the user.

Focus on:
- Personal information (location, job, age, hobbies, interests)
- Preferences (likes, dislikes, favorites)
- Personality traits and communication style
- Skills, abilities, languages spoken
- Opinions on topics
- Relationships with other users mentioned

Rules:
- Only extract clear, verifiable facts
- Be conservative - don't speculate or infer too much
- Assign confidence scores: 1.0 (certain), 0.9 (very confident), 0.8 (confident), 0.7 (somewhat confident)
- Don't extract facts below 0.7 confidence
- Include a short quote as evidence for each fact
- Use standardized fact_key names (e.g., "location", "profession", "hobby", "language", "favorite_food")

Return JSON with this structure:
{{
  "facts": [
    {{
      "fact_type": "personal|preference|trait|skill|opinion",
      "fact_key": "standardized_key",
      "fact_value": "the actual fact",
      "confidence": 0.7-1.0,
      "evidence": "quote supporting this"
    }}
  ]
}}

Conversation context:
{context}

Current message from user @{username} (ID: {user_id}):
{message}

Extract facts as JSON:"""


class FactExtractor:
    """Extracts user facts from conversations using Gemini."""

    def __init__(self, gemini_client: Any) -> None:
        self._gemini = gemini_client
        self._extraction_semaphore = asyncio.Semaphore(
            2
        )  # Limit concurrent extractions

    async def extract_user_facts(
        self,
        message: str,
        user_id: int,
        username: str | None,
        context: list[dict[str, Any]] | None = None,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Extract facts from a user's message and conversation context.

        Returns list of fact dicts ready to be stored.
        """
        async with self._extraction_semaphore:
            try:
                # Format context
                context_str = ""
                if context:
                    for turn in context[-5:]:  # Last 5 turns for context
                        role = turn.get("role", "")
                        parts = turn.get("parts", [])
                        if parts and isinstance(parts, list):
                            for part in parts:
                                if isinstance(part, dict) and "text" in part:
                                    text = part["text"]
                                    if not text.startswith("[meta]"):
                                        context_str += f"{role}: {text}\n"

                # Build prompt
                prompt = FACT_EXTRACTION_PROMPT.format(
                    context=context_str or "(no prior context)",
                    username=username or f"user_{user_id}",
                    user_id=user_id,
                    message=message,
                )

                # Call Gemini
                response_data = await self._gemini.generate(
                    history=[],
                    user_parts=[{"text": prompt}],
                    system_prompt="You are a fact extraction system. Return only valid JSON.",
                )

                response = response_data.get("text", "")
                if not response:
                    return []

                # Parse JSON response
                # Try to extract JSON from response
                response_text = response.strip()

                # Remove markdown code blocks if present
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    response_text = (
                        "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
                    )
                    if response_text.startswith("json"):
                        response_text = response_text[4:].strip()

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    LOGGER.warning(
                        "Failed to parse fact extraction JSON from Gemini",
                        extra={
                            "user_id": user_id,
                            "error": str(e),
                            "error_position": e.pos,
                            "response_preview": response_text[:500],
                        },
                    )
                    LOGGER.debug(
                        f"Full Gemini response for fact extraction (user {user_id}): {response_text}",
                        extra={
                            "user_id": user_id,
                            "message_preview": message[:100],
                            "full_response": response_text,
                        },
                    )
                    telemetry.increment_counter("fact_extraction_errors")
                    return []

                # Validate and filter facts
                facts = data.get("facts", [])
                if not isinstance(facts, list):
                    return []

                valid_facts = []
                for fact in facts:
                    if not isinstance(fact, dict):
                        continue

                    # Check required fields
                    if not all(
                        k in fact
                        for k in ["fact_type", "fact_key", "fact_value", "confidence"]
                    ):
                        continue

                    # Validate fact_type
                    if fact["fact_type"] not in [
                        "personal",
                        "preference",
                        "trait",
                        "skill",
                        "opinion",
                    ]:
                        continue

                    # Filter by confidence
                    confidence = float(fact["confidence"])
                    if confidence < min_confidence:
                        continue

                    valid_facts.append(
                        {
                            "fact_type": fact["fact_type"],
                            "fact_key": fact["fact_key"],
                            "fact_value": fact["fact_value"],
                            "confidence": confidence,
                            "evidence_text": fact.get("evidence", ""),
                        }
                    )

                LOGGER.debug(
                    f"Extracted {len(valid_facts)} facts for user {user_id}",
                    extra={"user_id": user_id, "fact_count": len(valid_facts)},
                )

                return valid_facts

            except Exception as e:
                LOGGER.error(
                    f"Fact extraction failed for user {user_id}: {e}",
                    extra={"user_id": user_id, "error": str(e)},
                    exc_info=True,
                )
                telemetry.increment_counter("fact_extraction_errors")
                return []


class UserProfileStore:
    """Manages user profiles, facts, and relationships."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init(self) -> None:
        """Initialize database connection. Called automatically by other methods."""
        async with self._init_lock:
            if self._initialized:
                return
            # Schema is applied by ContextStore.init()

            # Add summary_updated_at column if missing (for Phase 2 summarization)
            async with get_db_connection(self._database_url) as conn:
                try:
                    await conn.execute(
                        "ALTER TABLE user_profiles ADD COLUMN summary_updated_at INTEGER"
                    )
                    LOGGER.info("Added summary_updated_at column to user_profiles")
                except (asyncpg.DuplicateColumnError, asyncpg.UndefinedColumnError):
                    pass
                except asyncpg.PostgresError as e:
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        pass
                    else:
                        raise

                try:
                    await conn.execute(
                        "ALTER TABLE user_profiles ADD COLUMN pronouns TEXT"
                    )
                    LOGGER.info("Added pronouns column to user_profiles")
                except (asyncpg.DuplicateColumnError, asyncpg.UndefinedColumnError):
                    pass
                except asyncpg.PostgresError as e:
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        pass
                    else:
                        raise

                try:
                    await conn.execute(
                        "ALTER TABLE user_profiles ADD COLUMN membership_status TEXT DEFAULT 'unknown'"
                    )
                    LOGGER.info("Added membership_status column to user_profiles")
                except (asyncpg.DuplicateColumnError, asyncpg.UndefinedColumnError):
                    pass
                except asyncpg.PostgresError as e:
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        pass
                    else:
                        raise

            self._initialized = True

    async def get_or_create_profile(
        self,
        user_id: int,
        chat_id: int,
        display_name: str | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """
        Get existing profile or create a new one.

        Returns profile dict with all fields.
        """
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            # Try to get existing profile
            row = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2",
                user_id,
                chat_id,
            )

            if row:
                # Update last_seen, membership, and optional names
                updates = [
                    "last_seen = $1",
                    "updated_at = $2",
                    "membership_status = $3",
                ]
                params: list[Any] = [now, now, "member"]

                param_idx = 4
                if display_name:
                    updates.append(f"display_name = ${param_idx}")
                    params.append(display_name)
                    param_idx += 1
                if username:
                    updates.append(f"username = ${param_idx}")
                    params.append(username)
                    param_idx += 1

                params.extend([user_id, chat_id])
                where_param_idx = param_idx

                await conn.execute(
                    f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}",
                    *params,
                )

                # Fetch updated row
                row = await conn.fetchrow(
                    "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2",
                    user_id,
                    chat_id,
                )
                return _augment_profile(dict(row)) if row else {}

            # Create new profile
            row = await conn.fetchrow(
                """
                INSERT INTO user_profiles
                (user_id, chat_id, display_name, username, pronouns, membership_status, first_seen, last_seen,
                 interaction_count, message_count, profile_version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, 0, 1, $9, $10)
                RETURNING *
                """,
                user_id,
                chat_id,
                display_name,
                username,
                None,
                "member",
                now,
                now,
                now,
                now,
            )

            telemetry.increment_counter("profiles_created")
            LOGGER.info(
                f"Created profile for user {user_id} in chat {chat_id}",
                extra={"user_id": user_id, "chat_id": chat_id},
            )

            return _augment_profile(dict(row)) if row else {}

    async def get_profile(
        self, user_id: int, chat_id: int | None = None, limit: int | None = None
    ) -> dict[str, Any] | None:
        """Get profile for a user in a chat, or None if not exists.

        Args:
            user_id: Telegram user ID
            chat_id: Chat ID (optional for summarization which aggregates across chats)
            limit: Max number of facts to include (for memory optimization)

        Returns:
            Profile dict with metadata and facts, or None if not found
        """
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            # If chat_id is None, aggregate across all chats for this user
            if chat_id is None:
                # Get user's most recent profile as base
                row = await conn.fetchrow(
                    """
                    SELECT * FROM user_profiles
                    WHERE user_id = $1
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    user_id,
                )
                if not row:
                    return None
                profile = _augment_profile(dict(row))

                # Get facts across all chats
                query = """
                    SELECT * FROM user_facts
                    WHERE user_id = $1 AND is_active = 1
                    ORDER BY confidence DESC, created_at DESC
                """
                params: list[Any] = [user_id]
                if limit:
                    query += " LIMIT $2"
                    params.append(limit)

                rows = await conn.fetch(query, *params)
                facts = [dict(row) for row in rows]

                profile["facts"] = facts
                return profile

            # Original behavior: get profile for specific chat
            row = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE user_id = $1 AND chat_id = $2",
                user_id,
                chat_id,
            )
            return _augment_profile(dict(row)) if row else None

    async def update_profile(self, user_id: int, chat_id: int, **kwargs: Any) -> None:
        """
        Update profile fields.

        Accepts any profile field as keyword argument.
        Always updates updated_at timestamp.
        """
        await self.init()

        if not kwargs:
            return

        now = int(time.time())
        kwargs["updated_at"] = now

        updates = []
        params = []
        for idx, (key, value) in enumerate(kwargs.items(), start=1):
            updates.append(f"{key} = ${idx}")
            params.append(value)

        params.extend([user_id, chat_id])
        where_param_idx = len(kwargs) + 1

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}",
                *params,
            )

        telemetry.increment_counter("profiles_updated")

    async def update_interaction_count(
        self, user_id: int, chat_id: int, thread_id: int | None = None
    ) -> None:
        """Increment interaction count and update last_seen."""
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            updates = [
                "interaction_count = interaction_count + 1",
                "message_count = message_count + 1",
                "last_seen = $1",
                "updated_at = $2",
                "membership_status = 'member'",
            ]
            params: list[Any] = [now, now]
            param_idx = 3

            if thread_id is not None:
                updates.append(f"last_active_thread = ${param_idx}")
                params.append(thread_id)
                param_idx += 1

            params.extend([user_id, chat_id])
            where_param_idx = param_idx

            await conn.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ${where_param_idx} AND chat_id = ${where_param_idx + 1}",
                *params,
            )

    async def list_chat_users(
        self,
        chat_id: int,
        limit: int | None = None,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        """Return users known in a chat ordered by activity."""
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            query = """
                SELECT user_id, display_name, username, pronouns, membership_status,
                       interaction_count, message_count, last_seen, created_at, updated_at
                FROM user_profiles
                WHERE chat_id = $1
            """
            params: list[Any] = [chat_id]

            if not include_inactive:
                query += (
                    " AND membership_status IN ('member', 'administrator', 'creator')"
                )

            query += """
                ORDER BY
                    CASE membership_status
                        WHEN 'member' THEN 0
                        WHEN 'administrator' THEN 0
                        WHEN 'creator' THEN 0
                        ELSE 1
                    END,
                    last_seen DESC
            """

            if limit:
                query += " LIMIT $2"
                params.append(limit)

            rows = await conn.fetch(query, *params)
            return [_augment_profile(dict(row)) for row in rows]

    async def add_fact(
        self,
        user_id: int,
        chat_id: int,
        fact_type: str,
        fact_key: str,
        fact_value: str,
        confidence: float = 1.0,
        source_message_id: int | None = None,
        evidence_text: str | None = None,
    ) -> int:
        """
        Add a new fact about a user.

        Returns the fact ID.
        Checks for similar existing facts and updates if found.
        Records fact versions for tracking changes over time.
        """
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            # Check if similar fact exists (same type and key)
            existing = await conn.fetchrow(
                """
                SELECT id, confidence, is_active, fact_value
                FROM user_facts
                WHERE user_id = $1 AND chat_id = $2 AND fact_type = $3 AND fact_key = $4
                ORDER BY created_at DESC LIMIT 1
                """,
                user_id, chat_id, fact_type, fact_key,
            )

            if existing:
                existing_id = existing["id"]
                existing_confidence = existing["confidence"]
                is_active = existing["is_active"]
                existing_value = existing["fact_value"]

                # Determine change type and whether to update
                value_changed = existing_value != fact_value
                confidence_changed = abs(confidence - existing_confidence) > 0.01

                # If new confidence is higher or fact was inactive, update it
                if confidence > existing_confidence or not is_active:
                    # Get current version count
                    row = await conn.fetchrow(
                        "SELECT COALESCE(MAX(version_number), 0) as ver FROM fact_versions WHERE fact_id = $1",
                        existing_id,
                    )
                    current_version = row["ver"] if row else 0

                    # Determine change type
                    if not is_active:
                        change_type = "correction"
                    elif value_changed:
                        change_type = (
                            "evolution"
                            if confidence > existing_confidence
                            else "correction"
                        )
                    elif confidence_changed:
                        change_type = "reinforcement"
                    else:
                        change_type = "reinforcement"

                    # Update fact
                    await conn.execute(
                        """
                        UPDATE user_facts
                        SET fact_value = $1, confidence = $2, is_active = 1,
                            updated_at = $3, last_mentioned = $4,
                            evidence_text = COALESCE($5, evidence_text)
                        WHERE id = $6
                        """,
                        fact_value, confidence, now, now, evidence_text, existing_id,
                    )

                    # Record version
                    await conn.execute(
                        """
                        INSERT INTO fact_versions
                        (fact_id, version_number, change_type, confidence_delta, created_at)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        existing_id,
                        current_version + 1,
                        change_type,
                        confidence - existing_confidence,
                        now,
                    )

                    LOGGER.debug(
                        f"Updated fact {existing_id} for user {user_id}: {fact_key}={fact_value} ({change_type})",
                        extra={
                            "user_id": user_id,
                            "fact_id": existing_id,
                            "fact_type": fact_type,
                            "change_type": change_type,
                        },
                    )
                    return existing_id
                else:
                    # Just update last_mentioned and record reinforcement
                    await conn.execute(
                        "UPDATE user_facts SET last_mentioned = $1 WHERE id = $2",
                        now, existing_id,
                    )

                    # Get current version count for reinforcement record
                    row = await conn.fetchrow(
                        "SELECT COALESCE(MAX(version_number), 0) as ver FROM fact_versions WHERE fact_id = $1",
                        existing_id,
                    )
                    current_version = row["ver"] if row else 0

                    # Record reinforcement
                    await conn.execute(
                        """
                        INSERT INTO fact_versions
                        (fact_id, version_number, change_type, confidence_delta, created_at)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        existing_id, current_version + 1, "reinforcement", 0.0, now,
                    )

                    return existing_id

            # Insert new fact
            fact_id = await conn.fetchval(
                """
                INSERT INTO user_facts
                (user_id, chat_id, fact_type, fact_key, fact_value, confidence,
                 source_message_id, evidence_text, is_active, created_at, updated_at, last_mentioned)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, $9, $10, $11)
                RETURNING id
                """,
                user_id,
                chat_id,
                fact_type,
                fact_key,
                fact_value,
                confidence,
                source_message_id,
                evidence_text,
                now,
                now,
                now,
            )

            # Record initial version
            await conn.execute(
                """
                INSERT INTO fact_versions
                (fact_id, version_number, change_type, confidence_delta, created_at)
                VALUES ($1, 1, 'creation', $2, $3)
                """,
                fact_id, confidence, now,
            )

            telemetry.increment_counter("facts_extracted")
            LOGGER.debug(
                f"Added fact {fact_id} for user {user_id}: {fact_key}={fact_value}",
                extra={
                    "user_id": user_id,
                    "fact_id": fact_id,
                    "fact_type": fact_type,
                    "confidence": confidence,
                },
            )

            return fact_id or 0

    async def get_facts(
        self,
        user_id: int,
        chat_id: int,
        fact_type: str | None = None,
        min_confidence: float = 0.0,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get facts for a user.

        DEPRECATED: user_facts table has been replaced with user_memories.
        This method now returns an empty list for compatibility.
        Use get_memories() for the new memory system.
        """
        await self.init()

        # Check if user_facts table exists (for backward compatibility)
        async with get_db_connection(self._database_url) as conn:
            try:
                # Check table existence in Postgres
                row = await conn.fetchrow(
                    "SELECT to_regclass('public.user_facts')"
                )
                if not row or not row[0]:
                    return []

                # Table exists, proceed with original query
                query = "SELECT * FROM user_facts WHERE user_id = $1 AND chat_id = $2"
                params: list[Any] = [user_id, chat_id]
                param_idx = 3

                if fact_type:
                    query += f" AND fact_type = ${param_idx}"
                    params.append(fact_type)
                    param_idx += 1

                if active_only:
                    query += " AND is_active = 1"

                if min_confidence > 0:
                    query += f" AND confidence >= ${param_idx}"
                    params.append(min_confidence)
                    param_idx += 1

                query += f" ORDER BY confidence DESC, updated_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
                params.append(limit)
                params.append(offset)

                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
            except Exception as e:
                LOGGER.error(
                    f"Unexpected error fetching facts (deprecated): {e}", exc_info=True
                )
                return []

    async def deactivate_fact(self, fact_id: int) -> None:
        """Mark a fact as inactive (soft delete).

        DEPRECATED: user_facts table has been replaced with user_memories.
        """
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            try:
                await conn.execute(
                    "UPDATE user_facts SET is_active = 0, updated_at = $1 WHERE id = $2",
                    int(time.time()), fact_id
                )
            except Exception as e:
                LOGGER.warning(
                    f"Database error deactivating fact {fact_id}: {e}", exc_info=True
                )

    async def delete_fact(self, fact_id: int) -> bool:
        """
        Permanently delete a fact.

        DEPRECATED: user_facts table has been replaced with user_memories.

        Returns True if fact was deleted, False if not found.
        """
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            try:
                status = await conn.execute(
                    "DELETE FROM user_facts WHERE id = $1",
                    fact_id
                )
                # status is like "DELETE 1"
                return status != "DELETE 0"
            except Exception as e:
                LOGGER.error(
                    f"Error deleting fact {fact_id}: {e}", exc_info=True
                )
                return False

    async def record_relationship(
        self,
        user_id: int,
        chat_id: int,
        related_user_id: int,
        relationship_type: str = "unknown",
        relationship_label: str | None = None,
    ) -> None:
        """Record a relationship between two users."""
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            # Check if relationship exists
            row = await conn.fetchrow(
                """
                SELECT id FROM user_relationships
                WHERE user_id = $1 AND related_user_id = $2 AND chat_id = $3
                """,
                user_id, related_user_id, chat_id,
            )

            if row:
                # Update existing
                await conn.execute(
                    """
                    UPDATE user_relationships
                    SET relationship_type = $1, relationship_label = $2,
                        updated_at = $3, interaction_count = interaction_count + 1
                    WHERE id = $4
                    """,
                    relationship_type, relationship_label, now, row["id"],
                )
            else:
                # Create new
                await conn.execute(
                    """
                    INSERT INTO user_relationships
                    (user_id, related_user_id, chat_id, relationship_type, relationship_label,
                     interaction_count, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, 1, $6, $7)
                    """,
                    user_id,
                    related_user_id,
                    chat_id,
                    relationship_type,
                    relationship_label,
                    now,
                    now,
                )

    async def get_relationships(
        self, user_id: int, chat_id: int, min_strength: float = 0.0
    ) -> list[dict[str, Any]]:
        """Get relationships for a user."""
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM user_relationships
                WHERE user_id = $1 AND chat_id = $2 AND strength >= $3
                ORDER BY strength DESC, interaction_count DESC
                """,
                user_id, chat_id, min_strength,
            )
            return [dict(row) for row in rows]

    async def get_user_summary(
        self,
        user_id: int,
        chat_id: int,
        include_facts: bool = True,
        include_relationships: bool = True,
        min_confidence: float = 0.7,
        max_facts: int = 10,
    ) -> str:
        """
        Generate a compact text summary of a user profile.

        Format: "@username (Name): Summary. Facts: key=value, ... Relationships: label, ..."
        """
        await self.init()

        profile = await self.get_profile(user_id, chat_id)
        if not profile:
            return f"User #{user_id} (no profile)"

        parts = []

        # Basic info
        username = profile.get("username") or ""
        display_name = profile.get("display_name") or ""
        if username and display_name:
            parts.append(f"{username} ({display_name})")
        elif username:
            parts.append(username)
        elif display_name:
            parts.append(display_name)
        else:
            parts.append(f"User #{user_id}")

        pronouns = (profile.get("pronouns") or "").strip()
        if pronouns:
            parts.append(f" [{pronouns}]")

        # Summary
        summary = profile.get("summary")
        if summary:
            parts.append(f": {summary}")

        # Facts
        if include_facts:
            facts = await self.get_facts(
                user_id, chat_id, min_confidence=min_confidence, limit=max_facts
            )
            if facts:
                fact_strs = [
                    f"{f['fact_key']}={f['fact_value']}" for f in facts[:max_facts]
                ]
                parts.append(f". Facts: {', '.join(fact_strs)}")

        # Relationships
        if include_relationships:
            relationships = await self.get_relationships(
                user_id, chat_id, min_strength=0.5
            )
            if relationships:
                rel_strs = []
                for rel in relationships[:5]:  # Max 5 relationships
                    label = rel.get("relationship_label") or rel.get(
                        "relationship_type"
                    )
                    rel_strs.append(f"{label} with user #{rel['related_user_id']}")
                if rel_strs:
                    parts.append(f". Relationships: {', '.join(rel_strs)}")

        return "".join(parts)

    async def update_pronouns(
        self, user_id: int, chat_id: int, pronouns: str | None
    ) -> None:
        """Set or clear pronouns for a user profile."""
        await self.init()
        await self.get_or_create_profile(user_id, chat_id)

        normalized = pronouns.strip() if pronouns else None
        if normalized == "":
            normalized = None

        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(
                """
                UPDATE user_profiles
                SET pronouns = $1, updated_at = $2
                WHERE user_id = $3 AND chat_id = $4
                """,
                normalized, now, user_id, chat_id,
            )

        telemetry.increment_counter("profiles_updated")

    async def delete_profile(self, user_id: int, chat_id: int) -> None:
        """
        Delete all profile data for a user in a chat.

        Cascades to facts and relationships due to foreign key constraints.
        """
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(
                "DELETE FROM user_profiles WHERE user_id = $1 AND chat_id = $2",
                user_id, chat_id,
            )

        LOGGER.info(
            f"Deleted profile for user {user_id} in chat {chat_id}",
            extra={"user_id": user_id, "chat_id": chat_id},
        )

    async def prune_old_facts(self, retention_days: int) -> int:
        """Delete facts older than retention_days. Returns count deleted."""
        await self.init()
        cutoff = int(time.time()) - (retention_days * 86400)

        async with get_db_connection(self._database_url) as conn:
            status = await conn.execute(
                "DELETE FROM user_facts WHERE created_at < $1 AND is_active = 0",
                cutoff,
            )
            # status is like "DELETE 5"
            try:
                deleted = int(status.split()[1])
            except (IndexError, ValueError):
                deleted = 0

        if deleted > 0:
            LOGGER.info(
                f"Pruned {deleted} old facts (retention: {retention_days} days)"
            )

        return deleted

    async def get_fact_count(self, user_id: int, chat_id: int) -> int:
        """Get count of active facts for a user."""
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_facts WHERE user_id = $1 AND chat_id = $2 AND is_active = 1",
                user_id, chat_id,
            )
            return count or 0

    async def clear_user_facts(self, user_id: int, chat_id: int) -> int:
        """
        Mark all facts for a user as inactive (soft delete).

        Returns count of facts cleared.
        """
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            status = await conn.execute(
                """
                UPDATE user_facts
                SET is_active = 0, updated_at = $1
                WHERE user_id = $2 AND chat_id = $3 AND is_active = 1
                """,
                now, user_id, chat_id,
            )
            # status is like "UPDATE 5"
            try:
                count = int(status.split()[1])
            except (IndexError, ValueError):
                count = 0

        if count > 0:
            LOGGER.info(
                f"Cleared {count} facts for user {user_id} in chat {chat_id}",
                extra={"user_id": user_id, "chat_id": chat_id, "count": count},
            )

        return count

    async def get_profiles_needing_summarization(self, limit: int = 50) -> list[int]:
        """Get list of user IDs whose profiles need summarization.

        Profiles need summarization if:
        - They have active facts
        - Summary is NULL or last_seen > summary_updated_at (profile changed)
        - Ordered by message_count DESC (most active users first)

        Args:
            limit: Maximum number of profiles to return

        Returns:
            List of user IDs needing summarization
        """
        await self.init()

        async with get_db_connection(self._database_url) as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT p.user_id
                FROM user_profiles p
                WHERE EXISTS (
                    SELECT 1 FROM user_facts f
                    WHERE f.user_id = p.user_id AND f.is_active = 1
                )
                AND (
                    p.summary IS NULL
                    OR p.last_seen > COALESCE(p.summary_updated_at, 0)
                )
                ORDER BY p.message_count DESC
                LIMIT $1
                """,
                limit,
            )
            return [row["user_id"] for row in rows]

    async def update_summary(self, user_id: int, summary: str) -> None:
        """Update the summary for a user's profile.

        Updates all profiles for this user across all chats to keep them in sync.
        Sets summary_updated_at to current timestamp.

        Args:
            user_id: Telegram user ID
            summary: Generated summary text
        """
        await self.init()
        now = int(time.time())

        async with get_db_connection(self._database_url) as conn:
            await conn.execute(
                """
                UPDATE user_profiles
                SET summary = $1, summary_updated_at = $2
                WHERE user_id = $3
                """,
                summary, now, user_id,
            )

        LOGGER.info(
            f"Updated summary for user {user_id}",
            extra={"user_id": user_id, "summary_length": len(summary)},
        )
        telemetry.increment_counter("profile_summaries_updated")
