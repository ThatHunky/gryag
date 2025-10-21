"""Resource monitoring service for tracking CPU and memory usage.

Optimized for i5-6500 (4C/4T, 16GB RAM) to detect resource pressure
and enable graceful degradation when system resources are constrained.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.telemetry import telemetry

if TYPE_CHECKING:
    from app.services.resource_optimizer import ResourceOptimizer

logger = logging.getLogger(__name__)


@dataclass
class ResourceStats:
    """System resource usage statistics."""

    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    cpu_percent: float
    process_memory_mb: float
    process_cpu_percent: float


class ResourceMonitor:
    """Legacy resource monitor placeholder (disabled)."""

    def is_available(self) -> bool:  # pragma: no cover - trivial
        return False

    def get_stats(self) -> ResourceStats | None:  # pragma: no cover - disabled
        return None

    def check_memory_pressure(self) -> tuple[bool, str | None]:  # pragma: no cover
        return False, None

    def check_cpu_pressure(self) -> tuple[bool, str | None]:  # pragma: no cover
        return False, None

    def log_resource_summary(self) -> None:  # pragma: no cover
        logger.debug("Resource monitoring disabled by configuration")


# Global singleton instance
_resource_monitor: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    """Get global ResourceMonitor singleton."""
    global _resource_monitor
    if _resource_monitor is None:
        _resource_monitor = ResourceMonitor()
    return _resource_monitor


async def run_resource_monitoring_task(
    resource_monitor: ResourceMonitor,
    resource_optimizer: ResourceOptimizer,
) -> None:
    """Periodically check and log resource usage with auto-optimization.

    This background task monitors system resources and applies optimizations
    when resource pressure is detected.

    Args:
        resource_monitor: The resource monitor instance to use for checking resources
        resource_optimizer: The resource optimizer instance to use for applying optimizations
    """
    while True:
        try:
            # Check and apply optimizations
            optimization_result = await resource_optimizer.check_and_optimize()

            if optimization_result.get("level_changed"):
                logger.info("Resource optimization applied", extra=optimization_result)

            # Regular resource monitoring
            if resource_monitor.is_available():
                resource_monitor.check_memory_pressure()
                resource_monitor.check_cpu_pressure()

                # Log detailed summary every 10 minutes
                if int(time.time()) % 600 < 60:  # Within first minute of 10-min window
                    resource_monitor.log_resource_summary()

                    # Also log optimization stats
                    opt_stats = resource_optimizer.get_stats()
                    if opt_stats["current_optimization_level"] > 0:
                        logger.info("Resource optimizer active", extra=opt_stats)

        except Exception as e:
            logger.error(f"Error in resource monitoring: {e}", exc_info=True)

        # Adaptive sleep based on optimization level
        sleep_time = 60
        if resource_optimizer.is_emergency_mode():
            sleep_time = 30  # Check more frequently in emergency mode

        await asyncio.sleep(sleep_time)
