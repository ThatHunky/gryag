"""
Tool definitions and callbacks for chat handler.

This module contains all tool definitions (function calling) and their
callback implementations used by the Gemini model during chat interactions.

Tools include:
- search_messages: Semantic search in chat history
- search_web: Web search (if enabled)
- calculator: Mathematical calculations
- weather: Weather information
- currency: Currency conversion
- polls: Poll creation and voting
- Memory tools: remember_fact, recall_facts, update_fact, forget_fact, etc.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from app.services.calculator import calculator_tool, CALCULATOR_TOOL_DEFINITION
from app.services.weather import weather_tool, WEATHER_TOOL_DEFINITION
from app.services.currency import currency_tool, CURRENCY_TOOL_DEFINITION
from app.services.polls import polls_tool, POLLS_TOOL_DEFINITION
from app.services.search_tool import search_web_tool, SEARCH_WEB_TOOL_DEFINITION
from app.services.tools import (
    REMEMBER_FACT_DEFINITION,
    RECALL_FACTS_DEFINITION,
    UPDATE_FACT_DEFINITION,
    FORGET_FACT_DEFINITION,
    FORGET_ALL_FACTS_DEFINITION,
    SET_PRONOUNS_DEFINITION,
    remember_fact_tool,
    recall_facts_tool,
    update_fact_tool,
    forget_fact_tool,
    forget_all_facts_tool,
    set_pronouns_tool,
)
from app.services.context_store import ContextStore, format_metadata
from app.services.gemini import GeminiClient
from app.services.user_profile import UserProfileStore
from app.config import Settings

logger = logging.getLogger(__name__)


def create_search_messages_tool(
    store: ContextStore,
    gemini_client: GeminiClient,
    chat_id: int,
    thread_id: int | None,
) -> Callable[[dict[str, Any]], Awaitable[str]]:
    """
    Create a search_messages tool callback for the current chat context.

    Args:
        store: Context store for message retrieval
        gemini_client: Gemini client for embeddings
        chat_id: Current chat ID
        thread_id: Current thread ID (if any)

    Returns:
        Async callback function for search_messages tool
    """

    async def search_messages_tool(params: dict[str, Any]) -> str:
        """Search chat history using semantic search."""
        query = (params or {}).get("query", "")
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"results": []})

        limit = params.get("limit", 5)
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 5
        limit_int = max(1, min(limit_int, 10))

        thread_only = params.get("thread_only", True)
        target_thread = thread_id if thread_only else None

        embedding = await gemini_client.embed_text(query)
        matches = await store.semantic_search(
            chat_id=chat_id,
            thread_id=target_thread,
            query_embedding=embedding,
            limit=limit_int,
        )

        payload = []
        for item in matches:
            meta_dict = item.get("metadata", {})
            payload.append(
                {
                    "score": round(float(item.get("score", 0.0)), 4),
                    "metadata": meta_dict,
                    "metadata_text": format_metadata(meta_dict),
                    "text": (item.get("text") or "")[:400],
                    "role": item.get("role"),
                    "message_id": item.get("message_id"),
                }
            )
        return json.dumps({"results": payload})

    return search_messages_tool


def get_search_messages_definition() -> dict[str, Any]:
    """Get the tool definition for search_messages."""
    return {
        "function_declarations": [
            {
                "name": "search_messages",
                "description": (
                    "Шукати релевантні повідомлення в історії чату за семантичною подібністю."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Запит або фраза для пошуку",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Скільки результатів повернути (1-10)",
                        },
                        "thread_only": {
                            "type": "boolean",
                            "description": "Чи обмежуватися поточним тредом",
                        },
                    },
                    "required": ["query"],
                },
            }
        ]
    }


def build_tool_definitions(settings: Settings) -> list[dict[str, Any]]:
    """
    Build the complete list of tool definitions based on settings.

    Args:
        settings: Application settings

    Returns:
        List of tool definitions in Gemini function calling format
    """
    tool_definitions: list[dict[str, Any]] = []

    # Always include search_messages
    tool_definitions.append(get_search_messages_definition())

    # Web search (if enabled)
    if settings.enable_search_grounding:
        tool_definitions.append(SEARCH_WEB_TOOL_DEFINITION)

    # Calculator
    tool_definitions.append(CALCULATOR_TOOL_DEFINITION)

    # Weather
    tool_definitions.append(WEATHER_TOOL_DEFINITION)

    # Currency
    tool_definitions.append(CURRENCY_TOOL_DEFINITION)

    # Polls
    tool_definitions.append(POLLS_TOOL_DEFINITION)

    # Memory tools (Phase 5.1)
    if settings.enable_tool_based_memory:
        tool_definitions.append(REMEMBER_FACT_DEFINITION)
        tool_definitions.append(RECALL_FACTS_DEFINITION)
        tool_definitions.append(UPDATE_FACT_DEFINITION)
        tool_definitions.append(FORGET_FACT_DEFINITION)
        tool_definitions.append(FORGET_ALL_FACTS_DEFINITION)
        tool_definitions.append(SET_PRONOUNS_DEFINITION)

    return tool_definitions


def build_tool_callbacks(
    settings: Settings,
    store: ContextStore,
    gemini_client: GeminiClient,
    profile_store: UserProfileStore,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
    tools_used_tracker: list[str] | None = None,
) -> dict[str, Callable[[dict[str, Any]], Awaitable[str]]]:
    """
    Build the complete dictionary of tool callbacks.

    Args:
        settings: Application settings
        store: Context store
        gemini_client: Gemini client
        profile_store: User profile store
        chat_id: Current chat ID
        thread_id: Current thread ID (if any)
        message_id: Current message ID
        tools_used_tracker: Optional list to track which tools are called

    Returns:
        Dictionary mapping tool names to callback functions
    """

    def make_tracked_callback(
        tool_name: str, original_callback: Callable[[dict[str, Any]], Awaitable[str]]
    ) -> Callable[[dict[str, Any]], Awaitable[str]]:
        """Wrapper to track tool usage."""

        async def wrapper(params: dict[str, Any]) -> str:
            if tools_used_tracker is not None:
                tools_used_tracker.append(tool_name)
            return await original_callback(params)

        return wrapper

    callbacks: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {}

    # Search messages tool
    search_messages = create_search_messages_tool(
        store, gemini_client, chat_id, thread_id
    )
    callbacks["search_messages"] = make_tracked_callback(
        "search_messages", search_messages
    )

    # Calculator
    callbacks["calculator"] = make_tracked_callback("calculator", calculator_tool)

    # Weather
    callbacks["weather"] = make_tracked_callback("weather", weather_tool)

    # Currency
    callbacks["currency"] = make_tracked_callback("currency", currency_tool)

    # Polls
    callbacks["polls"] = make_tracked_callback("polls", polls_tool)

    # Web search (if enabled)
    if settings.enable_search_grounding:
        callbacks["search_web"] = make_tracked_callback(
            "search_web",
            lambda params: search_web_tool(params, gemini_client),
        )

    # Memory tools (if enabled)
    if settings.enable_tool_based_memory:
        callbacks["remember_fact"] = make_tracked_callback(
            "remember_fact",
            lambda params: remember_fact_tool(
                **params,
                chat_id=chat_id,
                message_id=message_id,
                profile_store=profile_store,
            ),
        )
        callbacks["recall_facts"] = make_tracked_callback(
            "recall_facts",
            lambda params: recall_facts_tool(
                **params,
                chat_id=chat_id,
                profile_store=profile_store,
            ),
        )
        callbacks["update_fact"] = make_tracked_callback(
            "update_fact",
            lambda params: update_fact_tool(
                **params,
                chat_id=chat_id,
                message_id=message_id,
                profile_store=profile_store,
            ),
        )
        callbacks["forget_fact"] = make_tracked_callback(
            "forget_fact",
            lambda params: forget_fact_tool(
                **params,
                chat_id=chat_id,
                message_id=message_id,
                profile_store=profile_store,
                context_store=store,
            ),
        )
        callbacks["forget_all_facts"] = make_tracked_callback(
            "forget_all_facts",
            lambda params: forget_all_facts_tool(
                **params,
                chat_id=chat_id,
                message_id=message_id,
                profile_store=profile_store,
                context_store=store,
            ),
        )
        callbacks["set_pronouns"] = make_tracked_callback(
            "set_pronouns",
            lambda params: set_pronouns_tool(
                **params,
                chat_id=chat_id,
                profile_store=profile_store,
            ),
        )

    return callbacks
