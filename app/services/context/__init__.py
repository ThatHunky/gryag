"""
Context and memory management services.

This package contains the enhanced context retrieval and memory management system
implementing multi-level context, hybrid search, episodic memory, fact graphs,
and adaptive retention.
"""

from __future__ import annotations

# Import implemented classes
from app.services.context.hybrid_search import HybridSearchEngine, SearchResult
from app.services.context.episodic_memory import EpisodicMemoryStore, Episode
from app.services.context.multi_level_context import (
    MultiLevelContextManager,
    LayeredContext,
    ImmediateContext,
    RecentContext,
    RelevantContext,
    BackgroundContext,
    EpisodicContext,
)

__all__ = [
    # Hybrid Search
    "HybridSearchEngine",
    "SearchResult",
    # Multi-Level Context
    "MultiLevelContextManager",
    "LayeredContext",
    "ImmediateContext",
    "RecentContext",
    "RelevantContext",
    "BackgroundContext",
    "EpisodicContext",
    # Episodic Memory
    "EpisodicMemoryStore",
    "Episode",
    # Future (not yet implemented)
    # "FactGraphManager",
    # "TemporalFactManager",
    # "AdaptiveRetentionManager",
    # "ImportanceScorer",
]
