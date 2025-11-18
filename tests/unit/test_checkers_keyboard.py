"""Tests for checkers inline keyboard rendering."""

from app.handlers.checkers import _create_board_keyboard
from app.services.checkers.game_engine import CheckersGame


def test_playable_empty_square_is_blank():
    """Ensure empty playable squares render as a single space."""
    empty_board = [[0] * 8 for _ in range(8)]
    game = CheckersGame(board=empty_board)

    markup = _create_board_keyboard(
        game=game,
        game_id="test-game",
        current_player=1,
    )

    # Row 0, col 1 is a dark (playable) square
    empty_square_button = markup.inline_keyboard[0][1]
    assert empty_square_button.text == " "
    assert empty_square_button.callback_data == "checkers:ignore"


def test_destination_highlight_keeps_blank_base():
    """Ensure highlighted destinations keep a blank base text."""
    board = [[0] * 8 for _ in range(8)]
    board[2][1] = 1  # Black piece positioned to move down-left
    game = CheckersGame(board=board)

    markup = _create_board_keyboard(
        game=game,
        game_id="test-game",
        current_player=1,
        selected_square=(2, 1),
    )

    destination_button = markup.inline_keyboard[3][0]
    assert destination_button.text == "🟢 "
    assert destination_button.callback_data == "checkers:move:test-game:3:0"
