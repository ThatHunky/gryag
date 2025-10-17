"""
Fact value normalization utilities for improved deduplication.

Provides canonical representations for common fact types (locations, languages, etc.)
to improve semantic deduplication and reduce storage of near-duplicates.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


# Canonical mappings for programming languages (handles common variants)
PROGRAMMING_LANGUAGE_CANONICAL = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "c++": "cpp",
    "c#": "csharp",
    "objective-c": "objc",
    "objective c": "objc",
}

# Canonical mappings for spoken languages
SPOKEN_LANGUAGE_CANONICAL = {
    "англійська": "english",
    "українська": "ukrainian",
    "російська": "russian",
    "польська": "polish",
    "німецька": "german",
    "французька": "french",
    "іспанська": "spanish",
    "англ": "english",
    "укр": "ukrainian",
    "рус": "russian",
}

# Common city name variants (Cyrillic/Latin)
LOCATION_CANONICAL = {
    "київ": "kyiv",
    "киев": "kyiv",
    "kiyv": "kyiv",
    "kiew": "kyiv",
    "львів": "lviv",
    "lvov": "lviv",
    "одеса": "odesa",
    "одесса": "odesa",
    "odessa": "odesa",
    "харків": "kharkiv",
    "харьков": "kharkiv",
    "kharkov": "kharkiv",
    "дніпро": "dnipro",
    "днепр": "dnipro",
    "dnipropetrovsk": "dnipro",
    "zaporizhzhia": "zaporizhzhia",
    "запоріжжя": "zaporizhzhia",
}


def normalize_unicode(text: str) -> str:
    """
    Normalize unicode text for comparison.

    Applies NFC normalization and strips combining marks.
    """
    # NFC normalization
    normalized = unicodedata.normalize("NFC", text)
    return normalized


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace: strip, collapse multiple spaces."""
    return re.sub(r"\s+", " ", text.strip())


def normalize_case(text: str) -> str:
    """Convert to lowercase for case-insensitive comparison."""
    return text.lower()


def remove_punctuation(text: str) -> str:
    """Remove common punctuation marks."""
    return re.sub(r"[.,!?;:\"'()\[\]{}]", "", text)


def normalize_basic(text: str) -> str:
    """
    Apply basic normalization: unicode, case, whitespace.

    This is a safe, general-purpose normalizer for all fact types.
    """
    text = normalize_unicode(text)
    text = normalize_case(text)
    text = normalize_whitespace(text)
    return text


def normalize_location(location: str) -> str:
    """
    Normalize location names for deduplication.

    Handles Cyrillic/Latin variants, common suffixes, and canonical mappings.
    """
    # Basic normalization
    normalized = normalize_basic(location)

    # Remove common suffixes
    normalized = re.sub(
        r",?\s*(ukraine|україна|украина)$", "", normalized, flags=re.IGNORECASE
    )
    normalized = re.sub(r",?\s*(oblast|область)$", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.strip()

    # Apply canonical mapping
    if normalized in LOCATION_CANONICAL:
        return LOCATION_CANONICAL[normalized]

    return normalized


def normalize_programming_language(lang: str) -> str:
    """
    Normalize programming language names.

    Handles common abbreviations and variant spellings.
    """
    normalized = normalize_basic(lang)

    # Remove "programming language" suffix
    normalized = re.sub(r"\s+(programming\s+)?language$", "", normalized)
    normalized = normalized.strip()

    # Apply canonical mapping
    if normalized in PROGRAMMING_LANGUAGE_CANONICAL:
        return PROGRAMMING_LANGUAGE_CANONICAL[normalized]

    return normalized


def normalize_spoken_language(lang: str) -> str:
    """
    Normalize spoken language names.

    Handles Ukrainian/Russian/English variants.
    """
    normalized = normalize_basic(lang)

    # Remove "language" suffix
    normalized = re.sub(r"\s+(мова|язык|language)$", "", normalized)
    normalized = normalized.strip()

    # Apply canonical mapping
    if normalized in SPOKEN_LANGUAGE_CANONICAL:
        return SPOKEN_LANGUAGE_CANONICAL[normalized]

    return normalized


def normalize_fact_value(fact_type: str, fact_key: str, fact_value: str) -> str:
    """
    Normalize fact value based on type and key.

    Applies type-specific normalization for better deduplication.

    Args:
        fact_type: Type of fact (personal, preference, skill, etc.)
        fact_key: Specific key (location, programming_language, etc.)
        fact_value: Raw value to normalize

    Returns:
        Normalized canonical value
    """
    # Type-specific normalization
    if fact_key == "location":
        return normalize_location(fact_value)
    elif fact_key == "programming_language":
        return normalize_programming_language(fact_value)
    elif fact_key == "language":
        return normalize_spoken_language(fact_value)
    elif fact_key == "age":
        # Age should be numeric only
        digits = re.sub(r"\D", "", fact_value)
        return digits if digits else fact_value
    else:
        # Generic normalization
        return normalize_basic(fact_value)


def get_dedup_key(fact: dict[str, Any]) -> tuple[str, str, str]:
    """
    Generate deduplication key for a fact.

    Uses normalized values to catch semantic duplicates.

    Args:
        fact: Fact dict with fact_type, fact_key, fact_value

    Returns:
        Tuple of (fact_type, fact_key, normalized_value) for dedup
    """
    fact_type = fact.get("fact_type", "")
    fact_key = fact.get("fact_key", "")
    fact_value = fact.get("fact_value", "")

    normalized_value = normalize_fact_value(fact_type, fact_key, fact_value)

    return (fact_type, fact_key, normalized_value)
