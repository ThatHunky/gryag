from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatAction


class TypingIndicator:
    """Async context manager that keeps Telegram typing indicator alive."""

    def __init__(self, bot: Bot, chat_id: int, interval: float = 4.0) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._interval = max(interval, 1.0)
        self._task: Optional[asyncio.Task] = None
        self._active = False

    async def __aenter__(self) -> "TypingIndicator":
        self._active = True
        await self._send()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            while self._active:
                await asyncio.sleep(self._interval)
                await self._send()
        except asyncio.CancelledError:
            pass

    async def _send(self) -> None:
        try:
            await self._bot.send_chat_action(self._chat_id, ChatAction.TYPING)
        except Exception:
            # Swallow errors to avoid breaking the main flow
            pass


def typing_indicator(bot: Bot, chat_id: int, interval: float = 4.0) -> TypingIndicator:
    """Convenience factory for TypingIndicator context manager."""
    return TypingIndicator(bot=bot, chat_id=chat_id, interval=interval)
