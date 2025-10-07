"""Memory tool handlers for Gemini function calling.

These tools give the model direct control over memory operations.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.services.user_profile import UserProfileStore
from app.services import telemetry

LOGGER = logging.getLogger(__name__)


async def remember_fact_tool(
    user_id: int,
    fact_type: str,
    fact_key: str,
    fact_value: str,
    confidence: float,
    source_excerpt: str | None = None,
    # Injected by handler
    chat_id: int | None = None,
    message_id: int | None = None,
    profile_store: UserProfileStore | None = None,
) -> str:
    """
    Tool handler for remembering facts.

    Args:
        user_id: Telegram user ID
        fact_type: Category (personal, preference, skill, trait, opinion, relationship)
        fact_key: Standardized key (location, hobby, programming_language, etc.)
        fact_value: The actual fact content
        confidence: Confidence score (0.5-1.0)
        source_excerpt: Quote from message (optional)
        chat_id: Chat ID (injected)
        message_id: Message ID (injected)
        profile_store: UserProfileStore instance (injected)

    Returns:
        JSON string for Gemini to interpret
    """
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # Check if fact already exists (basic duplicate detection)
        existing_facts = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            limit=100,
        )

        # Simple duplicate check: same type + key
        for fact in existing_facts:
            if fact.get("fact_type") == fact_type and fact.get("fact_key") == fact_key:

                # Check if values are similar
                existing_value = fact.get("fact_value", "").lower()
                new_value = fact_value.lower()

                if (
                    existing_value == new_value
                    or existing_value in new_value
                    or new_value in existing_value
                ):
                    telemetry.increment_counter(
                        "memory_tool_duplicate_detected",
                        tool="remember_fact",
                        fact_type=fact_type,
                    )

                    return json.dumps(
                        {
                            "status": "skipped",
                            "reason": "duplicate",
                            "message": f"This fact is already known: {fact_type}.{fact_key} = {existing_value}",
                            "existing_fact_id": fact.get("id"),
                        }
                    )

        # Store the new fact
        fact_id = await profile_store.add_fact(
            user_id=user_id,
            chat_id=chat_id,
            fact_type=fact_type,
            fact_key=fact_key,
            fact_value=fact_value,
            confidence=confidence,
            evidence_text=source_excerpt,
            source_message_id=message_id,
        )

        # Telemetry
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="remember_fact",
            fact_type=fact_type,
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="remember_fact",
        )

        LOGGER.info(
            f"Remembered fact: {fact_type}.{fact_key}={fact_value} (confidence={confidence})",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "fact_id": fact_id,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "fact_id": fact_id,
                "message": f"Remembered: {fact_type} → {fact_key} = {fact_value}",
            }
        )

    except Exception as e:
        LOGGER.error(f"remember_fact tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="remember_fact",
            error_type=type(e).__name__,
        )

        return json.dumps(
            {
                "status": "error",
                "message": str(e),
            }
        )


async def recall_facts_tool(
    user_id: int,
    fact_types: list[str] | None = None,
    search_query: str | None = None,
    limit: int = 10,
    # Injected by handler
    chat_id: int | None = None,
    profile_store: UserProfileStore | None = None,
) -> str:
    """
    Tool handler for recalling existing facts.

    Args:
        user_id: Telegram user ID
        fact_types: Filter by types (optional)
        search_query: Semantic search query (optional, not yet implemented)
        limit: Max results (default 10)
        chat_id: Chat ID (injected)
        profile_store: UserProfileStore instance (injected)

    Returns:
        JSON string with list of facts
    """
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # Get facts from profile store
        facts = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            limit=limit * 2,  # Get more for filtering
        )

        # Filter by type if requested
        if fact_types:
            facts = [f for f in facts if f.get("fact_type") in fact_types]

        # TODO: Implement semantic search if query provided
        # For now, just simple text matching
        if search_query:
            query_lower = search_query.lower()
            facts = [
                f
                for f in facts
                if query_lower in f.get("fact_value", "").lower()
                or query_lower in f.get("fact_key", "").lower()
            ]

        # Limit results
        facts = facts[:limit]

        # Format for Gemini
        result = {
            "status": "success",
            "count": len(facts),
            "facts": [
                {
                    "fact_id": f.get("id"),
                    "type": f.get("fact_type"),
                    "key": f.get("fact_key"),
                    "value": f.get("fact_value"),
                    "confidence": f.get("confidence"),
                    "created_at": f.get("created_at"),
                }
                for f in facts
            ],
        }

        # Telemetry
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="recall_facts",
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="recall_facts",
        )

        LOGGER.info(
            f"Recalled {len(facts)} facts for user {user_id}",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "fact_count": len(facts),
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(result)

    except Exception as e:
        LOGGER.error(f"recall_facts tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="recall_facts",
            error_type=type(e).__name__,
        )

        return json.dumps(
            {
                "status": "error",
                "message": str(e),
            }
        )


async def update_fact_tool(
    user_id: int,
    fact_type: str,
    fact_key: str,
    new_value: str,
    confidence: float,
    change_reason: str,
    source_excerpt: str | None = None,
    # Injected by handler
    chat_id: int | None = None,
    message_id: int | None = None,
    profile_store: UserProfileStore | None = None,
) -> str:
    """
    Tool handler for updating existing facts.

    Args:
        user_id: Telegram user ID
        fact_type: Category to update
        fact_key: Which fact to update
        new_value: New/corrected value
        confidence: Confidence in new value (0.5-1.0)
        change_reason: Why changing (correction, update, refinement, contradiction)
        source_excerpt: Quote supporting update (optional)
        chat_id: Chat ID (injected)
        message_id: Message ID (injected)
        profile_store: UserProfileStore instance (injected)

    Returns:
        JSON string with update result
    """
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # Find the existing fact
        existing_facts = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            limit=100,
        )

        target_fact = None
        for fact in existing_facts:
            if fact.get("fact_type") == fact_type and fact.get("fact_key") == fact_key:
                target_fact = fact
                break

        if not target_fact:
            # Fact doesn't exist - suggest using remember_fact instead
            telemetry.increment_counter(
                "memory_tool_not_found",
                tool="update_fact",
                fact_type=fact_type,
            )

            return json.dumps(
                {
                    "status": "not_found",
                    "message": f"No existing fact found for {fact_type}.{fact_key}. Use remember_fact instead.",
                    "suggestion": "remember_fact",
                }
            )

        old_value = target_fact.get("fact_value")
        fact_id = target_fact.get("id")

        # Update the fact directly via SQL (force update regardless of confidence)
        import aiosqlite

        try:
            now = int(time.time())
            async with aiosqlite.connect(profile_store._db_path) as db:
                await db.execute(
                    """
                    UPDATE user_facts 
                    SET fact_value = ?, confidence = ?, updated_at = ?, last_mentioned = ?,
                        evidence_text = COALESCE(?, evidence_text)
                    WHERE id = ?
                    """,
                    (new_value, confidence, now, now, source_excerpt, fact_id),
                )
                await db.commit()
        except Exception as e:
            telemetry.increment_counter(
                "memory_tool_error", tool="update_fact", error=type(e).__name__
            )
            LOGGER.error(f"Failed to update fact {fact_id}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": "database_error",
                    "message": str(e),
                }
            )

        # Telemetry
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="update_fact",
            fact_type=fact_type,
            change_reason=change_reason,
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="update_fact",
        )

        LOGGER.info(
            f"Updated fact: {fact_type}.{fact_key}: {old_value} → {new_value} ({change_reason})",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "fact_id": fact_id,
                "change_reason": change_reason,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "fact_id": fact_id,
                "old_value": old_value,
                "new_value": new_value,
                "change_reason": change_reason,
                "message": f"Updated {fact_type}.{fact_key}: {old_value} → {new_value}",
            }
        )

    except Exception as e:
        LOGGER.error(f"update_fact tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="update_fact",
            error_type=type(e).__name__,
        )

        return json.dumps(
            {
                "status": "error",
                "message": str(e),
            }
        )


async def forget_all_facts_tool(
    user_id: int,
    reason: str,
    # Injected by handler
    chat_id: int | None = None,
    message_id: int | None = None,
    profile_store: UserProfileStore | None = None,
) -> str:
    """
    Tool handler for forgetting ALL facts about a user (bulk delete).

    Use this when user explicitly asks to "forget everything" about them.
    This is more efficient than calling forget_fact multiple times.

    Args:
        user_id: Telegram user ID
        reason: Why forget all (usually "user_requested")
        chat_id: Chat ID (injected)
        message_id: Message ID (injected)
        profile_store: UserProfileStore instance (injected)

    Returns:
        JSON string with result
    """
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # Soft delete ALL active facts for this user
        import aiosqlite

        try:
            now = int(time.time())
            async with aiosqlite.connect(profile_store._db_path) as db:
                # Get count before deletion
                cursor = await db.execute(
                    """
                    SELECT COUNT(*) FROM user_facts 
                    WHERE user_id = ? AND chat_id = ? AND is_active = 1
                    """,
                    (user_id, chat_id),
                )
                row = await cursor.fetchone()
                count_before = row[0] if row else 0

                # Update all facts to mark as inactive
                await db.execute(
                    """
                    UPDATE user_facts 
                    SET is_active = 0, updated_at = ?
                    WHERE user_id = ? AND chat_id = ? AND is_active = 1
                    """,
                    (now, user_id, chat_id),
                )
                await db.commit()

        except Exception as e:
            telemetry.increment_counter(
                "memory_tool_error", tool="forget_all_facts", error=type(e).__name__
            )
            LOGGER.error(f"Failed to forget all facts for user {user_id}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": "database_error",
                    "message": str(e),
                }
            )

        # Telemetry
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="forget_all_facts",
            count=count_before,
            reason=reason,
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="forget_all_facts",
        )

        LOGGER.info(
            f"Forgot ALL {count_before} facts for user {user_id} (reason: {reason})",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "count": count_before,
                "reason": reason,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "count": count_before,
                "reason": reason,
                "message": f"Forgot all {count_before} facts about user (reason: {reason})",
            }
        )

    except Exception as e:
        LOGGER.error(f"forget_all_facts tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="forget_all_facts",
            error_type=type(e).__name__,
        )
        return json.dumps(
            {
                "status": "error",
                "error": "unknown_error",
                "message": str(e),
            }
        )


async def forget_fact_tool(
    user_id: int,
    fact_type: str,
    fact_key: str,
    reason: str,
    replacement_fact_id: int | None = None,
    # Injected by handler
    chat_id: int | None = None,
    message_id: int | None = None,
    profile_store: UserProfileStore | None = None,
) -> str:
    """
    Tool handler for forgetting (archiving) facts.

    Args:
        user_id: Telegram user ID
        fact_type: Category of fact to forget
        fact_key: Which fact to forget
        reason: Why forget (outdated, incorrect, superseded, user_requested)
        replacement_fact_id: If superseded, ID of new fact (optional)
        chat_id: Chat ID (injected)
        message_id: Message ID (injected)
        profile_store: UserProfileStore instance (injected)

    Returns:
        JSON string with result
    """
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # Find the existing fact
        existing_facts = await profile_store.get_facts(
            user_id=user_id,
            chat_id=chat_id,
            limit=100,
        )

        target_fact = None
        for fact in existing_facts:
            if (
                fact.get("fact_type") == fact_type
                and fact.get("fact_key") == fact_key
                and fact.get("is_active", 1) == 1
            ):
                target_fact = fact
                break

        if not target_fact:
            # Fact doesn't exist or already forgotten
            telemetry.increment_counter(
                "memory_tool_not_found",
                tool="forget_fact",
                fact_type=fact_type,
            )

            return json.dumps(
                {
                    "status": "not_found",
                    "message": f"No active fact found for {fact_type}.{fact_key}. It may already be forgotten.",
                    "suggestion": "Use recall_facts to check existing facts",
                }
            )

        fact_id = target_fact.get("id")
        fact_value = target_fact.get("fact_value")

        # Soft delete: set is_active = 0
        import aiosqlite

        try:
            now = int(time.time())
            async with aiosqlite.connect(profile_store._db_path) as db:
                # Update the fact to mark as inactive
                await db.execute(
                    """
                    UPDATE user_facts 
                    SET is_active = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, fact_id),
                )
                await db.commit()

                # TODO: In future, store reason and replacement_fact_id in fact_versions table

        except Exception as e:
            telemetry.increment_counter(
                "memory_tool_error", tool="forget_fact", error=type(e).__name__
            )
            LOGGER.error(f"Failed to forget fact {fact_id}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": "database_error",
                    "message": str(e),
                }
            )

        # Telemetry
        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="forget_fact",
            fact_type=fact_type,
            reason=reason,
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="forget_fact",
        )

        LOGGER.info(
            f"Forgot fact: {fact_type}.{fact_key} = {fact_value} (reason: {reason})",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "fact_id": fact_id,
                "reason": reason,
                "replacement_fact_id": replacement_fact_id,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "fact_id": fact_id,
                "forgotten_value": fact_value,
                "reason": reason,
                "replacement_fact_id": replacement_fact_id,
                "message": f"Forgot {fact_type}.{fact_key} = {fact_value} ({reason})",
            }
        )

    except Exception as e:
        LOGGER.error(f"forget_fact tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="forget_fact",
            error_type=type(e).__name__,
        )

        return json.dumps(
            {
                "status": "error",
                "message": str(e),
            }
        )
