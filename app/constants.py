"""Application-wide constants."""

from aiogram.types import BotCommand

# Bot commands available to all users
USER_COMMANDS = [
    BotCommand(
        command="gryag",
        description="Запитати бота (альтернатива @mention або reply)",
    ),
    BotCommand(
        command="checkers",
        description="🎮 Створити виклик у шашки",
    ),
    BotCommand(
        command="checkers_abandon",
        description="🏳️ Скасувати виклик або здатися",
    ),
]

# Command descriptions for UI
COMMAND_DESCRIPTIONS = {
    "gryag": "Запитати бота (альтернатива @mention або reply)",
    "checkers": "🎮 Створити виклик у шашки",
    "checkers_abandon": "🏳️ Скасувати виклик або здатися",
}

# Checkers commands (exported for command throttle)
CHECKERS_COMMANDS = [
    BotCommand(
        command="checkers",
        description="🎮 Створити виклик у шашки",
    ),
    BotCommand(
        command="checkers_abandon",
        description="🏳️ Скасувати виклик або здатися",
    ),
]
