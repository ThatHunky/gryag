"""
Integration helpers for bot self-learning in chat handler.

Provides background tasks that analyze bot interactions and user reactions
to populate the bot self-learning system without blocking message flow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from aiogram.types import Message

from app.services.bot_profile import BotProfileStore
from app.services.bot_learning import BotLearningEngine
from app.services.context_store import ContextStore

LOGGER = logging.getLogger(__name__)


async def track_bot_interaction(
    bot_profile: BotProfileStore,
    bot_id: int,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
    response_text: str,
    response_time_ms: int,
    token_count: int,
    tools_used: list[str] | None = None,
) -> None:
    """
    Record bot's interaction after sending a response.

    This is a fire-and-forget background task that tracks the bot's
    response for later analysis. Initial outcome is "neutral" and will
    be updated if user reacts.

    Args:
        bot_profile: Bot profile store
        bot_id: Bot's Telegram user ID (unused, profile uses internal ID)
        chat_id: Chat ID
        thread_id: Thread ID (optional)
        message_id: Bot's response message ID
        response_text: What bot said
        response_time_ms: Time taken to generate response
        token_count: Estimated token count
        tools_used: List of tool names used (if any)
    """
    try:
        # Generate context tags
        now = datetime.now()
        context_tags = [
            (
                "morning"
                if 6 <= now.hour < 12
                else (
                    "afternoon"
                    if 12 <= now.hour < 18
                    else "evening" if 18 <= now.hour < 22 else "night"
                )
            ),
            "weekend" if now.weekday() >= 5 else "weekday",
        ]

        # Add tool tags if tools were used
        if tools_used:
            context_tags.extend([f"tool_{tool}" for tool in tools_used])

        # Record interaction with initial "neutral" outcome
        # This will be updated later if user reacts
        await bot_profile.record_interaction_outcome(
            outcome="neutral",  # Initial outcome, may be updated by reactions
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
            interaction_type="response",
            response_text=response_text[:500],  # Truncate for storage
            response_length=len(response_text),
            response_time_ms=response_time_ms,
            token_count=token_count,
            tools_used=tools_used or [],
            context_snapshot={
                "hour": now.hour,
                "weekday": now.weekday(),
                "thread_id": thread_id,
            },
        )

        LOGGER.debug(
            f"Tracked bot interaction: message_id={message_id}, "
            f"time={response_time_ms}ms, tokens={token_count}, "
            f"tools={tools_used or []}"
        )

    except Exception as e:
        LOGGER.error(
            f"Failed to track bot interaction {message_id}: {e}",
            exc_info=True,
            extra={"chat_id": chat_id, "message_id": message_id},
        )


async def process_potential_reaction(
    message: Message,
    bot_profile: BotProfileStore,
    bot_learning: BotLearningEngine,
    store: ContextStore,
    bot_id: int,
    chat_id: int,
    thread_id: int | None,
    user_id: int,
    reaction_timeout_seconds: int = 300,
) -> None:
    """
    Check if user message is a reaction to bot's previous message.

    If the user responds within reaction_timeout_seconds after a bot message,
    analyze the sentiment and update the interaction outcome.

    This is a background task that doesn't block message processing.

    Args:
        message: User's message (potential reaction)
        bot_profile: Bot profile store
        bot_learning: Bot learning engine
        store: Context store for history lookup
        bot_id: Bot's user ID
        chat_id: Chat ID
        thread_id: Thread ID (optional)
        user_id: User's ID
        reaction_timeout_seconds: Max time to consider as reaction (default 5 min)
    """
    try:
        # Get recent messages to find bot's last response
        recent_messages = await store.recent(
            chat_id=chat_id,
            thread_id=thread_id,
            max_messages=20,  # Look at last 20 messages
        )

        # Find most recent bot message
        bot_message = None
        bot_message_id = None
        bot_timestamp = None

        for msg in reversed(recent_messages):
            if msg.get("role") == "model":
                bot_message = msg.get("text")
                # Try to get message_id from metadata
                metadata = msg.get("metadata", {})
                bot_message_id = metadata.get("message_id")
                # Get timestamp from message or metadata
                bot_timestamp = msg.get("ts") or metadata.get("ts")
                break

        if not bot_message or not bot_timestamp:
            # No recent bot message found
            return

        # Calculate reaction delay
        current_timestamp = int(time.time())
        reaction_delay = current_timestamp - bot_timestamp

        # Only consider as reaction if within timeout
        if reaction_delay > reaction_timeout_seconds:
            LOGGER.debug(
                f"Message too old to be reaction: {reaction_delay}s > {reaction_timeout_seconds}s"
            )
            return

        # Get user's text
        user_text = (message.text or message.caption or "").strip()
        if not user_text:
            # No text to analyze
            return

        # Generate context tags
        now = datetime.now()
        context_tags = [
            (
                "morning"
                if 6 <= now.hour < 12
                else (
                    "afternoon"
                    if 12 <= now.hour < 18
                    else "evening" if 18 <= now.hour < 22 else "night"
                )
            ),
            "weekend" if now.weekday() >= 5 else "weekday",
        ]

        # Analyze user sentiment and learn from reaction
        await bot_learning.learn_from_user_reaction(
            user_message=user_text,
            bot_previous_response=bot_message,
            chat_id=chat_id,
            reaction_delay_seconds=reaction_delay,
            context_tags=context_tags,
        )

        # Detect sentiment to update interaction outcome
        sentiment, confidence = bot_learning.detect_user_sentiment(user_text)
        sentiment_score = bot_learning.calculate_sentiment_score(sentiment)

        # Record a new outcome entry for the reaction
        # (We don't update the original, we track reactions separately)
        if sentiment != "neutral":  # Only record non-neutral reactions
            try:
                await bot_profile.record_interaction_outcome(
                    outcome=sentiment,  # "praised", "positive", "negative", "corrected"
                    chat_id=chat_id,
                    thread_id=thread_id,
                    message_id=bot_message_id,  # Link to bot's message
                    interaction_type="user_reaction",  # Different type to distinguish
                    user_reaction=user_text[:200],
                    reaction_delay_seconds=reaction_delay,
                    sentiment_score=sentiment_score,
                    context_snapshot={
                        "hour": now.hour,
                        "weekday": now.weekday(),
                        "original_sentiment": sentiment,
                    },
                )

                LOGGER.info(
                    f"Recorded user reaction: message_id={bot_message_id}, "
                    f"sentiment={sentiment}, confidence={confidence:.2f}, "
                    f"delay={reaction_delay}s"
                )
            except Exception as e:
                LOGGER.warning(
                    f"Failed to record user reaction for message {bot_message_id}: {e}"
                )

        # Learn from performance metrics
        # (We don't have exact timing here, but we can still learn from outcome)
        await bot_learning.learn_from_performance_metrics(
            response_time_ms=0,  # Not available in reaction context
            token_count=0,  # Not available in reaction context
            outcome=sentiment,
            chat_id=chat_id,
            context_tags=context_tags,
        )

    except Exception as e:
        LOGGER.error(
            f"Failed to process potential reaction: {e}",
            exc_info=True,
            extra={"chat_id": chat_id, "user_id": user_id},
        )


def get_context_tags(
    hour_of_day: int | None = None, is_weekend: bool | None = None
) -> list[str]:
    """
    Generate context tags for bot learning.

    Tags are used to categorize when and how the bot interacts,
    allowing it to learn time-based and context-based patterns.

    Args:
        hour_of_day: Hour (0-23)
        is_weekend: Whether it's weekend

    Returns:
        List of context tags (e.g., ["morning", "weekday"])
    """
    tags = []

    if hour_of_day is not None:
        if 6 <= hour_of_day < 12:
            tags.append("morning")
        elif 12 <= hour_of_day < 18:
            tags.append("afternoon")
        elif 18 <= hour_of_day < 22:
            tags.append("evening")
        else:
            tags.append("night")

    if is_weekend is not None:
        tags.append("weekend" if is_weekend else "weekday")

    return tags


def estimate_token_count(text: str) -> int:
    """
    Estimate token count from text.

    Simple heuristic: ~4 characters per token for English/Ukrainian.
    This is approximate but good enough for tracking patterns.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Simple estimation: 4 chars ≈ 1 token
    # This is conservative and works reasonably well for mixed content
    return max(1, len(text) // 4)
