"""Summary generator for creating chat history summaries."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import Settings
from app.repositories.chat_summary_repository import ChatSummaryRepository
from app.services.gemini import GeminiClient

logger = logging.getLogger(__name__)


class SummaryGenerator:
    """Generates 30-day and 7-day chat summaries."""

    def __init__(
        self,
        settings: Settings,
        gemini_client: GeminiClient,
        summary_repository: ChatSummaryRepository,
        context_store: Any | None = None,
    ) -> None:
        """
        Initialize summary generator.

        Args:
            settings: Application settings
            gemini_client: Gemini client for generation
            summary_repository: Repository for storing summaries
            context_store: Optional context store for message retrieval
        """
        self.settings = settings
        self.gemini_client = gemini_client
        self.summary_repository = summary_repository
        self.context_store = context_store

    async def generate_30day_summary(self, chat_id: int) -> bool:
        """
        Generate 30-day summary for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            True if successful, False otherwise
        """
        try:
            now = int(time.time())
            period_end = now
            period_start = now - (30 * 24 * 60 * 60)  # 30 days ago

            # Retrieve messages for the period
            messages = await self._get_messages_for_period(
                chat_id, period_start, period_end
            )

            if not messages:
                logger.info(f"No messages found for 30-day summary in chat {chat_id}")
                return False

            # Build prompt
            prompt = self._build_30day_prompt(messages)

            # Generate summary
            logger.info(f"Generating 30-day summary for chat {chat_id}...")
            result = await self.gemini_client.generate(
                system_prompt="You are a helpful assistant that creates concise chat summaries.",
                history=None,
                user_parts=[{"text": prompt}],
                tools=None,
            )
            response = result.get("text", "").strip()

            if not response or not response.strip():
                logger.warning(f"Empty response for 30-day summary in chat {chat_id}")
                return False

            # Save summary
            token_count = len(response) // 4  # Rough estimate
            model_version = getattr(self.gemini_client, "_model_name", "unknown")

            await self.summary_repository.save_summary(
                chat_id=chat_id,
                summary_type="30days",
                period_start=period_start,
                period_end=period_end,
                summary_text=response.strip(),
                token_count=token_count,
                model_version=model_version,
            )

            logger.info(f"Successfully generated 30-day summary for chat {chat_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to generate 30-day summary for chat {chat_id}: {e}",
                exc_info=True,
            )
            return False

    async def generate_7day_summary(self, chat_id: int) -> bool:
        """
        Generate 7-day summary for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            True if successful, False otherwise
        """
        try:
            now = int(time.time())
            period_end = now
            period_start = now - (7 * 24 * 60 * 60)  # 7 days ago

            # Retrieve messages for the period
            messages = await self._get_messages_for_period(
                chat_id, period_start, period_end
            )

            if not messages:
                logger.info(f"No messages found for 7-day summary in chat {chat_id}")
                return False

            # Build prompt
            prompt = self._build_7day_prompt(messages)

            # Generate summary
            logger.info(f"Generating 7-day summary for chat {chat_id}...")
            result = await self.gemini_client.generate(
                system_prompt="You are a helpful assistant that creates concise chat summaries.",
                history=None,
                user_parts=[{"text": prompt}],
                tools=None,
            )
            response = result.get("text", "").strip()

            if not response or not response.strip():
                logger.warning(f"Empty response for 7-day summary in chat {chat_id}")
                return False

            # Save summary
            token_count = len(response) // 4  # Rough estimate
            model_version = getattr(self.gemini_client, "_model_name", "unknown")

            await self.summary_repository.save_summary(
                chat_id=chat_id,
                summary_type="7days",
                period_start=period_start,
                period_end=period_end,
                summary_text=response.strip(),
                token_count=token_count,
                model_version=model_version,
            )

            logger.info(f"Successfully generated 7-day summary for chat {chat_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to generate 7-day summary for chat {chat_id}: {e}",
                exc_info=True,
            )
            return False

    async def _get_messages_for_period(
        self, chat_id: int, period_start: int, period_end: int
    ) -> list[dict[str, Any]]:
        """
        Retrieve messages for a time period.

        Args:
            chat_id: Chat ID
            period_start: Start timestamp
            period_end: End timestamp

        Returns:
            List of message dicts
        """
        if self.context_store:
            # Use context store if available
            # Get recent messages (we'll filter by timestamp)
            all_messages = await self.context_store.recent(
                chat_id=chat_id, thread_id=None, max_messages=1000
            )
            # Filter by timestamp
            filtered = [
                msg
                for msg in all_messages
                if period_start <= (msg.get("ts") or msg.get("timestamp", 0)) <= period_end
            ]
            return filtered
        else:
            # Direct database query
            from app.infrastructure.db_utils import get_db_connection

            query = """
                SELECT role, text, media, ts, sender_name, sender_username
                FROM messages
                WHERE chat_id = $1
                  AND thread_id IS NULL
                  AND ts >= $2
                  AND ts <= $3
                ORDER BY ts ASC
                LIMIT 1000
            """

            async with get_db_connection(self.settings.database_url) as conn:
                rows = await conn.fetch(query, chat_id, period_start, period_end)

            return [dict(row) for row in rows]

    def _build_30day_prompt(self, messages: list[dict[str, Any]]) -> str:
        """
        Build prompt for 30-day summary.

        Args:
            messages: List of messages

        Returns:
            Prompt string
        """
        # Format messages
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            # Extract text from either direct 'text' field or 'parts' array
            text = msg.get("text", "").strip()
            if not text and "parts" in msg:
                # Extract text from parts array (format from context_store.recent())
                parts = msg.get("parts", [])
                text_parts = [
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict) and "text" in part
                ]
                text = " ".join(text_parts).strip()
            sender_name = msg.get("sender_name") or msg.get("username", "User")

            if not text:
                continue

            if role == "user":
                formatted.append(f"{sender_name}: {text}")
            elif role == "model" or role == "assistant":
                formatted.append(f"Bot: {text}")
            else:
                formatted.append(text)

        messages_text = "\n".join(formatted)

        prompt = f"""Create a concise summary of the following 30-day chat history. Focus on:
- Key topics and discussions
- Important events or announcements
- Notable user activity and participation
- Recurring themes or patterns
- Significant changes or developments

Do NOT include:
- The bot's own response patterns or style
- Technical details about the bot's behavior
- Repetitive or trivial interactions

Chat history:
{messages_text}

Summary:"""

        return prompt

    def _build_7day_prompt(self, messages: list[dict[str, Any]]) -> str:
        """
        Build prompt for 7-day summary.

        Args:
            messages: List of messages

        Returns:
            Prompt string
        """
        # Format messages
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            # Extract text from either direct 'text' field or 'parts' array
            text = msg.get("text", "").strip()
            if not text and "parts" in msg:
                # Extract text from parts array (format from context_store.recent())
                parts = msg.get("parts", [])
                text_parts = [
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict) and "text" in part
                ]
                text = " ".join(text_parts).strip()
            sender_name = msg.get("sender_name") or msg.get("username", "User")

            if not text:
                continue

            if role == "user":
                formatted.append(f"{sender_name}: {text}")
            elif role == "model" or role == "assistant":
                formatted.append(f"Bot: {text}")
            else:
                formatted.append(text)

        messages_text = "\n".join(formatted)

        prompt = f"""Create a concise summary of the following 7-day chat history. Focus on:
- Recent topics and discussions
- Recent events or announcements
- User activity and engagement
- Current themes or trends
- Recent changes or developments

Do NOT include:
- The bot's own response patterns or style
- Technical details about the bot's behavior
- Repetitive or trivial interactions

Chat history:
{messages_text}

Summary:"""

        return prompt

