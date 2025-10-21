"""Application-wide constants."""

from aiogram.types import BotCommand

# Bot commands available to all users
USER_COMMANDS = [
    BotCommand(
        command="gryag",
        description="Запитати бота (альтернатива @mention або reply)",
    ),
]

# Command descriptions for UI
COMMAND_DESCRIPTIONS = {
    "gryag": "Запитати бота (альтернатива @mention або reply)",
}
