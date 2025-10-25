#!/usr/bin/env python3
"""Utility to wipe and reinitialize the gryag SQLite database.

This script deletes the configured database file and reapplies the canonical
schema from ``db/schema.sql``. Use this to start from a clean slate when
testing memory features.

Usage:
    python scripts/reset_database.py --force

Add ``--backup`` if you want to keep a timestamped copy before wiping.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on sys.path so imports work regardless of CWD
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env if present
load_dotenv(PROJECT_ROOT / ".env")


def resolve_db_path() -> Path:
    """Resolve the database path from environment (defaults to ./gryag.db)."""
    raw_path = os.environ.get("DB_PATH", "./gryag.db")
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()
    return db_path


def apply_schema(db_path: Path, schema_path: Path) -> None:
    """Create a fresh database from the canonical schema."""
    schema_sql = schema_path.read_text(encoding="utf-8")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        conn.commit()


def backup_database(db_path: Path, backups_dir: Path | None) -> Path:
    """Create a timestamped backup copy of the existing database."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target_dir = backups_dir or db_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"{db_path.name}.bak.{timestamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def confirm(force: bool) -> bool:
    """Ask the user to confirm destructive action unless --force is set."""
    if force:
        return True

    answer = input(
        "This will DELETE the current database and recreate an empty one. "
        "Type 'reset' to continue: "
    ).strip()
    return answer.lower() == "reset"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Save a timestamped backup before wiping the database.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Optional directory for storing backups (defaults next to DB).",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        help="Path to schema.sql (defaults to repo db/schema.sql).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    db_path = resolve_db_path()
    schema_path = args.schema or (PROJECT_ROOT / "db" / "schema.sql")

    if not schema_path.exists():
        print(f"✗ Schema file not found: {schema_path}")
        return 1

    print("Resetting gryag database")
    print(f"  Database path: {db_path}")
    print(f"  Schema path:   {schema_path}")

    if not confirm(args.force):
        print("Aborted. Nothing was changed.")
        return 1

    backup_path: Path | None = None
    if args.backup and db_path.exists():
        backup_path = backup_database(db_path, args.backup_dir)
        print(f"  Backup saved to: {backup_path}")

    if db_path.exists():
        db_path.unlink()
        print("  Existing database deleted.")
    else:
        print("  No existing database found — creating a new one.")

    try:
        apply_schema(db_path, schema_path)
    except Exception as exc:  # pragma: no cover - critical failure path
        print(f"✗ Failed to reapply schema: {exc}")
        if backup_path is not None:
            print(
                "  Original database is preserved at the backup path above. "
                "Restore manually if needed."
            )
        return 1

    print("✓ Database recreated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
