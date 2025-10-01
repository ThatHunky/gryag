"""Fact extraction module with multiple strategies."""

from .base import FactExtractor
from .hybrid import HybridFactExtractor, create_hybrid_extractor
from .local_model import LocalModelFactExtractor
from .model_manager import ModelManager
from .rule_based import RuleBasedFactExtractor

__all__ = [
    "FactExtractor",
    "RuleBasedFactExtractor",
    "LocalModelFactExtractor",
    "ModelManager",
    "HybridFactExtractor",
    "create_hybrid_extractor",
]
