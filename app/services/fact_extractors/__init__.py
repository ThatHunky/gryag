"""Fact extraction module with multiple strategies."""

from .base import FactExtractor
from .hybrid import HybridFactExtractor, create_hybrid_extractor
from .rule_based import RuleBasedFactExtractor

__all__ = [
    "FactExtractor",
    "RuleBasedFactExtractor",
    "HybridFactExtractor",
    "create_hybrid_extractor",
]
