"""RequestMetricWriter — async batch writer for HTTP request metrics.

Extracted from AINDY/core/request_metric_writer.py with one change:
the DB-hardcoded _flush() is replaced with a pluggable flush_fn callback.
The writer itself has zero database or framework dependencies.

Usage::

    from nodus_observability_framework import RequestMetricWriter, PendingMetric

    def my_flush(batch):
        for metric in batch:
            print(metric.path, metric.status_code, metric.duration_ms)

    writer = RequestMetricWriter(flush_fn=my_flush)
    writer.start()
    writer.enqueue(PendingMetric("req-1", "trace-1", None, "GET", "/api", 200, 12.5))
    writer.stop()

AINDY integration — the flush callback that writes to RequestMetric ORM::

    def _make_aindy_flush_fn():
        def _flush(metrics):
            from AINDY.db.database import SessionLocal
            from AINDY.db.models.request_metric import RequestMetric
            from sqlalchemy import insert
            mappings = [
                {"request_id": m.request_id, "trace_id": m.trace_id,
                 "user_id": m.user_id, "method": m.method, "path": m.path,
                 "status_code": m.status_code, "duration_ms": m.duration_ms,
                 "created_at": m.created_at}
                for m in metrics
            ]
            db = SessionLocal()
            try:
                db.execute(insert(RequestMetric), mappings)
                db.commit()
            finally:
                db.close()
        return _flush
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_QUEUE_MAX = 10_000
_FLUSH_INTERVAL = 5.0
_BATCH_SIZE = 200

FlushFn = Callable[[list["PendingMetric"]], None]


@dataclass
class PendingMetric:
    """One HTTP request metric pending persistence.

    Attributes
    ----------
    request_id:   Unique ID for this request (trace ID or generated UUID).
    trace_id:     Distributed trace ID for correlation.
    user_id:      Authenticated user/tenant ID (opaque — caller owns the type).
    method:       HTTP method (``"GET"``, ``"POST"``, etc.).
    path:         Request URL path.
    status_code:  HTTP response status code.
    duration_ms:  Request handling duration in milliseconds.
    created_at:   UTC timestamp when the metric was enqueued.
    """

    request_id: str
    trace_id: str
    user_id: Any
    method: str
    path: str
    status_code: int
    duration_ms: float
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RequestMetricWriter:
    """Thread-safe non-blocking background writer for HTTP request metrics.

    The persistence backend is fully pluggable via *flush_fn* — the writer
    knows nothing about databases, ORMs, or schemas.

    Args:
        flush_fn:               Called with a list of ``PendingMetric`` on each
                                flush cycle.  Exceptions are caught and logged;
                                never propagated to callers.
        queue_size:             Max metrics buffered before drops (default: 10 000).
        batch_size:             Max metrics per ``flush_fn`` call (default: 200).
        flush_interval_seconds: Background flush cadence in seconds (default: 5.0).
        on_drop:                Optional callback fired with the drop count increment
                                when the queue is full.  Useful for Prometheus metrics.
    """

    def __init__(
        self,
        flush_fn: FlushFn,
        *,
        queue_size: int = _QUEUE_MAX,
        batch_size: int = _BATCH_SIZE,
        flush_interval_seconds: float = _FLUSH_INTERVAL,
        on_drop: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._flush_fn = flush_fn
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._on_drop = on_drop
        self._queue: queue.Queue[PendingMetric] = queue.Queue(maxsize=queue_size)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._dropped = 0
        self._last_flush_monotonic = 0.0

    def start(self) -> None:
        """Start the background flush daemon thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_flush_monotonic = 0.0
        self._thread = threading.Thread(
            target=self._run,
            name="nodus-request-metric-writer",
            daemon=True,
        )
        self._thread.start()
        logger.info("[RequestMetricWriter] Background writer started.")

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the background thread to stop, then flush remaining metrics."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        while not self._queue.empty():
            self._flush()
        logger.info("[RequestMetricWriter] Background writer stopped.")

    def enqueue(self, metric: PendingMetric) -> bool:
        """Non-blocking enqueue.  Returns False (and increments drop count) if full."""
        try:
            self._queue.put_nowait(metric)
            return True
        except queue.Full:
            self._dropped += 1
            if self._on_drop is not None:
                try:
                    self._on_drop(1)
                except Exception:
                    pass
            if self._dropped % 100 == 1:
                logger.warning(
                    "[RequestMetricWriter] Queue full; dropped %d metrics total",
                    self._dropped,
                )
            return False

    def snapshot(self) -> dict[str, int | bool | float]:
        """Return a snapshot of current writer state for monitoring."""
        return {
            "queue_depth": int(self._queue.qsize()),
            "dropped_total": int(self._dropped),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "last_flush_monotonic": float(self._last_flush_monotonic),
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._flush_interval)
            self._flush()

    def _flush(self) -> None:
        batch: list[PendingMetric] = []
        try:
            while len(batch) < self._batch_size:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass

        if not batch:
            return

        try:
            self._flush_fn(batch)
            self._last_flush_monotonic = time.monotonic()
        except Exception as exc:
            logger.warning(
                "[RequestMetricWriter] Batch flush failed (%d metrics): %s",
                len(batch),
                exc,
            )
