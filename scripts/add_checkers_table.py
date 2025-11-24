#!/usr/bin/env python3
"""Add checkers_games table to existing PostgreSQL database."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.infrastructure.db_utils import get_db_connection


async def add_checkers_table():
    """Add checkers_games table if it doesn't exist."""
    settings = get_settings()

    checkers_table_sql = """
-- Checkers Game - User vs. user challenge-based gameplay
CREATE TABLE IF NOT EXISTS checkers_games (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    challenger_id BIGINT NOT NULL,
    opponent_id BIGINT,
    current_player BIGINT,
    game_state TEXT NOT NULL,  -- JSON board state (empty JSON while pending)
    game_status TEXT NOT NULL CHECK(game_status IN ('pending', 'active', 'finished', 'cancelled')),
    winner_id BIGINT,
    challenge_message_id BIGINT,
    board_message_id BIGINT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkers_games_chat_thread
    ON checkers_games(chat_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_challenger
    ON checkers_games(challenger_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_opponent
    ON checkers_games(opponent_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_status
    ON checkers_games(game_status);
"""

    try:
        async with get_db_connection(settings.database_url) as conn:
            await conn.execute(checkers_table_sql)
        print("✅ Successfully added checkers_games table and indexes")
        return 0
    except Exception as e:
        print(f"❌ Error adding checkers_games table: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(add_checkers_table())
    sys.exit(exit_code)

