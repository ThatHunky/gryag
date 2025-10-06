"""User profile repository.

Handles data access for user profiles and facts.
"""

from __future__ import annotations

import json
from datetime import datetime
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
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserFact:
    """User fact entity.

    Represents a single fact about a user.
    """

    def __init__(
        self,
        fact_id: Optional[int],
        user_id: int,
        chat_id: int,
        category: str,
        fact_text: str,
        confidence: float,
        source_message_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.fact_id = fact_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.category = category
        self.fact_text = fact_text
        self.confidence = confidence
        self.source_message_id = source_message_id
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "fact_id": self.fact_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "category": self.category,
            "fact_text": self.fact_text,
            "confidence": self.confidence,
            "source_message_id": self.source_message_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
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
                   created_at, updated_at
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
            created_at=(
                datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
            ),
            updated_at=(
                datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
            ),
        )

    async def save(self, profile: UserProfile) -> UserProfile:
        """Save or update user profile.

        Args:
            profile: UserProfile to save

        Returns:
            Saved profile
        """
        query = """
            INSERT INTO user_profiles (
                user_id, chat_id, first_name, last_name, username,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
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
                profile.created_at.isoformat(),
                datetime.utcnow().isoformat(),
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
        self, user_id: int, chat_id: int, category: Optional[str] = None
    ) -> List[UserFact]:
        """Get facts for a user.

        Args:
            user_id: User ID
            chat_id: Chat ID
            category: Optional category filter

        Returns:
            List of UserFact objects
        """
        if category:
            query = """
                SELECT * FROM user_facts
                WHERE user_id = ? AND chat_id = ? AND category = ?
                ORDER BY confidence DESC, created_at DESC
            """
            rows = await self._fetch_all(query, (user_id, chat_id, category))
        else:
            query = """
                SELECT * FROM user_facts
                WHERE user_id = ? AND chat_id = ?
                ORDER BY confidence DESC, created_at DESC
            """
            rows = await self._fetch_all(query, (user_id, chat_id))

        facts = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
            facts.append(
                UserFact(
                    fact_id=row["fact_id"],
                    user_id=row["user_id"],
                    chat_id=row["chat_id"],
                    category=row["category"],
                    fact_text=row["fact_text"],
                    confidence=row["confidence"],
                    source_message_id=row.get("source_message_id"),
                    created_at=(
                        datetime.fromisoformat(row["created_at"])
                        if row["created_at"]
                        else None
                    ),
                    updated_at=(
                        datetime.fromisoformat(row["updated_at"])
                        if row["updated_at"]
                        else None
                    ),
                    metadata=metadata,
                )
            )
        return facts

    async def add_fact(self, fact: UserFact) -> UserFact:
        """Add a fact to user profile.

        Args:
            fact: UserFact to add

        Returns:
            Saved fact with generated fact_id
        """
        query = """
            INSERT INTO user_facts (
                user_id, chat_id, category, fact_text, confidence,
                source_message_id, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self._execute(
            query,
            (
                fact.user_id,
                fact.chat_id,
                fact.category,
                fact.fact_text,
                fact.confidence,
                fact.source_message_id,
                fact.created_at.isoformat(),
                fact.updated_at.isoformat(),
                json.dumps(fact.metadata) if fact.metadata else "{}",
            ),
        )

        fact.fact_id = cursor.lastrowid
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
        if not fact.fact_id:
            raise ValueError("Fact must have fact_id to update")

        query = """
            UPDATE user_facts
            SET fact_text = ?, confidence = ?, updated_at = ?, metadata = ?
            WHERE fact_id = ?
        """
        cursor = await self._execute(
            query,
            (
                fact.fact_text,
                fact.confidence,
                datetime.utcnow().isoformat(),
                json.dumps(fact.metadata) if fact.metadata else "{}",
                fact.fact_id,
            ),
        )

        if cursor.rowcount == 0:
            raise UserProfileNotFoundError(
                "Fact not found",
                context={"fact_id": fact.fact_id},
            )

        return fact

    async def delete_fact(self, fact_id: int) -> bool:
        """Delete a fact.

        Args:
            fact_id: Fact ID to delete

        Returns:
            True if deleted, False if not found
        """
        query = "DELETE FROM user_facts WHERE fact_id = ?"
        cursor = await self._execute(query, (fact_id,))
        return cursor.rowcount > 0
