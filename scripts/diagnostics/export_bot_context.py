#!/usr/bin/env python3
"""Export full bot context for a chat to a markdown file."""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import get_settings
from app.repositories.chat_summary_repository import ChatSummaryRepository
from app.services.context_store import ContextStore
from app.services.instruction.system_instruction_builder import SystemInstructionBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def export_context(chat_id: int, output_file: str | None = None) -> None:
    """Export full bot context for a chat."""
    settings = get_settings()

    # Initialize services
    summary_repository = ChatSummaryRepository(database_url=settings.database_url)
    context_store = ContextStore(
        database_url=settings.database_url,
        redis_client=None,
    )
    await context_store.init()

    # Initialize builder
    builder = SystemInstructionBuilder(
        settings=settings,
        summary_repository=summary_repository,
        context_store=context_store,
    )

    # Get recent messages for immediate context
    messages = await context_store.recent(
        chat_id=chat_id, thread_id=None, max_messages=30
    )

    # Build full system instruction
    logger.info(f"Building full context for chat {chat_id}...")
    full_context = await builder.assemble_system_instruction(
        chat_id=chat_id,
        chat_name=None,  # Could be fetched from database if needed
        member_count=None,
        messages=messages,
        current_message=None,
        replied_to_message=None,
    )

    # Add metadata header
    kyiv_tz = ZoneInfo("Europe/Kiev")
    now = datetime.now(kyiv_tz)
    metadata = f"""# Bot Context Export

**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}
**Chat ID**: `{chat_id}`
**Messages in immediate context**: {len(messages)}

---

"""

    full_document = metadata + full_context

    # Write to file
    if output_file:
        output_path = Path(output_file)
    else:
        output_path = Path(f"bot_context_chat_{chat_id}_{now.strftime('%Y%m%d_%H%M%S')}.md")

    output_path.write_text(full_document, encoding="utf-8")
    logger.info(f"✅ Full context exported to: {output_path}")
    logger.info(f"   File size: {len(full_document)} characters")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Export full bot context for a chat")
    parser.add_argument(
        "--chat-id",
        type=int,
        required=True,
        help="Chat ID to export context for",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: bot_context_chat_<id>_<timestamp>.md)",
    )
    args = parser.parse_args()

    try:
        await export_context(args.chat_id, args.output)
    except Exception as e:
        logger.error(f"Failed to export context: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

