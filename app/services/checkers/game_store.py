"""Database operations for checkers games."""

from __future__ import annotations

import logging
import time
from typing import Literal
import uuid

from app.infrastructure.db_utils import get_db_connection

logger = logging.getLogger(__name__)

GameStatus = Literal["pending", "active", "finished", "cancelled"]


class CheckersGameStore:
    """Database operations for checkers games."""
    
    def __init__(self, database_url: str):
        """Initialize game store with database URL."""
        self.database_url = database_url
    
    async def create_challenge(
        self,
        chat_id: int,
        thread_id: int | None,
        challenger_id: int,
    ) -> str:
        """Create a new challenge awaiting an opponent. Returns game ID."""
        game_id = str(uuid.uuid4())
        current_time = int(time.time())

        async with get_db_connection(self.database_url) as conn:
            await conn.execute(
                """
                INSERT INTO checkers_games 
                (id, chat_id, thread_id, challenger_id, opponent_id, current_player,
                 game_state, game_status, winner_id, challenge_message_id, board_message_id,
                 created_at, updated_at)
                VALUES ($1, $2, $3, $4, NULL, NULL, $5, 'pending', NULL, NULL, NULL, $6, $6)
                """,
                game_id,
                chat_id,
                thread_id,
                challenger_id,
                "{}",
                current_time,
            )

        logger.info(f"Created pending checkers challenge {game_id} in chat {chat_id}")
        return game_id
    
    async def set_challenge_message(self, game_id: str, message_id: int) -> None:
        """Store Telegram message ID for a challenge announcement."""
        current_time = int(time.time())
        async with get_db_connection(self.database_url) as conn:
            await conn.execute(
                """
                UPDATE checkers_games
                SET challenge_message_id = $2,
                    updated_at = $3
                WHERE id = $1
                """,
                game_id,
                message_id,
                current_time,
            )

    async def cancel_challenge(self, game_id: str, user_id: int) -> bool:
        """Cancel a pending challenge. Returns True if cancelled."""
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(
                """
                SELECT challenger_id, game_status
                FROM checkers_games
                WHERE id = $1
                """,
                game_id,
            )

            if not row:
                return False

            if row["game_status"] != "pending" or row["challenger_id"] != user_id:
                return False

            current_time = int(time.time())
            await conn.execute(
                """
                UPDATE checkers_games
                SET game_status = 'cancelled',
                    updated_at = $2
                WHERE id = $1
                """,
                game_id,
                current_time,
            )

            logger.info(f"Challenge {game_id} cancelled by user {user_id}")
            return True

    async def accept_challenge(
        self,
        game_id: str,
        opponent_id: int,
        game_state_json: str,
        board_message_id: int,
        starting_player_id: int,
    ) -> bool:
        """Accept a pending challenge and activate the game."""
        current_time = int(time.time())
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(
                """
                SELECT challenger_id, game_status
                FROM checkers_games
                WHERE id = $1
                """,
                game_id,
            )

            if not row or row["game_status"] != "pending":
                return False

            if row["challenger_id"] == opponent_id:
                return False  # Cannot accept own challenge

            await conn.execute(
                """
                UPDATE checkers_games
                SET opponent_id = $2,
                    current_player = $5,
                    game_state = $3,
                    game_status = 'active',
                    board_message_id = $4,
                    updated_at = $6
                WHERE id = $1
                """,
                game_id,
                opponent_id,
                game_state_json,
                board_message_id,
                starting_player_id,
                current_time,
            )

        logger.info(f"Challenge {game_id} accepted by user {opponent_id}")
        return True
    
    async def get_game(self, game_id: str) -> dict | None:
        """Get game by ID. Returns None if not found."""
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, chat_id, thread_id, challenger_id, opponent_id, current_player,
                       game_state, game_status, winner_id, challenge_message_id,
                       board_message_id, created_at, updated_at
                FROM checkers_games
                WHERE id = $1
                """,
                game_id,
            )
            
            if not row:
                return None
            
            return {
                "id": row["id"],
                "chat_id": row["chat_id"],
                "thread_id": row["thread_id"],
                "challenger_id": row["challenger_id"],
                "opponent_id": row["opponent_id"],
                "current_player": row["current_player"],
                "game_state": row["game_state"],
                "game_status": row["game_status"],
                "winner_id": row["winner_id"],
                "challenge_message_id": row["challenge_message_id"],
                "board_message_id": row["board_message_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
    
    async def get_open_game(
        self, chat_id: int, thread_id: int | None, user_id: int
    ) -> dict | None:
        """Get pending or active game for user in chat/thread."""
        async with get_db_connection(self.database_url) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, chat_id, thread_id, challenger_id, opponent_id, current_player,
                       game_state, game_status, winner_id, challenge_message_id,
                       board_message_id, created_at, updated_at
                FROM checkers_games
                WHERE chat_id = $1 
                  AND (thread_id = $2 OR (thread_id IS NULL AND $2 IS NULL))
                  AND game_status IN ('pending', 'active')
                  AND (challenger_id = $3 OR opponent_id = $3)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                chat_id,
                thread_id,
                user_id,
            )
            
            if not row:
                return None
            
            return {
                "id": row["id"],
                "chat_id": row["chat_id"],
                "thread_id": row["thread_id"],
                "challenger_id": row["challenger_id"],
                "opponent_id": row["opponent_id"],
                "current_player": row["current_player"],
                "game_state": row["game_state"],
                "game_status": row["game_status"],
                "winner_id": row["winner_id"],
                "challenge_message_id": row["challenge_message_id"],
                "board_message_id": row["board_message_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
    
    async def update_game(
        self,
        game_id: str,
        game_state_json: str,
        current_player: int,
        game_status: GameStatus | None = None,
        winner_id: int | None = None,
        board_message_id: int | None = None,
    ) -> None:
        """Update game state."""
        current_time = int(time.time())
        
        updates = ["updated_at = $2", "game_state = $3", "current_player = $4"]
        params = [game_id, current_time, game_state_json, current_player]
        param_index = 5
        
        if game_status:
            updates.append(f"game_status = ${param_index}")
            params.append(game_status)
            param_index += 1
        
        if winner_id is not None:
            updates.append(f"winner_id = ${param_index}")
            params.append(winner_id)
            param_index += 1
        
        if board_message_id is not None:
            updates.append(f"board_message_id = ${param_index}")
            params.append(board_message_id)
            param_index += 1
        
        async with get_db_connection(self.database_url) as conn:
            await conn.execute(
                f"""
                UPDATE checkers_games
                SET {', '.join(updates)}
                WHERE id = $1
                """,
                *params,
            )
        
        logger.debug(f"Updated checkers game {game_id}")
    
    async def get_user_games(
        self, user_id: int, status: GameStatus | None = None, limit: int = 10
    ) -> list[dict]:
        """Get games for a user, optionally filtered by status."""
        async with get_db_connection(self.database_url) as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT id, chat_id, thread_id, challenger_id, opponent_id, current_player,
                           game_state, game_status, winner_id, challenge_message_id,
                           board_message_id, created_at, updated_at
                    FROM checkers_games
                    WHERE (challenger_id = $1 OR opponent_id = $1)
                      AND game_status = $2
                    ORDER BY updated_at DESC
                    LIMIT $3
                    """,
                    user_id,
                    status,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, chat_id, thread_id, challenger_id, opponent_id, current_player,
                           game_state, game_status, winner_id, challenge_message_id,
                           board_message_id, created_at, updated_at
                    FROM checkers_games
                    WHERE challenger_id = $1 OR opponent_id = $1
                    ORDER BY updated_at DESC
                    LIMIT $2
                    """,
                    user_id,
                    limit,
                )
            
            return [
                {
                    "id": row["id"],
                    "chat_id": row["chat_id"],
                    "thread_id": row["thread_id"],
                    "challenger_id": row["challenger_id"],
                    "opponent_id": row["opponent_id"],
                    "current_player": row["current_player"],
                    "game_state": row["game_state"],
                    "game_status": row["game_status"],
                    "winner_id": row["winner_id"],
                    "challenge_message_id": row["challenge_message_id"],
                    "board_message_id": row["board_message_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

