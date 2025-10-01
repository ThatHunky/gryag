"""Resource monitoring service for tracking CPU and memory usage.

Optimized for i5-6500 (4C/4T, 16GB RAM) to detect resource pressure
and enable graceful degradation when system resources are constrained.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

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
    """Monitor system and process resource usage.

    Tracks CPU and memory to detect resource pressure on i5-6500 hardware.
    Provides thresholds for graceful degradation decisions.
    """

    # i5-6500 specific thresholds (16GB RAM)
    MEMORY_WARNING_THRESHOLD = 80.0  # 12.8GB
    MEMORY_CRITICAL_THRESHOLD = 90.0  # 14.4GB
    CPU_WARNING_THRESHOLD = 85.0
    CPU_CRITICAL_THRESHOLD = 95.0

    def __init__(self) -> None:
        """Initialize resource monitor."""
        if psutil is None:
            logger.warning(
                "psutil not available - resource monitoring disabled. "
                "Install with: pip install psutil"
            )
            self._available = False
        else:
            self._available = True
            self._process = psutil.Process(os.getpid())

        self._last_memory_warning_time = 0.0
        self._last_cpu_warning_time = 0.0

    def is_available(self) -> bool:
        """Check if resource monitoring is available."""
        return self._available

    def get_stats(self) -> ResourceStats | None:
        """Get current resource usage statistics.

        Returns:
            ResourceStats with current usage, or None if psutil unavailable
        """
        if not self._available:
            return None

        try:
            # System-wide stats
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # Process-specific stats
            process_memory = self._process.memory_info()
            process_cpu = self._process.cpu_percent(interval=0.1)

            stats = ResourceStats(
                memory_used_mb=memory.used / (1024 * 1024),
                memory_total_mb=memory.total / (1024 * 1024),
                memory_percent=memory.percent,
                cpu_percent=cpu_percent,
                process_memory_mb=process_memory.rss / (1024 * 1024),
                process_cpu_percent=process_cpu,
            )

            # Update telemetry
            telemetry.set_gauge("memory_usage_mb", int(stats.memory_used_mb))
            telemetry.set_gauge("memory_percent", int(stats.memory_percent))
            telemetry.set_gauge("cpu_usage_percent", int(stats.cpu_percent))
            telemetry.set_gauge("process_memory_mb", int(stats.process_memory_mb))
            telemetry.set_gauge("process_cpu_percent", int(stats.process_cpu_percent))

            return stats

        except Exception as exc:
            logger.error(
                "Failed to collect resource stats: %s",
                exc,
                exc_info=True,
            )
            return None

    def check_memory_pressure(self) -> tuple[bool, str | None]:
        """Check if system is under memory pressure.

        Returns:
            Tuple of (is_critical, reason_message)
            - is_critical: True if memory usage exceeds thresholds
            - reason_message: Human-readable explanation, or None if OK
        """
        stats = self.get_stats()
        if stats is None:
            return False, None

        if stats.memory_percent >= self.MEMORY_CRITICAL_THRESHOLD:
            msg = (
                f"CRITICAL: Memory usage at {stats.memory_percent:.1f}% "
                f"({stats.memory_used_mb:.0f}MB / {stats.memory_total_mb:.0f}MB)"
            )
            logger.error(msg)
            telemetry.increment_counter("memory_pressure_critical")
            return True, msg

        if stats.memory_percent >= self.MEMORY_WARNING_THRESHOLD:
            import time

            now = time.time()
            # Throttle warnings to once per 5 minutes
            if now - self._last_memory_warning_time > 300:
                msg = (
                    f"WARNING: Memory usage at {stats.memory_percent:.1f}% "
                    f"({stats.memory_used_mb:.0f}MB / {stats.memory_total_mb:.0f}MB)"
                )
                logger.warning(msg)
                telemetry.increment_counter("memory_pressure_warning")
                self._last_memory_warning_time = now
            return False, None

        return False, None

    def check_cpu_pressure(self) -> tuple[bool, str | None]:
        """Check if system is under CPU pressure.

        Returns:
            Tuple of (is_critical, reason_message)
            - is_critical: True if CPU usage exceeds thresholds
            - reason_message: Human-readable explanation, or None if OK
        """
        stats = self.get_stats()
        if stats is None:
            return False, None

        if stats.cpu_percent >= self.CPU_CRITICAL_THRESHOLD:
            msg = f"CRITICAL: CPU usage at {stats.cpu_percent:.1f}%"
            logger.error(msg)
            telemetry.increment_counter("cpu_pressure_critical")
            return True, msg

        if stats.cpu_percent >= self.CPU_WARNING_THRESHOLD:
            import time

            now = time.time()
            # Throttle warnings to once per 5 minutes
            if now - self._last_cpu_warning_time > 300:
                msg = f"WARNING: CPU usage at {stats.cpu_percent:.1f}%"
                logger.warning(msg)
                telemetry.increment_counter("cpu_pressure_warning")
                self._last_cpu_warning_time = now
            return False, None

        return False, None

    def should_disable_local_model(self) -> bool:
        """Determine if local model should be disabled due to resource pressure.

        Returns True if memory usage exceeds critical threshold (90% on i5-6500).
        This triggers graceful degradation to rule-based + Gemini fallback.
        """
        is_critical, _ = self.check_memory_pressure()
        return is_critical

    def log_resource_summary(self) -> None:
        """Log a summary of current resource usage."""
        stats = self.get_stats()
        if stats is None:
            logger.debug("Resource monitoring unavailable")
            return

        logger.info(
            "Resource usage: Memory %.1f%% (%dMB/%dMB), CPU %.1f%%, "
            "Process: %dMB RAM, %.1f%% CPU",
            stats.memory_percent,
            stats.memory_used_mb,
            stats.memory_total_mb,
            stats.cpu_percent,
            stats.process_memory_mb,
            stats.process_cpu_percent,
            extra={
                "memory_percent": stats.memory_percent,
                "memory_used_mb": stats.memory_used_mb,
                "cpu_percent": stats.cpu_percent,
                "process_memory_mb": stats.process_memory_mb,
            },
        )


# Global singleton instance
_resource_monitor: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    """Get global ResourceMonitor singleton."""
    global _resource_monitor
    if _resource_monitor is None:
        _resource_monitor = ResourceMonitor()
    return _resource_monitor
