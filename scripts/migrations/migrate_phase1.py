#!/usr/bin/env python3
"""
Phase 1 Migration: Memory and Context Improvements

This script:
1. Applies the new schema additions (FTS, episodes, fact relationships, etc.)
2. Populates FTS index from existing messages
3. Creates initial message_importance records
4. Validates the migration

Run after updating db/schema.sql.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

import aiosqlite

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

DB_PATH = Path("./gryag.db")
SCHEMA_PATH = Path("./db/schema.sql")


async def apply_schema(db_path: Path) -> None:
    """Apply schema from schema.sql file."""
    if not SCHEMA_PATH.exists():
        LOGGER.error(f"Schema file not found: {SCHEMA_PATH}")
        sys.exit(1)

    LOGGER.info(f"Applying schema from {SCHEMA_PATH}")

    async with aiosqlite.connect(db_path) as db:
        with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            schema_sql = fh.read()

        await db.executescript(schema_sql)
        await db.commit()

    LOGGER.info("Schema applied successfully")


async def populate_fts_index(db_path: Path) -> None:
    """Populate FTS index from existing messages."""
    LOGGER.info("Populating FTS index from existing messages...")

    async with aiosqlite.connect(db_path) as db:
        # Check if messages_fts exists
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ) as cursor:
            if not await cursor.fetchone():
                LOGGER.warning(
                    "messages_fts table doesn't exist, skipping FTS population"
                )
                return

        # Count existing messages
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE text IS NOT NULL"
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        if total == 0:
            LOGGER.info("No messages to index")
            return

        LOGGER.info(f"Indexing {total} messages...")

        # Clear existing FTS data (triggers will re-populate)
        try:
            await db.execute("DELETE FROM messages_fts")
        except Exception as e:
            LOGGER.warning(f"Could not clear FTS table (might be corrupted): {e}")
            # Drop and recreate FTS table
            LOGGER.info("Recreating FTS table...")
            await db.execute("DROP TABLE IF EXISTS messages_fts")
            await db.execute(
                """
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    text,
                    content='messages',
                    content_rowid='id',
                    tokenize='porter unicode61'
                )
            """
            )
            await db.commit()

        # Batch insert into FTS
        batch_size = 1000
        async with db.execute(
            "SELECT id, text FROM messages WHERE text IS NOT NULL ORDER BY id"
        ) as cursor:
            batch = []
            count = 0

            async for row in cursor:
                batch.append((row[0], row[1]))

                if len(batch) >= batch_size:
                    await db.executemany(
                        "INSERT INTO messages_fts(rowid, text) VALUES (?, ?)", batch
                    )
                    count += len(batch)
                    LOGGER.info(f"Indexed {count}/{total} messages...")
                    batch = []

            # Insert remaining
            if batch:
                await db.executemany(
                    "INSERT INTO messages_fts(rowid, text) VALUES (?, ?)", batch
                )
                count += len(batch)

        await db.commit()
        LOGGER.info(f"FTS index populated with {count} messages")


async def create_initial_importance_records(db_path: Path) -> None:
    """Create initial message_importance records for existing messages."""
    LOGGER.info("Creating initial message importance records...")

    async with aiosqlite.connect(db_path) as db:
        # Check if table exists
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='message_importance'"
        ) as cursor:
            if not await cursor.fetchone():
                LOGGER.warning("message_importance table doesn't exist, skipping")
                return

        # Count messages without importance records
        async with db.execute(
            """
            SELECT COUNT(*) FROM messages m
            WHERE NOT EXISTS (
                SELECT 1 FROM message_importance mi WHERE mi.message_id = m.id
            )
            """
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        if total == 0:
            LOGGER.info("All messages already have importance records")
            return

        LOGGER.info(f"Creating importance records for {total} messages...")

        # Create records in batches
        batch_size = 1000
        now = int(time.time())

        async with db.execute(
            """
            SELECT id FROM messages m
            WHERE NOT EXISTS (
                SELECT 1 FROM message_importance mi WHERE mi.message_id = m.id
            )
            ORDER BY id
            """
        ) as cursor:
            batch = []
            count = 0

            async for row in cursor:
                # Default importance score of 0.5, retention 90 days
                batch.append((row[0], 0.5, 0, None, 90, 0, now, now))

                if len(batch) >= batch_size:
                    await db.executemany(
                        """
                        INSERT INTO message_importance 
                        (message_id, importance_score, access_count, last_accessed, 
                         retention_days, consolidated, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        batch,
                    )
                    count += len(batch)
                    LOGGER.info(f"Created {count}/{total} importance records...")
                    batch = []

            # Insert remaining
            if batch:
                await db.executemany(
                    """
                    INSERT INTO message_importance 
                    (message_id, importance_score, access_count, last_accessed, 
                     retention_days, consolidated, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                count += len(batch)

        await db.commit()
        LOGGER.info(f"Created {count} importance records")


async def validate_migration(db_path: Path) -> bool:
    """Validate that migration completed successfully."""
    LOGGER.info("Validating migration...")

    async with aiosqlite.connect(db_path) as db:
        # Check new tables exist
        required_tables = [
            "messages_fts",
            "message_importance",
            "episodes",
            "episode_accesses",
            "fact_relationships",
            "fact_versions",
            "fact_clusters",
        ]

        for table in required_tables:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ) as cursor:
                if not await cursor.fetchone():
                    LOGGER.error(f"Table {table} not found!")
                    return False

        LOGGER.info("All required tables exist")

        # Check FTS index
        async with db.execute("SELECT COUNT(*) FROM messages_fts") as cursor:
            row = await cursor.fetchone()
            fts_count = row[0] if row else 0

        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE text IS NOT NULL"
        ) as cursor:
            row = await cursor.fetchone()
            msg_count = row[0] if row else 0

        if fts_count != msg_count:
            LOGGER.warning(f"FTS count ({fts_count}) != message count ({msg_count})")
            # This is OK if some messages have NULL text
        else:
            LOGGER.info(f"FTS index has {fts_count} entries")

        # Check indexes exist
        required_indexes = [
            "idx_messages_ts",
            "idx_messages_user_ts",
            "idx_episodes_chat",
            "idx_fact_relationships_fact1",
            "idx_message_importance_score",
        ]

        for index in required_indexes:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index,),
            ) as cursor:
                if not await cursor.fetchone():
                    LOGGER.warning(f"Index {index} not found (may be OK)")

        LOGGER.info("Validation complete")

    return True


async def main() -> None:
    """Run migration."""
    if not DB_PATH.exists():
        LOGGER.error(f"Database not found: {DB_PATH}")
        LOGGER.info("Run the bot first to create the database")
        sys.exit(1)

    LOGGER.info("=" * 80)
    LOGGER.info("Phase 1 Migration: Memory and Context Improvements")
    LOGGER.info("=" * 80)

    # Backup recommendation
    LOGGER.warning(f"It's recommended to backup {DB_PATH} before proceeding")
    response = input("Continue with migration? (yes/no): ")
    if response.lower() not in ("yes", "y"):
        LOGGER.info("Migration cancelled")
        return

    try:
        # Step 1: Apply schema
        await apply_schema(DB_PATH)

        # Step 2: Populate FTS index
        await populate_fts_index(DB_PATH)

        # Step 3: Create initial importance records
        await create_initial_importance_records(DB_PATH)

        # Step 4: Validate
        success = await validate_migration(DB_PATH)

        if success:
            LOGGER.info("=" * 80)
            LOGGER.info("Migration completed successfully!")
            LOGGER.info("=" * 80)
        else:
            LOGGER.error("Migration validation failed - please review errors above")
            sys.exit(1)

    except Exception as e:
        LOGGER.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
