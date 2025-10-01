#!/usr/bin/env python3
"""Add embedding column to user_facts table."""

import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "gryag.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if column exists
    cursor.execute("PRAGMA table_info(user_facts)")
    columns = [col[1] for col in cursor.fetchall()]

    if "embedding" in columns:
        print("✓ Embedding column already exists")
    else:
        # Add column
        cursor.execute("ALTER TABLE user_facts ADD COLUMN embedding TEXT")
        conn.commit()
        print("✓ Embedding column added to user_facts table")

except Exception as e:
    print(f"✗ Error: {e}")
finally:
    conn.close()
