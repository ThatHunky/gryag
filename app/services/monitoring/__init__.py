"""
Continuous learning monitoring system.

This module provides intelligent continuous monitoring of all chat messages
to extract facts, track conversations, and enable proactive engagement.

Public API:
    - ContinuousMonitor: Main orchestrator for monitoring system
    - MessageClassifier: Filters low-value messages
    - ConversationAnalyzer: Tracks conversation windows
    - FactQualityManager: Manages fact quality and deduplication
    - ProactiveTrigger: Decides when to send proactive responses
    - EventQueue: Priority queue for async processing
"""

from __future__ import annotations

__all__ = [
    "ContinuousMonitor",
    "MessageClassifier",
    "ConversationAnalyzer",
    "FactQualityManager",
    "ProactiveTrigger",
    "EventQueue",
]


# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "ContinuousMonitor":
        from app.services.monitoring.continuous_monitor import ContinuousMonitor

        return ContinuousMonitor
    elif name == "MessageClassifier":
        from app.services.monitoring.message_classifier import MessageClassifier

        return MessageClassifier
    elif name == "ConversationAnalyzer":
        from app.services.monitoring.conversation_analyzer import ConversationAnalyzer

        return ConversationAnalyzer
    elif name == "FactQualityManager":
        from app.services.monitoring.fact_quality_manager import FactQualityManager

        return FactQualityManager
    elif name == "ProactiveTrigger":
        from app.services.monitoring.proactive_trigger import ProactiveTrigger

        return ProactiveTrigger
    elif name == "EventQueue":
        from app.services.monitoring.event_system import EventQueue

        return EventQueue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
