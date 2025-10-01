from __future__ import annotations

import logging
from collections import Counter
from threading import Lock
from typing import Any, Tuple


_METRICS: Counter[tuple[str, Tuple[tuple[str, Any], ...]]] = Counter()
_LOCK = Lock()
_LOGGER = logging.getLogger("gryag.telemetry")


def _normalize_labels(labels: dict[str, Any]) -> Tuple[tuple[str, Any], ...]:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def increment_counter(name: str, amount: int = 1, **labels: Any) -> None:
    """Increment an in-memory counter and emit a debug log entry."""

    key = (name, _normalize_labels(labels))
    with _LOCK:
        _METRICS[key] += amount
        value = _METRICS[key]
    if _LOGGER.isEnabledFor(logging.DEBUG):
        payload: dict[str, Any] = {"metric": name, "value": value}
        if labels:
            payload["labels"] = labels
        _LOGGER.debug("metric_increment", extra={"telemetry": payload})


def set_gauge(name: str, value: int, **labels: Any) -> None:
    """Set a gauge value (overwrites previous value) and emit a debug log entry."""

    key = (name, _normalize_labels(labels))
    with _LOCK:
        _METRICS[key] = value
    if _LOGGER.isEnabledFor(logging.DEBUG):
        payload: dict[str, Any] = {"metric": name, "value": value}
        if labels:
            payload["labels"] = labels
        _LOGGER.debug("metric_set", extra={"telemetry": payload})


def snapshot() -> dict[str, int]:
    """Return a snapshot of all counters for diagnostics/testing."""

    with _LOCK:
        return {
            _render_key(name, labels): count
            for (name, labels), count in _METRICS.items()
        }


def reset() -> None:
    """Clear all counters (primarily for testing)."""

    with _LOCK:
        _METRICS.clear()


def _render_key(name: str, labels: Tuple[tuple[str, Any], ...]) -> str:
    if not labels:
        return name
    label_str = ",".join(f"{key}={value}" for key, value in labels)
    return f"{name}{{{label_str}}}"


# Module-level telemetry API object for imports
class _Telemetry:
    """Simple telemetry API wrapper for module-level access."""

    increment_counter = staticmethod(increment_counter)
    set_gauge = staticmethod(set_gauge)
    snapshot = staticmethod(snapshot)
    reset = staticmethod(reset)


telemetry = _Telemetry()
