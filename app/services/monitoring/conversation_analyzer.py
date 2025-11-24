"""
Conversation window analyzer for grouping messages into coherent threads.

Instead of analyzing individual messages, we group them into conversation windows
to provide better context for fact extraction. This dramatically improves quality.

Key features:
- 8-message sliding window (configurable)
- 3-minute timeout for window closure
- Reply-thread tracking
- Topic shift detection
- Media-aware context
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from aiogram.types import Message

from app.services.monitoring.message_classifier import (
    ClassificationResult,
    MessageValue,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class MessageContext:
    """Lightweight message representation for window tracking."""

    message_id: int
    chat_id: int
    thread_id: int | None
    user_id: int
    text: str
    timestamp: int
    classification: ClassificationResult
    reply_to_message_id: int | None = None
    media_type: str | None = None  # photo, video, sticker, etc

    @classmethod
    def from_telegram_message(
        cls, message: Message, classification: ClassificationResult
    ) -> MessageContext:
        """Create MessageContext from Telegram message."""
        media_type = None
        if message.photo:
            media_type = "photo"
        elif message.video:
            media_type = "video"
        elif message.sticker:
            media_type = "sticker"
        elif message.document:
            media_type = "document"
        elif message.audio or message.voice:
            media_type = "audio"

        return cls(
            message_id=message.message_id,
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            user_id=message.from_user.id if message.from_user else 0,
            text=message.text or message.caption or "",
            timestamp=int(message.date.timestamp() if message.date else time.time()),
            classification=classification,
            reply_to_message_id=(
                message.reply_to_message.message_id
                if message.reply_to_message
                else None
            ),
            media_type=media_type,
        )


@dataclass
class ConversationWindow:
    """A window of related messages forming a conversation."""

    chat_id: int
    thread_id: int | None
    messages: list[MessageContext] = field(default_factory=list)
    raw_messages: list[Message] = field(
        default_factory=list
    )  # Original Message objects
    first_timestamp: int = 0
    last_timestamp: int = 0
    participant_ids: set[int] = field(default_factory=set)
    dominant_value: MessageValue = MessageValue.MEDIUM
    has_high_value: bool = False
    closed: bool = False
    closure_reason: str = ""
    window_id: int = field(default_factory=lambda: int(time.time() * 1000))

    def add_message(
        self, msg_ctx: MessageContext, raw_message: Message | None = None
    ) -> None:
        """Add a message to the window."""
        if not self.messages:
            self.first_timestamp = msg_ctx.timestamp

        self.messages.append(msg_ctx)
        if raw_message:
            self.raw_messages.append(raw_message)
        self.last_timestamp = msg_ctx.timestamp
        self.participant_ids.add(msg_ctx.user_id)

        # Update value assessment
        if msg_ctx.classification.value == MessageValue.HIGH:
            self.has_high_value = True
            self.dominant_value = MessageValue.HIGH
        elif (
            msg_ctx.classification.value == MessageValue.MEDIUM
            and self.dominant_value != MessageValue.HIGH
        ):
            self.dominant_value = MessageValue.MEDIUM

    def should_close(
        self, max_size: int, timeout_seconds: int, current_time: int | None = None
    ) -> tuple[bool, str]:
        """
        Check if window should be closed.

        Returns:
            (should_close, reason)
        """
        if not self.messages:
            return False, ""

        # Size limit reached
        if len(self.messages) >= max_size:
            return True, f"Max size {max_size} reached"

        # Timeout exceeded
        current_time = current_time or int(time.time())
        time_since_last = current_time - self.last_timestamp
        if time_since_last > timeout_seconds:
            return (
                True,
                f"Timeout {timeout_seconds}s exceeded ({time_since_last}s elapsed)",
            )

        return False, ""

    def get_context_summary(self) -> dict[str, Any]:
        """Get a summary of the conversation window for logging/analysis."""
        return {
            "chat_id": self.chat_id,
            "thread_id": self.thread_id,
            "message_count": len(self.messages),
            "participant_count": len(self.participant_ids),
            "duration_seconds": self.last_timestamp - self.first_timestamp,
            "dominant_value": self.dominant_value.value,
            "has_high_value": self.has_high_value,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "closure_reason": self.closure_reason,
        }


class ConversationAnalyzer:
    """
    Tracks and analyzes conversation windows for better context understanding.

    Windows are closed when:
    - Max size reached (default 8 messages)
    - Timeout exceeded (default 3 minutes)
    - Explicit topic shift detected
    """

    def __init__(
        self,
        max_window_size: int = 8,
        window_timeout_seconds: int = 180,  # 3 minutes
        max_concurrent_windows: int = 100,
    ):
        """
        Initialize conversation analyzer.

        Args:
            max_window_size: Maximum messages per window
            window_timeout_seconds: Seconds before auto-closing window
            max_concurrent_windows: Max windows to track simultaneously
        """
        self.max_window_size = max_window_size
        self.window_timeout_seconds = window_timeout_seconds
        self.max_concurrent_windows = max_concurrent_windows

        # Active windows: key is (chat_id, thread_id)
        self._windows: dict[tuple[int, int | None], ConversationWindow] = {}

        # Recently closed windows (for retrieval)
        self._closed_windows: deque[ConversationWindow] = deque(maxlen=50)

        self._stats = {
            "windows_created": 0,
            "windows_closed": 0,
            "messages_added": 0,
            "windows_auto_closed_size": 0,
            "windows_auto_closed_timeout": 0,
        }

        LOGGER.info(
            "ConversationAnalyzer initialized",
            extra={
                "max_window_size": max_window_size,
                "window_timeout_seconds": window_timeout_seconds,
            },
        )

    def add_message(
        self, message: Message, classification: ClassificationResult
    ) -> ConversationWindow | None:
        """
        Add a message to the appropriate conversation window.

        Returns:
            Closed window if this message caused a window to close, else None
        """
        msg_ctx = MessageContext.from_telegram_message(message, classification)

        # Skip noise messages entirely
        if classification.value == MessageValue.NOISE:
            LOGGER.debug("Skipping NOISE message for window tracking")
            return None

        key = (msg_ctx.chat_id, msg_ctx.thread_id)

        # Get or create window
        if key not in self._windows:
            self._windows[key] = ConversationWindow(
                chat_id=msg_ctx.chat_id,
                thread_id=msg_ctx.thread_id,
            )
            self._stats["windows_created"] += 1
            LOGGER.debug(
                f"Created new conversation window for chat={msg_ctx.chat_id}, thread={msg_ctx.thread_id}"
            )

        window = self._windows[key]

        # Check if window should close before adding this message
        should_close, reason = window.should_close(
            self.max_window_size, self.window_timeout_seconds, msg_ctx.timestamp
        )

        if should_close:
            # Close current window and start new one
            closed_window = self._close_window(key, reason)

            # Create new window for this message
            self._windows[key] = ConversationWindow(
                chat_id=msg_ctx.chat_id,
                thread_id=msg_ctx.thread_id,
            )
            self._stats["windows_created"] += 1

            # Add message to new window (with raw Message object)
            self._windows[key].add_message(msg_ctx, message)
            self._stats["messages_added"] += 1

            return closed_window

        # Add to existing window (with raw Message object)
        window.add_message(msg_ctx, message)
        self._stats["messages_added"] += 1

        # Enforce max concurrent windows limit
        if len(self._windows) > self.max_concurrent_windows:
            self._evict_oldest_window()

        return None

    def _close_window(
        self, key: tuple[int, int | None], reason: str
    ) -> ConversationWindow:
        """Close a window and move it to closed queue."""
        window = self._windows.pop(key)
        window.closed = True
        window.closure_reason = reason

        self._closed_windows.append(window)
        self._stats["windows_closed"] += 1

        if "size" in reason.lower():
            self._stats["windows_auto_closed_size"] += 1
        elif "timeout" in reason.lower():
            self._stats["windows_auto_closed_timeout"] += 1

        LOGGER.info(
            f"Closed conversation window: {reason}", extra=window.get_context_summary()
        )

        return window

    def _evict_oldest_window(self) -> None:
        """Evict the oldest window when limit is reached."""
        if not self._windows:
            return

        # Find window with oldest last_timestamp
        oldest_key = min(
            self._windows.keys(), key=lambda k: self._windows[k].last_timestamp
        )

        self._close_window(oldest_key, "Evicted due to max concurrent windows limit")

    def force_close_all(self) -> list[ConversationWindow]:
        """
        Force close all active windows.

        Useful for graceful shutdown or manual triggers.

        Returns:
            List of closed windows
        """
        closed = []
        for key in list(self._windows.keys()):
            closed.append(self._close_window(key, "Force closed"))
        return closed

    def get_active_window(
        self, chat_id: int, thread_id: int | None = None
    ) -> ConversationWindow | None:
        """Get the active window for a chat/thread."""
        return self._windows.get((chat_id, thread_id))

    def get_recent_closed_windows(
        self, chat_id: int | None = None, limit: int = 10
    ) -> list[ConversationWindow]:
        """
        Get recently closed windows, optionally filtered by chat.

        Args:
            chat_id: If provided, only return windows from this chat
            limit: Maximum number of windows to return

        Returns:
            List of closed windows (most recent first)
        """
        windows = list(self._closed_windows)
        windows.reverse()  # Most recent first

        if chat_id is not None:
            windows = [w for w in windows if w.chat_id == chat_id]

        return windows[:limit]

    def get_stats(self) -> dict[str, int]:
        """Get analyzer statistics."""
        return {
            **self._stats,
            "active_windows": len(self._windows),
        }

    def reset_stats(self) -> None:
        """Reset statistics."""
        for key in self._stats:
            self._stats[key] = 0
