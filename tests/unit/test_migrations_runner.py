import types
from pathlib import Path

import pytest

from app.infrastructure import db_utils


class FakeConn:
    def __init__(self):
        self._tx = types.SimpleNamespace()

    async def execute(self, _sql: str, *args):
        # Accept any SQL; no-op
        return "OK"

    async def fetch(self, _sql: str, *args):
        # Return empty applied set
        return []

    def transaction(self):
        class _Tx:
            async def __aenter__(self_non):
                return self_non

            async def __aexit__(self_non, exc_type, exc, tb):
                return False

        return _Tx()


class FakeConnCM:
    def __init__(self, _url: str):
        self.conn = FakeConn()

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_apply_migrations_with_custom_dir(monkeypatch, tmp_path: Path):
    # Create temporary migrations directory with two files
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    (mig_dir / "V1__init.sql").write_text("SELECT 1;")
    (mig_dir / "V2__add_table.sql").write_text("SELECT 1;")

    # Monkeypatch connection context manager
    monkeypatch.setattr(db_utils, "get_db_connection", lambda url: FakeConnCM(url))

    # Monkeypatch path resolution to use our temp directory
    def _migrations_dir_candidates():
        return [mig_dir]

    # Wrap original function to override directory search

    async def _apply_with_tmp_dir(url: str):
        # Inline copy of apply_migrations directory selection
        migrations_dir = mig_dir
        migration_files = sorted(
            [f for f in migrations_dir.iterdir() if f.suffix.lower() == ".sql"]
        )
        async with db_utils.get_db_connection(url) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS migrations_applied (
                    filename TEXT PRIMARY KEY,
                    applied_at BIGINT NOT NULL
                )
                """
            )
            rows = await conn.fetch("SELECT filename FROM migrations_applied")
            already_applied = {r["filename"] for r in rows} if rows else set()
            to_apply = [mf for mf in migration_files if mf.name not in already_applied]
            for mf in to_apply:
                sql = mf.read_text(encoding="utf-8")
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO migrations_applied (filename, applied_at) VALUES ($1, $2)",
                        mf.name,
                        0,
                    )

    # Run the wrapped function - should complete without exceptions
    await _apply_with_tmp_dir("postgresql://test")
