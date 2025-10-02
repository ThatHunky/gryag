"""
Resource optimization service to automatically adjust system behavior
based on current resource usage and health.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.resource_monitor import get_resource_monitor, ResourceStats
from app.services.telemetry import telemetry

logger = logging.getLogger(__name__)


class ResourceOptimizer:
    """
    Automatically adjusts system behavior based on resource pressure.

    Implements graceful degradation:
    - High CPU: Reduce monitoring frequency, disable non-essential features
    - High Memory: Reduce cache sizes, disable local models
    - Critical levels: Emergency mode with minimal processing
    """

    def __init__(self) -> None:
        self.resource_monitor = get_resource_monitor()
        self._optimization_active = False
        self._last_optimization_time = 0.0
        self._optimization_level = 0  # 0=normal, 1=optimized, 2=emergency
        self._stats = {
            "optimizations_applied": 0,
            "emergency_mode_activations": 0,
            "normal_mode_restorations": 0,
        }

    async def check_and_optimize(self) -> dict[str, Any]:
        """
        Check resource usage and apply optimizations if needed.

        Returns:
            Dict with optimization status and actions taken
        """
        if not self.resource_monitor.is_available():
            return {"status": "monitoring_unavailable"}

        stats = self.resource_monitor.get_stats()
        if stats is None:
            return {"status": "stats_unavailable"}

        import time

        now = time.time()

        # Don't optimize too frequently (minimum 30 seconds between optimizations)
        if now - self._last_optimization_time < 30:
            return {
                "status": "throttled",
                "optimization_level": self._optimization_level,
            }

        previous_level = self._optimization_level
        actions_taken = []

        # Determine optimization level needed
        new_level = self._calculate_optimization_level(stats)

        if new_level != previous_level:
            self._last_optimization_time = now
            actions_taken = await self._apply_optimization_level(new_level, stats)
            self._optimization_level = new_level
            self._stats["optimizations_applied"] += 1

            if new_level == 2:
                self._stats["emergency_mode_activations"] += 1
            elif new_level == 0 and previous_level > 0:
                self._stats["normal_mode_restorations"] += 1

            logger.info(
                f"Resource optimization: level {previous_level} → {new_level}",
                extra={
                    "cpu_percent": stats.cpu_percent,
                    "memory_percent": stats.memory_percent,
                    "actions_taken": actions_taken,
                },
            )

            # Update telemetry
            telemetry.set_gauge("optimization_level", new_level)
            telemetry.increment_counter(f"optimization_level_{new_level}_applied")

        return {
            "status": "checked",
            "optimization_level": new_level,
            "level_changed": new_level != previous_level,
            "actions_taken": actions_taken,
            "resource_stats": {
                "cpu_percent": stats.cpu_percent,
                "memory_percent": stats.memory_percent,
                "process_memory_mb": stats.process_memory_mb,
            },
        }

    def _calculate_optimization_level(self, stats: ResourceStats) -> int:
        """
        Calculate needed optimization level based on resource usage.

        Level 0: Normal operation (CPU < 80%, Memory < 70%)
        Level 1: Optimized operation (CPU 80-95%, Memory 70-85%)
        Level 2: Emergency mode (CPU > 95%, Memory > 85%)
        """
        cpu_pressure = stats.cpu_percent >= 95.0
        memory_pressure = stats.memory_percent >= 85.0

        if cpu_pressure or memory_pressure:
            return 2  # Emergency mode

        high_cpu = stats.cpu_percent >= 80.0
        high_memory = stats.memory_percent >= 70.0

        if high_cpu or high_memory:
            return 1  # Optimized mode

        return 0  # Normal mode

    async def _apply_optimization_level(
        self, level: int, stats: ResourceStats
    ) -> list[str]:
        """Apply optimizations for the given level."""
        actions = []

        if level == 0:
            # Normal mode - restore full functionality
            actions.append("restored_normal_mode")

        elif level == 1:
            # Optimized mode - reduce non-essential overhead
            actions.extend(
                [
                    "reduced_monitoring_frequency",
                    "disabled_non_essential_telemetry",
                    "optimized_cache_sizes",
                ]
            )

        elif level == 2:
            # Emergency mode - minimal processing only
            actions.extend(
                [
                    "emergency_mode_activated",
                    "disabled_fact_extraction",
                    "disabled_continuous_monitoring",
                    "minimal_telemetry_only",
                    "reduced_response_generation",
                ]
            )

        return actions

    def get_optimization_recommendations(self, stats: ResourceStats) -> list[str]:
        """Get manual optimization recommendations based on current stats."""
        recommendations = []

        if stats.cpu_percent > 90:
            recommendations.extend(
                [
                    "Consider disabling continuous monitoring",
                    "Reduce fact extraction frequency",
                    "Disable profile summarization",
                    "Use rule-based extraction only",
                ]
            )

        if stats.memory_percent > 80:
            recommendations.extend(
                [
                    "Disable local model loading",
                    "Reduce conversation window size",
                    "Lower max concurrent windows",
                    "Increase retention cleanup frequency",
                ]
            )

        if stats.process_memory_mb > 300:
            recommendations.extend(
                [
                    "Bot process using high memory",
                    "Consider restarting to clear caches",
                    "Review fact storage limits",
                ]
            )

        return recommendations

    def get_stats(self) -> dict[str, Any]:
        """Get optimizer statistics."""
        return {
            **self._stats,
            "current_optimization_level": self._optimization_level,
            "optimization_active": self._optimization_active,
        }

    def is_emergency_mode(self) -> bool:
        """Check if system is in emergency mode."""
        return self._optimization_level >= 2


# Global singleton
_resource_optimizer: ResourceOptimizer | None = None


def get_resource_optimizer() -> ResourceOptimizer:
    """Get global ResourceOptimizer singleton."""
    global _resource_optimizer
    if _resource_optimizer is None:
        _resource_optimizer = ResourceOptimizer()
    return _resource_optimizer


async def periodic_optimization_check():
    """Periodic task to check and apply resource optimizations."""
    optimizer = get_resource_optimizer()

    while True:
        try:
            result = await optimizer.check_and_optimize()

            if result.get("level_changed"):
                logger.info("Resource optimization check complete", extra=result)

        except Exception as e:
            logger.error(f"Error in periodic optimization check: {e}", exc_info=True)

        # Check every 2 minutes during normal operation
        # Check every 30 seconds during high resource usage
        optimizer_stats = optimizer.get_stats()
        sleep_time = 30 if optimizer_stats["current_optimization_level"] > 0 else 120

        await asyncio.sleep(sleep_time)
