"""Memory management tools for Gemini function calling."""

from .memory_tools import (
    remember_fact_tool,
    recall_facts_tool,
    update_fact_tool,
    forget_fact_tool,
    forget_all_facts_tool,
)

from .memory_definitions import (
    REMEMBER_FACT_DEFINITION,
    RECALL_FACTS_DEFINITION,
    UPDATE_FACT_DEFINITION,
    FORGET_FACT_DEFINITION,
    FORGET_ALL_FACTS_DEFINITION,
)

__all__ = [
    # Tool handlers
    "remember_fact_tool",
    "recall_facts_tool",
    "update_fact_tool",
    "forget_fact_tool",
    "forget_all_facts_tool",
    # Tool definitions
    "REMEMBER_FACT_DEFINITION",
    "RECALL_FACTS_DEFINITION",
    "UPDATE_FACT_DEFINITION",
    "FORGET_FACT_DEFINITION",
    "FORGET_ALL_FACTS_DEFINITION",
]
