from __future__ import annotations

import logging
from typing import Callable

from prometheus_client import Counter, Histogram, start_http_server

from app.config import Settings

logger = logging.getLogger(__name__)

# Core metrics
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


def start_metrics_server(settings: Settings) -> None:
    if not settings.enable_health_metrics:
        logger.info("Metrics disabled (ENABLE_HEALTH_METRICS=false)")
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


