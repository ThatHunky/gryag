"""Gemini tool definitions for the simplified memory management system."""

# Remember a memory
REMEMBER_MEMORY_DEFINITION = {
    "function_declarations": [
        {
            "name": "remember_memory",
            "description": (
                "Store a NEW piece of information about the user. The information should be a simple, self-contained statement. "
                "Use this IMMEDIATELY when the user asks you to remember something (е.g., 'запам'ятай', 'remember', 'save'). "
                "Do NOT call recall_memories before this if the user explicitly asks to remember - just store it directly. "
                "Returns confirmation or an error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The Telegram user ID.",
                    },
                    "memory_text": {
                        "type": "string",
                        "description": "The single piece of information to remember (e.g., 'User lives in Kyiv', 'User prefers concise answers').",
                    },
                },
                "required": ["user_id", "memory_text"],
            },
        }
    ]
}

# Recall all memories
RECALL_MEMORIES_DEFINITION = {
    "function_declarations": [
        {
            "name": "recall_memories",
            "description": (
                "Retrieve all stored memories for a user. Use this when you need to CHECK what you already know, "
                "or when the user asks what you remember about them. "
                "Do NOT use this before remember_memory - just remember directly. "
                "Returns a list of all known information, each with an ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The Telegram user ID.",
                    },
                },
                "required": ["user_id"],
            },
        }
    ]
}

# Forget a specific memory by ID
FORGET_MEMORY_DEFINITION = {
    "function_declarations": [
        {
            "name": "forget_memory",
            "description": (
                "Forget a specific piece of information about the user, identified by its unique ID. "
                "To get the ID, you must call `recall_memories` first. Returns confirmation or an error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The Telegram user ID.",
                    },
                    "memory_id": {
                        "type": "integer",
                        "description": "The unique ID of the memory to forget.",
                    },
                },
                "required": ["user_id", "memory_id"],
            },
        }
    ]
}

# Forget all memories for a user
FORGET_ALL_MEMORIES_DEFINITION = {
    "function_declarations": [
        {
            "name": "forget_all_memories",
            "description": (
                "Permanently delete ALL stored memories for a user. This is a destructive action. "
                "Use only when the user explicitly asks to 'forget everything'. Returns a count of forgotten memories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The Telegram user ID.",
                    },
                },
                "required": ["user_id"],
            },
        }
    ]
}


# This tool is separate from the memory system and modifies the user's profile directly.
SET_PRONOUNS_DEFINITION = {
    "function_declarations": [
        {
            "name": "set_pronouns",
            "description": (
                "Update the user's pronouns. Use when the user explicitly tells you their pronouns "
                "or asks you to change them. Send an empty string to clear stored pronouns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "pronouns": {
                        "type": "string",
                        "description": "User's pronouns in a short format (e.g., 'she/her'). Use an empty string to clear.",
                    },
                },
                "required": ["user_id", "pronouns"],
            },
        }
    ]
}
