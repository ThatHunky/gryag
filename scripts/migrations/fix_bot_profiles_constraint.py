#!/usr/bin/env python3
"""Fix bot_profiles table UNIQUE constraint issue.

The original schema had bot_id as UNIQUE, which prevents
creating multiple profiles (global + per-chat). This script
fixes the constraint.
"""

import sqlite3
import sys

DB_PATH = "gryag.db"


def main():
    print("🔧 Fixing bot_profiles UNIQUE constraint...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_profiles'"
    )
    if not cursor.fetchone():
        print("✅ bot_profiles table doesn't exist yet - no migration needed")
        conn.close()
        return 0

    # Check current schema
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bot_profiles'"
    )
    current_schema = cursor.fetchone()[0]

    if "bot_id INTEGER NOT NULL UNIQUE" in current_schema:
        print("⚠️  Found incorrect UNIQUE constraint on bot_id")
        print("   Recreating table with correct schema...")

        # Backup existing data
        cursor.execute("SELECT * FROM bot_profiles")
        existing_data = cursor.fetchall()
        print(f"   Backing up {len(existing_data)} existing profile(s)")

        # Drop and recreate
        cursor.execute("DROP TABLE IF EXISTS bot_profiles")

        # Create with correct schema
        cursor.execute(
            """
            CREATE TABLE bot_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                bot_username TEXT,
                bot_name TEXT,
                chat_id INTEGER,
                profile_version INTEGER DEFAULT 1,
                total_interactions INTEGER DEFAULT 0,
                positive_interactions INTEGER DEFAULT 0,
                negative_interactions INTEGER DEFAULT 0,
                effectiveness_score REAL DEFAULT 0.5,
                last_self_reflection INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(bot_id, chat_id)
            )
        """
        )

        # Restore data (if any)
        if existing_data:
            cursor.executemany(
                """
                INSERT INTO bot_profiles (
                    id, bot_id, bot_username, bot_name, chat_id,
                    profile_version, total_interactions, positive_interactions,
                    negative_interactions, effectiveness_score, last_self_reflection,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                existing_data,
            )
            print(f"   Restored {len(existing_data)} profile(s)")

        conn.commit()
        print("✅ bot_profiles table fixed successfully")

    else:
        print("✅ bot_profiles table already has correct schema")

    conn.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"❌ Migration failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
