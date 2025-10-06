"""Conversation repository.

Handles data access for messages and conversation history.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.repositories.base import Repository


class Message:
    """Message entity.

    Represents a single message in a conversation.
    """

    def __init__(
        self,
        message_id: Optional[int],
        chat_id: int,
        thread_id: Optional[int],
        user_id: int,
        role: str,
        text: str,
        media: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        created_at: Optional[datetime] = None,
    ):
        self.message_id = message_id
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.user_id = user_id
        self.role = role
        self.text = text
        self.media = media or {}
        self.metadata = metadata or {}
        self.embedding = embedding
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "role": self.role,
            "text": self.text,
            "media": self.media,
            "metadata": self.metadata,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ConversationRepository(Repository[Message]):
    """Repository for conversation messages.

    Provides data access methods for messages and conversation history.
    """

    async def find_by_id(self, message_id: int) -> Optional[Message]:
        """Find message by ID.

        Args:
            message_id: Message ID

        Returns:
            Message or None if not found
        """
        query = """
            SELECT * FROM messages WHERE message_id = ?
        """
        row = await self._fetch_one(query, (message_id,))

        if not row:
            return None

        return self._row_to_message(row)

    async def save(self, message: Message) -> Message:
        """Save message to database.

        Args:
            message: Message to save

        Returns:
            Saved message with generated message_id
        """
        query = """
            INSERT INTO messages (
                chat_id, thread_id, user_id, role, text,
                media, metadata, embedding, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self._execute(
            query,
            (
                message.chat_id,
                message.thread_id,
                message.user_id,
                message.role,
                message.text,
                json.dumps(message.media) if message.media else "{}",
                json.dumps(message.metadata) if message.metadata else "{}",
                json.dumps(message.embedding) if message.embedding else None,
                message.created_at.isoformat(),
            ),
        )

        message.message_id = cursor.lastrowid
        return message

    async def delete(self, message_id: int) -> bool:
        """Delete message by ID.

        Args:
            message_id: Message ID

        Returns:
            True if deleted, False if not found
        """
        query = "DELETE FROM messages WHERE message_id = ?"
        cursor = await self._execute(query, (message_id,))
        return cursor.rowcount > 0

    async def get_recent_messages(
        self,
        chat_id: int,
        thread_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[Message]:
        """Get recent messages for a chat.

        Args:
            chat_id: Chat ID
            thread_id: Optional thread ID
            limit: Maximum number of messages

        Returns:
            List of Message objects, newest first
        """
        if thread_id is not None:
            query = """
                SELECT * FROM messages
                WHERE chat_id = ? AND thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = await self._fetch_all(query, (chat_id, thread_id, limit))
        else:
            query = """
                SELECT * FROM messages
                WHERE chat_id = ? AND (thread_id IS NULL OR thread_id = 0)
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = await self._fetch_all(query, (chat_id, limit))

        return [self._row_to_message(row) for row in rows]

    async def get_messages_by_user(
        self,
        chat_id: int,
        user_id: int,
        limit: int = 100,
    ) -> List[Message]:
        """Get messages from specific user in a chat.

        Args:
            chat_id: Chat ID
            user_id: User ID
            limit: Maximum number of messages

        Returns:
            List of Message objects
        """
        query = """
            SELECT * FROM messages
            WHERE chat_id = ? AND user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        rows = await self._fetch_all(query, (chat_id, user_id, limit))
        return [self._row_to_message(row) for row in rows]

    async def search_messages(
        self,
        chat_id: int,
        query_text: str,
        limit: int = 20,
    ) -> List[Message]:
        """Search messages by text.

        Args:
            chat_id: Chat ID
            query_text: Text to search for
            limit: Maximum results

        Returns:
            List of matching Message objects
        """
        query = """
            SELECT * FROM messages
            WHERE chat_id = ? AND text LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        rows = await self._fetch_all(query, (chat_id, f"%{query_text}%", limit))
        return [self._row_to_message(row) for row in rows]

    async def semantic_search(
        self,
        chat_id: int,
        query_embedding: List[float],
        thread_id: Optional[int] = None,
        limit: int = 5,
    ) -> List[tuple[Message, float]]:
        """Search messages by embedding similarity.

        Args:
            chat_id: Chat ID
            query_embedding: Query embedding vector
            thread_id: Optional thread ID
            limit: Maximum results

        Returns:
            List of (Message, similarity_score) tuples
        """
        # Fetch messages with embeddings
        if thread_id is not None:
            query = """
                SELECT * FROM messages
                WHERE chat_id = ? AND thread_id = ? AND embedding IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 100
            """
            rows = await self._fetch_all(query, (chat_id, thread_id))
        else:
            query = """
                SELECT * FROM messages
                WHERE chat_id = ? AND embedding IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 100
            """
            rows = await self._fetch_all(query, (chat_id,))

        # Calculate cosine similarity
        results = []
        for row in rows:
            message = self._row_to_message(row)
            if message.embedding:
                similarity = self._cosine_similarity(query_embedding, message.embedding)
                results.append((message, similarity))

        # Sort by similarity and limit
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def _row_to_message(self, row) -> Message:
        """Convert database row to Message object."""
        media = json.loads(row["media"]) if row.get("media") else {}
        metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
        embedding = json.loads(row["embedding"]) if row.get("embedding") else None

        return Message(
            message_id=row["message_id"],
            chat_id=row["chat_id"],
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            role=row["role"],
            text=row["text"],
            media=media,
            metadata=metadata,
            embedding=embedding,
            created_at=(
                datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
            ),
        )

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)
