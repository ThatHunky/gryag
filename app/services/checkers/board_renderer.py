"""Board rendering for checkers game with emoji-based display."""

from __future__ import annotations

from app.services.checkers.game_engine import CheckersGame, Player


def render_board(game: CheckersGame, current_player: Player | None = None) -> str:
    """Render checkers board as emoji-based text with coordinates."""
    board = game.get_board()
    lines = []
    
    # Header with column labels
    lines.append("   a  b  c  d  e  f  g  h")
    lines.append("")
    
    # Board rows
    for row in range(8):
        line = f"{8 - row} "  # Row number (8 to 1)
        
        for col in range(8):
            piece = board[row][col]
            square_type = (row + col) % 2
            
            if square_type == 0:  # Light square (not playable)
                line += "⬜"
            else:  # Dark square (playable)
                if piece == 0:
                    line += "⬛"  # Empty dark square
                elif piece == 1:
                    line += "⚫"  # Black piece
                elif piece == 2:
                    line += "⚪"  # White piece
                elif piece == 3:
                    line += "♚"  # Black king
                elif piece == 4:
                    line += "♔"  # White king
                else:
                    line += "❓"  # Unknown
            
            line += " "
        
        line += f" {8 - row}"  # Row number on right
        lines.append(line)
    
    # Footer
    lines.append("")
    lines.append("   a  b  c  d  e  f  g  h")
    
    # Game status
    forced_capture_hint = False
    if current_player:
        player_name = "⚫ Чорні" if current_player == 1 else "⚪ Білі"
        lines.append(f"\nХід: {player_name}")

        try:
            valid_moves = game.get_valid_moves(current_player)
        except Exception:
            valid_moves = []

        if valid_moves and any(move.jumps for move in valid_moves):
            forced_capture_hint = True
    
    is_over, winner = game.check_game_over()
    if is_over:
        if winner:
            winner_name = "⚫ Чорні" if winner == 1 else "⚪ Білі"
            lines.append(f"🎉 Перемога: {winner_name}")
        else:
            lines.append("🤝 Нічия")
    elif forced_capture_hint:
        lines.append("⚠️ Є обов'язковий удар. Обери фігуру, що може бити суперника.")
    
    return "\n".join(lines)


def render_board_compact(game: CheckersGame, current_player: Player | None = None) -> str:
    """Render compact board representation for inline display."""
    board = game.get_board()
    lines = []
    
    # Compact header
    lines.append("`  a b c d e f g h`")
    
    for row in range(8):
        line = f"`{8 - row}`"
        for col in range(8):
            piece = board[row][col]
            square_type = (row + col) % 2
            
            if square_type == 0:
                line += "⬜"
            else:
                if piece == 0:
                    line += "⬛"  # Empty dark square
                elif piece == 1:
                    line += "⚫"  # Black piece
                elif piece == 2:
                    line += "⚪"  # White piece
                elif piece == 3:
                    line += "♚"  # Black king
                elif piece == 4:
                    line += "♔"  # White king
                else:
                    line += "?"
            line += " "
        line += f"`{8 - row}`"
        lines.append(line)
    
    lines.append("`  a b c d e f g h`")
    
    if current_player:
        player_emoji = "⚫" if current_player == 1 else "⚪"
        lines.append(f"\n{player_emoji} Хід")
    
    return "\n".join(lines)

