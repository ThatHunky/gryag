#!/usr/bin/env python3
"""
Migrate from separate user_facts and chat_facts tables to unified facts table.

This script:
1. Creates new unified facts table
2. Migrates all data from user_facts and chat_facts
3. Fixes misplaced chat facts (user_id < 0 in user_facts)
4. Validates data integrity
5. Keeps old tables as backup (_old suffix)

Usage:
    python scripts/migrations/migrate_to_unified_facts.py [--db-path gryag.db] [--dry-run]
"""

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


UNIFIED_FACTS_SCHEMA = """
-- Unified facts table (replaces user_facts and chat_facts)
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Entity identification
    entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'chat')),
    entity_id INTEGER NOT NULL,  -- user_id or chat_id
    chat_context INTEGER,  -- chat_id where this was learned (for user facts only)
    
    -- Fact taxonomy (unified categories)
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        -- User-level categories
        'personal', 'preference', 'skill', 'trait', 'opinion', 'relationship',
        -- Chat-level categories
        'tradition', 'rule', 'norm', 'topic', 'culture', 'event', 'shared_knowledge'
    )),
    
    -- Fact content
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    fact_description TEXT,
    
    -- Confidence and evidence
    confidence REAL DEFAULT 0.7 CHECK(confidence >= 0 AND confidence <= 1),
    evidence_count INTEGER DEFAULT 1,
    evidence_text TEXT,
    source_message_id INTEGER,
    
    -- Consensus (for chat facts)
    participant_consensus REAL,
    participant_ids TEXT,  -- JSON array
    
    -- Lifecycle
    first_observed INTEGER NOT NULL,
    last_reinforced INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,
    
    -- Metadata
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    
    -- Embedding for semantic search
    embedding TEXT,
    
    -- Composite unique constraint
    UNIQUE(entity_type, entity_id, chat_context, fact_category, fact_key)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_chat_context ON facts(chat_context) WHERE entity_type = 'user';
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(fact_category);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence);
CREATE INDEX IF NOT EXISTS idx_facts_last_reinforced ON facts(last_reinforced);
"""


def get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Get row counts from all fact tables."""
    cursor = conn.cursor()
    counts = {}

    for table in ["user_facts", "chat_facts", "facts"]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = 0

    return counts


def backup_old_tables(conn: sqlite3.Connection) -> None:
    """Rename old tables with _old suffix for safety."""
    cursor = conn.cursor()

    logger.info("Backing up old tables...")

    # Check if old tables exist
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts'"
    )
    if cursor.fetchone():
        cursor.execute("ALTER TABLE user_facts RENAME TO user_facts_old")
        logger.info("Renamed user_facts → user_facts_old")

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_facts'"
    )
    if cursor.fetchone():
        cursor.execute("ALTER TABLE chat_facts RENAME TO chat_facts_old")
        logger.info("Renamed chat_facts → chat_facts_old")

    conn.commit()


def create_unified_table(conn: sqlite3.Connection) -> None:
    """Create the new unified facts table."""
    logger.info("Creating unified facts table...")
    cursor = conn.cursor()
    cursor.executescript(UNIFIED_FACTS_SCHEMA)
    conn.commit()
    logger.info("Unified facts table created successfully")


def migrate_user_facts(conn: sqlite3.Connection) -> int:
    """
    Migrate data from user_facts_old to unified facts table.

    Handles both:
    - Regular user facts (user_id > 0)
    - Misplaced chat facts (user_id < 0)

    Returns number of rows migrated.
    """
    logger.info("Migrating user_facts...")
    cursor = conn.cursor()

    # Check if old table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts_old'"
    )
    if not cursor.fetchone():
        logger.warning("user_facts_old table not found, skipping")
        return 0

    # Migrate with entity_type auto-detection
    cursor.execute(
        """
        INSERT INTO facts (
            entity_type,
            entity_id,
            chat_context,
            fact_category,
            fact_key,
            fact_value,
            confidence,
            evidence_count,
            evidence_text,
            source_message_id,
            first_observed,
            last_reinforced,
            is_active,
            created_at,
            updated_at,
            embedding
        )
        SELECT 
            CASE 
                WHEN user_id < 0 THEN 'chat'
                ELSE 'user'
            END as entity_type,
            CASE 
                WHEN user_id < 0 THEN user_id
                ELSE user_id
            END as entity_id,
            CASE 
                WHEN user_id < 0 THEN NULL
                ELSE chat_id
            END as chat_context,
            fact_type as fact_category,
            fact_key,
            fact_value,
            confidence,
            1 as evidence_count,
            evidence_text,
            source_message_id,
            created_at as first_observed,
            COALESCE(last_mentioned, updated_at, created_at) as last_reinforced,
            is_active,
            created_at,
            updated_at,
            embedding
        FROM user_facts_old
    """
    )

    migrated = cursor.rowcount
    conn.commit()

    # Count misplaced chat facts
    cursor.execute("SELECT COUNT(*) FROM user_facts_old WHERE user_id < 0")
    misplaced = cursor.fetchone()[0]

    logger.info(f"Migrated {migrated} rows from user_facts")
    if misplaced > 0:
        logger.info(f"  ✓ Fixed {misplaced} misplaced chat facts (user_id < 0)")

    return migrated


def migrate_chat_facts(conn: sqlite3.Connection) -> int:
    """
    Migrate data from chat_facts_old to unified facts table.

    Returns number of rows migrated.
    """
    logger.info("Migrating chat_facts...")
    cursor = conn.cursor()

    # Check if old table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_facts_old'"
    )
    if not cursor.fetchone():
        logger.warning("chat_facts_old table not found, skipping")
        return 0

    cursor.execute(
        """
        INSERT INTO facts (
            entity_type,
            entity_id,
            chat_context,
            fact_category,
            fact_key,
            fact_value,
            fact_description,
            confidence,
            evidence_count,
            participant_consensus,
            first_observed,
            last_reinforced,
            is_active,
            decay_rate,
            created_at,
            updated_at
        )
        SELECT 
            'chat' as entity_type,
            chat_id as entity_id,
            NULL as chat_context,
            fact_category,
            fact_key,
            fact_value,
            fact_description,
            confidence,
            evidence_count,
            participant_consensus,
            first_observed,
            last_reinforced,
            is_active,
            decay_rate,
            created_at,
            updated_at
        FROM chat_facts_old
    """
    )

    migrated = cursor.rowcount
    conn.commit()
    logger.info(f"Migrated {migrated} rows from chat_facts")

    return migrated


def validate_migration(
    conn: sqlite3.Connection, initial_counts: dict[str, int]
) -> bool:
    """
    Validate that migration was successful.

    Checks:
    - All rows migrated (no data loss)
    - Entity types correct
    - No duplicate keys

    Returns True if valid, False otherwise.
    """
    logger.info("Validating migration...")
    cursor = conn.cursor()

    # Check total count
    cursor.execute("SELECT COUNT(*) FROM facts")
    final_count = cursor.fetchone()[0]
    expected_count = initial_counts.get("user_facts", 0) + initial_counts.get(
        "chat_facts", 0
    )

    if final_count != expected_count:
        logger.error(
            f"❌ Row count mismatch: expected {expected_count}, got {final_count}"
        )
        return False

    logger.info(f"✓ Row count matches: {final_count}")

    # Check entity types
    cursor.execute("SELECT entity_type, COUNT(*) FROM facts GROUP BY entity_type")
    entity_counts = dict(cursor.fetchall())
    logger.info(f"✓ Entity types: {entity_counts}")

    # Check for duplicates
    cursor.execute(
        """
        SELECT entity_type, entity_id, chat_context, fact_category, fact_key, COUNT(*)
        FROM facts
        GROUP BY entity_type, entity_id, chat_context, fact_category, fact_key
        HAVING COUNT(*) > 1
    """
    )
    duplicates = cursor.fetchall()

    if duplicates:
        logger.error(f"❌ Found {len(duplicates)} duplicate fact keys")
        for dup in duplicates[:5]:  # Show first 5
            logger.error(f"   {dup}")
        return False

    logger.info("✓ No duplicate fact keys")

    # Check chat facts were migrated correctly
    cursor.execute("SELECT COUNT(*) FROM facts WHERE entity_type = 'chat'")
    chat_fact_count = cursor.fetchone()[0]

    # Count misplaced chat facts from old user_facts
    try:
        cursor.execute("SELECT COUNT(*) FROM user_facts_old WHERE user_id < 0")
        result = cursor.fetchone()
        misplaced_count = result[0] if result else 0
    except sqlite3.OperationalError:
        misplaced_count = 0

    expected_chat_facts = initial_counts.get("chat_facts", 0) + misplaced_count
    if chat_fact_count != expected_chat_facts:
        logger.warning(
            f"⚠ Chat fact count: expected {expected_chat_facts}, got {chat_fact_count}"
        )
    else:
        logger.info(f"✓ Chat facts migrated correctly: {chat_fact_count}")

    logger.info("✅ Migration validation passed!")
    return True


def rollback_migration(conn: sqlite3.Connection) -> None:
    """Rollback migration by restoring old tables."""
    logger.info("Rolling back migration...")
    cursor = conn.cursor()

    # Drop new table
    cursor.execute("DROP TABLE IF EXISTS facts")

    # Restore old tables
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts_old'"
    )
    if cursor.fetchone():
        cursor.execute("ALTER TABLE user_facts_old RENAME TO user_facts")

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_facts_old'"
    )
    if cursor.fetchone():
        cursor.execute("ALTER TABLE chat_facts_old RENAME TO chat_facts")

    conn.commit()
    logger.info("✓ Rollback complete")


def main() -> int:
    """Run the migration."""
    parser = argparse.ArgumentParser(description="Migrate to unified facts table")
    parser.add_argument(
        "--db-path",
        default="gryag.db",
        help="Path to SQLite database (default: gryag.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback migration and restore old tables",
    )

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return 1

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))

        if args.rollback:
            rollback_migration(conn)
            return 0

        # Get initial counts
        initial_counts = get_table_counts(conn)
        logger.info(f"Initial counts: {initial_counts}")

        if args.dry_run:
            logger.info("DRY RUN - no changes will be made")
            logger.info(
                f"Would migrate {initial_counts.get('user_facts', 0)} user facts"
            )
            logger.info(
                f"Would migrate {initial_counts.get('chat_facts', 0)} chat facts"
            )
            return 0

        # Backup old tables
        backup_old_tables(conn)

        # Create new table
        create_unified_table(conn)

        # Migrate data
        user_count = migrate_user_facts(conn)
        chat_count = migrate_chat_facts(conn)

        logger.info(f"Total migrated: {user_count + chat_count} facts")

        # Validate
        if not validate_migration(conn, initial_counts):
            logger.error("❌ Validation failed! Rolling back...")
            rollback_migration(conn)
            return 1

        logger.info("✅ Migration completed successfully!")
        logger.info("Old tables preserved as user_facts_old and chat_facts_old")
        logger.info("You can drop them after verifying everything works")

        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
