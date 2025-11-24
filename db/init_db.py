from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)


async def create_schema(db_path: Path | str):
    """Create database schema from schema.sql file."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).parent.parent / "db/schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")

    async with get_db_connection(db_path) as db:
        with open(schema_path) as f:
            await db.executescript(f.read())
        await db.commit()
        logger.info(f"Database schema created at {db_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example usage:
    # python -m db.init_db
    db_file = Path(__file__).parent.parent / "gryag.db"
    asyncio.run(create_schema(db_file))
