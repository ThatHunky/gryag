"""Resource monitoring service for tracking CPU and memory usage.

Optimized for i5-6500 (4C/4T, 16GB RAM) to detect resource pressure
and enable graceful degradation when system resources are constrained.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.telemetry import telemetry

if TYPE_CHECKING:
    pass

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
