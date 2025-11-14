"""Checkers game handlers for Telegram bot."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InaccessibleMessage,
)
from aiogram.enums import ParseMode

from app.config import Settings
from app.services.checkers.game_engine import CheckersGame, Player
from app.services.checkers.board_renderer import render_board
from app.services.checkers.game_store import CheckersGameStore

router = Router()
logger = logging.getLogger(__name__)


# In-memory storage for selected squares (game_id -> {user_id: (row, col)})
_selected_squares: dict[str, dict[int, tuple[int, int] | None]] = {}


def _get_user_display_name(user: Any) -> str:
    """Get display name for user."""
    if not user:
        return "Користувач"
    return user.full_name or user.username or f"User {user.id}"


def _create_challenge_keyboard(game_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for a pending challenge."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Приєднатися до гри",
                    callback_data=f"checkers:join:{game_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати виклик",
                    callback_data=f"checkers:cancel:{game_id}",
                )
            ],
        ]
    )


def _create_final_keyboard(game_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for post-game actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Реванш",
                    callback_data=f"checkers:rematch:{game_id}",
                )
            ],
        ]
    )


async def _fetch_user_name(bot: Bot, chat_id: int, user_id: int) -> str:
    """Fetch user's display name from chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return _get_user_display_name(member.user)
    except Exception as e:
        logger.debug(f"Cannot fetch name for user {user_id} in chat {chat_id}: {e}")
        return f"Користувач {user_id}"


def _create_board_keyboard(
    game: CheckersGame,
    game_id: str,
    current_player: Player,
    selected_square: tuple[int, int] | None = None,
) -> InlineKeyboardMarkup:
    """Create inline keyboard for checkers board."""
    board = game.get_board()
    keyboard = []
    
    # Get valid moves for current player
    valid_moves = game.get_valid_moves(current_player)
    valid_from_squares = {(m.from_row, m.from_col) for m in valid_moves}
    valid_to_squares = {(m.to_row, m.to_col) for m in valid_moves}
    
    # If a square is selected, show valid destination squares
    if selected_square:
        from_row, from_col = selected_square
        valid_destinations = {
            (m.to_row, m.to_col)
            for m in valid_moves
            if m.from_row == from_row and m.from_col == from_col
        }
    else:
        valid_destinations = set()
    
    # Only show playable squares (dark squares) for cleaner interface
    for row in range(8):
        row_buttons = []
        for col in range(8):
            square_type = (row + col) % 2
            piece = board[row][col]

            if square_type == 0:  # Light square (not playable)
                button_text = " "
                callback_data = "checkers:ignore"
            else:
                # Determine button text
                if piece == 0:
                    button_text = " "
                elif piece == 1:
                    button_text = "⚫"
                elif piece == 2:
                    button_text = "⚪"
                elif piece == 3:
                    button_text = "♚"
                elif piece == 4:
                    button_text = "♔"
                else:
                    button_text = "❓"

                # Highlight indicators (priority: selected > valid destination)
                if selected_square and selected_square == (row, col):
                    button_text = f"🔵{button_text}"
                elif selected_square and (row, col) in valid_destinations:
                    button_text = f"🟢{button_text}"

                # Check if this square is part of a valid move
                is_valid_from = (row, col) in valid_from_squares
                is_valid_to = (row, col) in valid_destinations
                is_current_piece = (
                    (current_player == 1 and piece in (1, 3)) or
                    (current_player == 2 and piece in (2, 4))
                )

                if selected_square:
                    callback_data = (
                        f"checkers:move:{game_id}:{row}:{col}"
                        if is_valid_to
                        else "checkers:ignore"
                    )
                else:
                    callback_data = (
                        f"checkers:select:{game_id}:{row}:{col}"
                        if is_valid_from and is_current_piece
                        else "checkers:ignore"
                    )

            row_buttons.append(
                InlineKeyboardButton(text=button_text, callback_data=callback_data)
            )

        keyboard.append(row_buttons)
    
    if selected_square:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="↩️ Скасувати вибір",
                    callback_data=f"checkers:clear:{game_id}",
                )
            ]
        )

    # Add separator row (empty row for visual spacing)
    keyboard.append([
        InlineKeyboardButton(text="━━━━━━━━━━━━━━━━━━━━", callback_data="checkers:ignore")
    ])
    
    # Add control buttons with better visibility
    control_row = [
        InlineKeyboardButton(
            text="🏳️ Здатися", callback_data=f"checkers:forfeit:{game_id}"
        )
    ]
    keyboard.append(control_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _send_game_board(
    bot: Bot,
    game: CheckersGame,
    game_id: str,
    current_player: Player,
    chat_id: int,
    challenger_id: int,
    opponent_id: int,
    thread_id: int | None = None,
    message_id: int | None = None,
    selected_square: tuple[int, int] | None = None,
) -> int:
    """Send or update game board message. Returns message ID."""
    board_text = render_board(game, current_player)

    challenger_name = await _fetch_user_name(bot, chat_id, challenger_id)
    opponent_name = await _fetch_user_name(bot, chat_id, opponent_id)

    # Add game info with better formatting
    player_name = "⚫ Чорні" if current_player == 1 else "⚪ Білі"
    info_text = (
        "<b>🎮 Шашки</b>\n"
        f"⚫ {challenger_name}\n"
        f"⚪ {opponent_name}\n\n"
        f"{board_text}\n\n"
        f"<b>{player_name} ходять</b>"
    )

    keyboard = _create_board_keyboard(game, game_id, current_player, selected_square)

    try:
        if message_id:
            # Update existing message
            await bot.edit_message_text(
                info_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return message_id
        else:
            # Send new message
            sent = await bot.send_message(
                chat_id=chat_id,
                text=info_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                message_thread_id=thread_id,
            )
            return sent.message_id
    except Exception as e:
        logger.error(f"Error sending/updating game board: {e}")
        raise


@router.message(Command(commands=["checkers", "шашки"]))
async def checkers_command(
    message: Message,
    settings: Settings,
    store: Any,  # ContextStore - not used but may be injected
) -> None:
    """Handle /checkers command to publish a public challenge."""
    if not message.from_user:
        await message.reply("❌ Помилка: невідомий користувач")
        return
    
    bot = message.bot
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    challenger_name = _get_user_display_name(message.from_user)
    
    game_store = CheckersGameStore(settings.database_url)
    existing_game = await game_store.get_open_game(chat_id, thread_id, user_id)

    if existing_game:
        status = existing_game["game_status"]
        if status == "pending":
            await message.reply(
                "⚠️ У тебе вже є відкритий виклик. Скасуй його, перш ніж створювати новий."
            )
        elif status == "active":
            await message.reply(
                "⚠️ Ти вже граєш у шашки. Заверши поточну гру, щоб почати нову."
            )
        else:
            await message.reply("⚠️ Заверш попередню гру перед створенням нової.")
        return

    try:
        game_id = await game_store.create_challenge(
            chat_id=chat_id,
            thread_id=thread_id,
            challenger_id=user_id,
        )
    except Exception as e:
        logger.error(f"Error creating checkers challenge: {e}", exc_info=True)
        await message.reply("❌ Не вдалося створити виклик. Спробуй ще раз пізніше.")
        return

    challenge_text = (
        f"🎮 {challenger_name} шукає суперника у шашки!\n"
        "Натисни кнопку нижче, щоб приєднатися до гри.\n"
        "Якщо передумав, скасуй виклик."
    )

    keyboard = _create_challenge_keyboard(game_id)

    try:
        challenge_message = await bot.send_message(
            chat_id=chat_id,
            text=challenge_text,
            reply_markup=keyboard,
            message_thread_id=thread_id,
        )
        await game_store.set_challenge_message(game_id, challenge_message.message_id)
    except Exception as e:
        logger.error(f"Error sending challenge message: {e}", exc_info=True)
        await message.reply("❌ Не вдалося надіслати виклик. Спробуй ще раз.")
        return

    await message.reply("✅ Виклик опубліковано! Чекаємо на суперника.")


@router.message(Command(commands=["checkers_abandon", "шашки_покинути"]))
async def checkers_abandon_command(
    message: Message,
    settings: Settings,
) -> None:
    """Handle /checkers_abandon command to cancel challenge or resign from a game."""
    if not message.from_user:
        await message.reply("❌ Помилка: невідомий користувач")
        return
    
    bot = message.bot
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    
    game_store = CheckersGameStore(settings.database_url)
    game_data = await game_store.get_open_game(chat_id, thread_id, user_id)

    if not game_data:
        await message.reply("❌ Немає активного виклику чи гри.")
        return

    game_id = game_data["id"]
    status = game_data["game_status"]

    if status == "pending":
        if game_data["challenger_id"] != user_id:
            await message.reply("❌ Скасувати виклик може лише його автор.")
            return

        success = await game_store.cancel_challenge(game_id, user_id)
        if not success:
            await message.reply("❌ Не вдалося скасувати виклик.")
            return

        _selected_squares.pop(game_id, None)

        challenge_message_id = game_data.get("challenge_message_id")
        if challenge_message_id:
            try:
                await bot.edit_message_text(
                    "❌ Виклик у шашки скасовано.",
                    chat_id=chat_id,
                    message_id=challenge_message_id,
                    reply_markup=None,
                )
            except Exception as e:
                logger.debug(f"Unable to edit challenge message {challenge_message_id}: {e}")

        await message.reply("✅ Виклик скасовано.")
        return

    if status != "active":
        await message.reply("❌ Гра вже завершена.")
        return

    challenger_id = game_data["challenger_id"]
    opponent_id = game_data["opponent_id"]

    if user_id not in (challenger_id, opponent_id):
        await message.reply("❌ Це не твоя гра.")
        return

    winner_id = opponent_id if user_id == challenger_id else challenger_id
    winner_player: Player = 2 if winner_id == opponent_id else 1

    try:
        game_engine = CheckersGame.from_json(game_data["game_state"])
    except Exception as e:
        logger.error(f"Error parsing game state during abandon command: {e}", exc_info=True)
        await message.reply("❌ Неможливо завершити гру через помилку стану.")
        return

    board_message_id = game_data.get("board_message_id")

    try:
        await game_store.update_game(
            game_id,
            game_engine.to_json(),
            current_player=winner_id,
            game_status="finished",
            winner_id=winner_id,
            board_message_id=board_message_id,
        )
    except Exception as e:
        logger.error(f"Error updating game after abandon command: {e}", exc_info=True)
        await message.reply("❌ Не вдалося завершити гру.")
        return

    try:
        board_text = render_board(game_engine, None)
        challenger_name = await _fetch_user_name(bot, chat_id, challenger_id)
        opponent_name = await _fetch_user_name(bot, chat_id, opponent_id)
        winner_text = "⚫ Чорні" if winner_player == 1 else "⚪ Білі"
        final_text = (
            "<b>Шашки - гра завершена</b>\n"
            f"⚫ {challenger_name}\n"
            f"⚪ {opponent_name}\n\n"
            f"{board_text}\n\n"
            f"🎉 Перемога: {winner_text}\n"
            "🏳️ Суперник здався."
        )

        if board_message_id:
            try:
                await bot.edit_message_text(
                    final_text,
                    chat_id=chat_id,
                    message_id=board_message_id,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_create_final_keyboard(game_id),
                )
            except Exception as e:
                logger.debug(f"Unable to edit board message {board_message_id}: {e}")
    except Exception as e:
        logger.error(f"Error rendering final board after abandon command: {e}", exc_info=True)

    _selected_squares.pop(game_id, None)
    await message.reply("🏳️ Ти здався. Гру завершено.")


@router.callback_query(lambda c: c.data and c.data.startswith("checkers:"))
async def checkers_callback(
    callback: CallbackQuery,
    settings: Settings,
) -> None:
    """Handle checkers game callbacks (challenge flow, moves, forfeits)."""
    if not callback.data or not callback.from_user or not callback.message:
        await callback.answer("❌ Помилка")
        return

    if isinstance(callback.message, InaccessibleMessage):
        await callback.answer("❌ Повідомлення недоступне")
        return

    bot = callback.bot
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id

    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else None

    game_store = CheckersGameStore(settings.database_url)

    if action == "ignore":
        await callback.answer("", show_alert=False)
        return

    if action == "clear":
        if len(parts) < 3:
            await callback.answer("❌ Помилка: неправильний формат")
            return

        game_id = parts[2]
        try:
            game_data = await game_store.get_game(game_id)
        except Exception as e:
            logger.error(f"Error fetching game {game_id} for clear: {e}", exc_info=True)
            await callback.answer("❌ Помилка")
            return

        if not game_data:
            await callback.answer("❌ Гру не знайдено")
            return

        if game_data["game_status"] != "active":
            await callback.answer("❌ Гра недоступна")
            return

        challenger_id = game_data["challenger_id"]
        opponent_id = game_data["opponent_id"]

        if user_id not in (challenger_id, opponent_id):
            await callback.answer("❌ Це не твоя гра")
            return

        current_player_id = game_data["current_player"]
        if current_player_id != user_id:
            await callback.answer("❌ Зараз хід суперника")
            return

        if game_id not in _selected_squares or _selected_squares[game_id].get(user_id) is None:
            await callback.answer("ℹ️ Немає активного вибору")
            return

        try:
            game_engine = CheckersGame.from_json(game_data["game_state"])
        except Exception as e:
            logger.error(f"Error parsing game state on clear: {e}", exc_info=True)
            await callback.answer("❌ Помилка зі станом гри")
            return

        current_player_enum: Player = 1 if user_id == challenger_id else 2
        _selected_squares[game_id][user_id] = None

        board_message_id = game_data["board_message_id"] or callback.message.message_id

        try:
            await _send_game_board(
                bot=bot,
                game=game_engine,
                game_id=game_id,
                current_player=current_player_enum,
                chat_id=chat_id,
                challenger_id=challenger_id,
                opponent_id=opponent_id,
                message_id=board_message_id,
            )
            await callback.answer("↩️ Вибір скасовано")
        except Exception as e:
            logger.error(f"Error updating board after clear: {e}", exc_info=True)
            await callback.answer("❌ Не вдалося оновити дошку")
        return

    if action in {"cancel", "join", "forfeit", "rematch"}:
        if len(parts) < 3:
            await callback.answer("❌ Помилка: неправильний формат")
            return

        game_id = parts[2]

        if action == "cancel":
            try:
                game = await game_store.get_game(game_id)
            except Exception as e:
                logger.error(f"Error fetching game {game_id} for cancel: {e}", exc_info=True)
                await callback.answer("❌ Помилка")
                return

            if not game:
                await callback.answer("❌ Виклик не знайдено")
                return

            if game["game_status"] != "pending":
                await callback.answer("❌ Цей виклик вже недоступний")
                return

            if game["challenger_id"] != user_id:
                await callback.answer("❌ Лише автор виклику може його скасувати")
                return

            success = await game_store.cancel_challenge(game_id, user_id)
            if not success:
                await callback.answer("❌ Не вдалося скасувати виклик")
                return

            try:
                await callback.message.edit_text(
                    "❌ Виклик у шашки скасовано.",
                    reply_markup=None,
                )
            except Exception as e:
                logger.debug(f"Failed to edit challenge message after cancel: {e}")

            _selected_squares.pop(game_id, None)
            await callback.answer("✅ Виклик скасовано")
            return

        if action == "rematch":
            try:
                game = await game_store.get_game(game_id)
            except Exception as e:
                logger.error(f"Error fetching game {game_id} for rematch: {e}", exc_info=True)
                await callback.answer("❌ Помилка")
                return

            if not game:
                await callback.answer("❌ Гру не знайдено")
                return

            if game["game_status"] not in {"finished", "cancelled"}:
                await callback.answer("❌ Реванш поки недоступний")
                return

            challenger_id = game["challenger_id"]
            opponent_id = game["opponent_id"]

            if user_id not in (challenger_id, opponent_id):
                await callback.answer("❌ Це не твоя гра")
                return

            existing_for_user = await game_store.get_open_game(chat_id, thread_id, user_id)
            if existing_for_user:
                await callback.answer("⚠️ Спершу заверши свій поточний виклик або гру")
                return

            try:
                new_game_id = await game_store.create_challenge(
                    chat_id=chat_id,
                    thread_id=thread_id,
                    challenger_id=user_id,
                )
            except Exception as e:
                logger.error(f"Error creating rematch challenge: {e}", exc_info=True)
                await callback.answer("❌ Не вдалося створити новий виклик")
                return

            challenger_name = await _fetch_user_name(bot, chat_id, user_id)
            if opponent_id:
                opponent_name = await _fetch_user_name(bot, chat_id, opponent_id)
                rematch_text = (
                    f"🔁 {challenger_name} хоче реванш у шашки проти {opponent_name}!\n"
                    "Натисни кнопку нижче, щоб приєднатися до нової партії."
                )
            else:
                rematch_text = (
                    f"🔁 {challenger_name} хоче зіграти реванш у шашки!\n"
                    "Натисни кнопку нижче, щоб приєднатися."
                )

            keyboard = _create_challenge_keyboard(new_game_id)

            try:
                challenge_message = await bot.send_message(
                    chat_id=chat_id,
                    text=rematch_text,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                )
                await game_store.set_challenge_message(new_game_id, challenge_message.message_id)
            except Exception as e:
                logger.error(f"Error sending rematch challenge: {e}", exc_info=True)
                await callback.answer("❌ Не вдалося надіслати новий виклик")
                return

            await callback.answer("✅ Новий виклик створено!")
            return

        if action == "join":
            try:
                game = await game_store.get_game(game_id)
            except Exception as e:
                logger.error(f"Error fetching game {game_id} for join: {e}", exc_info=True)
                await callback.answer("❌ Помилка")
                return

            if not game:
                await callback.answer("❌ Виклик не знайдено")
                return

            if game["game_status"] != "pending":
                await callback.answer("❌ До цієї гри вже приєдналися")
                return

            challenger_id = game["challenger_id"]

            if challenger_id == user_id:
                await callback.answer("⚠️ Це твій власний виклик")
                return

            existing_for_user = await game_store.get_open_game(chat_id, thread_id, user_id)
            if existing_for_user:
                await callback.answer("⚠️ Спершу заверши свою поточну гру або виклик")
                return

            game_engine = CheckersGame()
            game_state_json = game_engine.to_json()

            try:
                board_message_id = await _send_game_board(
                    bot=bot,
                    game=game_engine,
                    game_id=game_id,
                    current_player=1,
                    chat_id=chat_id,
                    challenger_id=challenger_id,
                    opponent_id=user_id,
                    thread_id=thread_id,
                )
            except Exception as e:
                logger.error(f"Error sending initial board message: {e}", exc_info=True)
                await callback.answer("❌ Не вдалося створити гру")
                return

            activated = await game_store.accept_challenge(
                game_id=game_id,
                opponent_id=user_id,
                game_state_json=game_state_json,
                board_message_id=board_message_id,
                starting_player_id=challenger_id,
            )

            if not activated:
                await callback.answer("❌ Не вдалося відкрити гру")
                return

            _selected_squares[game_id] = {
                challenger_id: None,
                user_id: None,
            }

            try:
                challenger_name = await _fetch_user_name(bot, chat_id, challenger_id)
                opponent_name = _get_user_display_name(callback.from_user)
                await callback.message.edit_text(
                    (
                        "<b>Шашки - гра розпочалася!</b>\n\n"
                        f"⚫ {challenger_name}\n"
                        f"⚪ {opponent_name}\n"
                        "Бажаємо успіху обом гравцям!"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                )
            except Exception as e:
                logger.debug(f"Failed to edit challenge message after join: {e}")

            await callback.answer("✅ Ти приєднався до гри! Хід чорних.")
            return

        if action == "forfeit":
            try:
                game_data = await game_store.get_game(game_id)
            except Exception as e:
                logger.error(f"Error fetching game {game_id} for forfeit: {e}", exc_info=True)
                await callback.answer("❌ Помилка")
                return

            if not game_data:
                await callback.answer("❌ Гру не знайдено")
                return

            if game_data["game_status"] != "active":
                await callback.answer("❌ Гра вже завершена")
                return

            challenger_id = game_data["challenger_id"]
            opponent_id = game_data["opponent_id"]

            if user_id not in (challenger_id, opponent_id):
                await callback.answer("❌ Це не твоя гра")
                return

            winner_id = opponent_id if user_id == challenger_id else challenger_id
            winner_player: Player = 2 if winner_id == opponent_id else 1

            try:
                game_engine = CheckersGame.from_json(game_data["game_state"])
            except Exception as e:
                logger.error(f"Error parsing game state on forfeit: {e}", exc_info=True)
                await callback.answer("❌ Помилка зі станом гри")
                return

            board_message_id = game_data["board_message_id"] or callback.message.message_id

            try:
                await game_store.update_game(
                    game_id,
                    game_engine.to_json(),
                    current_player=winner_id,
                    game_status="finished",
                    winner_id=winner_id,
                    board_message_id=board_message_id,
                )
            except Exception as e:
                logger.error(f"Error updating game after forfeit: {e}", exc_info=True)
                await callback.answer("❌ Не вдалося завершити гру")
                return

            try:
                board_text = render_board(game_engine, None)
                challenger_name = await _fetch_user_name(bot, chat_id, challenger_id)
                opponent_name = await _fetch_user_name(bot, chat_id, opponent_id)
                winner_text = "⚫ Чорні" if winner_player == 1 else "⚪ Білі"
                final_text = (
                    "<b>Шашки - гра завершена</b>\n"
                    f"⚫ {challenger_name}\n"
                    f"⚪ {opponent_name}\n\n"
                    f"{board_text}\n\n"
                    f"🎉 Перемога: {winner_text}\n"
                    "🏳️ Суперник здався."
                )

                await bot.edit_message_text(
                    final_text,
                    chat_id=chat_id,
                    message_id=board_message_id,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_create_final_keyboard(game_id),
                )
            except Exception as e:
                logger.error(f"Error updating board after forfeit: {e}", exc_info=True)

            _selected_squares.pop(game_id, None)
            await callback.answer("🏳️ Ти здався. Гру завершено.")
            return

    if len(parts) < 3:
        await callback.answer("❌ Помилка: неправильний формат")
        return

    game_id = parts[2]

    try:
        game_data = await game_store.get_game(game_id)
    except Exception as e:
        logger.error(f"Error fetching game {game_id}: {e}", exc_info=True)
        await callback.answer("❌ Помилка")
        return

    if not game_data:
        await callback.answer("❌ Гра не знайдена")
        return

    if game_data["game_status"] != "active":
        await callback.answer("❌ Гра недоступна")
        return

    challenger_id = game_data["challenger_id"]
    opponent_id = game_data["opponent_id"]

    if not opponent_id:
        await callback.answer("❌ Гра ще не почалася")
        return

    current_player_id = game_data["current_player"]

    if current_player_id not in (challenger_id, opponent_id):
        await callback.answer("❌ Невідомий стан гри")
        return

    current_player_enum: Player = 1 if current_player_id == challenger_id else 2

    if action == "select":
        if len(parts) < 5:
            await callback.answer("❌ Помилка: неправильний формат")
            return
        try:
            row = int(parts[3])
            col = int(parts[4])
        except ValueError:
            await callback.answer("❌ Невірні координати")
            return

        if current_player_id != user_id:
            await callback.answer("❌ Зачекай на свій хід")
            return

        try:
            game_engine = CheckersGame.from_json(game_data["game_state"])
        except Exception as e:
            logger.error(f"Error parsing game state on select: {e}", exc_info=True)
            await callback.answer("❌ Помилка зі станом гри")
            return

        _selected_squares.setdefault(game_id, {})
        _selected_squares[game_id][user_id] = (row, col)

        try:
            await _send_game_board(
                bot=bot,
                game=game_engine,
                game_id=game_id,
                current_player=current_player_enum,
                chat_id=chat_id,
                challenger_id=challenger_id,
                opponent_id=opponent_id,
                thread_id=thread_id,
                message_id=game_data["board_message_id"] or callback.message.message_id,
                selected_square=(row, col),
            )
            await callback.answer("✅ Обери клітинку для ходу.")
        except Exception as e:
            logger.error(f"Error updating board after select: {e}", exc_info=True)
            await callback.answer("❌ Не вдалося оновити дошку")
        return

    if action == "move":
        if len(parts) < 5:
            await callback.answer("❌ Помилка: неправильний формат")
            return
        try:
            to_row = int(parts[3])
            to_col = int(parts[4])
        except ValueError:
            await callback.answer("❌ Невірні координати")
            return

        if current_player_id != user_id:
            await callback.answer("❌ Зачекай на свій хід")
            return

        selected = _selected_squares.get(game_id, {}).get(user_id)
        if not selected:
            await callback.answer("❌ Спочатку обери фігуру")
            return

        from_row, from_col = selected

        try:
            game_engine = CheckersGame.from_json(game_data["game_state"])
        except Exception as e:
            logger.error(f"Error parsing game state on move: {e}", exc_info=True)
            await callback.answer("❌ Помилка зі станом гри")
            return

        try:
            valid_moves = game_engine.get_valid_moves(current_player_enum)
        except Exception as e:
            logger.error(f"Error getting valid moves: {e}", exc_info=True)
            await callback.answer("❌ Не вдалося перевірити хід")
            return

        matching_move = next(
            (
                vm
                for vm in valid_moves
                if vm.from_row == from_row
                and vm.from_col == from_col
                and vm.to_row == to_row
                and vm.to_col == to_col
            ),
            None,
        )

        if not matching_move:
            await callback.answer("❌ Невірний хід")
            if game_id in _selected_squares:
                _selected_squares[game_id][user_id] = None
            return

        try:
            success = game_engine.make_move(matching_move, current_player_enum)
        except Exception as e:
            logger.error(f"Error executing move: {e}", exc_info=True)
            await callback.answer("❌ Помилка при виконанні ходу")
            if game_id in _selected_squares:
                _selected_squares[game_id][user_id] = None
            return

        if not success:
            await callback.answer("❌ Невірний хід")
            if game_id in _selected_squares:
                _selected_squares[game_id][user_id] = None
            return

        if game_id in _selected_squares:
            _selected_squares[game_id][user_id] = None

        try:
            is_over, winner_player = game_engine.check_game_over()
        except Exception as e:
            logger.error(f"Error checking game over: {e}", exc_info=True)
            is_over, winner_player = False, None

        board_message_id = game_data["board_message_id"] or callback.message.message_id

        if is_over:
            winner_id = (
                challenger_id if winner_player == 1 else opponent_id if winner_player == 2 else None
            )
            try:
                await game_store.update_game(
                    game_id,
                    game_engine.to_json(),
                    current_player=user_id,
                    game_status="finished",
                    winner_id=winner_id,
                    board_message_id=board_message_id,
                )
            except Exception as e:
                logger.error(f"Error saving finished game: {e}", exc_info=True)

            try:
                board_text = render_board(game_engine, None)
                challenger_name = await _fetch_user_name(bot, chat_id, challenger_id)
                opponent_name = await _fetch_user_name(bot, chat_id, opponent_id)
                if winner_player == 1:
                    winner_text = "⚫ Чорні"
                elif winner_player == 2:
                    winner_text = "⚪ Білі"
                else:
                    winner_text = "🤝 Нічия"

                final_text = (
                    "<b>Шашки - гра завершена</b>\n"
                    f"⚫ {challenger_name}\n"
                    f"⚪ {opponent_name}\n\n"
                    f"{board_text}\n\n"
                    f"🎉 Перемога: {winner_text}"
                )

                await bot.edit_message_text(
                    final_text,
                    chat_id=chat_id,
                    message_id=board_message_id,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"Error showing final board: {e}", exc_info=True)

            _selected_squares.pop(game_id, None)
            await callback.answer("🎉 Гра завершена!")
            return

        next_player_id = opponent_id if current_player_id == challenger_id else challenger_id
        next_player_enum: Player = 1 if next_player_id == challenger_id else 2

        try:
            await game_store.update_game(
                game_id,
                game_engine.to_json(),
                current_player=next_player_id,
                board_message_id=board_message_id,
            )
        except Exception as e:
            logger.error(f"Error updating game state: {e}", exc_info=True)
            await callback.answer("❌ Не вдалося зберегти хід")
            return

        try:
            await _send_game_board(
                bot=bot,
                game=game_engine,
                game_id=game_id,
                current_player=next_player_enum,
                chat_id=chat_id,
                challenger_id=challenger_id,
                opponent_id=opponent_id,
                thread_id=thread_id,
                message_id=board_message_id,
            )
            await callback.answer("✅ Хід виконано")
        except Exception as e:
            logger.error(f"Error refreshing board after move: {e}", exc_info=True)
            await callback.answer("❌ Не вдалося оновити дошку")
        return

    await callback.answer("❌ Невідомий запит")

