#!/usr/bin/env python3
"""
Diagnostic script to identify potential token overflow issues.

Checks:
1. Message text lengths in the database
2. Metadata sizes
3. Embedding sizes (should NOT be sent to Gemini)
4. Recent context assembly token counts
5. Multi-level context token budgets

Run with: python scripts/diagnostics/check_token_overflow.py
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import Settings


def estimate_tokens(text: str) -> int:
    """Rough token estimation: words * 1.3"""
    if not text:
        return 0
    return int(len(text.split()) * 1.3)


def check_database_messages():
    """Check message sizes in the database."""
    db_path = Path("gryag.db")
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("DATABASE MESSAGE ANALYSIS")
    print("=" * 70)

    # Total message count
    cursor.execute("SELECT COUNT(*) as total FROM messages")
    total = cursor.fetchone()["total"]
    print(f"\n📊 Total messages: {total:,}")

    # Check text lengths
    cursor.execute(
        """
        SELECT 
            id,
            chat_id,
            user_id,
            role,
            LENGTH(text) as text_length,
            text
        FROM messages 
        WHERE text IS NOT NULL
        ORDER BY LENGTH(text) DESC 
        LIMIT 10
    """
    )

    print("\n🔍 Top 10 longest text messages:")
    print("-" * 70)
    for row in cursor.fetchall():
        text_len = row["text_length"]
        tokens = estimate_tokens(row["text"])
        text_preview = (
            (row["text"][:100] + "...") if len(row["text"]) > 100 else row["text"]
        )
        print(
            f"  ID {row['id']} | {row['role']:5s} | {text_len:,} chars | ~{tokens:,} tokens"
        )
        print(f"    Preview: {text_preview}")
        print()

    # Check media JSON sizes
    cursor.execute(
        """
        SELECT 
            id,
            chat_id,
            role,
            LENGTH(media) as media_length,
            media
        FROM messages 
        WHERE media IS NOT NULL
        ORDER BY LENGTH(media) DESC 
        LIMIT 5
    """
    )

    print("\n📸 Top 5 largest media JSON:")
    print("-" * 70)
    for row in cursor.fetchall():
        media_len = row["media_length"]
        try:
            media_data = json.loads(row["media"])
            media_count = (
                len(media_data.get("media", []))
                if isinstance(media_data, dict)
                else len(media_data)
            )
            print(
                f"  ID {row['id']} | {row['role']:5s} | {media_len:,} chars | {media_count} media items"
            )
        except json.JSONDecodeError as e:
            print(
                f"  ID {row['id']} | {row['role']:5s} | {media_len:,} chars | (invalid JSON: {e})"
            )
        except Exception as e:
            print(
                f"  ID {row['id']} | {row['role']:5s} | {media_len:,} chars | (error processing media: {e})"
            )

    # Check embedding sizes (these should NOT be sent to Gemini!)
    cursor.execute(
        """
        SELECT 
            COUNT(*) as count,
            AVG(LENGTH(embedding)) as avg_length,
            MAX(LENGTH(embedding)) as max_length
        FROM messages 
        WHERE embedding IS NOT NULL
    """
    )

    row = cursor.fetchone()
    print(f"\n🧬 Embedding statistics:")
    print("-" * 70)
    print(f"  Messages with embeddings: {row['count']:,}")
    print(f"  Average embedding JSON size: {int(row['avg_length'] or 0):,} chars")
    print(f"  Maximum embedding JSON size: {int(row['max_length'] or 0):,} chars")
    print(f"  ⚠️  NOTE: Embeddings should NEVER be sent to Gemini API!")

    # Check recent messages per chat
    cursor.execute(
        """
        SELECT 
            chat_id,
            COUNT(*) as msg_count,
            MAX(id) as latest_id
        FROM messages
        GROUP BY chat_id
        ORDER BY msg_count DESC
        LIMIT 5
    """
    )

    print(f"\n💬 Top 5 most active chats:")
    print("-" * 70)
    for row in cursor.fetchall():
        print(
            f"  Chat {row['chat_id']}: {row['msg_count']:,} messages (latest ID: {row['latest_id']})"
        )

    conn.close()


def check_context_settings():
    """Check context-related settings."""
    settings = Settings()

    print("\n" + "=" * 70)
    print("CONTEXT CONFIGURATION")
    print("=" * 70)

    print(f"\n📐 Token budgets:")
    print(f"  context_token_budget: {settings.context_token_budget:,} tokens")
    print(f"  max_turns: {settings.max_turns}")
    print(f"  enable_multi_level_context: {settings.enable_multi_level_context}")

    if settings.enable_multi_level_context:
        # Calculate allocations
        total = settings.context_token_budget
        print(f"\n  Multi-level allocations (from {total:,} tokens):")
        print(f"    - Immediate (20%): {int(total * 0.20):,} tokens")
        print(f"    - Recent (30%): {int(total * 0.30):,} tokens")
        print(f"    - Relevant (25%): {int(total * 0.25):,} tokens")
        print(f"    - Background (15%): {int(total * 0.15):,} tokens")
        print(f"    - Episodic (10%): {int(total * 0.10):,} tokens")

    print(f"\n🖼️  Media settings:")
    print(
        f"  gemini_max_media_items: {getattr(settings, 'gemini_max_media_items', 28)}"
    )

    print(f"\n🔍 Hybrid search:")
    print(f"  enable_hybrid_search: {settings.enable_hybrid_search}")
    print(f"  hybrid_search_limit: {settings.hybrid_search_limit}")

    print(f"\n📚 Profile settings:")
    print(f"  enable_user_profiles: {settings.enable_user_profiles}")
    print(f"  max_facts_per_user: {settings.max_facts_per_user}")

    print(f"\n💾 Episodic memory:")
    print(f"  enable_episodic_memory: {settings.enable_episodic_memory}")


def simulate_context_assembly():
    """Simulate a context assembly to estimate sizes."""
    settings = Settings()

    print("\n" + "=" * 70)
    print("CONTEXT ASSEMBLY SIMULATION")
    print("=" * 70)

    print(f"\n🔬 Simulating typical message context assembly...")

    # Simulate typical message sizes
    avg_user_msg = "Can you help me with this problem? I'm trying to understand how to fix this issue."
    avg_bot_msg = "Звісно! Зараз розберемося. Спочатку треба..."

    user_tokens = estimate_tokens(avg_user_msg)
    bot_tokens = estimate_tokens(avg_bot_msg)

    print(f"\n  Average user message: ~{user_tokens} tokens")
    print(f"  Average bot message: ~{bot_tokens} tokens")
    print(f"  Average turn (user + bot): ~{user_tokens + bot_tokens} tokens")

    # Calculate full history
    max_turns = settings.max_turns
    estimated_history = (user_tokens + bot_tokens) * max_turns

    print(f"\n  With max_turns={max_turns}:")
    print(f"    Estimated history size: ~{estimated_history:,} tokens")

    # Add system prompt estimate
    system_prompt_tokens = 500  # Approximate
    print(f"    System prompt: ~{system_prompt_tokens} tokens")

    # Add profile context estimate
    profile_tokens = 200  # Approximate
    print(f"    Profile context: ~{profile_tokens} tokens")

    total_estimated = estimated_history + system_prompt_tokens + profile_tokens
    print(f"\n  📊 Total estimated: ~{total_estimated:,} tokens")

    # Check against Gemini limits
    gemini_limit = 1_048_576  # Gemini 2.0 Flash limit
    print(f"\n  Gemini API limit: {gemini_limit:,} tokens")

    if total_estimated > gemini_limit:
        print(
            f"  ⚠️  WARNING: Estimated tokens exceed limit by {total_estimated - gemini_limit:,} tokens!"
        )
    else:
        print(f"  ✅ Safe margin: {gemini_limit - total_estimated:,} tokens remaining")


def main():
    """Run all diagnostic checks."""
    print("\n" + "=" * 70)
    print("🔍 TOKEN OVERFLOW DIAGNOSTIC TOOL")
    print("=" * 70)
    print("\nChecking for potential token overflow issues...")

    check_database_messages()
    check_context_settings()
    simulate_context_assembly()

    print("\n" + "=" * 70)
    print("✅ DIAGNOSTIC COMPLETE")
    print("=" * 70)
    print("\n💡 If you see token overflow errors:")
    print("  1. Check if embeddings are being sent to Gemini (they shouldn't be!)")
    print("  2. Reduce context_token_budget in .env")
    print("  3. Reduce max_turns in .env")
    print("  4. Check for abnormally long messages in the database")
    print("  5. Verify media items are being limited (max 28 for Gemma models)")
    print()


if __name__ == "__main__":
    main()
