from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command(commands=["ping"]))
async def ping_command(message: Message, settings: Settings) -> None:
    # Simple health check command; relies on middleware-injected Settings
    await message.reply("pong")


