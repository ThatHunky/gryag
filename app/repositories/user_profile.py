"""User profile repository.

Handles data access for user profiles and facts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.exceptions import DatabaseError, UserProfileNotFoundError
from app.repositories.base import Repository


class UserProfile:
    """User profile entity.

    Represents a user's profile with facts and relationships.
    """

    def __init__(
        self,
        user_id: int,
        chat_id: int,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        first_seen: Optional[int] = None,  # Added to match schema
        last_seen: Optional[int] = None,  # Added to match schema
        created_at: Optional[int] = None,  # Changed to int (Unix timestamp)
        updated_at: Optional[int] = None,  # Changed to int (Unix timestamp)
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        now = int(datetime.now(timezone.utc).timestamp())
        self.first_seen = first_seen or now
        self.last_seen = last_seen or now
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class UserFact:
    """User fact entity.

    Represents a single fact about a user.
    """

    def __init__(
        self,
        id: Optional[int],  # Changed from fact_id to match schema
        user_id: int,
        chat_id: int,
        fact_type: str,  # Changed from category to match schema
        fact_key: str,  # Added to match schema
        fact_value: str,  # Changed from fact_text to match schema
        confidence: float,
        source_message_id: Optional[int] = None,
        evidence_text: Optional[str] = None,  # Added to match schema
        is_active: int = 1,  # Added to match schema
        created_at: Optional[int] = None,  # Changed to int (Unix timestamp)
        updated_at: Optional[int] = None,  # Changed to int (Unix timestamp)
        last_mentioned: Optional[int] = None,  # Added to match schema
    ):
        self.id = id
        self.user_id = user_id
        self.chat_id = chat_id
        self.fact_type = fact_type
        self.fact_key = fact_key
        self.fact_value = fact_value
        self.confidence = confidence
        self.source_message_id = source_message_id
        self.evidence_text = evidence_text
        self.is_active = is_active
        self.created_at = created_at or int(datetime.now(timezone.utc).timestamp())
        self.updated_at = updated_at or int(datetime.now(timezone.utc).timestamp())
        self.last_mentioned = last_mentioned

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "fact_type": self.fact_type,
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "confidence": self.confidence,
            "source_message_id": self.source_message_id,
            "evidence_text": self.evidence_text,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_mentioned": self.last_mentioned,
        }


class UserProfileRepository(Repository[UserProfile]):
    """Repository for user profiles.

    Provides data access methods for user profiles and facts.
    """

    async def find_by_id(self, user_id: int, chat_id: int) -> Optional[UserProfile]:
        """Find user profile by user_id and chat_id.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            UserProfile or None if not found
        """
        query = """
            SELECT user_id, chat_id, first_name, last_name, username,
                   first_seen, last_seen, created_at, updated_at
            FROM user_profiles
            WHERE user_id = ? AND chat_id = ?
        """
        row = await self._fetch_one(query, (user_id, chat_id))

        if not row:
            return None

        return UserProfile(
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def save(self, profile: UserProfile) -> UserProfile:
        """Save or update user profile.

        Args:
            profile: UserProfile to save

        Returns:
            Saved profile
        """
        now = int(datetime.now(timezone.utc).timestamp())
        query = """
            INSERT INTO user_profiles (
                user_id, chat_id, first_name, last_name, username,
                first_seen, last_seen, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
                last_seen = excluded.last_seen,
                updated_at = excluded.updated_at
        """
        await self._execute(
            query,
            (
                profile.user_id,
                profile.chat_id,
                profile.first_name,
                profile.last_name,
                profile.username,
                profile.first_seen,
                now,  # last_seen
                profile.created_at,
                now,  # updated_at
            ),
        )

        return profile

    async def delete(self, user_id: int, chat_id: int) -> bool:
        """Delete user profile.

        Args:
            user_id: User ID
            chat_id: Chat ID

        Returns:
            True if deleted, False if not found
        """
        query = "DELETE FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        cursor = await self._execute(query, (user_id, chat_id))
        return cursor.rowcount > 0

    async def get_facts(
        self, user_id: int, chat_id: int, fact_type: Optional[str] = None
    ) -> List[UserFact]:
        """Get facts for a user.

        Args:
            user_id: User ID
            chat_id: Chat ID
            fact_type: Optional fact type filter

        Returns:
            List of UserFact objects
        """
        if fact_type:
            query = """
                SELECT * FROM user_facts
                WHERE user_id = ? AND chat_id = ? AND fact_type = ?
                ORDER BY confidence DESC, created_at DESC
            """
            rows = await self._fetch_all(query, (user_id, chat_id, fact_type))
        else:
            query = """
                SELECT * FROM user_facts
                WHERE user_id = ? AND chat_id = ?
                ORDER BY confidence DESC, created_at DESC
            """
            rows = await self._fetch_all(query, (user_id, chat_id))

        facts = []
        for row in rows:
            facts.append(
                UserFact(
                    id=row["id"],
                    user_id=row["user_id"],
                    chat_id=row["chat_id"],
                    fact_type=row["fact_type"],
                    fact_key=row["fact_key"],
                    fact_value=row["fact_value"],
                    confidence=row["confidence"],
                    source_message_id=row["source_message_id"],
                    evidence_text=row["evidence_text"],
                    is_active=row["is_active"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    last_mentioned=row["last_mentioned"],
                )
            )
        return facts

    async def add_fact(self, fact: UserFact) -> UserFact:
        """Add a fact to user profile.

        Args:
            fact: UserFact to add

        Returns:
            Saved fact with generated id
        """
        query = """
            INSERT INTO user_facts (
                user_id, chat_id, fact_type, fact_key, fact_value, confidence,
                source_message_id, evidence_text, is_active, created_at, updated_at, last_mentioned
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self._execute(
            query,
            (
                fact.user_id,
                fact.chat_id,
                fact.fact_type,
                fact.fact_key,
                fact.fact_value,
                fact.confidence,
                fact.source_message_id,
                fact.evidence_text,
                fact.is_active,
                fact.created_at,
                fact.updated_at,
                fact.last_mentioned,
            ),
        )

        fact.id = cursor.lastrowid
        return fact

    async def update_fact(self, fact: UserFact) -> UserFact:
        """Update existing fact.

        Args:
            fact: UserFact to update

        Returns:
            Updated fact

        Raises:
            UserProfileNotFoundError: If fact doesn't exist
        """
        if not fact.id:
            raise ValueError("Fact must have id to update")

        query = """
            UPDATE user_facts
            SET fact_key = ?, fact_value = ?, confidence = ?, evidence_text = ?, 
                is_active = ?, updated_at = ?, last_mentioned = ?
            WHERE id = ?
        """
        cursor = await self._execute(
            query,
            (
                fact.fact_key,
                fact.fact_value,
                fact.confidence,
                fact.evidence_text,
                fact.is_active,
                int(datetime.now(timezone.utc).timestamp()),
                fact.last_mentioned,
                fact.id,
            ),
        )

        if cursor.rowcount == 0:
            raise UserProfileNotFoundError(
                "Fact not found",
                context={"id": fact.id},
            )

        return fact

    async def delete_fact(self, fact_id: int) -> bool:
        """Delete a fact.

        Args:
            fact_id: Fact ID to delete

        Returns:
            True if deleted, False if not found
        """
        query = "DELETE FROM user_facts WHERE id = ?"
        cursor = await self._execute(query, (fact_id,))
        return cursor.rowcount > 0
