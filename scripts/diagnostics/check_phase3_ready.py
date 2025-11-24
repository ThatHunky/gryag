#!/usr/bin/env python3
"""
Quick Phase 3 readiness check.

Checks database state without requiring bot dependencies.
Run: python3 check_phase3_ready.py
"""

import sqlite3
from pathlib import Path


def check_readiness():
    """Check if Phase 3 is ready for testing."""
    db_path = Path(__file__).parent / "gryag.db"

    print("=" * 70)
    print("Phase 3 Readiness Check")
    print("=" * 70)
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check 1: Phase 3 tables exist
    print("✓ Database tables:")
    required_tables = [
        "conversation_windows",
        "fact_quality_metrics",
        "message_metadata",
    ]
    for table in required_tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"    • {table:30} exists ({count} records)")

    # Check 2: Embedding column
    print()
    print("✓ Quality processing support:")
    cursor.execute("PRAGMA table_info(user_facts)")
    columns = [col[1] for col in cursor.fetchall()]
    if "embedding" in columns:
        print("    • user_facts.embedding column: EXISTS")
    else:
        print("    ⚠ user_facts.embedding column: MISSING (need to add)")
        print("      This is required for semantic deduplication")

    # Check 3: Historical data
    print()
    print("✓ Historical data available:")
    cursor.execute("SELECT COUNT(*) FROM messages")
    message_count = cursor.fetchone()[0]
    print(f"    • {message_count} messages in database")

    cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM messages")
    chat_count = cursor.fetchone()[0]
    print(f"    • {chat_count} unique chats")

    cursor.execute("SELECT COUNT(*) FROM user_facts")
    fact_count = cursor.fetchone()[0]
    print(f"    • {fact_count} user facts stored")

    # Check 4: Window-extracted facts
    print()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM user_facts
        WHERE evidence_text LIKE '%extracted_from_window%'
    """
    )
    window_facts = cursor.fetchone()[0]

    if window_facts > 0:
        print("✓ Phase 3 is ACTIVE:")
        print(f"    • {window_facts} facts extracted from conversation windows")

        # Show recent window activity
        cursor.execute(
            """
            SELECT 
                COUNT(*) as windows,
                SUM(message_count) as total_messages,
                MAX(created_at) as last_window
            FROM conversation_windows
        """
        )
        row = cursor.fetchone()
        if row[0] > 0:
            print(f"    • {row[0]} windows processed")
            print(f"    • {row[1]} messages analyzed")
            print(f"    • Last window: {row[2]}")

        # Show quality processing stats
        cursor.execute(
            """
            SELECT 
                COUNT(*) as runs,
                AVG(duplicates_removed) as avg_dupes,
                AVG(conflicts_resolved) as avg_conflicts
            FROM fact_quality_metrics
        """
        )
        row = cursor.fetchone()
        if row[0] > 0:
            print()
            print("✓ Quality processing:")
            print(f"    • {row[0]} quality checks performed")
            print(f"    • Avg duplicates removed: {row[1]:.1f}")
            print(f"    • Avg conflicts resolved: {row[2]:.1f}")

        print()
        print("=" * 70)
        print("✓ Phase 3 is WORKING! Continuous learning is active.")
        print("=" * 70)

    else:
        print("⚠ Phase 3 NOT YET ACTIVE:")
        print("    • No window-extracted facts found")
        print("    • Bot needs to process some conversations")

        print()
        print("Next steps to activate Phase 3:")
        print("  1. Ensure .env has: ENABLE_CONTINUOUS_MONITORING=true")
        print("  2. Start bot: python -m app.main (or docker-compose up)")
        print("  3. Send 8-10 messages in a test chat")
        print("  4. Wait 3+ minutes for window timeout")
        print("  5. Check logs for: 'Extracted N facts from window'")
        print("  6. Run this script again to verify")
        print()
        print("=" * 70)
        print("⚠ Phase 3 ready but NOT YET ACTIVE")
        print("=" * 70)

    conn.close()

    print()
    print("Configuration checklist:")
    print("  [ ] ENABLE_CONTINUOUS_MONITORING=true")
    print("  [ ] ENABLE_MESSAGE_FILTERING=false (recommended for testing)")
    print("  [ ] ENABLE_ASYNC_PROCESSING=false (recommended for testing)")
    print()
    print("For detailed testing, see: PHASE_3_TESTING_GUIDE.md")


if __name__ == "__main__":
    check_readiness()
