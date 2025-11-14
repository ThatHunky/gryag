"""Tests for checkers board rendering helper."""

from app.services.checkers.board_renderer import render_board
from app.services.checkers.game_engine import CheckersGame


def test_render_board_without_forced_capture_has_no_hint():
    """Initial board should not show the forced capture hint."""
    game = CheckersGame()

    output = render_board(game, current_player=1)

    assert "⚠️ Є обов'язковий удар" not in output


def test_render_board_with_forced_capture_shows_hint():
    """When a capture is available, the hint should appear."""
    board = [[0] * 8 for _ in range(8)]
    board[2][1] = 1  # Black piece
    board[3][2] = 2  # White piece to capture

    game = CheckersGame(board=board)

    output = render_board(game, current_player=1)

    assert "⚠️ Є обов'язковий удар. Обери фігуру, що може бити суперника." in output

