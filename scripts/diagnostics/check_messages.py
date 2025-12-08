#!/usr/bin/env python3
"""Check actual messages in database for a chat."""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import os
from dotenv import load_dotenv
load_dotenv()

from app.infrastructure.db_utils import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def check_messages(chat_id: int, limit: int = 20) -> None:
    """Check actual messages in database."""
    database_url = os.getenv("DATABASE_URL", "postgresql://gryag:gryag@localhost:5433/gryag")
    kyiv_tz = ZoneInfo("Europe/Kiev")
    
    async with get_db_connection(database_url) as conn:
        rows = await conn.fetch("""
            SELECT role, text, ts, sender_name, sender_username, id
            FROM messages
            WHERE chat_id = $1
            ORDER BY ts DESC
            LIMIT $2
        """, chat_id, limit)
        
        logger.info(f"Found {len(rows)} recent messages for chat {chat_id}\n")
        
        for i, row in enumerate(rows, 1):
            text = row['text'] or ''
            text_preview = text[:100] if text else '(EMPTY)'
            ts = row['ts']
            dt = datetime.fromtimestamp(ts, tz=kyiv_tz) if ts else None
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S %Z') if dt else 'Unknown'
            
            logger.info(f"{i}. [{row['role']}] {row['sender_name'] or 'Unknown'}")
            logger.info(f"   Time: {time_str}")
            logger.info(f"   Text: {text_preview}")
            logger.info(f"   Text length: {len(text) if text else 0}")
            logger.info("")


async def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        logger.error("Usage: python check_messages.py <chat_id> [limit]")
        sys.exit(1)

    try:
        chat_id = int(sys.argv[1])
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    except ValueError:
        logger.error(f"Invalid chat_id or limit: {sys.argv[1:]}")
        sys.exit(1)

    await check_messages(chat_id, limit)


if __name__ == "__main__":
    asyncio.run(main())

