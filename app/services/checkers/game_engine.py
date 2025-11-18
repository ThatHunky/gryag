"""Checkers game engine with move validation and game state management."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

# Board representation: 0=empty, 1=black piece, 2=white piece, 3=black king, 4=white king
Player = Literal[1, 2]  # 1 = black (player1), 2 = white (player2 or AI)


@dataclass
class Move:
    """Represents a checkers move."""

    from_row: int
    from_col: int
    to_row: int
    to_col: int
    jumps: list[tuple[int, int]]  # List of jumped pieces (row, col)


class CheckersGame:
    """Manages checkers game state, validates moves, and checks win conditions."""

    BOARD_SIZE = 8

    def _find_matching_move(self, move: Move, player: Player) -> Move | None:
        """Return the engine-generated move that matches supplied coordinates."""
        for candidate in self.get_valid_moves(player):
            if (
                move.from_row == candidate.from_row
                and move.from_col == candidate.from_col
                and move.to_row == candidate.to_row
                and move.to_col == candidate.to_col
            ):
                return candidate
        return None

    def _validate_simple_move(self, move: Move, player: Player) -> bool:
        """Validate a non-capturing move lands on an adjacent dark square."""
        if move.jumps:
            return False

        dr = move.to_row - move.from_row
        dc = move.to_col - move.from_col

        # Check if move is diagonal
        if abs(dr) != abs(dc):
            return False

        if not self._is_valid_position(move.to_row, move.to_col):
            return False
        if not self._is_playable_square(move.to_row, move.to_col):
            return False
        if self.board[move.to_row][move.to_col] != 0:
            return False

        piece = self.board[move.from_row][move.from_col]
        if not self._is_player_piece(piece, player):
            return False

        if not self._is_playable_square(move.from_row, move.from_col):
            return False

        is_king = piece in (3, 4)
        distance = abs(dr)

        if is_king:
            # Ukrainian checkers: queen can move any diagonal distance
            # Validate entire path is clear
            if distance == 0:
                return False
            row_dir = 1 if dr > 0 else -1
            col_dir = 1 if dc > 0 else -1
            for step in range(1, distance):
                check_row = move.from_row + step * row_dir
                check_col = move.from_col + step * col_dir
                if self.board[check_row][check_col] != 0:
                    return False
            return True
        else:
            # Regular piece: must be exactly 1 cell
            if distance != 1:
                return False
            return True

    def _validate_jump_sequence(self, move: Move, player: Player) -> bool:
        """Ensure jump sequence is physically reachable."""
        if not move.jumps:
            return False

        if not self._is_valid_position(move.from_row, move.from_col):
            return False

        piece = self.board[move.from_row][move.from_col]
        if not self._is_player_piece(piece, player):
            return False

        is_king = piece in (3, 4)
        temp_board = [row[:] for row in self.board]
        current_row, current_col = move.from_row, move.from_col
        temp_board[current_row][current_col] = 0

        for jump_row, jump_col in move.jumps:
            dr = jump_row - current_row
            dc = jump_col - current_col

            # Check if move is diagonal
            if abs(dr) != abs(dc):
                return False

            if not self._is_valid_position(jump_row, jump_col):
                return False

            jumped_piece = temp_board[jump_row][jump_col]
            if jumped_piece == 0 or self._is_player_piece(jumped_piece, player):
                return False

            if is_king:
                # Ukrainian checkers: queen can jump any distance
                # Validate path to jumped piece is clear
                distance = abs(dr)
                row_dir = 1 if dr > 0 else -1
                col_dir = 1 if dc > 0 else -1

                for step in range(1, distance):
                    check_row = current_row + step * row_dir
                    check_col = current_col + step * col_dir
                    if temp_board[check_row][check_col] != 0:
                        return False

                # Landing square is one step beyond the jumped piece
                landing_row = jump_row + row_dir
                landing_col = jump_col + col_dir
            else:
                # Regular piece: must jump adjacent piece
                if abs(dr) != 1 or abs(dc) != 1:
                    return False

                landing_row = current_row + 2 * dr
                landing_col = current_col + 2 * dc

            if not self._is_valid_position(landing_row, landing_col):
                return False
            if not self._is_playable_square(landing_row, landing_col):
                return False
            if temp_board[landing_row][landing_col] != 0:
                return False

            temp_board[jump_row][jump_col] = 0
            current_row, current_col = landing_row, landing_col

        return (current_row, current_col) == (move.to_row, move.to_col)

    def _validate_move_path(self, move: Move, player: Player) -> bool:
        """Validate that move structure matches board geometry."""
        if move.jumps:
            return self._validate_jump_sequence(move, player)
        return self._validate_simple_move(move, player)

    def __init__(self, board: list[list[int]] | None = None):
        """Initialize game with optional board state."""
        if board is None:
            self.board = self._create_initial_board()
        else:
            self.board = [row[:] for row in board]  # Deep copy

    @staticmethod
    def _create_initial_board() -> list[list[int]]:
        """Create initial checkers board setup."""
        board = [[0] * 8 for _ in range(8)]
        # Place black pieces (player 1) on top rows
        for row in range(3):
            for col in range(8):
                if (row + col) % 2 == 1:
                    board[row][col] = 1
        # Place white pieces (player 2) on bottom rows
        for row in range(5, 8):
            for col in range(8):
                if (row + col) % 2 == 1:
                    board[row][col] = 2
        return board

    def get_board(self) -> list[list[int]]:
        """Get current board state (deep copy)."""
        return [row[:] for row in self.board]

    def get_piece(self, row: int, col: int) -> int:
        """Get piece at given position."""
        if not self._is_valid_position(row, col):
            return 0
        return self.board[row][col]

    def _is_valid_position(self, row: int, col: int) -> bool:
        """Check if position is within board bounds."""
        return 0 <= row < self.BOARD_SIZE and 0 <= col < self.BOARD_SIZE

    def _is_playable_square(self, row: int, col: int) -> bool:
        """Check if square is playable (dark squares only in checkers)."""
        return (row + col) % 2 == 1

    def get_valid_moves(self, player: Player) -> list[Move]:
        """Get all valid moves for a player."""
        moves = []

        # First, check for mandatory jumps
        jump_moves = []
        for row in range(self.BOARD_SIZE):
            for col in range(self.BOARD_SIZE):
                piece = self.board[row][col]
                if self._is_player_piece(piece, player):
                    jumps = self._get_jumps_from(row, col, player)
                    jump_moves.extend(jumps)

        if jump_moves:
            return jump_moves

        # If no jumps, return regular moves
        for row in range(self.BOARD_SIZE):
            for col in range(self.BOARD_SIZE):
                piece = self.board[row][col]
                if self._is_player_piece(piece, player):
                    moves.extend(self._get_moves_from(row, col, player))

        return moves

    def _is_player_piece(self, piece: int, player: Player) -> bool:
        """Check if piece belongs to player."""
        if player == 1:
            return piece in (1, 3)  # Black piece or black king
        else:
            return piece in (2, 4)  # White piece or white king

    def _get_moves_from(self, row: int, col: int, player: Player) -> list[Move]:
        """Get regular moves (non-jumps) from a position."""
        moves = []
        piece = self.board[row][col]
        is_king = piece in (3, 4)

        if player == 1:  # Black moves down
            directions = (
                [(1, -1), (1, 1)]
                if not is_king
                else [(1, -1), (1, 1), (-1, -1), (-1, 1)]
            )
        else:  # White moves up
            directions = (
                [(-1, -1), (-1, 1)]
                if not is_king
                else [(1, -1), (1, 1), (-1, -1), (-1, 1)]
            )

        for dr, dc in directions:
            if is_king:
                # Ukrainian checkers: queen can slide diagonally across all empty cells
                for distance in range(1, self.BOARD_SIZE):
                    new_row, new_col = row + distance * dr, col + distance * dc
                    if not self._is_valid_position(new_row, new_col):
                        break
                    if not self._is_playable_square(new_row, new_col):
                        break
                    if self.board[new_row][new_col] != 0:
                        # Hit a piece, stop sliding
                        break
                    moves.append(Move(row, col, new_row, new_col, []))
            else:
                # Regular piece: only one cell
                new_row, new_col = row + dr, col + dc
                if self._is_valid_position(
                    new_row, new_col
                ) and self._is_playable_square(new_row, new_col):
                    if self.board[new_row][new_col] == 0:
                        moves.append(Move(row, col, new_row, new_col, []))

        return moves

    def _get_jump_directions(self, player: Player) -> list[tuple[int, int]]:
        """Return directions for evaluating capture moves."""
        if player == 1:
            return [(1, -1), (1, 1), (-1, -1), (-1, 1)]
        return [(-1, -1), (-1, 1), (1, -1), (1, 1)]

    def _get_jumps_from(self, row: int, col: int, player: Player) -> list[Move]:
        """Get jump moves from a position (recursive for multi-jumps)."""
        jumps = []
        directions = self._get_jump_directions(player)
        piece = self.board[row][col]
        is_king = piece in (3, 4)

        for dr, dc in directions:
            if is_king:
                # Ukrainian checkers: queen can jump over opponent pieces at any distance
                # Scan diagonally to find opponent pieces
                for distance in range(1, self.BOARD_SIZE):
                    jump_row, jump_col = row + distance * dr, col + distance * dc

                    if not self._is_valid_position(jump_row, jump_col):
                        break
                    if not self._is_playable_square(jump_row, jump_col):
                        continue

                    jumped_piece = self.board[jump_row][jump_col]
                    if jumped_piece == 0:
                        # Empty cell, continue scanning
                        continue

                    if self._is_player_piece(jumped_piece, player):
                        # Own piece, stop scanning in this direction
                        break

                    # Found opponent piece, check if landing square is empty
                    land_row, land_col = jump_row + dr, jump_col + dc

                    if not self._is_valid_position(land_row, land_col):
                        break
                    if not self._is_playable_square(land_row, land_col):
                        break
                    if self.board[land_row][land_col] != 0:
                        # Landing square is occupied, stop scanning
                        break

                    # Check that path to jumped piece is clear
                    path_clear = True
                    for step in range(1, distance):
                        check_row = row + step * dr
                        check_col = col + step * dc
                        if self.board[check_row][check_col] != 0:
                            path_clear = False
                            break

                    if not path_clear:
                        break

                    # Valid jump found, check for multi-jumps
                    jump_pos = (jump_row, jump_col)
                    move = Move(row, col, land_row, land_col, [jump_pos])

                    # Try to find additional jumps from landing position
                    # Temporarily make the jump to check for multi-jumps
                    temp_board = [r[:] for r in self.board]
                    temp_board[land_row][land_col] = temp_board[row][col]
                    temp_board[row][col] = 0
                    temp_board[jump_row][jump_col] = 0

                    # Check for additional jumps
                    additional_jumps = self._get_jumps_from_recursive(
                        land_row, land_col, player, temp_board
                    )

                    if additional_jumps:
                        # Combine with multi-jumps
                        for multi_move in additional_jumps:
                            combined_jumps = [jump_pos] + multi_move.jumps
                            jumps.append(
                                Move(
                                    row,
                                    col,
                                    multi_move.to_row,
                                    multi_move.to_col,
                                    combined_jumps,
                                )
                            )
                    else:
                        jumps.append(move)

                    # In Ukrainian checkers, queen can only jump one piece at a time per direction
                    # Continue scanning to find other jumps in the same direction
            else:
                # Regular piece: only adjacent jumps
                jump_row, jump_col = row + dr, col + dc
                land_row, land_col = row + 2 * dr, col + 2 * dc

                if (
                    self._is_valid_position(jump_row, jump_col)
                    and self._is_valid_position(land_row, land_col)
                    and self._is_playable_square(land_row, land_col)
                    and self.board[land_row][land_col] == 0
                ):

                    jumped_piece = self.board[jump_row][jump_col]
                    if jumped_piece != 0 and not self._is_player_piece(
                        jumped_piece, player
                    ):
                        # Valid jump found, check for multi-jumps
                        jump_pos = (jump_row, jump_col)
                        move = Move(row, col, land_row, land_col, [jump_pos])

                        # Try to find additional jumps from landing position
                        # Temporarily make the jump to check for multi-jumps
                        temp_board = [r[:] for r in self.board]
                        temp_board[land_row][land_col] = temp_board[row][col]
                        temp_board[row][col] = 0
                        temp_board[jump_row][jump_col] = 0

                        # Check for additional jumps
                        additional_jumps = self._get_jumps_from_recursive(
                            land_row, land_col, player, temp_board
                        )

                        if additional_jumps:
                            # Combine with multi-jumps
                            for multi_move in additional_jumps:
                                combined_jumps = [jump_pos] + multi_move.jumps
                                jumps.append(
                                    Move(
                                        row,
                                        col,
                                        multi_move.to_row,
                                        multi_move.to_col,
                                        combined_jumps,
                                    )
                                )
                        else:
                            jumps.append(move)

        return jumps

    def _get_jumps_from_recursive(
        self, row: int, col: int, player: Player, board: list[list[int]]
    ) -> list[Move]:
        """Recursive helper for finding multi-jumps."""
        jumps = []

        directions = self._get_jump_directions(player)
        piece = board[row][col]
        is_king = piece in (3, 4)

        for dr, dc in directions:
            if is_king:
                # Ukrainian checkers: queen can jump over opponent pieces at any distance
                # Scan diagonally to find opponent pieces
                for distance in range(1, self.BOARD_SIZE):
                    jump_row, jump_col = row + distance * dr, col + distance * dc

                    if not (0 <= jump_row < 8 and 0 <= jump_col < 8):
                        break
                    if (jump_row + jump_col) % 2 != 1:
                        continue

                    jumped_piece = board[jump_row][jump_col]
                    if jumped_piece == 0:
                        # Empty cell, continue scanning
                        continue

                    if self._is_player_piece(jumped_piece, player):
                        # Own piece, stop scanning in this direction
                        break

                    # Found opponent piece, check if landing square is empty
                    land_row, land_col = jump_row + dr, jump_col + dc

                    if not (0 <= land_row < 8 and 0 <= land_col < 8):
                        break
                    if (land_row + land_col) % 2 != 1:
                        break
                    if board[land_row][land_col] != 0:
                        # Landing square is occupied, stop scanning
                        break

                    # Check that path to jumped piece is clear
                    path_clear = True
                    for step in range(1, distance):
                        check_row = row + step * dr
                        check_col = col + step * dc
                        if board[check_row][check_col] != 0:
                            path_clear = False
                            break

                    if not path_clear:
                        break

                    jump_pos = (jump_row, jump_col)
                    move = Move(row, col, land_row, land_col, [jump_pos])

                    # Continue multi-jump
                    temp_board = [r[:] for r in board]
                    temp_board[land_row][land_col] = temp_board[row][col]
                    temp_board[row][col] = 0
                    temp_board[jump_row][jump_col] = 0

                    additional = self._get_jumps_from_recursive(
                        land_row, land_col, player, temp_board
                    )
                    if additional:
                        for multi in additional:
                            combined = [jump_pos] + multi.jumps
                            jumps.append(
                                Move(row, col, multi.to_row, multi.to_col, combined)
                            )
                    else:
                        jumps.append(move)

                    # In Ukrainian checkers, queen can only jump one piece at a time per direction
                    # Continue scanning to find other jumps in the same direction
            else:
                # Regular piece: only adjacent jumps
                jump_row, jump_col = row + dr, col + dc
                land_row, land_col = row + 2 * dr, col + 2 * dc

                if (
                    0 <= jump_row < 8
                    and 0 <= jump_col < 8
                    and 0 <= land_row < 8
                    and 0 <= land_col < 8
                    and (land_row + land_col) % 2 == 1
                    and board[land_row][land_col] == 0
                ):

                    jumped_piece = board[jump_row][jump_col]
                    if jumped_piece != 0 and not self._is_player_piece(
                        jumped_piece, player
                    ):
                        jump_pos = (jump_row, jump_col)
                        move = Move(row, col, land_row, land_col, [jump_pos])

                        # Continue multi-jump
                        temp_board = [r[:] for r in board]
                        temp_board[land_row][land_col] = temp_board[row][col]
                        temp_board[row][col] = 0
                        temp_board[jump_row][jump_col] = 0

                        additional = self._get_jumps_from_recursive(
                            land_row, land_col, player, temp_board
                        )
                        if additional:
                            for multi in additional:
                                combined = [jump_pos] + multi.jumps
                                jumps.append(
                                    Move(row, col, multi.to_row, multi.to_col, combined)
                                )
                        else:
                            jumps.append(move)

        return jumps

    def is_valid_move(self, move: Move, player: Player) -> bool:
        """Check if a move is valid for the current player."""
        matching_move = self._find_matching_move(move, player)
        if matching_move is None:
            return False

        if move.jumps != matching_move.jumps:
            return False

        return self._validate_move_path(matching_move, player)

    def make_move(self, move: Move, player: Player) -> bool:
        """Execute a move. Returns True if move was successful."""
        matching_move = self._find_matching_move(move, player)
        if matching_move is None:
            return False

        if move.jumps != matching_move.jumps:
            return False

        if not self._validate_move_path(matching_move, player):
            return False

        piece = self.board[matching_move.from_row][matching_move.from_col]

        # Move piece
        self.board[matching_move.to_row][matching_move.to_col] = piece
        self.board[matching_move.from_row][matching_move.from_col] = 0

        # Remove jumped pieces
        for jump_row, jump_col in matching_move.jumps:
            self.board[jump_row][jump_col] = 0

        # Check for king promotion
        if player == 1 and matching_move.to_row == 7:  # Black reaches bottom
            if piece == 1:
                self.board[matching_move.to_row][
                    matching_move.to_col
                ] = 3  # Promote to king
        elif player == 2 and matching_move.to_row == 0:  # White reaches top
            if piece == 2:
                self.board[matching_move.to_row][
                    matching_move.to_col
                ] = 4  # Promote to king

        return True

    def check_game_over(self) -> tuple[bool, Player | None]:
        """Check if game is over. Returns (is_over, winner)."""
        player1_moves = self.get_valid_moves(1)
        player2_moves = self.get_valid_moves(2)

        # Check if players have pieces
        player1_pieces = sum(1 for row in self.board for cell in row if cell in (1, 3))
        player2_pieces = sum(1 for row in self.board for cell in row if cell in (2, 4))

        if player1_pieces == 0:
            return (True, 2)  # Player 2 wins
        if player2_pieces == 0:
            return (True, 1)  # Player 1 wins

        if not player1_moves:
            return (True, 2)  # Player 1 has no moves
        if not player2_moves:
            return (True, 1)  # Player 2 has no moves

        return (False, None)

    def to_dict(self) -> dict:
        """Serialize game state to dictionary."""
        return {"board": self.board}

    @classmethod
    def from_dict(cls, data: dict) -> CheckersGame:
        """Deserialize game state from dictionary."""
        board = data.get("board")
        if board is None:
            return cls()
        return cls(board)

    def to_json(self) -> str:
        """Serialize game state to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> CheckersGame:
        """Deserialize game state from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
