#!/usr/bin/env python3
"""Dump dynamic system instructions for a chat to a markdown file."""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

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


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Dump dynamic system instructions")
    parser.add_argument(
        "chat_id",
        type=int,
        help="Chat ID to dump instructions for",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="docs/dumps",
        help="Output directory for dump files",
    )
    args = parser.parse_args()

    settings = get_settings()

    # Initialize services
    summary_repository = ChatSummaryRepository(database_url=settings.database_url)
    context_store = ContextStore(
        database_url=settings.database_url,
        redis_client=None,
    )
    await context_store.init()

    builder = SystemInstructionBuilder(
        settings=settings,
        summary_repository=summary_repository,
        context_store=context_store,
    )

    # Get chat info
    from app.infrastructure.db_utils import get_db_connection

    chat_query = """
        SELECT chat_id, chat_title, participant_count
        FROM chat_profiles
        WHERE chat_id = $1
        LIMIT 1
    """

    async with get_db_connection(settings.database_url) as conn:
        chat_row = await conn.fetchrow(chat_query, args.chat_id)

    chat_name = chat_row["chat_title"] if chat_row else None
    member_count = chat_row["participant_count"] if chat_row else None

    # Get recent messages
    messages = await context_store.recent(
        chat_id=args.chat_id, thread_id=None, max_messages=50
    )

    # Build system instruction
    instruction = await builder.assemble_system_instruction(
        chat_id=args.chat_id,
        chat_name=chat_name,
        member_count=member_count,
        messages=messages,
    )

    # Print to console
    print("=" * 80)
    print(f"Dynamic System Instructions for Chat {args.chat_id}")
    print("=" * 80)
    print(instruction)
    print("=" * 80)

    # Save to file
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"dynamic_instructions_chat_{args.chat_id}_{timestamp}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Dynamic System Instructions\n\n")
        f.write(f"**Chat ID**: {args.chat_id}\n")
        f.write(f"**Chat Name**: {chat_name or 'Unknown'}\n")
        f.write(f"**Member Count**: {member_count or 'Unknown'}\n")
        f.write(f"**Generated**: {datetime.now().isoformat()}\n\n")
        f.write("---\n\n")
        f.write(instruction)

    logger.info(f"Saved instructions to {filename}")


if __name__ == "__main__":
    asyncio.run(main())

