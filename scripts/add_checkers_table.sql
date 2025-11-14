-- Add checkers_games table to existing PostgreSQL database
-- Run this with: psql $DATABASE_URL -f scripts/add_checkers_table.sql
-- Or inside Docker: docker exec -i gryag-postgres psql -U gryag -d gryag < scripts/add_checkers_table.sql

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

