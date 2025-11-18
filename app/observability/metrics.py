from __future__ import annotations

import logging
from collections.abc import Callable

from app.config import Settings

logger = logging.getLogger(__name__)

# Try to import prometheus_client, but make it optional
try:
    from prometheus_client import Counter, Histogram, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Create dummy classes for when prometheus_client is not available
    class Counter:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

    class Histogram:
        def __init__(self, *args, **kwargs):
            pass

        def time(self):
            return _NoOpContextManager()

    class _NoOpContextManager:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def start_http_server(*args, **kwargs):
        pass


# Core metrics (will be no-ops if prometheus_client is not available)
if PROMETHEUS_AVAILABLE:
    messages_processed = Counter(
        "gryag_messages_processed_total", "Total number of messages processed"
    )
    rate_limit_hits = Counter(
        "gryag_rate_limit_hits_total", "Total number of rate limit hits"
    )
    handler_latency_seconds = Histogram(
        "gryag_handler_latency_seconds",
        "Handler latency in seconds",
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
    )
    tokens_used = Counter(
        "gryag_tokens_used_total", "Total tokens used across responses", ["type"]
    )
else:
    # Create no-op instances when prometheus is not available
    messages_processed = Counter()
    rate_limit_hits = Counter()
    handler_latency_seconds = Histogram()
    tokens_used = Counter()


def start_metrics_server(settings: Settings) -> None:
    if not settings.enable_health_metrics:
        logger.info("Metrics disabled (ENABLE_HEALTH_METRICS=false)")
        return
    if not PROMETHEUS_AVAILABLE:
        logger.warning(
            "Metrics enabled but prometheus_client not available. "
            "Install prometheus_client to enable metrics."
        )
        return
    start_http_server(settings.metrics_port)
    logger.info(
        "Prometheus metrics server started", extra={"port": settings.metrics_port}
    )


def record_tokens(kind: str, amount: int) -> None:
    try:
        tokens_used.labels(kind).inc(amount)
    except Exception:
        # Avoid surfacing metrics failures
        pass


def track_handler_latency() -> Callable:
    """
    Decorator to track handler latency via Histogram.
    Usage:
        @track_handler_latency()
        async def handler(...):
            ...
    """

    def _decorator(func: Callable):
        async def _wrapper(*args, **kwargs):
            with handler_latency_seconds.time():
                return await func(*args, **kwargs)

        return _wrapper

    return _decorator
