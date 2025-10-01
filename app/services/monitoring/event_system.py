"""
Event-driven processing system with priority queue and async workers.

Handles:
- Priority queue for message processing
- Async worker pool with circuit breakers
- Graceful degradation under load
- Event logging and metrics
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

LOGGER = logging.getLogger(__name__)


class EventPriority(Enum):
    """Priority levels for event processing."""

    CRITICAL = 0  # Addressed messages, explicit bot interactions
    HIGH = 1  # High-value messages, questions
    MEDIUM = 2  # Medium-value messages, context
    LOW = 3  # Low-value messages, background processing


@dataclass(order=True)
class Event:
    """Event to be processed by workers."""

    # Order by priority first, then timestamp
    priority: int = field(compare=True)
    timestamp: float = field(compare=True)

    # Actual data (not used for comparison)
    event_type: str = field(compare=False)
    data: dict[str, Any] = field(compare=False, default_factory=dict)
    retry_count: int = field(compare=False, default=0)

    @classmethod
    def create(
        cls,
        event_type: str,
        data: dict[str, Any],
        priority: EventPriority = EventPriority.MEDIUM,
    ) -> Event:
        """Create a new event with proper ordering."""
        return cls(
            priority=priority.value,
            timestamp=time.time(),
            event_type=event_type,
            data=data,
        )


class CircuitBreaker:
    """
    Simple circuit breaker for worker protection.

    States:
    - CLOSED: Normal operation
    - OPEN: Too many failures, reject requests
    - HALF_OPEN: Testing if system recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before trying again
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._state = "CLOSED"

    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        if self._state == "OPEN":
            # Check if we should try half-open
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "HALF_OPEN"
                self._success_count = 0
                LOGGER.info("Circuit breaker entering HALF_OPEN state")
                return False
            return True
        return False

    def record_success(self) -> None:
        """Record a successful operation."""
        if self._state == "HALF_OPEN":
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = "CLOSED"
                self._failure_count = 0
                LOGGER.info("Circuit breaker CLOSED (recovered)")
        elif self._state == "CLOSED":
            # Reset failure count on success
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == "HALF_OPEN":
            # Failed during recovery, go back to OPEN
            self._state = "OPEN"
            LOGGER.warning("Circuit breaker OPEN (failed during recovery)")
        elif self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            LOGGER.warning(
                f"Circuit breaker OPEN (threshold {self.failure_threshold} reached)"
            )

    def get_state(self) -> str:
        """Get current state."""
        return self._state


# Type alias for event handler
EventHandler = Callable[[Event], Awaitable[None]]


class EventQueue:
    """
    Priority queue with async worker pool and circuit breakers.

    Features:
    - Priority-based processing
    - Configurable worker pool
    - Circuit breaker protection
    - Graceful degradation
    - Event retry logic
    """

    def __init__(
        self,
        num_workers: int = 3,
        max_queue_size: int = 1000,
        enable_circuit_breaker: bool = True,
        max_retries: int = 2,
    ):
        """
        Initialize event queue.

        Args:
            num_workers: Number of async workers
            max_queue_size: Maximum queue size
            enable_circuit_breaker: Enable circuit breaker protection
            max_retries: Maximum retry attempts per event
        """
        self.num_workers = num_workers
        self.max_queue_size = max_queue_size
        self.max_retries = max_retries

        self._queue: asyncio.PriorityQueue[Event] = asyncio.PriorityQueue(
            maxsize=max_queue_size
        )
        self._handlers: dict[str, EventHandler] = {}
        self._workers: list[asyncio.Task] = []
        self._running = False

        self._circuit_breaker = CircuitBreaker() if enable_circuit_breaker else None

        self._stats = {
            "events_queued": 0,
            "events_processed": 0,
            "events_failed": 0,
            "events_retried": 0,
            "events_dropped": 0,
            "queue_full_count": 0,
        }

        LOGGER.info(
            "EventQueue initialized",
            extra={
                "num_workers": num_workers,
                "max_queue_size": max_queue_size,
                "circuit_breaker_enabled": enable_circuit_breaker is not None,
            },
        )

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type] = handler
        LOGGER.debug(f"Registered handler for event type: {event_type}")

    async def enqueue(
        self,
        event_type: str,
        data: dict[str, Any],
        priority: EventPriority = EventPriority.MEDIUM,
    ) -> bool:
        """
        Add an event to the queue.

        Returns:
            True if enqueued, False if queue full or circuit open
        """
        # Check circuit breaker
        if self._circuit_breaker and self._circuit_breaker.is_open():
            LOGGER.warning(
                "Event rejected: circuit breaker is OPEN",
                extra={"event_type": event_type},
            )
            self._stats["events_dropped"] += 1
            return False

        event = Event.create(event_type, data, priority)

        try:
            self._queue.put_nowait(event)
            self._stats["events_queued"] += 1
            return True
        except asyncio.QueueFull:
            # Queue full, drop low-priority events
            if priority.value >= EventPriority.LOW.value:
                LOGGER.warning(
                    "Queue full, dropping LOW priority event",
                    extra={"event_type": event_type},
                )
                self._stats["events_dropped"] += 1
                self._stats["queue_full_count"] += 1
                return False

            # For high-priority events, try to evict a low-priority event
            # This is a simplified approach; a real implementation would need
            # a custom priority queue with eviction
            LOGGER.warning(
                "Queue full, high-priority event may be delayed",
                extra={"event_type": event_type},
            )
            self._stats["queue_full_count"] += 1

            # Try with timeout
            try:
                await asyncio.wait_for(self._queue.put(event), timeout=5.0)
                self._stats["events_queued"] += 1
                return True
            except asyncio.TimeoutError:
                self._stats["events_dropped"] += 1
                return False

    async def start(self) -> None:
        """Start worker pool."""
        if self._running:
            LOGGER.warning("EventQueue already running")
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.num_workers)
        ]
        LOGGER.info(f"Started {self.num_workers} workers")

    async def stop(self) -> None:
        """Stop worker pool gracefully."""
        if not self._running:
            return

        LOGGER.info("Stopping workers...")
        self._running = False

        # Cancel all workers
        for worker in self._workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

        LOGGER.info("All workers stopped")

    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes events."""
        LOGGER.debug(f"Worker {worker_id} started")

        while self._running:
            try:
                # Get event with timeout to allow graceful shutdown
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Process event
            try:
                await self._process_event(event)
                self._stats["events_processed"] += 1

                if self._circuit_breaker:
                    self._circuit_breaker.record_success()

            except Exception as e:
                LOGGER.error(
                    f"Worker {worker_id} failed to process event",
                    exc_info=e,
                    extra={"event_type": event.event_type},
                )
                self._stats["events_failed"] += 1

                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()

                # Retry logic
                if event.retry_count < self.max_retries:
                    event.retry_count += 1
                    event.timestamp = time.time()  # Reset timestamp for retry
                    try:
                        self._queue.put_nowait(event)
                        self._stats["events_retried"] += 1
                        LOGGER.info(
                            f"Retrying event (attempt {event.retry_count}/{self.max_retries})",
                            extra={"event_type": event.event_type},
                        )
                    except asyncio.QueueFull:
                        LOGGER.warning("Queue full, could not retry event")
                        self._stats["events_dropped"] += 1

            finally:
                self._queue.task_done()

        LOGGER.debug(f"Worker {worker_id} stopped")

    async def _process_event(self, event: Event) -> None:
        """Process a single event."""
        handler = self._handlers.get(event.event_type)

        if not handler:
            LOGGER.warning(f"No handler registered for event type: {event.event_type}")
            return

        await handler(event)

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        stats: dict[str, Any] = self._stats.copy()
        stats["queue_size"] = self._queue.qsize()
        stats["workers_running"] = len([w for w in self._workers if not w.done()])

        if self._circuit_breaker:
            stats["circuit_breaker_state"] = self._circuit_breaker.get_state()

        return stats

    def is_healthy(self) -> bool:
        """Check if queue is healthy."""
        if not self._running:
            return False

        if self._circuit_breaker and self._circuit_breaker.is_open():
            return False

        # Check if queue is overwhelmed
        if self._queue.qsize() > self.max_queue_size * 0.9:
            return False

        return True
