"""
Base utilities for tool implementations.

Provides common functions for formatting and compressing tool responses.
"""

import json
from typing import Any


def compact_json(data: Any, max_length: int | None = None) -> str:
    """
    Convert data to compact JSON string with minimal whitespace.

    Optimized for token efficiency:
    - No indentation or extra spaces
    - Consistent key ordering (sorted)
    - Optional truncation to max_length

    Args:
        data: Any JSON-serializable data structure
        max_length: Maximum string length (chars). If exceeded, truncates with ellipsis.

    Returns:
        Compact JSON string

    Examples:
        >>> compact_json({"result": 42, "status": "ok"})
        '{"result":42,"status":"ok"}'

        >>> compact_json({"data": "x" * 100}, max_length=30)
        '{"data":"xxxxxxxxxxxxxxxx...'
    """
    # Compact JSON without whitespace, sorted keys for consistency
    result = json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

    if max_length is not None:
        if max_length <= 0:
            return ""

        if len(result) <= max_length:
            return result

        if max_length <= 3:
            return result[:max_length]

        # Truncate and add ellipsis within the budget
        return result[: max_length - 3] + "..."

    return result


def truncate_text(
    text: str, max_tokens: int = 300, words_per_token: float = 0.75
) -> str:
    """
    Truncate text to approximate token budget.

    Uses word-based heuristic: ~0.75 words per token (1.3 tokens per word).

    Args:
        text: Input text
        max_tokens: Maximum token budget
        words_per_token: Conversion ratio (words/token)

    Returns:
        Truncated text with ellipsis if needed
    """
    max_words = int(max_tokens * words_per_token)
    words = text.split()

    if len(words) <= max_words:
        return text

    truncated = " ".join(words[:max_words])
    return truncated + "..."


def format_tool_error(error: str, max_length: int = 200) -> str:
    """
    Format tool error as compact JSON.

    Args:
        error: Error message
        max_length: Maximum response length

    Returns:
        Compact JSON error response
    """
    error_text = error[: max_length - 50] if len(error) > max_length - 50 else error
    return compact_json({"error": error_text}, max_length=max_length)
