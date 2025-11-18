"""Memory tool handlers for Gemini function calling.

These tools give the model direct control over the simplified memory system.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from app.repositories.memory_repository import MemoryRepository
from app.services import telemetry

if TYPE_CHECKING:
    from app.services.user_profile import UserProfileStore
    from app.services.user_profile_adapter import UserProfileStoreAdapter


LOGGER = logging.getLogger(__name__)


async def remember_memory_tool(
    user_id: int,
    memory_text: str,
    # Injected by handler
    chat_id: int | None = None,
    memory_repo: MemoryRepository | None = None,
) -> str:
    """Tool handler for remembering a simple memory."""
    start_time = time.time()

    try:
        if not memory_repo:
            return json.dumps(
                {"status": "error", "message": "Memory repository not available"}
            )
        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        new_memory = await memory_repo.add_memory(
            user_id=user_id,
            chat_id=chat_id,
            memory_text=memory_text,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="remember_memory",
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="remember_memory",
        )

        LOGGER.info(
            f"Remembered memory for user {user_id}: '{memory_text}'",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "memory_id": new_memory.id,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "memory_id": new_memory.id,
                "message": f"Remembered: '{memory_text}'",
            }
        )

    except Exception as e:
        LOGGER.error(f"remember_memory tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="remember_memory",
            error_type=type(e).__name__,
        )
        return json.dumps({"status": "error", "message": str(e)})


async def recall_memories_tool(
    user_id: int,
    # Injected by handler
    chat_id: int | None = None,
    memory_repo: MemoryRepository | None = None,
) -> str:
    """Tool handler for recalling all memories for a user."""
    start_time = time.time()

    try:
        if not memory_repo:
            return json.dumps(
                {"status": "error", "message": "Memory repository not available"}
            )
        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        memories = await memory_repo.get_memories_for_user(
            user_id=user_id, chat_id=chat_id
        )

        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="recall_memories",
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="recall_memories",
        )

        LOGGER.info(
            f"Recalled {len(memories)} memories for user {user_id}",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "count": len(memories),
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "count": len(memories),
                "memories": [
                    {
                        "id": mem.id,
                        "memory": mem.memory_text,
                        "created_at": mem.created_at,
                    }
                    for mem in memories
                ],
            }
        )

    except Exception as e:
        LOGGER.error(f"recall_memories tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="recall_memories",
            error_type=type(e).__name__,
        )
        return json.dumps({"status": "error", "message": str(e)})


async def forget_memory_tool(
    user_id: int,
    memory_id: int,
    # Injected by handler
    chat_id: int | None = None,
    memory_repo: MemoryRepository | None = None,
) -> str:
    """Tool handler for forgetting a specific memory by its ID."""
    start_time = time.time()

    try:
        if not memory_repo:
            return json.dumps(
                {"status": "error", "message": "Memory repository not available"}
            )
        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        # For security, ensure the memory belongs to the user/chat before deleting
        memory_to_delete = await memory_repo.get_memory_by_id(memory_id)
        if (
            not memory_to_delete
            or memory_to_delete.user_id != user_id
            or memory_to_delete.chat_id != chat_id
        ):
            telemetry.increment_counter(
                "memory_tool_not_found",
                tool="forget_memory",
            )
            return json.dumps(
                {
                    "status": "not_found",
                    "message": "Memory not found or you do not have permission to delete it.",
                }
            )

        deleted = await memory_repo.delete_memory(memory_id=memory_id)

        latency_ms = int((time.time() - start_time) * 1000)
        if deleted:
            telemetry.increment_counter(
                "memory_tool_used",
                tool="forget_memory",
                status="success",
            )
            LOGGER.info(
                f"Forgot memory {memory_id} for user {user_id}",
                extra={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "memory_id": memory_id,
                    "latency_ms": latency_ms,
                },
            )
            return json.dumps(
                {
                    "status": "success",
                    "forgotten_memory_id": memory_id,
                    "message": "Memory forgotten.",
                }
            )
        else:
            # This case should be rare given the check above, but is included for completeness
            telemetry.increment_counter(
                "memory_tool_not_found",
                tool="forget_memory",
            )
            return json.dumps(
                {"status": "not_found", "message": "Memory could not be forgotten."}
            )

    except Exception as e:
        LOGGER.error(f"forget_memory tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="forget_memory",
            error_type=type(e).__name__,
        )
        return json.dumps({"status": "error", "message": str(e)})


async def forget_all_memories_tool(
    user_id: int,
    # Injected by handler
    chat_id: int | None = None,
    memory_repo: MemoryRepository | None = None,
) -> str:
    """Tool handler for forgetting all memories for a user."""
    start_time = time.time()

    try:
        if not memory_repo:
            return json.dumps(
                {"status": "error", "message": "Memory repository not available"}
            )
        if not chat_id:
            return json.dumps({"status": "error", "message": "Chat ID not provided"})

        deleted_count = await memory_repo.delete_all_memories(
            user_id=user_id, chat_id=chat_id
        )

        latency_ms = int((time.time() - start_time) * 1000)
        telemetry.increment_counter(
            "memory_tool_used",
            tool="forget_all_memories",
            count=deleted_count,
            status="success",
        )
        telemetry.set_gauge(
            "memory_tool_latency_ms",
            latency_ms,
            tool="forget_all_memories",
        )

        LOGGER.info(
            f"Forgot all {deleted_count} memories for user {user_id}",
            extra={
                "user_id": user_id,
                "chat_id": chat_id,
                "count": deleted_count,
                "latency_ms": latency_ms,
            },
        )

        return json.dumps(
            {
                "status": "success",
                "count": deleted_count,
                "message": f"Forgot all {deleted_count} memories for the user.",
            }
        )

    except Exception as e:
        LOGGER.error(f"forget_all_memories tool failed: {e}", exc_info=True)
        telemetry.increment_counter(
            "memory_tool_error",
            tool="forget_all_memories",
            error_type=type(e).__name__,
        )
        return json.dumps({"status": "error", "message": str(e)})


async def set_pronouns_tool(
    user_id: int,
    pronouns: str,
    # Injected by handler
    chat_id: int | None = None,
    profile_store: UserProfileStore | UserProfileStoreAdapter | None = None,
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
