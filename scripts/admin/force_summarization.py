#!/usr/bin/env python3
"""Force summarization for a specific chat or all active chats."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import get_settings
from app.repositories.chat_summary_repository import ChatSummaryRepository
from app.services.embedding_cache import EmbeddingCache
from app.services.gemini import GeminiClient
from app.services.instruction.summary_generator import SummaryGenerator
from app.services.context_store import ContextStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Force summarization for chats")
    parser.add_argument(
        "--chat-id",
        type=int,
        help="Specific chat ID to summarize (if not provided, summarizes all active chats)",
    )
    parser.add_argument(
        "--summary-type",
        choices=["30days", "7days", "both"],
        default="both",
        help="Type of summary to generate",
    )
    args = parser.parse_args()

    settings = get_settings()

    # Initialize services
    gemini_client = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
        embedding_cache=EmbeddingCache(
            db_path=settings.database_url,
        ),
    )

    summary_repository = ChatSummaryRepository(database_url=settings.database_url)
    context_store = ContextStore(
        database_url=settings.database_url,
        redis_client=None,
    )
    await context_store.init()

    generator = SummaryGenerator(
        settings=settings,
        gemini_client=gemini_client,
        summary_repository=summary_repository,
        context_store=context_store,
    )

    if args.chat_id:
        # Generate for specific chat
        logger.info(f"Generating {args.summary_type} summary for chat {args.chat_id}...")
        success = await generator.generate_30day_summary(
            args.chat_id
        ) if args.summary_type in ("30days", "both") else True
        if args.summary_type in ("7days", "both"):
            success = (
                await generator.generate_7day_summary(args.chat_id) and success
            )

        if success:
            logger.info(f"Successfully generated summaries for chat {args.chat_id}")
        else:
            logger.error(f"Failed to generate summaries for chat {args.chat_id}")
            sys.exit(1)
    else:
        # Generate for all active chats
        from app.infrastructure.db_utils import get_db_connection

        query = """
            SELECT DISTINCT chat_id
            FROM messages
            WHERE ts >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')::BIGINT
            ORDER BY chat_id
        """

        async with get_db_connection(settings.database_url) as conn:
            rows = await conn.fetch(query)

        chat_ids = [row["chat_id"] for row in rows]
        logger.info(f"Found {len(chat_ids)} active chats")

        for chat_id in chat_ids:
            logger.info(f"Processing chat {chat_id}...")
            if args.summary_type in ("30days", "both"):
                await generator.generate_30day_summary(chat_id)
            if args.summary_type in ("7days", "both"):
                await generator.generate_7day_summary(chat_id)

        logger.info(f"Completed summarization for {len(chat_ids)} chats")


if __name__ == "__main__":
    asyncio.run(main())

