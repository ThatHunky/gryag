"""Unit tests for the CheckersGameStore challenge flow."""

from __future__ import annotations

import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = SimpleNamespace(
        PostgresConnectionError=Exception,
        InterfaceError=Exception,
    )

from app.services.checkers.game_engine import CheckersGame
from app.services.checkers.game_store import CheckersGameStore


class FakeConnection:
    """Minimal in-memory substitute for asyncpg connection."""

    def __init__(self) -> None:
        self.games: dict[str, dict[str, Any]] = {}

    async def execute(self, sql: str, *params: Any) -> None:
        if "INSERT INTO checkers_games" in sql:
            game_id, chat_id, thread_id, challenger_id, game_state_json, timestamp = (
                params
            )
            self.games[game_id] = {
                "id": game_id,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "challenger_id": challenger_id,
                "opponent_id": None,
                "current_player": None,
                "game_state": game_state_json,
                "game_status": "pending",
                "winner_id": None,
                "challenge_message_id": None,
                "board_message_id": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            return

        if "SET challenge_message_id" in sql:
            game_id, message_id, timestamp = params
            self.games[game_id]["challenge_message_id"] = message_id
            self.games[game_id]["updated_at"] = timestamp
            return

        if "SET game_status = 'cancelled'" in sql:
            game_id, timestamp = params
            self.games[game_id]["game_status"] = "cancelled"
            self.games[game_id]["updated_at"] = timestamp
            return

        if "SET opponent_id" in sql and "game_status = 'active'" in sql:
            (
                game_id,
                opponent_id,
                game_state_json,
                board_message_id,
                current_player,
                timestamp,
            ) = params
            record = self.games[game_id]
            record["opponent_id"] = opponent_id
            record["current_player"] = current_player
            record["game_state"] = game_state_json
            record["board_message_id"] = board_message_id
            record["game_status"] = "active"
            record["updated_at"] = timestamp
            return

        if sql.strip().startswith("UPDATE checkers_games"):
            game_id = params[0]
            record = self.games[game_id]
            record["updated_at"] = params[1]
            record["game_state"] = params[2]
            record["current_player"] = params[3]
            index = 4
            if "game_status" in sql:
                record["game_status"] = params[index]
                index += 1
            if "winner_id" in sql:
                record["winner_id"] = params[index]
                index += 1
            if "board_message_id" in sql:
                record["board_message_id"] = params[index]
            return

        raise AssertionError(f"Unexpected execute call: {sql}")

    async def fetchrow(self, sql: str, *params: Any) -> dict[str, Any] | None:
        if "SELECT challenger_id, game_status" in sql:
            game_id = params[0]
            record = self.games.get(game_id)
            if not record:
                return None
            return {
                "challenger_id": record["challenger_id"],
                "game_status": record["game_status"],
            }

        if "WHERE id = $1" in sql and "SELECT" in sql:
            game_id = params[0]
            record = self.games.get(game_id)
            if not record:
                return None
            return record.copy()

        if "game_status IN ('pending', 'active')" in sql:
            chat_id, thread_id, user_id = params
            candidates: list[dict[str, Any]] = []
            for record in self.games.values():
                if record["chat_id"] != chat_id:
                    continue
                record_thread = record["thread_id"]
                if record_thread != thread_id:
                    if not (record_thread is None and thread_id is None):
                        continue
                if record["game_status"] not in {"pending", "active"}:
                    continue
                if user_id not in (record["challenger_id"], record["opponent_id"]):
                    continue
                candidates.append(record)
            if not candidates:
                return None
            return max(candidates, key=lambda r: r["created_at"]).copy()

        raise AssertionError(f"Unexpected fetchrow call: {sql}")

    async def fetch(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        user_id = params[0]
        if "AND game_status = $2" in sql:
            status = params[1]
            limit = params[2]
        else:
            status = None
            limit = params[1]

        records = [
            record.copy()
            for record in self.games.values()
            if user_id in (record["challenger_id"], record["opponent_id"])
        ]
        if status:
            records = [r for r in records if r["game_status"] == status]
        records.sort(key=lambda r: r["updated_at"], reverse=True)
        return records[:limit]


@pytest.fixture
def fake_db(monkeypatch) -> FakeConnection:
    """Patch get_db_connection to use in-memory fake connection."""

    connection = FakeConnection()

    @asynccontextmanager
    async def fake_get_db_connection(
        _database_url: str,
    ) -> AsyncIterator[FakeConnection]:
        yield connection

    monkeypatch.setattr(
        "app.services.checkers.game_store.get_db_connection",
        fake_get_db_connection,
    )

    # Freeze time to avoid flakiness in updated_at ordering
    base_time = time.time()

    original_time = time.time

    def frozen_time() -> float:
        return base_time

    monkeypatch.setattr(time, "time", frozen_time)

    yield connection

    monkeypatch.setattr(time, "time", original_time)


@pytest.mark.asyncio
async def test_create_and_accept_challenge(fake_db: FakeConnection):
    store = CheckersGameStore("postgresql://test")

    game_id = await store.create_challenge(chat_id=1, thread_id=None, challenger_id=10)
    await store.set_challenge_message(game_id, 12345)

    pending = await store.get_open_game(chat_id=1, thread_id=None, user_id=10)
    assert pending is not None
    assert pending["game_status"] == "pending"
    assert pending["challenge_message_id"] == 12345

    game_state = CheckersGame().to_json()
    activated = await store.accept_challenge(
        game_id=game_id,
        opponent_id=20,
        game_state_json=game_state,
        board_message_id=222,
        starting_player_id=10,
    )
    assert activated is True

    game_data = await store.get_game(game_id)
    assert game_data["game_status"] == "active"
    assert game_data["opponent_id"] == 20
    assert game_data["current_player"] == 10
    assert game_data["board_message_id"] == 222


@pytest.mark.asyncio
async def test_cancel_challenge_only_challenger(fake_db: FakeConnection):
    store = CheckersGameStore("postgresql://test")
    game_id = await store.create_challenge(chat_id=2, thread_id=5, challenger_id=30)

    cancelled = await store.cancel_challenge(game_id, user_id=99)
    assert cancelled is False
    assert fake_db.games[game_id]["game_status"] == "pending"

    cancelled = await store.cancel_challenge(game_id, user_id=30)
    assert cancelled is True
    assert fake_db.games[game_id]["game_status"] == "cancelled"


@pytest.mark.asyncio
async def test_update_game_finishes_match(fake_db: FakeConnection):
    store = CheckersGameStore("postgresql://test")
    game_id = await store.create_challenge(chat_id=3, thread_id=None, challenger_id=40)
    game_state = CheckersGame().to_json()
    await store.accept_challenge(
        game_id=game_id,
        opponent_id=50,
        game_state_json=game_state,
        board_message_id=303,
        starting_player_id=40,
    )

    updated_state = CheckersGame().to_json()
    await store.update_game(
        game_id=game_id,
        game_state_json=updated_state,
        current_player=50,
        game_status="finished",
        winner_id=50,
        board_message_id=404,
    )

    game_data = await store.get_game(game_id)
    assert game_data["game_status"] == "finished"
    assert game_data["winner_id"] == 50
    assert game_data["board_message_id"] == 404

    recent_games = await store.get_user_games(user_id=50)
    assert len(recent_games) == 1
    assert recent_games[0]["id"] == game_id
