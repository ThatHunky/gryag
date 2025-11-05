"""Utility to convert SQLite queries to PostgreSQL format."""

from __future__ import annotations

import re
from typing import Any


def convert_query_to_postgres(query: str, params: tuple | list | None = None) -> tuple[str, tuple | list | None]:
    """Convert SQLite query with ? placeholders to PostgreSQL with $1, $2, etc.
    
    Args:
        query: SQL query with ? placeholders
        params: Query parameters (tuple or list)
        
    Returns:
        Tuple of (converted_query, params) - params unchanged for asyncpg
    """
    if params is None:
        return query, None
    
    # Count number of ? placeholders
    placeholder_count = query.count('?')
    
    if placeholder_count == 0:
        return query, params
    
    # Replace ? with $1, $2, etc.
    converted = query
    for i in range(1, placeholder_count + 1):
        converted = converted.replace('?', f'${i}', 1)
    
    return converted, params

