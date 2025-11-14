"""Unit tests for the checkers game engine."""

from app.services.checkers.game_engine import CheckersGame, Move


def test_black_piece_can_capture_backward():
    board = [[0] * 8 for _ in range(8)]
    board[4][3] = 1  # Black man
    board[3][2] = 2  # White man to capture

    game = CheckersGame(board)
    moves = game.get_valid_moves(1)

    capture_moves = [
        move
        for move in moves
        if (move.from_row, move.from_col) == (4, 3)
        and (move.to_row, move.to_col) == (2, 1)
    ]

    assert len(capture_moves) == 1
    assert capture_moves[0].jumps == [(3, 2)]


def test_white_piece_can_capture_backward():
    board = [[0] * 8 for _ in range(8)]
    board[3][4] = 2  # White man
    board[4][5] = 1  # Black man to capture

    game = CheckersGame(board)
    moves = game.get_valid_moves(2)

    capture_moves = [
        move
        for move in moves
        if (move.from_row, move.from_col) == (3, 4)
        and (move.to_row, move.to_col) == (5, 6)
    ]

    assert len(capture_moves) == 1
    assert capture_moves[0].jumps == [(4, 5)]


def test_multi_jump_including_backward_capture():
    board = [[0] * 8 for _ in range(8)]
    board[4][3] = 1  # Black man
    board[3][2] = 2  # First white piece
    board[1][2] = 2  # Second white piece for chained capture

    game = CheckersGame(board)
    moves = game.get_valid_moves(1)

    multi_jump_moves = [
        move
        for move in moves
        if (move.from_row, move.from_col) == (4, 3)
        and (move.to_row, move.to_col) == (0, 3)
    ]

    assert len(multi_jump_moves) == 1
    multi_move = multi_jump_moves[0]
    assert multi_move.jumps == [(3, 2), (1, 2)]

    success = game.make_move(multi_move, 1)
    assert success

    board_after = game.get_board()
    assert board_after[0][3] == 1  # Piece landed on the last square without promotion
    assert board_after[3][2] == 0
    assert board_after[1][2] == 0


def test_non_capturing_move_cannot_jump_multiple_squares():
    game = CheckersGame()
    invalid_move = Move(from_row=2, from_col=1, to_row=4, to_col=3, jumps=[])

    assert game.make_move(invalid_move, 1) is False
    # Board should remain unchanged at destination
    assert game.get_board()[4][3] == 0


def test_invalid_jump_sequence_is_rejected():
    board = [[0] * 8 for _ in range(8)]
    board[4][3] = 1  # Black man
    board[3][2] = 2
    board[1][2] = 2

    game = CheckersGame(board)
    # Correct move would be [(3,2), (1,2)], but reverse order is impossible
    invalid_move = Move(
        from_row=4,
        from_col=3,
        to_row=0,
        to_col=3,
        jumps=[(1, 2), (3, 2)],
    )

    assert game.make_move(invalid_move, 1) is False


def test_queen_can_move_multiple_cells_diagonally():
    """Test Ukrainian checkers: queen can slide diagonally across multiple empty cells."""
    board = [[0] * 8 for _ in range(8)]
    board[3][2] = 3  # Black king (queen) at playable square (3+2=5, odd)
    
    game = CheckersGame(board)
    moves = game.get_valid_moves(1)
    
    # Queen should be able to move to multiple positions diagonally
    queen_moves = [move for move in moves if (move.from_row, move.from_col) == (3, 2)]
    
    # Should have moves in all 4 diagonal directions, multiple cells each
    assert len(queen_moves) > 4  # More than just adjacent cells
    
    # Check that queen can move to a distant playable cell (e.g., from (3,2) to (0,5))
    distant_move = next(
        (m for m in queen_moves if m.to_row == 0 and m.to_col == 5),
        None
    )
    assert distant_move is not None
    assert distant_move.jumps == []


def test_queen_can_jump_over_piece_at_distance():
    """Test Ukrainian checkers: queen can jump over opponent pieces at any distance."""
    board = [[0] * 8 for _ in range(8)]
    board[0][1] = 3  # Black king (queen) at playable square (0+1=1, odd)
    board[3][4] = 2  # White piece 3 cells away diagonally (3+4=7, odd)
    
    game = CheckersGame(board)
    moves = game.get_valid_moves(1)
    
    # Queen should be able to jump over the white piece
    jump_moves = [
        move for move in moves
        if (move.from_row, move.from_col) == (0, 1)
        and move.jumps == [(3, 4)]
    ]
    
    assert len(jump_moves) > 0
    # Landing should be one cell beyond the jumped piece
    jump_move = jump_moves[0]
    assert jump_move.to_row == 4
    assert jump_move.to_col == 5


def test_queen_multi_jump_across_distances():
    """Test Ukrainian checkers: queen can perform multi-jumps across different distances."""
    board = [[0] * 8 for _ in range(8)]
    board[0][1] = 3  # Black king (queen) at playable square
    board[2][3] = 2  # First white piece (2+3=5, odd)
    board[5][6] = 2  # Second white piece (5+6=11, odd)
    
    game = CheckersGame(board)
    moves = game.get_valid_moves(1)
    
    # Should find multi-jump moves
    multi_jump_moves = [
        move for move in moves
        if (move.from_row, move.from_col) == (0, 1)
        and len(move.jumps) == 2
    ]
    
    assert len(multi_jump_moves) > 0
    multi_move = multi_jump_moves[0]
    assert (2, 3) in multi_move.jumps
    assert (5, 6) in multi_move.jumps


def test_regular_piece_still_moves_one_cell():
    """Test that regular pieces (non-queens) still move only one cell."""
    board = [[0] * 8 for _ in range(8)]
    board[3][2] = 1  # Black regular piece (not a king) at playable square (3+2=5, odd)
    
    game = CheckersGame(board)
    moves = game.get_valid_moves(1)
    
    regular_moves = [move for move in moves if (move.from_row, move.from_col) == (3, 2)]
    
    # Regular piece should only have 2 moves (forward diagonally)
    assert len(regular_moves) == 2
    
    # All moves should be exactly 1 cell away
    for move in regular_moves:
        dr = abs(move.to_row - move.from_row)
        dc = abs(move.to_col - move.from_col)
        assert dr == 1
        assert dc == 1


def test_queen_cannot_move_through_pieces():
    """Test that queen cannot move through pieces, only to empty cells."""
    board = [[0] * 8 for _ in range(8)]
    board[0][1] = 3  # Black king (queen) at playable square
    board[2][3] = 1  # Own piece blocking the path (2+3=5, odd)
    board[4][5] = 0  # Empty playable cell beyond (4+5=9, odd)
    
    game = CheckersGame(board)
    moves = game.get_valid_moves(1)
    
    queen_moves = [move for move in moves if (move.from_row, move.from_col) == (0, 1)]
    
    # Should not be able to move to (4,5) because path is blocked
    blocked_move = next(
        (m for m in queen_moves if m.to_row == 4 and m.to_col == 5),
        None
    )
    assert blocked_move is None
    
    # Should be able to move to (1,2) before the blocking piece (1+2=3, odd)
    valid_move = next(
        (m for m in queen_moves if m.to_row == 1 and m.to_col == 2),
        None
    )
    assert valid_move is not None

