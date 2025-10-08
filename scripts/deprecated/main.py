import asyncio
import logging
"""Compatibility shim. Delegates execution to app.main.run()."""

from app.main import run


if __name__ == "__main__":
    run()
	from aiogram import Bot, Dispatcher  # type: ignore
