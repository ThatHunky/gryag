"""Chat summary repository for storing and retrieving chat summaries."""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.base import Repository

logger = logging.getLogger(__name__)


class ChatSummaryRepository(Repository):
    """Repository for chat summaries."""

    async def save_summary(
        self,
        chat_id: int,
        summary_type: str,
        period_start: int,
        period_end: int,
        summary_text: str,
        token_count: int | None = None,
        model_version: str | None = None,
    ) -> int:
        """
        Save a chat summary.

        Args:
            chat_id: Chat ID
            summary_type: '30days' or '7days'
            period_start: Start timestamp
            period_end: End timestamp
            summary_text: Summary text
            token_count: Optional token count
            model_version: Optional model version

        Returns:
            Summary ID
        """
        import time

        generated_at = int(time.time())

        query = """
            INSERT INTO chat_summaries (
                chat_id, summary_type, period_start, period_end,
                summary_text, token_count, generated_at, model_version
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (chat_id, summary_type, period_start)
            DO UPDATE SET
                period_end = EXCLUDED.period_end,
                summary_text = EXCLUDED.summary_text,
                token_count = EXCLUDED.token_count,
                generated_at = EXCLUDED.generated_at,
                model_version = EXCLUDED.model_version
            RETURNING id
        """

        try:
            row = await self._fetch_one(
                query,
                (
                    chat_id,
                    summary_type,
                    period_start,
                    period_end,
                    summary_text,
                    token_count,
                    generated_at,
                    model_version,
                ),
            )
            if row:
                return row["id"]
            raise ValueError("Failed to save summary")
        except Exception as e:
            logger.error(f"Failed to save chat summary: {e}", exc_info=True)
            raise

    async def get_latest_summary(
        self, chat_id: int, summary_type: str
    ) -> dict[str, Any] | None:
        """
        Get the latest summary for a chat.

        Args:
            chat_id: Chat ID
            summary_type: '30days' or '7days'

        Returns:
            Summary dict or None
        """
        query = """
            SELECT id, chat_id, summary_type, period_start, period_end,
                   summary_text, token_count, generated_at, model_version
            FROM chat_summaries
            WHERE chat_id = $1 AND summary_type = $2
            ORDER BY period_end DESC
            LIMIT 1
        """

        try:
            row = await self._fetch_one(query, (chat_id, summary_type))
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Failed to get latest summary: {e}", exc_info=True)
            return None

    async def get_summaries_for_period(
        self, chat_id: int, start_ts: int, end_ts: int
    ) -> list[dict[str, Any]]:
        """
        Get summaries that overlap with a time period.

        Args:
            chat_id: Chat ID
            start_ts: Start timestamp
            end_ts: End timestamp

        Returns:
            List of summary dicts
        """
        query = """
            SELECT id, chat_id, summary_type, period_start, period_end,
                   summary_text, token_count, generated_at, model_version
            FROM chat_summaries
            WHERE chat_id = $1
              AND period_start <= $3
              AND period_end >= $2
            ORDER BY period_end DESC
        """

        try:
            rows = await self._fetch_all(query, (chat_id, start_ts, end_ts))
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get summaries for period: {e}", exc_info=True)
            return []

    async def find_by_id(self, id: Any) -> dict[str, Any] | None:
        """Find summary by ID."""
        query = """
            SELECT id, chat_id, summary_type, period_start, period_end,
                   summary_text, token_count, generated_at, model_version
            FROM chat_summaries
            WHERE id = $1
        """
        row = await self._fetch_one(query, (id,))
        return dict(row) if row else None

    async def save(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Save entity (not used, use save_summary instead)."""
        raise NotImplementedError("Use save_summary instead")

    async def delete(self, id: Any) -> bool:
        """Delete summary by ID."""
        query = "DELETE FROM chat_summaries WHERE id = $1"
        result = await self._execute(query, (id,))
        return "DELETE" in result

