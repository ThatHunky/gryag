#!/usr/bin/env python3
"""
Token Usage Audit Tool

Analyzes stored conversations and identifies high-token offenders.
Provides insights for optimizing token budgets and context assembly.

Usage:
    python scripts/diagnostics/token_audit.py [options]

Examples:
    # Audit all conversations
    python scripts/diagnostics/token_audit.py

    # Show top 10 token-heavy chats
    python scripts/diagnostics/token_audit.py --top 10

    # Analyze specific chat
    python scripts/diagnostics/token_audit.py --chat-id 12345

    # Export results to JSON
    python scripts/diagnostics/token_audit.py --output report.json
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))



@dataclass
class ChatTokenStats:
    """Token usage statistics for a chat."""

    chat_id: int
    thread_id: int | None
    message_count: int
    total_tokens: int
    avg_tokens_per_message: float
    max_tokens_per_message: int
    median_tokens_per_message: float
    user_message_count: int
    model_message_count: int
    user_tokens: int
    model_tokens: int
    has_embeddings: bool
    embedding_coverage_pct: float


@dataclass
class MessageTokenStats:
    """Token statistics for individual message."""

    message_id: int
    chat_id: int
    thread_id: int | None
    role: str
    token_count: int
    text_length: int
    has_media: bool
    has_embedding: bool
    timestamp: int


class TokenAuditor:
    """Analyzes token usage in stored conversations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _estimate_tokens(self, text: str | None) -> int:
        """Estimate token count from text (same heuristic as context manager)."""
        if not text:
            return 0
        words = len(text.split())
        return int(words * 1.3)

    async def analyze_chats(
        self, chat_id: int | None = None, limit: int | None = None
    ) -> list[ChatTokenStats]:
        """
        Analyze token usage per chat.

        Args:
            chat_id: Analyze specific chat only (None for all)
            limit: Maximum number of chats to analyze

        Returns:
            List of ChatTokenStats sorted by total tokens (descending)
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            # Build query
            if chat_id is not None:
                where_clause = "WHERE chat_id = ?"
                params = (chat_id,)
            else:
                where_clause = ""
                params = ()

            query = f"""
                SELECT 
                    chat_id,
                    thread_id,
                    role,
                    text,
                    media,
                    embedding
                FROM messages
                {where_clause}
                ORDER BY chat_id, thread_id, id
            """

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            # Group by (chat_id, thread_id)
            chat_data: dict[tuple[int, int | None], list[sqlite3.Row]] = defaultdict(
                list
            )

            for row in rows:
                key = (row["chat_id"], row["thread_id"])
                chat_data[key].append(row)

            # Compute stats for each chat/thread
            stats_list = []

            for (cid, tid), messages in chat_data.items():
                tokens_per_msg = []
                user_msgs = 0
                model_msgs = 0
                user_tokens_total = 0
                model_tokens_total = 0
                embedding_count = 0

                for msg in messages:
                    token_count = self._estimate_tokens(msg["text"])
                    tokens_per_msg.append(token_count)

                    if msg["role"] == "user":
                        user_msgs += 1
                        user_tokens_total += token_count
                    else:
                        model_msgs += 1
                        model_tokens_total += token_count

                    if msg["embedding"]:
                        embedding_count += 1

                total_msgs = len(messages)
                total_tokens = sum(tokens_per_msg)
                avg_tokens = total_tokens / total_msgs if total_msgs > 0 else 0

                # Median
                sorted_tokens = sorted(tokens_per_msg)
                mid = len(sorted_tokens) // 2
                median_tokens = (
                    sorted_tokens[mid]
                    if len(sorted_tokens) % 2 == 1
                    else (
                        (sorted_tokens[mid - 1] + sorted_tokens[mid]) / 2
                        if sorted_tokens
                        else 0
                    )
                )

                stats = ChatTokenStats(
                    chat_id=cid,
                    thread_id=tid,
                    message_count=total_msgs,
                    total_tokens=total_tokens,
                    avg_tokens_per_message=round(avg_tokens, 1),
                    max_tokens_per_message=max(tokens_per_msg) if tokens_per_msg else 0,
                    median_tokens_per_message=round(median_tokens, 1),
                    user_message_count=user_msgs,
                    model_message_count=model_msgs,
                    user_tokens=user_tokens_total,
                    model_tokens=model_tokens_total,
                    has_embeddings=embedding_count > 0,
                    embedding_coverage_pct=(
                        round((embedding_count / total_msgs) * 100, 1)
                        if total_msgs > 0
                        else 0
                    ),
                )

                stats_list.append(stats)

            # Sort by total tokens (descending)
            stats_list.sort(key=lambda s: s.total_tokens, reverse=True)

            if limit:
                stats_list = stats_list[:limit]

            return stats_list

        finally:
            conn.close()

    async def find_heavy_messages(
        self, min_tokens: int = 500, limit: int = 20
    ) -> list[MessageTokenStats]:
        """
        Find messages with high token counts.

        Args:
            min_tokens: Minimum token threshold
            limit: Max results to return

        Returns:
            List of MessageTokenStats sorted by token count (descending)
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute(
                """
                SELECT id, chat_id, thread_id, role, text, media, embedding, ts
                FROM messages
                ORDER BY id DESC
                """
            )

            messages = []

            for row in cursor.fetchall():
                token_count = self._estimate_tokens(row["text"])

                if token_count >= min_tokens:
                    has_media = bool(row["media"] and row["media"] != "[]")

                    msg_stats = MessageTokenStats(
                        message_id=row["id"],
                        chat_id=row["chat_id"],
                        thread_id=row["thread_id"],
                        role=row["role"],
                        token_count=token_count,
                        text_length=len(row["text"]) if row["text"] else 0,
                        has_media=has_media,
                        has_embedding=bool(row["embedding"]),
                        timestamp=row["ts"],
                    )

                    messages.append(msg_stats)

            # Sort by token count
            messages.sort(key=lambda m: m.token_count, reverse=True)

            return messages[:limit]

        finally:
            conn.close()

    async def get_summary(self) -> dict[str, Any]:
        """Get overall database token usage summary."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute("SELECT COUNT(*) as total FROM messages")
            total_messages = cursor.fetchone()["total"]

            cursor = conn.execute("SELECT text FROM messages")
            all_texts = [row["text"] for row in cursor.fetchall()]

            total_tokens = sum(self._estimate_tokens(text) for text in all_texts)
            avg_tokens = total_tokens / total_messages if total_messages > 0 else 0

            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM messages WHERE embedding IS NOT NULL"
            )
            messages_with_embeddings = cursor.fetchone()["count"]

            return {
                "total_messages": total_messages,
                "total_tokens": total_tokens,
                "avg_tokens_per_message": round(avg_tokens, 1),
                "messages_with_embeddings": messages_with_embeddings,
                "embedding_coverage_pct": (
                    round((messages_with_embeddings / total_messages) * 100, 1)
                    if total_messages > 0
                    else 0
                ),
            }

        finally:
            conn.close()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit token usage in gryag conversations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "gryag.db",
        help="Path to SQLite database (default: ./gryag.db)",
    )

    parser.add_argument(
        "--chat-id",
        type=int,
        help="Analyze specific chat ID only",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Show top N token-heavy chats (default: 10)",
    )

    parser.add_argument(
        "--heavy-threshold",
        type=int,
        default=500,
        help="Minimum tokens for 'heavy message' (default: 500)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Export results to JSON file",
    )

    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Show only summary statistics",
    )

    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"Error: Database not found at {args.db_path}", file=sys.stderr)
        sys.exit(1)

    auditor = TokenAuditor(args.db_path)

    print("=== gryag Token Usage Audit ===\n")

    # Overall summary
    summary = await auditor.get_summary()
    print("Overall Statistics:")
    print(f"  Total messages: {summary['total_messages']:,}")
    print(f"  Total tokens: {summary['total_tokens']:,}")
    print(f"  Avg tokens/message: {summary['avg_tokens_per_message']}")
    print(f"  Embedding coverage: {summary['embedding_coverage_pct']}%")
    print()

    if args.summary_only:
        return

    # Chat statistics
    print(f"Top {args.top} Token-Heavy Chats:")
    print("-" * 80)

    chat_stats = await auditor.analyze_chats(chat_id=args.chat_id, limit=args.top)

    for i, stats in enumerate(chat_stats, 1):
        thread_info = f" (thread {stats.thread_id})" if stats.thread_id else ""
        print(f"\n{i}. Chat {stats.chat_id}{thread_info}")
        print(
            f"   Messages: {stats.message_count} ({stats.user_message_count} user, {stats.model_message_count} model)"
        )
        print(f"   Total tokens: {stats.total_tokens:,}")
        print(
            f"   Avg: {stats.avg_tokens_per_message} | Median: {stats.median_tokens_per_message} | Max: {stats.max_tokens_per_message}"
        )
        print(
            f"   User tokens: {stats.user_tokens:,} | Model tokens: {stats.model_tokens:,}"
        )
        print(f"   Embeddings: {stats.embedding_coverage_pct}% coverage")

    # Heavy messages
    print(f"\n\nHeaviest Messages (>= {args.heavy_threshold} tokens):")
    print("-" * 80)

    heavy_msgs = await auditor.find_heavy_messages(
        min_tokens=args.heavy_threshold, limit=20
    )

    if not heavy_msgs:
        print("  (none found)")
    else:
        for msg in heavy_msgs[:10]:
            print(f"\n  Message #{msg.message_id} (chat {msg.chat_id})")
            print(f"    Role: {msg.role}")
            print(f"    Tokens: {msg.token_count:,} ({msg.text_length} chars)")
            print(
                f"    Media: {'yes' if msg.has_media else 'no'} | Embedding: {'yes' if msg.has_embedding else 'no'}"
            )

    # Export if requested
    if args.output:
        export_data = {
            "summary": summary,
            "chat_stats": [asdict(s) for s in chat_stats],
            "heavy_messages": [asdict(m) for m in heavy_msgs],
        }

        with args.output.open("w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"\n\nResults exported to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
