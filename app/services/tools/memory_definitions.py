"""Gemini tool definitions for memory management."""

# Remember fact tool
REMEMBER_FACT_DEFINITION = {
    "function_declarations": [
        {
            "name": "remember_fact",
            "description": (
                "Store a new fact about a user. Use when you learn something important "
                "about them (location, preferences, skills, etc.). Always call recall_facts "
                "BEFORE using this to check for duplicates. Returns confirmation or error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "personal",
                            "preference",
                            "skill",
                            "trait",
                            "opinion",
                            "relationship",
                        ],
                        "description": "Category of fact",
                    },
                    "fact_key": {
                        "type": "string",
                        "description": "Standardized key (e.g., 'location', 'programming_language', 'hobby')",
                    },
                    "fact_value": {
                        "type": "string",
                        "description": "The actual fact content",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "How confident you are (0.5-1.0). Use 0.9+ for certain, 0.7-0.8 for probable, 0.5-0.6 for uncertain.",
                    },
                    "source_excerpt": {
                        "type": "string",
                        "description": "Quote from message that supports this fact (optional)",
                    },
                },
                "required": [
                    "user_id",
                    "fact_type",
                    "fact_key",
                    "fact_value",
                    "confidence",
                ],
            },
        }
    ]
}

# Recall facts tool
RECALL_FACTS_DEFINITION = {
    "function_declarations": [
        {
            "name": "recall_facts",
            "description": (
                "Search for existing facts about a user. Use BEFORE storing new facts "
                "to check for duplicates or contradictions. Returns list of known facts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "fact_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by fact types (optional, e.g., ['personal', 'skill'])",
                    },
                    "search_query": {
                        "type": "string",
                        "description": "Semantic search query (optional, e.g., 'programming')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10, max 50)",
                    },
                },
                "required": ["user_id"],
            },
        }
    ]
}

# Update fact tool
UPDATE_FACT_DEFINITION = {
    "function_declarations": [
        {
            "name": "update_fact",
            "description": (
                "Update an existing fact when you learn new or corrected information. "
                "Use when user corrects something or provides more details. "
                "Returns updated fact or error if not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "personal",
                            "preference",
                            "skill",
                            "trait",
                            "opinion",
                            "relationship",
                        ],
                        "description": "Category of fact to update",
                    },
                    "fact_key": {
                        "type": "string",
                        "description": "Which fact to update (e.g., 'location', 'job')",
                    },
                    "new_value": {
                        "type": "string",
                        "description": "New or corrected value",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence in the new value (0.5-1.0)",
                    },
                    "change_reason": {
                        "type": "string",
                        "enum": ["correction", "update", "refinement", "contradiction"],
                        "description": "Why is this being changed?",
                    },
                    "source_excerpt": {
                        "type": "string",
                        "description": "Quote from message supporting this update (optional)",
                    },
                },
                "required": [
                    "user_id",
                    "fact_type",
                    "fact_key",
                    "new_value",
                    "confidence",
                    "change_reason",
                ],
            },
        }
    ]
}

# Forget fact tool
FORGET_FACT_DEFINITION = {
    "function_declarations": [
        {
            "name": "forget_fact",
            "description": (
                "Mark a specific fact as outdated or incorrect. The fact is archived (not deleted) "
                "for audit trail. Use when user asks to forget something specific, or when info "
                "becomes obsolete. Returns confirmation or error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "personal",
                            "preference",
                            "skill",
                            "trait",
                            "opinion",
                            "relationship",
                        ],
                        "description": "Category of fact to forget",
                    },
                    "fact_key": {
                        "type": "string",
                        "description": "Which fact to forget (e.g., 'phone_number', 'location')",
                    },
                    "reason": {
                        "type": "string",
                        "enum": [
                            "outdated",
                            "incorrect",
                            "superseded",
                            "user_requested",
                        ],
                        "description": "Why forget this fact?",
                    },
                    "replacement_fact_id": {
                        "type": "integer",
                        "description": "If superseded, ID of the new fact that replaces this one (optional)",
                    },
                },
                "required": ["user_id", "fact_type", "fact_key", "reason"],
            },
        }
    ]
}

# Forget all facts tool (bulk delete)
FORGET_ALL_FACTS_DEFINITION = {
    "function_declarations": [
        {
            "name": "forget_all_facts",
            "description": (
                "Archive ALL facts about a user in one operation. Use when user explicitly "
                "asks to 'forget everything' about them. This is more efficient than calling "
                "forget_fact multiple times. Facts are archived (not deleted) for audit trail. "
                "Returns count of facts forgotten."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "Telegram user ID",
                    },
                    "reason": {
                        "type": "string",
                        "enum": [
                            "user_requested",
                            "privacy_request",
                            "data_reset",
                        ],
                        "description": "Why forget all facts? Usually 'user_requested'",
                    },
                },
                "required": ["user_id", "reason"],
            },
        }
    ]
}
