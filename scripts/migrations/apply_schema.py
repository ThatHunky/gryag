#!/usr/bin/env python3
"""
Apply Phase 3 schema updates to database.

This script updates the database schema without starting the bot.
Run: python3 apply_schema.py
"""

import sqlite3
from pathlib import Path


def apply_schema():
    """Apply schema.sql to database."""
    db_path = Path(__file__).parent / "gryag.db"
    schema_path = Path(__file__).parent / "db" / "schema.sql"

    print("Applying schema updates...")
    print(f"  Database: {db_path}")
    print(f"  Schema:   {schema_path}")
    print()

    # Read schema
    with open(schema_path) as f:
        schema_sql = f.read()

    # Apply to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Execute schema
        cursor.executescript(schema_sql)
        conn.commit()

        # Check what tables exist now
        cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """
        )
        tables = [row[0] for row in cursor.fetchall()]

        print("✓ Schema applied successfully")
        print(f"  Found {len(tables)} tables:")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"    • {table:30} {count:>6} records")

        # Check for Phase 3 tables specifically
        phase3_tables = [
            "conversation_windows",
            "fact_quality_metrics",
            "message_metadata",
        ]

        print()
        print("Phase 3 tables:")
        for table in phase3_tables:
            if table in tables:
                print(f"  ✓ {table}")
            else:
                print(f"  ✗ {table} (missing)")

    except Exception as e:
        print(f"✗ Error applying schema: {e}")
        return 1
    finally:
        conn.close()

    print()
    print("✓ Done! Now run: python3 test_phase3.py")
    return 0


if __name__ == "__main__":
    exit(apply_schema())
