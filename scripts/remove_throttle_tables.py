"""Remove throttle-related database tables."""

import asyncio
from pathlib import Path

import aiosqlite


async def migrate():
    """Remove throttle tables from database."""
    db_path = Path("./gryag.db")

    if not db_path.exists():
        print("❌ Database not found at ./gryag.db")
        return

    async with aiosqlite.connect(db_path) as db:
        # Backup first
        backup_path = "gryag.db.pre-throttle-removal"
        print(f"📦 Creating backup: {backup_path}")
        await db.execute(f"VACUUM INTO '{backup_path}'")
        print(f"✅ Backup created: {backup_path}")

        # Drop tables
        print("🗑️  Dropping throttle tables...")
        await db.execute("DROP TABLE IF EXISTS quotas")
        await db.execute("DROP TABLE IF EXISTS notices")

        await db.commit()
        print("✅ Throttle tables removed successfully")
        print("\n📊 Remaining tables:")

        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = await cursor.fetchall()
            for table in tables:
                print(f"   - {table[0]}")


if __name__ == "__main__":
    asyncio.run(migrate())
