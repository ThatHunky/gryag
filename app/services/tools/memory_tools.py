"""Memory tool handlers for Gemini function calling.

These tools give the model direct control over memory operations.

Updated to use UnifiedFactRepository for both user and chat facts.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TYPE_CHECKING

from app.repositories.fact_repository import UnifiedFactRepository
from app.services import telemetry

if TYPE_CHECKING:
    from app.services.user_profile import UserProfileStore
    from app.services.user_profile_adapter import UserProfileStoreAdapter
    from app.services.context_store import ContextStore

LOGGER = logging.getLogger(__name__)


def _resolve_fact_repo(
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None",
    explicit_repo: UnifiedFactRepository | None,
) -> UnifiedFactRepository | None:
    """Prefer explicit repo, then profile_store-backed repo, else None."""
    if explicit_repo:
        return explicit_repo

    if profile_store is None:
        return None

    repo = getattr(profile_store, "fact_repository", None)
    if isinstance(repo, UnifiedFactRepository):
        return repo

    repo = getattr(profile_store, "_fact_repo", None)
    if isinstance(repo, UnifiedFactRepository):
        return repo

    return None


def _resolve_db_path(
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None",
) -> str | None:
    """Fetch legacy db path if available for fallback operations."""
    if profile_store is None:
        return None

    db_path = getattr(profile_store, "_db_path", None)
    if db_path is None:
        return None
    return str(db_path)


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
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
    fact_repo: UnifiedFactRepository | None = None,
) -> str:
    """
    Tool handler for remembering facts.

    Auto-detects entity type:
    - user_id > 0 → user fact (stored with chat_context)
    - user_id < 0 → chat fact (user_id is actually chat_id)

    Args:
        user_id: Telegram user ID (or chat ID if negative)
        fact_type: Category (maps to fact_category in unified schema)
        fact_key: Standardized key (location, hobby, programming_language, etc.)
        fact_value: The actual fact content
        confidence: Confidence score (0.5-1.0)
        source_excerpt: Quote from message (optional)
        chat_id: Chat ID context (injected)
        message_id: Message ID (injected)
        fact_repo: UnifiedFactRepository instance (injected)

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

        # Resolve fact repository for compatibility (unused for legacy path)
        fact_repo = _resolve_fact_repo(profile_store, fact_repo)

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
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
    fact_repo: UnifiedFactRepository | None = None,
    gemini_client: Any | None = None,
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

        fact_repo = _resolve_fact_repo(profile_store, fact_repo)

        # Candidate collection strategy:
        # - Prefer unified fact repository if available (can include embeddings)
        # - Fallback to legacy profile_store.get_facts
        candidates: list[dict[str, Any]] = []
        if fact_repo:
            # Pull a reasonably large set for filtering/ranking
            repo_facts = await fact_repo.get_facts(
                entity_id=user_id,
                chat_context=chat_id,
                categories=fact_types if fact_types else None,
                limit=max(100, limit * 5),
            )
            candidates.extend(repo_facts)
        if not candidates:
            # Legacy path
            facts = await profile_store.get_facts(  # type: ignore[union-attr]
                user_id=user_id,
                chat_id=chat_id,
                limit=max(100, limit * 5),
            )
            # Map to a unified shape (fact_type -> fact_category)
            for f in facts:
                f.setdefault("fact_category", f.get("fact_type"))
            if fact_types:
                facts = [f for f in facts if f.get("fact_category") in fact_types]
            candidates.extend(facts)

        # Ranking: semantic if possible else substring filter
        ranked: list[tuple[float, dict[str, Any]]] = []
        if search_query and gemini_client and candidates:
            try:
                query_emb = await gemini_client.embed_text(search_query)
            except Exception:
                query_emb = []

            def _cos(vec1: list[float], vec2: list[float]) -> float:
                try:
                    import math

                    if not vec1 or not vec2 or len(vec1) != len(vec2):
                        return 0.0
                    dp = sum(a * b for a, b in zip(vec1, vec2))
                    m1 = math.sqrt(sum(a * a for a in vec1))
                    m2 = math.sqrt(sum(b * b for b in vec2))
                    if m1 == 0 or m2 == 0:
                        return 0.0
                    return dp / (m1 * m2)
                except Exception:
                    return 0.0

            # Score by embedding if available, fallback to substring boost
            ql = search_query.lower()
            for f in candidates:
                emb = f.get("embedding")
                score = 0.0
                if isinstance(emb, list) and query_emb:
                    score = _cos(query_emb, emb)
                # Apply a small textual boost so that exact matches surface even without embeddings
                val = str(f.get("fact_value", "")).lower()
                key = str(f.get("fact_key", "")).lower()
                if ql in val or ql in key:
                    score += 0.05
                ranked.append((float(score), f))

            ranked.sort(key=lambda x: x[0], reverse=True)
            selected = [f for _, f in ranked[:limit]]
        else:
            # Simple substring filter
            selected = candidates
            if search_query:
                ql = search_query.lower()
                selected = [
                    f
                    for f in selected
                    if ql in str(f.get("fact_value", "")).lower()
                    or ql in str(f.get("fact_key", "")).lower()
                ]
            # Limit results
            selected = selected[:limit]

        facts = selected

        # Format for Gemini
        result = {
            "status": "success",
            "count": len(facts),
            "facts": [],
        }

        for f in facts:
            result["facts"].append(
                {
                    "fact_id": f.get("id"),
                    "type": f.get("fact_type") or f.get("fact_category"),
                    "key": f.get("fact_key"),
                    "value": f.get("fact_value"),
                    "confidence": f.get("confidence"),
                    "created_at": f.get("created_at"),
                }
            )

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
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
    fact_repo: UnifiedFactRepository | None = None,
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

        fact_repo = _resolve_fact_repo(profile_store, fact_repo)

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

        # Update the fact
        try:
            if fact_repo:
                updated = await fact_repo.update_fact(
                    fact_id=fact_id,
                    fact_value=new_value,
                    confidence=confidence,
                    evidence_text=source_excerpt,
                )
            else:
                # Legacy fallback to direct SQL
                import aiosqlite

                db_path = _resolve_db_path(profile_store)
                if not db_path:
                    raise RuntimeError(
                        "Database path unavailable for legacy profile store"
                    )

                now = int(time.time())
                async with aiosqlite.connect(db_path) as db:
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
                updated = True

            if not updated:
                telemetry.increment_counter(
                    "memory_tool_not_found",
                    tool="update_fact",
                    fact_type=fact_type,
                )
                return json.dumps(
                    {
                        "status": "not_found",
                        "message": f"Unable to update fact {fact_type}.{fact_key}; record missing.",
                    }
                )

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
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
    fact_repo: UnifiedFactRepository | None = None,
    context_store: "ContextStore | None" = None,
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

        fact_repo = _resolve_fact_repo(profile_store, fact_repo)

        messages_deleted = 0

        try:
            if fact_repo:
                count_before = await fact_repo.delete_all_facts(
                    entity_id=user_id,
                    chat_context=chat_id,
                    soft=False,
                )
            else:
                # Legacy fallback: deactivate facts in user_facts table
                import aiosqlite

                db_path = _resolve_db_path(profile_store)
                if not db_path:
                    raise RuntimeError(
                        "Database path unavailable for legacy profile store"
                    )

                async with aiosqlite.connect(db_path) as db:
                    cursor = await db.execute(
                        """
                        SELECT COUNT(*) FROM user_facts 
                        WHERE user_id = ? AND chat_id = ? AND is_active = 1
                        """,
                        (user_id, chat_id),
                    )
                    row = await cursor.fetchone()
                    count_before = row[0] if row else 0

                    await db.execute(
                        """
                        DELETE FROM user_facts
                        WHERE user_id = ? AND chat_id = ?
                        """,
                        (user_id, chat_id),
                    )
                    await db.commit()

            if context_store:
                messages_deleted = await context_store.delete_user_messages(
                    chat_id=chat_id,
                    user_id=user_id,
                )

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
            messages_deleted=messages_deleted,
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
                "messages_deleted": messages_deleted,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "count": count_before,
                "reason": reason,
                "messages_deleted": messages_deleted,
                "message": (
                    f"Forgot all {count_before} facts about user (reason: {reason}); "
                    f"removed {messages_deleted} stored messages."
                ),
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


async def set_pronouns_tool(
    user_id: int,
    pronouns: str,
    # Injected by handler
    chat_id: int | None = None,
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
) -> str:
    """Update or clear a user's pronouns."""
    start_time = time.time()

    try:
        if not profile_store:
            return json.dumps(
                {"status": "error", "message": "Profile store not available"}
            )

        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        normalized = (pronouns or "").strip()
        stored = normalized if normalized else None

        # Cap length to avoid flooding
        if stored and len(stored) > 64:
            stored = stored[:64]

        await profile_store.update_pronouns(
            user_id=user_id,
            chat_id=chat_id,
            pronouns=stored,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="set_pronouns",
            status="cleared" if stored is None else "success",
        )
        telemetry.set_gauge("memory_tool_latency_ms", latency_ms, tool="set_pronouns")

        if stored:
            message = f"Stored pronouns: {stored}"
        else:
            message = "Cleared stored pronouns"

        return json.dumps(
            {
                "status": "success",
                "pronouns": stored or "",
                "message": message,
            }
        )

    except Exception as e:
        LOGGER.error(f"set_pronouns tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="set_pronouns",
            error_type=type(e).__name__,
        )

        return json.dumps(
            {
                "status": "error",
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
    profile_store: "UserProfileStore | UserProfileStoreAdapter | None" = None,
    fact_repo: UnifiedFactRepository | None = None,
    context_store: "ContextStore | None" = None,
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

        fact_repo = _resolve_fact_repo(profile_store, fact_repo)

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
        source_message_id = target_fact.get("source_message_id")

        # Soft delete the fact
        try:
            if fact_repo:
                deleted = await fact_repo.delete_fact(fact_id=fact_id, soft=False)
            else:
                import aiosqlite

                db_path = _resolve_db_path(profile_store)
                if not db_path:
                    raise RuntimeError(
                        "Database path unavailable for legacy profile store"
                    )

                async with aiosqlite.connect(db_path) as db:
                    cursor = await db.execute(
                        "DELETE FROM user_facts WHERE id = ?",
                        (fact_id,),
                    )
                    await db.commit()
                    deleted = cursor.rowcount > 0

            if not deleted:
                telemetry.increment_counter(
                    "memory_tool_not_found",
                    tool="forget_fact",
                    fact_type=fact_type,
                )
                return json.dumps(
                    {
                        "status": "not_found",
                        "message": f"Fact {fact_type}.{fact_key} already forgotten or missing.",
                    }
                )

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

        message_deleted = False
        if context_store and source_message_id:
            try:
                message_deleted = await context_store.delete_message_by_external_id(
                    chat_id=chat_id,
                    external_message_id=source_message_id,
                )
            except Exception as e:
                LOGGER.warning(
                    f"Failed to delete source message {source_message_id} for fact {fact_id}: {e}"
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
                "message_deleted": message_deleted,
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
                "message_deleted": message_deleted,
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
