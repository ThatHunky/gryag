"""User profiling system for learning about users over time."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

from app.services import telemetry

LOGGER = logging.getLogger(__name__)


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
                response = await self._gemini.generate(
                    history=[],
                    user_parts=[{"text": prompt}],
                    system_prompt="You are a fact extraction system. Return only valid JSON.",
                )

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
                except json.JSONDecodeError:
                    LOGGER.warning(
                        f"Failed to parse fact extraction JSON: {response_text[:200]}",
                        extra={"user_id": user_id},
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

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init(self) -> None:
        """Initialize database connection. Called automatically by other methods."""
        async with self._init_lock:
            if self._initialized:
                return
            # Schema is applied by ContextStore.init()

            # Add summary_updated_at column if missing (for Phase 2 summarization)
            async with aiosqlite.connect(self._db_path) as db:
                try:
                    await db.execute(
                        "ALTER TABLE user_profiles ADD COLUMN summary_updated_at INTEGER"
                    )
                    await db.commit()
                    LOGGER.info("Added summary_updated_at column to user_profiles")
                except aiosqlite.OperationalError:
                    # Column already exists
                    pass

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

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # Try to get existing profile
            async with db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                # Update last_seen and names if provided
                updates = ["last_seen = ?"]
                params: list[Any] = [now]

                if display_name:
                    updates.append("display_name = ?")
                    params.append(display_name)
                if username:
                    updates.append("username = ?")
                    params.append(username)

                params.extend([user_id, chat_id])

                await db.execute(
                    f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ? AND chat_id = ?",
                    params,
                )
                await db.commit()

                # Fetch updated row
                async with db.execute(
                    "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                    (user_id, chat_id),
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else {}

            # Create new profile
            await db.execute(
                """
                INSERT INTO user_profiles 
                (user_id, chat_id, display_name, username, first_seen, last_seen, 
                 interaction_count, message_count, profile_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1, ?, ?)
                """,
                (user_id, chat_id, display_name, username, now, now, now, now),
            )
            await db.commit()

            telemetry.increment_counter("profiles_created")
            LOGGER.info(
                f"Created profile for user {user_id} in chat {chat_id}",
                extra={"user_id": user_id, "chat_id": chat_id},
            )

            # Return the newly created profile
            async with db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}

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

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # If chat_id is None, aggregate across all chats for this user
            if chat_id is None:
                # Get user's most recent profile as base
                async with db.execute(
                    """
                    SELECT * FROM user_profiles 
                    WHERE user_id = ?
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    profile = dict(row)

                # Get facts across all chats
                query = """
                    SELECT * FROM user_facts 
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY confidence DESC, created_at DESC
                """
                params: list[Any] = [user_id]
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)

                async with db.execute(query, params) as cursor:
                    facts = [dict(row) for row in await cursor.fetchall()]

                profile["facts"] = facts
                return profile

            # Original behavior: get profile for specific chat
            async with db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

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

        updates = [f"{key} = ?" for key in kwargs.keys()]
        params = list(kwargs.values())
        params.extend([user_id, chat_id])

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ? AND chat_id = ?",
                params,
            )
            await db.commit()

        telemetry.increment_counter("profiles_updated")

    async def update_interaction_count(
        self, user_id: int, chat_id: int, thread_id: int | None = None
    ) -> None:
        """Increment interaction count and update last_seen."""
        await self.init()
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            updates = [
                "interaction_count = interaction_count + 1",
                "message_count = message_count + 1",
                "last_seen = ?",
            ]
            params: list[Any] = [now]

            if thread_id is not None:
                updates.append("last_active_thread = ?")
                params.append(thread_id)

            params.extend([user_id, chat_id])

            await db.execute(
                f"UPDATE user_profiles SET {', '.join(updates)} WHERE user_id = ? AND chat_id = ?",
                params,
            )
            await db.commit()

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
        """
        await self.init()
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            # Check if similar fact exists (same type and key)
            async with db.execute(
                """
                SELECT id, confidence, is_active 
                FROM user_facts 
                WHERE user_id = ? AND chat_id = ? AND fact_type = ? AND fact_key = ? 
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, chat_id, fact_type, fact_key),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                existing_id, existing_confidence, is_active = existing

                # If new confidence is higher or fact was inactive, update it
                if confidence > existing_confidence or not is_active:
                    await db.execute(
                        """
                        UPDATE user_facts 
                        SET fact_value = ?, confidence = ?, is_active = 1, 
                            updated_at = ?, last_mentioned = ?,
                            evidence_text = COALESCE(?, evidence_text)
                        WHERE id = ?
                        """,
                        (fact_value, confidence, now, now, evidence_text, existing_id),
                    )
                    await db.commit()
                    LOGGER.debug(
                        f"Updated fact {existing_id} for user {user_id}: {fact_key}={fact_value}",
                        extra={
                            "user_id": user_id,
                            "fact_id": existing_id,
                            "fact_type": fact_type,
                        },
                    )
                    return existing_id
                else:
                    # Just update last_mentioned
                    await db.execute(
                        "UPDATE user_facts SET last_mentioned = ? WHERE id = ?",
                        (now, existing_id),
                    )
                    await db.commit()
                    return existing_id

            # Insert new fact
            cursor = await db.execute(
                """
                INSERT INTO user_facts 
                (user_id, chat_id, fact_type, fact_key, fact_value, confidence, 
                 source_message_id, evidence_text, is_active, created_at, updated_at, last_mentioned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
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
                ),
            )
            fact_id = cursor.lastrowid
            await db.commit()

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
    ) -> list[dict[str, Any]]:
        """
        Get facts for a user.

        Can filter by fact_type and minimum confidence.
        Returns list of fact dicts sorted by confidence (descending).
        """
        await self.init()

        query = "SELECT * FROM user_facts WHERE user_id = ? AND chat_id = ?"
        params: list[Any] = [user_id, chat_id]

        if fact_type:
            query += " AND fact_type = ?"
            params.append(fact_type)

        if active_only:
            query += " AND is_active = 1"

        if min_confidence > 0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def deactivate_fact(self, fact_id: int) -> None:
        """Mark a fact as inactive (soft delete)."""
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE user_facts SET is_active = 0, updated_at = ? WHERE id = ?",
                (int(time.time()), fact_id),
            )
            await db.commit()

        LOGGER.info(f"Deactivated fact {fact_id}")

    async def delete_fact(self, fact_id: int) -> bool:
        """
        Permanently delete a fact.

        Returns True if fact was deleted, False if not found.
        """
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))
            deleted = cursor.rowcount or 0
            await db.commit()

        if deleted > 0:
            LOGGER.info(f"Deleted fact {fact_id}")
            return True

        return False

    async def record_relationship(
        self,
        user_id: int,
        chat_id: int,
        related_user_id: int,
        relationship_type: str = "unknown",
        relationship_label: str | None = None,
        strength: float = 0.5,
        sentiment: str = "neutral",
    ) -> None:
        """
        Record or update a relationship between users.

        Automatically increments interaction_count and updates last_interaction.
        """
        await self.init()
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            # Check if relationship exists
            async with db.execute(
                """
                SELECT id, interaction_count FROM user_relationships 
                WHERE user_id = ? AND chat_id = ? AND related_user_id = ?
                """,
                (user_id, chat_id, related_user_id),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                rel_id, current_count = existing
                await db.execute(
                    """
                    UPDATE user_relationships 
                    SET relationship_type = ?, relationship_label = COALESCE(?, relationship_label),
                        strength = ?, sentiment = ?, interaction_count = ?,
                        last_interaction = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        relationship_type,
                        relationship_label,
                        strength,
                        sentiment,
                        current_count + 1,
                        now,
                        now,
                        rel_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO user_relationships 
                    (user_id, chat_id, related_user_id, relationship_type, relationship_label,
                     strength, interaction_count, last_interaction, sentiment, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        chat_id,
                        related_user_id,
                        relationship_type,
                        relationship_label,
                        strength,
                        now,
                        sentiment,
                        now,
                        now,
                    ),
                )

            await db.commit()

    async def get_relationships(
        self, user_id: int, chat_id: int, min_strength: float = 0.0
    ) -> list[dict[str, Any]]:
        """Get relationships for a user, sorted by strength."""
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM user_relationships 
                WHERE user_id = ? AND chat_id = ? AND strength >= ?
                ORDER BY strength DESC, interaction_count DESC
                """,
                (user_id, chat_id, min_strength),
            ) as cursor:
                rows = await cursor.fetchall()
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

    async def delete_profile(self, user_id: int, chat_id: int) -> None:
        """
        Delete all profile data for a user in a chat.

        Cascades to facts and relationships due to foreign key constraints.
        """
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM user_profiles WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            )
            await db.commit()

        LOGGER.info(
            f"Deleted profile for user {user_id} in chat {chat_id}",
            extra={"user_id": user_id, "chat_id": chat_id},
        )

    async def prune_old_facts(self, retention_days: int) -> int:
        """Delete facts older than retention_days. Returns count deleted."""
        await self.init()
        cutoff = int(time.time()) - (retention_days * 86400)

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_facts WHERE created_at < ? AND is_active = 0",
                (cutoff,),
            )
            deleted = cursor.rowcount or 0
            await db.commit()

        if deleted > 0:
            LOGGER.info(
                f"Pruned {deleted} old facts (retention: {retention_days} days)"
            )

        return deleted

    async def get_fact_count(self, user_id: int, chat_id: int) -> int:
        """Get count of active facts for a user."""
        await self.init()

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM user_facts WHERE user_id = ? AND chat_id = ? AND is_active = 1",
                (user_id, chat_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def clear_user_facts(self, user_id: int, chat_id: int) -> int:
        """
        Mark all facts for a user as inactive (soft delete).

        Returns count of facts cleared.
        """
        await self.init()
        now = int(time.time())

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE user_facts 
                SET is_active = 0, updated_at = ?
                WHERE user_id = ? AND chat_id = ? AND is_active = 1
                """,
                (now, user_id, chat_id),
            )
            count = cursor.rowcount or 0
            await db.commit()

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

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
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
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

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

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE user_profiles 
                SET summary = ?, summary_updated_at = ?
                WHERE user_id = ?
                """,
                (summary, now, user_id),
            )
            await db.commit()

        LOGGER.info(
            f"Updated summary for user {user_id}",
            extra={"user_id": user_id, "summary_length": len(summary)},
        )
        telemetry.increment_counter("profile_summaries_updated")
