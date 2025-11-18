"""Donation reminder scheduler service.

Sends periodic donation reminders to active chats to support bot infrastructure costs.
- Group chats: Runs every 2 days at 18:00 Ukraine time (Europe/Kiev timezone)
- Private chats: Runs weekly on Saturday at 19:00 Ukraine time
- Only sends to chats where bot was active in the last 24 hours
- Can be triggered on-demand via /gryagdonate command (admin only, bypasses filters)
- Respects chat whitelist/blacklist settings
- Tracks last send timestamp per chat to avoid spam
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.infrastructure.db_utils import get_db_connection
from app.infrastructure.query_converter import convert_query_to_postgres

if TYPE_CHECKING:
    from aiogram import Bot

    from app.services.context_store import ContextStore

logger = logging.getLogger(__name__)

# Donation message content
DONATION_MESSAGE = """щоб гряг продовжував функціонувати треба оплачувати його комуналку (API)

підтримати проєкт:

🔗Посилання на банку
https://send.monobank.ua/jar/77iG8mGBsH

💳Номер картки банки
4874 1000 2180 1892"""


class DonationScheduler:
    """Background service for sending periodic donation reminders."""

    # Send interval in seconds for group chats (2 days = 48 hours)
    GROUP_SEND_INTERVAL_SECONDS = 2 * 24 * 60 * 60

    # Send interval in seconds for private chats (7 days = 168 hours)
    PRIVATE_SEND_INTERVAL_SECONDS = 7 * 24 * 60 * 60

    # Activity check window (24 hours)
    ACTIVITY_WINDOW_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        bot: Bot,
        db_path: str | Path,
        context_store: ContextStore,
        target_chat_ids: list[int] | None = None,
        ignored_chat_ids: list[int] | None = None,
    ) -> None:
        """Initialize donation scheduler.

        Args:
            bot: Telegram bot instance for sending messages
            db_path: Path to SQLite database for tracking send timestamps
            context_store: Context store for checking bot activity
            target_chat_ids: List of chat IDs to send to (if None, sends to all active chats)
            ignored_chat_ids: List of chat IDs to never send donation messages to
        """
        self.bot = bot
        self.database_url = str(db_path)  # Accept database_url string
        self.context_store = context_store
        self.target_chat_ids = target_chat_ids or []
        self.ignored_chat_ids = set(ignored_chat_ids or [])
        self.scheduler = AsyncIOScheduler(timezone="Europe/Kiev")
        self._running = False
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Initialize database table for tracking send timestamps."""
        # Schema is managed by schema_postgresql.sql
        async with get_db_connection(self.database_url) as conn:
            await conn.execute("SELECT 1")  # Verify connection
        logger.info("Donation scheduler database initialized")

    async def start(self) -> None:
        """Start the donation reminder scheduler."""
        if self._running:
            logger.warning("Donation scheduler already running")
            return

        try:
            # Initialize database
            await self.init()

            # Schedule daily check at 18:00 Ukraine time for group chats
            # This will check if 2 days have passed since last send for each group
            group_trigger = CronTrigger(
                hour=18,
                minute=0,
                second=0,
                timezone="Europe/Kiev",
            )

            self.scheduler.add_job(
                self._send_scheduled_reminders_groups,
                trigger=group_trigger,
                id="donation_reminder_groups",
                name="Send donation reminders to groups",
                replace_existing=True,
            )

            # Schedule weekly check on Saturday at 19:00 Ukraine time for private chats
            # This will check if 7 days have passed since last send for each private chat
            private_trigger = CronTrigger(
                day_of_week="sat",
                hour=19,
                minute=0,
                second=0,
                timezone="Europe/Kiev",
            )

            self.scheduler.add_job(
                self._send_scheduled_reminders_private,
                trigger=private_trigger,
                id="donation_reminder_private",
                name="Send donation reminders to private chats",
                replace_existing=True,
            )

            self.scheduler.start()
            self._running = True

            logger.info(
                "Donation scheduler started (groups: daily at 18:00, private: Saturday at 19:00 Ukraine time)"
            )
        except Exception as e:
            logger.error(f"Failed to start donation scheduler: {e}", exc_info=True)
            self._running = False
            logger.warning(
                "Donation scheduler will continue trying to initialize on next attempt"
            )

    async def stop(self) -> None:
        """Stop the donation reminder scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Donation scheduler stopped")

    async def _send_scheduled_reminders_groups(self) -> None:
        """Check all group chats and send reminders if 2 days have passed."""
        current_ts = int(time.time())

        async with self._lock:
            for chat_id in self.target_chat_ids:
                try:
                    # Skip ignored chats
                    if chat_id in self.ignored_chat_ids:
                        logger.debug(
                            f"Skipping chat {chat_id} (in ignored chat IDs list)"
                        )
                        continue

                    # Only send to groups (negative chat IDs)
                    if chat_id >= 0:
                        logger.debug(
                            f"Skipping chat {chat_id} (not a group, private chat)"
                        )
                        continue

                    # Check if bot has been active in this chat recently (last 24 hours)
                    has_activity = await self._check_recent_activity(
                        chat_id, current_ts
                    )
                    if not has_activity:
                        logger.debug(
                            f"Skipping chat {chat_id} (no bot activity in last 24 hours)"
                        )
                        continue

                    # Check if enough time has passed since last send (2 days for groups)
                    should_send = await self._should_send_to_chat(
                        chat_id, current_ts, self.GROUP_SEND_INTERVAL_SECONDS
                    )

                    if should_send:
                        await self._send_donation_message(chat_id, current_ts)
                        logger.info(
                            f"Sent scheduled donation reminder to group chat {chat_id}"
                        )
                    else:
                        logger.debug(
                            f"Skipping chat {chat_id} (not enough time since last send)"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to send donation reminder to chat {chat_id}: {e}",
                        exc_info=True,
                    )

    async def _send_scheduled_reminders_private(self) -> None:
        """Check all private chats and send reminders if 7 days have passed."""
        current_ts = int(time.time())

        async with self._lock:
            for chat_id in self.target_chat_ids:
                try:
                    # Skip ignored chats
                    if chat_id in self.ignored_chat_ids:
                        logger.debug(
                            f"Skipping chat {chat_id} (in ignored chat IDs list)"
                        )
                        continue

                    # Only send to private chats (positive chat IDs)
                    if chat_id < 0:
                        logger.debug(
                            f"Skipping chat {chat_id} (not a private chat, group)"
                        )
                        continue

                    # Check if bot has been active in this chat recently (last 24 hours)
                    has_activity = await self._check_recent_activity(
                        chat_id, current_ts
                    )
                    if not has_activity:
                        logger.debug(
                            f"Skipping chat {chat_id} (no bot activity in last 24 hours)"
                        )
                        continue

                    # Check if enough time has passed since last send (7 days for private)
                    should_send = await self._should_send_to_chat(
                        chat_id, current_ts, self.PRIVATE_SEND_INTERVAL_SECONDS
                    )

                    if should_send:
                        await self._send_donation_message(chat_id, current_ts)
                        logger.info(
                            f"Sent scheduled donation reminder to private chat {chat_id}"
                        )
                    else:
                        logger.debug(
                            f"Skipping chat {chat_id} (not enough time since last send)"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to send donation reminder to chat {chat_id}: {e}",
                        exc_info=True,
                    )

    async def _check_recent_activity(self, chat_id: int, current_ts: int) -> bool:
        """Check if bot has been active in this chat recently.

        Args:
            chat_id: Chat ID to check
            current_ts: Current timestamp

        Returns:
            True if bot has sent messages in the last 24 hours, False otherwise
        """
        activity_cutoff = current_ts - self.ACTIVITY_WINDOW_SECONDS

        try:
            # Query context store for recent bot messages (role='model')
            query, params = convert_query_to_postgres(
                """
                SELECT COUNT(*) as count FROM messages
                WHERE chat_id = $1 AND role = 'model' AND ts >= $2
                """,
                (chat_id, activity_cutoff),
            )
            async with get_db_connection(self.database_url) as conn:
                row = await conn.fetchrow(query, *params)
                count = row["count"] if row else 0

                return count > 0

        except Exception as e:
            logger.error(
                f"Failed to check activity for chat {chat_id}: {e}",
                exc_info=True,
            )
            # Default to False (don't send if we can't verify activity)
            return False

    async def _should_send_to_chat(
        self, chat_id: int, current_ts: int, interval_seconds: int
    ) -> bool:
        """Check if we should send donation message to this chat.

        Args:
            chat_id: Chat ID to check
            current_ts: Current timestamp
            interval_seconds: Required interval in seconds since last send

        Returns:
            True if we should send, False otherwise
        """
        try:
            query, params = convert_query_to_postgres(
                "SELECT last_send_ts FROM donation_sends WHERE chat_id = $1",
                (chat_id,),
            )
            async with get_db_connection(self.database_url) as conn:
                row = await conn.fetchrow(query, *params)

                if not row:
                    # Never sent before, should send
                    return True

                last_send_ts = row["last_send_ts"]
                time_since_last = current_ts - last_send_ts

                # Check if enough time has passed based on the interval
                return time_since_last >= interval_seconds
        except Exception as e:
            logger.warning(
                f"Failed to check send interval for chat {chat_id}: {e}",
                exc_info=True,
            )
            # Default to False (don't send if we can't verify timing)
            return False

    async def _send_donation_message(self, chat_id: int, current_ts: int) -> None:
        """Send donation message to a chat and update database.

        Args:
            chat_id: Chat ID to send to
            current_ts: Current timestamp
        """
        try:
            # Send message to Telegram
            await self.bot.send_message(chat_id, DONATION_MESSAGE)
        except Exception as e:
            logger.warning(
                f"Failed to send donation message to chat {chat_id}: {e}",
                exc_info=True,
            )
            # Re-raise to be caught by caller, but log the error
            raise

        # Update database tracking
        try:
            query, params = convert_query_to_postgres(
                """
                INSERT INTO donation_sends (chat_id, last_send_ts, send_count)
                VALUES ($1, $2, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    last_send_ts = excluded.last_send_ts,
                    send_count = send_count + 1
                """,
                (chat_id, current_ts),
            )
            async with get_db_connection(self.database_url) as conn:
                await conn.execute(query, *params)
        except Exception as e:
            logger.error(
                f"Failed to update donation send database for chat {chat_id}: {e}",
                exc_info=True,
            )
            # Don't re-raise - we already sent the message, just couldn't track it

    async def send_now(self, chat_id: int, bypass_ignored: bool = True) -> bool:
        """Send donation message immediately to a specific chat.

        This is used by the /gryagdonate command for on-demand sends.
        Bypasses group and activity filters (admin-triggered, so can send anywhere).
        By default, bypasses ignored chat IDs list for admin convenience.

        Args:
            chat_id: Chat ID to send to
            bypass_ignored: If True, ignores the ignored_chat_ids list (default True)

        Returns:
            True if sent successfully, False otherwise
        """
        # Check if chat is in ignored list (unless bypassing)
        if not bypass_ignored and chat_id in self.ignored_chat_ids:
            logger.info(
                f"Cannot send on-demand donation message to chat {chat_id}: chat is in ignored list"
            )
            return False

        current_ts = int(time.time())

        async with self._lock:
            try:
                await self._send_donation_message(chat_id, current_ts)
                logger.info(f"Sent on-demand donation message to chat {chat_id}")
                return True
            except Exception as e:
                logger.error(
                    f"Failed to send on-demand donation message to chat {chat_id}: {e}",
                    exc_info=True,
                )
                return False

    def add_chat(self, chat_id: int) -> None:
        """Add a chat to the target list.

        Args:
            chat_id: Chat ID to add
        """
        if chat_id not in self.target_chat_ids:
            self.target_chat_ids.append(chat_id)
            logger.debug(f"Added chat {chat_id} to donation scheduler targets")

    def remove_chat(self, chat_id: int) -> None:
        """Remove a chat from the target list.

        Args:
            chat_id: Chat ID to remove
        """
        if chat_id in self.target_chat_ids:
            self.target_chat_ids.remove(chat_id)
            logger.debug(f"Removed chat {chat_id} from donation scheduler targets")
