#!/usr/bin/env python3
"""
Diagnostic: Check fact storage/retrieval for all recent users.

This helps diagnose why users might not see their facts.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.user_profile_adapter import UserProfileStoreAdapter
import aiosqlite


async def main():
    """Run diagnostics."""
    db_path = Path(__file__).parent.parent.parent / "gryag.db"

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return

    print("=" * 80)
    print("FACT STORAGE/RETRIEVAL DIAGNOSTIC")
    print("=" * 80)

    # Initialize adapter
    adapter = UserProfileStoreAdapter(db_path)
    await adapter.init()

    # Get all users with facts in the last 24 hours
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Get recent facts
        cursor = await db.execute(
            """
            SELECT DISTINCT entity_id, chat_context 
            FROM facts 
            WHERE entity_type='user' 
              AND created_at > strftime('%s', 'now') - 86400
            ORDER BY entity_id
        """
        )
        recent_users = await cursor.fetchall()

    if not recent_users:
        print("\n⚠️  No facts created in the last 24 hours")
        return

    print(f"\n📊 Found {len(recent_users)} user(s) with recent facts\n")

    for row in recent_users:
        user_id = row[0]
        chat_context = row[1]

        print(f"\n{'='*80}")
        print(f"👤 User ID: {user_id}")
        print(f"💬 Chat Context: {chat_context}")
        print(f"{'='*80}\n")

        # Test 1: Direct query
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, fact_category, fact_key, fact_value, is_active, confidence
                FROM facts
                WHERE entity_type='user' AND entity_id=? AND chat_context=?
                ORDER BY created_at DESC
            """,
                (user_id, chat_context),
            )
            direct_facts = await cursor.fetchall()

        print(f"✅ Direct SQL Query: {len(direct_facts)} facts")
        for fact in direct_facts:
            active = "✓" if fact[4] else "✗"
            print(
                f"   [{fact[0]}] {active} {fact[1]}.{fact[2]} = {fact[3][:40]}... (conf: {fact[5]:.2f})"
            )

        # Test 2: Via adapter (all facts)
        adapter_facts_all = await adapter.get_facts(
            user_id=user_id, chat_id=chat_context, limit=100, min_confidence=0.0
        )

        print(f"\n✅ Adapter Query (all): {len(adapter_facts_all)} facts")
        for fact in adapter_facts_all:
            active = "✓" if fact.get("is_active", 1) else "✗"
            print(
                f"   [{fact['id']}] {active} {fact['fact_type']}.{fact['fact_key']} = {fact['fact_value'][:40]}..."
            )

        # Test 3: Via adapter (active only)
        # The adapter actually queries the repository which filters by is_active=1 by default
        active_count = len([f for f in adapter_facts_all if f.get("is_active", 1) == 1])

        print(f"\n✅ Active Facts Only: {active_count} facts")

        # Test 4: Simulate /gryagfacts command
        print(f"\n🔍 Simulating /gryagfacts command...")
        facts_for_command = await adapter.get_facts(
            user_id=user_id,
            chat_id=chat_context,
            fact_type=None,  # No filter
            limit=20,
        )

        if not facts_for_command:
            print(f"   ❌ PROBLEM: /gryagfacts would show NO FACTS!")
            print(f"   But direct query found {len(direct_facts)} facts")
            print(f"   Active facts: {active_count}")

            # Diagnose why
            if active_count == 0:
                print(f"   💡 CAUSE: All facts are INACTIVE (is_active=0)")
                print(f"   💡 SOLUTION: Reactivate facts or check why they're inactive")
            else:
                print(
                    f"   💡 CAUSE: Unknown - adapter query returning empty despite active facts"
                )
        else:
            print(f"   ✅ /gryagfacts would show {len(facts_for_command)} facts")
            for fact in facts_for_command:
                print(
                    f"      - {fact['fact_type']}.{fact['fact_key']}: {fact['fact_value'][:40]}..."
                )

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")

    # Overall stats
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) as inactive
            FROM facts WHERE entity_type='user'
        """
        )
        row = await cursor.fetchone()
        total, active, inactive = row[0], row[1], row[2]

    print(f"📊 Total user facts: {total}")
    print(f"   ✅ Active: {active} ({active/total*100:.1f}%)")
    print(f"   ❌ Inactive: {inactive} ({inactive/total*100:.1f}%)")

    if inactive > total * 0.3:  # More than 30% inactive
        print(f"\n⚠️  WARNING: {inactive/total*100:.1f}% of facts are inactive!")
        print(f"   This may indicate a data migration or deletion issue.")
        print(f"   Consider investigating why so many facts are marked inactive.")

    print(f"\n✅ Diagnostic complete!")


if __name__ == "__main__":
    asyncio.run(main())
