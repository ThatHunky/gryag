#!/usr/bin/env python3
"""Check summary status for a specific chat."""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.infrastructure.db_utils import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def check_summaries(chat_id: int) -> None:
    """Check summary status for a chat."""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "postgresql://gryag:gryag@localhost:5433/gryag")

    query = """
        SELECT 
            id,
            chat_id,
            summary_type,
            period_start,
            period_end,
            LENGTH(summary_text) as summary_length,
            token_count,
            generated_at,
            model_version
        FROM chat_summaries
        WHERE chat_id = $1
        ORDER BY summary_type, period_end DESC
    """

    async with get_db_connection(database_url) as conn:
        rows = await conn.fetch(query, chat_id)

    if not rows:
        logger.info(f"No summaries found for chat {chat_id}")
        return

    logger.info(f"Found {len(rows)} summary record(s) for chat {chat_id}:\n")

    kyiv_tz = ZoneInfo("Europe/Kiev")
    for row in rows:
        summary_type = row["summary_type"]
        period_start = datetime.fromtimestamp(row["period_start"], tz=kyiv_tz)
        period_end = datetime.fromtimestamp(row["period_end"], tz=kyiv_tz)
        generated_at = datetime.fromtimestamp(row["generated_at"], tz=kyiv_tz)
        age_days = (datetime.now(kyiv_tz) - generated_at).days

        logger.info(f"Summary Type: {summary_type}")
        logger.info(f"  ID: {row['id']}")
        logger.info(f"  Period: {period_start.strftime('%Y-%m-%d %H:%M:%S %Z')} to {period_end.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"  Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')} ({age_days} days ago)")
        logger.info(f"  Summary Length: {row['summary_length']} characters")
        logger.info(f"  Token Count: {row['token_count']}")
        logger.info(f"  Model Version: {row['model_version']}")
        logger.info("")

    # Check for missing summaries
    summary_types = {row["summary_type"] for row in rows}
    if "30days" not in summary_types:
        logger.warning("⚠️  30-day summary is MISSING")
    if "7days" not in summary_types:
        logger.warning("⚠️  7-day summary is MISSING")


async def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        logger.error("Usage: python check_summaries.py <chat_id>")
        sys.exit(1)

    try:
        chat_id = int(sys.argv[1])
    except ValueError:
        logger.error(f"Invalid chat_id: {sys.argv[1]}")
        sys.exit(1)

    await check_summaries(chat_id)


if __name__ == "__main__":
    asyncio.run(main())

