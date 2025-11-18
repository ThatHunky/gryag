"""User profile repository.

Handles data access for user profiles and facts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.user_profile import UserProfile
from app.repositories.base import Repository

# class UserFact:
#     """User fact entity.
#
#     Represents a single fact about a user.
#     """
#
#     def __init__(
#         self,
#         id: Optional[int],  # Changed from fact_id to match schema
#         user_id: int,
#         chat_id: int,
#         fact_type: str,  # Changed from category to match schema
#         fact_key: str,  # Added to match schema
#         fact_value: str,  # Changed from fact_text to match schema
#         confidence: float,
#         source_message_id: Optional[int] = None,
#         evidence_text: Optional[str] = None,  # Added to match schema
#         is_active: int = 1,  # Added to match schema
#         created_at: Optional[int] = None,  # Changed to int (Unix timestamp)
#         updated_at: Optional[int] = None,  # Changed to int (Unix timestamp)
#         last_mentioned: Optional[int] = None,  # Added to match schema
#     ):
#         self.id = id
#         self.user_id = user_id
#         self.chat_id = chat_id
#         self.fact_type = fact_type
#         self.fact_key = fact_key
#         self.fact_value = fact_value
#         self.confidence = confidence
#         self.source_message_id = source_message_id
#         self.evidence_text = evidence_text
#         self.is_active = is_active
#         self.created_at = created_at or int(datetime.now(timezone.utc).timestamp())
#         self.updated_at = updated_at or int(datetime.now(timezone.utc).timestamp())
#         self.last_mentioned = last_mentioned
#
#     def to_dict(self) -> Dict[str, Any]:
#         """Convert to dictionary."""
#         return {
#             "id": self.id,
#             "user_id": self.user_id,
#             "chat_id": self.chat_id,
#             "fact_type": self.fact_type,
#             "fact_key": self.fact_key,
#             "fact_value": self.fact_value,
#             "confidence": self.confidence,
#             "source_message_id": self.source_message_id,
#             "evidence_text": self.evidence_text,
#             "is_active": self.is_active,
#             "created_at": self.created_at,
#             "updated_at": self.updated_at,
#             "last_mentioned": self.last_mentioned,
#         }


class UserProfileRepository(Repository[UserProfile]):
    """Repository for user profiles.

    Provides data access methods for user profiles and facts.
    """

    async def find_by_id(self, id: Any) -> UserProfile | None:
        """Find user profile by a composite ID (user_id, chat_id).

        Args:
            id: A tuple containing (user_id, chat_id)

        Returns:
            UserProfile or None if not found
        """
        if not isinstance(id, tuple) or len(id) != 2:
            raise TypeError("ID must be a tuple of (user_id, chat_id)")
        user_id, chat_id = id

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

    async def save(self, entity: UserProfile) -> UserProfile:
        """Save or update user profile.

        Args:
            entity: UserProfile to save

        Returns:
            Saved profile
        """
        now = int(datetime.now(UTC).timestamp())
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
                entity.user_id,
                entity.chat_id,
                entity.first_name,
                entity.last_name,
                entity.username,
                entity.first_seen,
                now,  # last_seen
                entity.created_at,
                now,  # updated_at
            ),
        )

        return entity

    async def delete(self, id: Any) -> bool:
        """Delete user profile by composite ID.

        Args:
            id: A tuple containing (user_id, chat_id)

        Returns:
            True if deleted, False if not found
        """
        if not isinstance(id, tuple) or len(id) != 2:
            raise TypeError("ID must be a tuple of (user_id, chat_id)")
        user_id, chat_id = id
        query = "DELETE FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        cursor = await self._execute(query, (user_id, chat_id))
        return cursor.rowcount > 0


#
#     async def get_facts(
#         self, user_id: int, chat_id: int, fact_type: Optional[str] = None
#     ) -> List[UserFact]:
#         """Get facts for a user.
#
#         Args:
#             user_id: User ID
#             chat_id: Chat ID
#             fact_type: Optional fact type filter
#
#         Returns:
#             List of UserFact objects
#         """
#         if fact_type:
#             query = """
#                 SELECT * FROM user_facts
#                 WHERE user_id = ? AND chat_id = ? AND fact_type = ?
#                 ORDER BY confidence DESC, created_at DESC
#             """
#             rows = await self._fetch_all(query, (user_id, chat_id, fact_type))
#         else:
#             query = """
#                 SELECT * FROM user_facts
#                 WHERE user_id = ? AND chat_id = ?
#                 ORDER BY confidence DESC, created_at DESC
#             """
#             rows = await self._fetch_all(query, (user_id, chat_id))
#
#         facts = []
#         for row in rows:
#             facts.append(
#                 UserFact(
#                     id=row["id"],
#                     user_id=row["user_id"],
#                     chat_id=row["chat_id"],
#                     fact_type=row["fact_type"],
#                     fact_key=row["fact_key"],
#                     fact_value=row["fact_value"],
#                     confidence=row["confidence"],
#                     source_message_id=row["source_message_id"],
#                     evidence_text=row["evidence_text"],
#                     is_active=row["is_active"],
#                     created_at=row["created_at"],
#                     updated_at=row["updated_at"],
#                     last_mentioned=row["last_mentioned"],
#                 )
#             )
#         return facts
#
#     async def add_fact(self, fact: UserFact) -> UserFact:
#         """Add a fact to user profile.
#
#         Args:
#             fact: UserFact to add
#
#         Returns:
#             Saved fact with generated id
#         """
#         query = """
#             INSERT INTO user_facts (
#                 user_id, chat_id, fact_type, fact_key, fact_value, confidence,
#                 source_message_id, evidence_text, is_active, created_at, updated_at, last_mentioned
#             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#         """
#         cursor = await self._execute(
#             query,
#             (
#                 fact.user_id,
#                 fact.chat_id,
#                 fact.fact_type,
#                 fact.fact_key,
#                 fact.fact_value,
#                 fact.confidence,
#                 fact.source_message_id,
#                 fact.evidence_text,
#                 fact.is_active,
#                 fact.created_at,
#                 fact.updated_at,
#                 fact.last_mentioned,
#             ),
#         )
#
#         fact.id = cursor.lastrowid
#         return fact
#
#     async def update_fact(self, fact: UserFact) -> UserFact:
#         """Update existing fact.
#
#         Args:
#             fact: UserFact to update
#
#         Returns:
#             Updated fact
#
#         Raises:
#             UserProfileNotFoundError: If fact doesn't exist
#         """
#         if not fact.id:
#             raise ValueError("Fact must have id to update")
#
#         query = """
#             UPDATE user_facts
#             SET fact_key = ?, fact_value = ?, confidence = ?, evidence_text = ?,
#                 is_active = ?, updated_at = ?, last_mentioned = ?
#             WHERE id = ?
#         """
#         cursor = await self._execute(
#             query,
#             (
#                 fact.fact_key,
#                 fact.fact_value,
#                 fact.confidence,
#                 fact.evidence_text,
#                 fact.is_active,
#                 int(datetime.now(timezone.utc).timestamp()),
#                 fact.last_mentioned,
#                 fact.id,
#             ),
#         )
#
#         if cursor.rowcount == 0:
#             raise UserProfileNotFoundError(
#                 "Fact not found",
#                 context={"id": fact.id},
#             )
#
#         return fact
#
#     async def delete_fact(self, fact_id: int) -> bool:
#         """Delete a fact.
#
#         Args:
#             fact_id: Fact ID to delete
#
#         Returns:
#             True if deleted, False if not found
#         """
#         query = "DELETE FROM user_facts WHERE id = ?"
#         cursor = await self._execute(query, (fact_id,))
#         return cursor.rowcount > 0
