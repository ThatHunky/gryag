"""
Shared text processing utilities for context services.

Provides common functions used across multiple context components:
- Keyword extraction
- Cosine similarity calculation
"""

from __future__ import annotations

import math


# Common English stop words for keyword extraction
ENGLISH_STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "been",
    "be",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "may",
    "might",
    "can",
    "about",
    "that",
    "this",
    "these",
    "those",
}


def extract_keywords(text: str, stop_words: set[str] | None = None) -> list[str]:
    """
    Extract keywords from text for search/indexing.

    Removes stop words, normalizes whitespace, and filters short words.

    Args:
        text: Text to extract keywords from
        stop_words: Custom stop words set (defaults to ENGLISH_STOP_WORDS)

    Returns:
        List of extracted keywords
    """
    if not text:
        return []

    if stop_words is None:
        stop_words = ENGLISH_STOP_WORDS

    # Split and clean
    words = text.lower().split()
    keywords = [
        w.strip(".,!?;:\"'()[]{}")
        for w in words
        if w.strip(".,!?;:\"'()[]{}") not in stop_words and len(w) > 2
    ]

    return keywords


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Cosine similarity score (0.0 to 1.0), or 0.0 if vectors are invalid
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)

