"""Chat profile repository.

Handles data access for chat profiles and chat-level facts.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.repositories.base import Repository


@dataclass
class ChatProfile:
    """Chat profile entity."""

    chat_id: int
    chat_type: str
    chat_title: Optional[str] = None
    participant_count: int = 0
    bot_joined_at: Optional[int] = None
    last_active: Optional[int] = None
    culture_summary: Optional[str] = None
    profile_version: int = 1
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "chat_title": self.chat_title,
            "participant_count": self.participant_count,
            "bot_joined_at": self.bot_joined_at,
            "last_active": self.last_active,
            "culture_summary": self.culture_summary,
            "profile_version": self.profile_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ChatFact:
    """Chat fact entity."""

    fact_id: Optional[int]
    chat_id: int
    fact_category: str
    fact_key: str
    fact_value: str
    fact_description: Optional[str] = None
    confidence: float = 0.7
    evidence_count: int = 1
    first_observed: Optional[int] = None
    last_reinforced: Optional[int] = None
    participant_consensus: Optional[float] = None
    is_active: int = 1
    decay_rate: float = 0.0
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    evidence_text: Optional[str] = None  # Temporary field for extraction

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "fact_id": self.fact_id,
            "chat_id": self.chat_id,
            "fact_category": self.fact_category,
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "fact_description": self.fact_description,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "first_observed": self.first_observed,
            "last_reinforced": self.last_reinforced,
            "participant_consensus": self.participant_consensus,
            "is_active": self.is_active,
            "decay_rate": self.decay_rate,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ChatFact":
        """Create from database row."""
        return cls(
            fact_id=row.get("id"),
            chat_id=row["chat_id"],
            fact_category=row["fact_category"],
            fact_key=row["fact_key"],
            fact_value=row["fact_value"],
            fact_description=row.get("fact_description"),
            confidence=row.get("confidence", 0.7),
            evidence_count=row.get("evidence_count", 1),
            first_observed=row.get("first_observed"),
            last_reinforced=row.get("last_reinforced"),
            participant_consensus=row.get("participant_consensus"),
            is_active=row.get("is_active", 1),
            decay_rate=row.get("decay_rate", 0.0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


class ChatProfileRepository(Repository):
    """Repository for chat profiles and facts."""

    async def get_or_create_profile(
        self,
        chat_id: int,
        chat_type: str,
        chat_title: Optional[str] = None,
    ) -> ChatProfile:
        """Get or create chat profile.

        Args:
            chat_id: Chat ID
            chat_type: Type of chat (group, supergroup, channel)
            chat_title: Optional chat title

        Returns:
            ChatProfile
        """
        # Check if exists
        existing = await self._get_profile(chat_id)
        if existing:
            # Update last_active
            now = int(time.time())
            await self._execute(
                "UPDATE chat_profiles SET last_active = ?, updated_at = ? WHERE chat_id = ?",
                (now, now, chat_id),
            )
            existing.last_active = now
            existing.updated_at = now
            return existing

        # Create new
        now = int(time.time())
        await self._execute(
            """
            INSERT INTO chat_profiles 
            (chat_id, chat_type, chat_title, bot_joined_at, last_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, chat_type, chat_title, now, now, now, now),
        )

        return await self._get_profile(chat_id)

    async def _get_profile(self, chat_id: int) -> Optional[ChatProfile]:
        """Get chat profile by ID."""
        query = "SELECT * FROM chat_profiles WHERE chat_id = ?"
        row = await self._fetch_one(query, (chat_id,))

        if not row:
            return None

        # Convert Row to dict for .get() support
        row_dict = dict(row)

        return ChatProfile(
            chat_id=row_dict["chat_id"],
            chat_type=row_dict["chat_type"],
            chat_title=row_dict.get("chat_title"),
            participant_count=row_dict.get("participant_count", 0),
            bot_joined_at=row_dict.get("bot_joined_at"),
            last_active=row_dict.get("last_active"),
            culture_summary=row_dict.get("culture_summary"),
            profile_version=row_dict.get("profile_version", 1),
            created_at=row_dict.get("created_at"),
            updated_at=row_dict.get("updated_at"),
        )

    async def add_chat_fact(
        self,
        chat_id: int,
        category: str,
        fact_key: str,
        fact_value: str,
        fact_description: Optional[str] = None,
        confidence: float = 0.7,
        evidence_text: Optional[str] = None,
    ) -> int:
        """Add or update a chat fact.

        If fact with same key exists:
        - Same value: Reinforcement (boost confidence, update last_reinforced)
        - Different value: Evolution (create new version, deprecate old)

        Args:
            chat_id: Chat ID
            category: Fact category
            fact_key: Fact key
            fact_value: Fact value
            fact_description: Human-readable description
            confidence: Confidence score (0-1)
            evidence_text: Evidence for the fact

        Returns:
            Fact ID (new or updated)
        """
        # Check for existing fact with same key
        existing = await self._get_fact_by_key(chat_id, fact_key)

        now = int(time.time())

        if existing:
            # Check if same value (reinforcement)
            if existing["fact_value"] == fact_value:
                # Boost confidence (weighted average)
                new_confidence = min(
                    1.0, existing["confidence"] * 0.7 + confidence * 0.3
                )
                new_evidence_count = existing["evidence_count"] + 1

                await self._execute(
                    """
                    UPDATE chat_facts
                    SET confidence = ?,
                        evidence_count = ?,
                        last_reinforced = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (new_confidence, new_evidence_count, now, now, existing["id"]),
                )

                # Record version (reinforcement)
                await self._record_fact_version(
                    existing["id"],
                    None,
                    1,  # Version doesn't increment for reinforcement
                    "reinforcement",
                    confidence - existing["confidence"],
                    f"Reinforced with evidence: {evidence_text[:100] if evidence_text else 'N/A'}",
                )

                return existing["id"]

            else:
                # Different value - evolution
                # Deactivate old fact
                await self._execute(
                    "UPDATE chat_facts SET is_active = 0, updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )

                # Create new fact
                cursor = await self._execute(
                    """
                    INSERT INTO chat_facts
                    (chat_id, fact_category, fact_key, fact_value, fact_description,
                     confidence, evidence_count, first_observed, last_reinforced,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        category,
                        fact_key,
                        fact_value,
                        fact_description,
                        confidence,
                        now,
                        now,
                        now,
                        now,
                    ),
                )

                new_fact_id = cursor.lastrowid

                # Record version (evolution)
                await self._record_fact_version(
                    new_fact_id,
                    existing["id"],
                    2,  # New version
                    "evolution",
                    confidence - existing["confidence"],
                    f"Value changed from '{existing['fact_value']}' to '{fact_value}'",
                )

                return new_fact_id

        else:
            # New fact
            cursor = await self._execute(
                """
                INSERT INTO chat_facts
                (chat_id, fact_category, fact_key, fact_value, fact_description,
                 confidence, evidence_count, first_observed, last_reinforced,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    category,
                    fact_key,
                    fact_value,
                    fact_description,
                    confidence,
                    now,
                    now,
                    now,
                    now,
                ),
            )

            fact_id = cursor.lastrowid

            # Record version (creation)
            await self._record_fact_version(
                fact_id,
                None,
                1,
                "creation",
                confidence,
                f"Initial creation: {evidence_text[:100] if evidence_text else 'N/A'}",
            )

            return fact_id

    async def _get_fact_by_key(
        self, chat_id: int, fact_key: str
    ) -> Optional[Dict[str, Any]]:
        """Get active fact by key."""
        query = """
            SELECT * FROM chat_facts
            WHERE chat_id = ? AND fact_key = ? AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """
        return await self._fetch_one(query, (chat_id, fact_key))

    async def _record_fact_version(
        self,
        fact_id: int,
        previous_version_id: Optional[int],
        version_number: int,
        change_type: str,
        confidence_delta: float,
        change_evidence: str,
    ) -> None:
        """Record a fact version change."""
        now = int(time.time())
        await self._execute(
            """
            INSERT INTO chat_fact_versions
            (fact_id, previous_version_id, version_number, change_type,
             confidence_delta, change_evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                previous_version_id,
                version_number,
                change_type,
                confidence_delta,
                change_evidence,
                now,
            ),
        )

    async def get_top_chat_facts(
        self,
        chat_id: int,
        limit: int = 10,
        min_confidence: float = 0.6,
        categories: Optional[List[str]] = None,
    ) -> List[ChatFact]:
        """Get top chat facts for context inclusion.

        Ranking factors:
        - Confidence (higher = better)
        - Recency (last_reinforced closer to now = better)
        - Evidence count (more reinforcement = better)
        - Category priority (rules > preferences > norms)

        Args:
            chat_id: Chat ID
            limit: Maximum number of facts to return
            min_confidence: Minimum confidence threshold
            categories: Optional list of categories to filter

        Returns:
            List of ChatFact objects, ranked by relevance
        """
        # Category weights
        category_weights = {
            "rule": 1.5,
            "preference": 1.2,
            "tradition": 1.1,
            "culture": 1.0,
            "norm": 0.9,
            "topic": 0.8,
            "shared_knowledge": 0.7,
            "event": 0.6,
        }

        query = """
            SELECT * FROM chat_facts
            WHERE chat_id = ?
            AND is_active = 1
            AND confidence >= ?
        """
        params = [chat_id, min_confidence]

        if categories:
            placeholders = ",".join("?" * len(categories))
            query += f" AND fact_category IN ({placeholders})"
            params.extend(categories)

        query += " ORDER BY confidence DESC, last_reinforced DESC"

        rows = await self._fetch_all(query, tuple(params))

        # Apply scoring
        now = int(time.time())
        scored_facts = []

        for row in rows:
            # Base score from confidence
            score = row["confidence"]

            # Category weight
            category_weight = category_weights.get(row["fact_category"], 1.0)
            score *= category_weight

            # Temporal decay (half-life = 30 days for chat facts)
            age_seconds = now - row["last_reinforced"]
            age_days = age_seconds / 86400
            temporal_factor = math.exp(-age_days / 30)
            score *= 0.5 + 0.5 * temporal_factor  # Don't fully decay

            # Evidence count boost (more reinforcement = better)
            evidence_boost = min(1.5, 1.0 + (row["evidence_count"] - 1) * 0.1)
            score *= evidence_boost

            scored_facts.append((score, row))

        # Sort by final score
        scored_facts.sort(key=lambda x: x[0], reverse=True)

        # Return top facts
        return [ChatFact.from_row(dict(row)) for score, row in scored_facts[:limit]]

    async def get_chat_summary(
        self, chat_id: int, max_facts: int = 10
    ) -> Optional[str]:
        """Generate concise chat profile summary for context.

        Format:
        Chat Profile:
        - Preferences: [top 2-3]
        - Rules: [top 1-2]
        - Culture: [top 1-2]

        Args:
            chat_id: Chat ID
            max_facts: Maximum facts to include

        Returns:
            Formatted summary string or None if no facts
        """
        facts = await self.get_top_chat_facts(chat_id, limit=max_facts)

        if not facts:
            return None

        # Group by category
        by_category: Dict[str, List[ChatFact]] = {}
        for fact in facts:
            by_category.setdefault(fact.fact_category, []).append(fact)

        # Build summary
        summary_parts = ["Chat Profile:"]

        # Prioritize categories
        priority_categories = ["rule", "preference", "tradition", "culture", "norm"]

        for category in priority_categories:
            if category not in by_category:
                continue

            category_facts = by_category[category][:3]  # Top 3 per category

            if category_facts:
                category_label = category.replace("_", " ").title()
                fact_descriptions = [
                    f.fact_description or f"{f.fact_key}: {f.fact_value}"
                    for f in category_facts
                ]
                summary_parts.append(
                    f"- {category_label}: {', '.join(fact_descriptions)}"
                )

        return "\n".join(summary_parts)

    async def delete_all_facts(self, chat_id: int) -> int:
        """Delete all facts for a chat (admin command).

        Args:
            chat_id: Chat ID

        Returns:
            Number of facts deleted
        """
        cursor = await self._execute(
            "DELETE FROM chat_facts WHERE chat_id = ?", (chat_id,)
        )
        return cursor.rowcount

    async def get_all_facts(
        self, chat_id: int, include_inactive: bool = False
    ) -> List[ChatFact]:
        """Get all facts for a chat.

        Args:
            chat_id: Chat ID
            include_inactive: Include inactive facts

        Returns:
            List of all facts
        """
        query = "SELECT * FROM chat_facts WHERE chat_id = ?"
        params = [chat_id]

        if not include_inactive:
            query += " AND is_active = 1"

        query += " ORDER BY confidence DESC, created_at DESC"

        rows = await self._fetch_all(query, tuple(params))
        return [ChatFact.from_row(dict(row)) for row in rows]

    # Abstract method implementations (required by base Repository)
    async def find_by_id(self, id: int) -> Optional[ChatProfile]:
        """Find chat profile by ID.

        Args:
            id: Chat ID

        Returns:
            ChatProfile if found, None otherwise
        """
        return await self._get_profile(id)

    async def save(self, entity: ChatProfile) -> ChatProfile:
        """Save chat profile.

        Args:
            entity: ChatProfile to save

        Returns:
            Saved ChatProfile
        """
        return await self.get_or_create_profile(
            chat_id=entity.chat_id,
            chat_type=entity.chat_type,
            chat_title=entity.chat_title,
        )

    async def delete(self, id: int) -> bool:
        """Delete chat profile and all its facts.

        Args:
            id: Chat ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            # Delete all facts first
            await self._execute("DELETE FROM chat_facts WHERE chat_id = ?", (id,))

            # Delete profile
            await self._execute("DELETE FROM chat_profiles WHERE chat_id = ?", (id,))

            return True
        except Exception:
            return False
