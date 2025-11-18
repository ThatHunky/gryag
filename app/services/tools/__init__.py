"""Memory management tools for Gemini function calling."""

from .memory_definitions import (
    FORGET_ALL_MEMORIES_DEFINITION,
    FORGET_MEMORY_DEFINITION,
    RECALL_MEMORIES_DEFINITION,
    REMEMBER_MEMORY_DEFINITION,
    SET_PRONOUNS_DEFINITION,
)
from .memory_tools import (
    forget_all_memories_tool,
    forget_memory_tool,
    recall_memories_tool,
    remember_memory_tool,
    set_pronouns_tool,
)

__all__ = [
    # Tool handlers
    "remember_memory_tool",
    "recall_memories_tool",
    "forget_memory_tool",
    "forget_all_memories_tool",
    "set_pronouns_tool",
    # Tool definitions
    "REMEMBER_MEMORY_DEFINITION",
    "RECALL_MEMORIES_DEFINITION",
    "FORGET_MEMORY_DEFINITION",
    "FORGET_ALL_MEMORIES_DEFINITION",
    "SET_PRONOUNS_DEFINITION",
]
