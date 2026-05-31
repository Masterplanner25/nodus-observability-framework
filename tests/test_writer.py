from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nodus_observability_framework import PendingMetric, RequestMetricWriter


def _metric(path: str = "/api/test", status: int = 200) -> PendingMetric:
    return PendingMetric(
        request_id="req-1",
        trace_id="trace-1",
        user_id=None,
        method="GET",
        path=path,
        status_code=status,
        duration_ms=12.5,
    )


# ── PendingMetric ─────────────────────────────────────────────────────────────

def test_pending_metric_defaults():
    m = _metric()
    assert m.method == "GET"
    assert m.status_code == 200
    assert m.duration_ms == 12.5
    assert m.created_at.tzinfo is not None


def test_pending_metric_created_at_utc():
    before = datetime.now(timezone.utc)
    m = _metric()
    after = datetime.now(timezone.utc)
    assert before <= m.created_at <= after


# ── RequestMetricWriter ───────────────────────────────────────────────────────

def test_enqueue_and_flush():
    collected: list = []
    writer = RequestMetricWriter(
        flush_fn=collected.extend,
        flush_interval_seconds=0.1,
    )
    writer.start()
    writer.enqueue(_metric("/a"))
    writer.enqueue(_metric("/b"))
    time.sleep(0.3)
    writer.stop()
    assert len(collected) == 2
    paths = {m.path for m in collected}
    assert "/a" in paths and "/b" in paths


def test_flush_fn_called_with_batch():
    batches: list[list] = []

    def capture(batch):
        batches.append(list(batch))

    writer = RequestMetricWriter(capture, flush_interval_seconds=0.1)
    writer.start()
    for i in range(5):
        writer.enqueue(_metric(f"/route/{i}"))
    time.sleep(0.3)
    writer.stop()
    total = sum(len(b) for b in batches)
    assert total == 5


def test_enqueue_returns_true_when_space():
    writer = RequestMetricWriter(lambda b: None, queue_size=10)
    writer.start()
    result = writer.enqueue(_metric())
    writer.stop()
    assert result is True


def test_enqueue_returns_false_when_full():
    writer = RequestMetricWriter(lambda b: None, queue_size=1, flush_interval_seconds=9999)
    writer.enqueue(_metric("/first"))     # fills the queue
    result = writer.enqueue(_metric("/second"))  # should be dropped
    assert result is False
    assert writer.snapshot()["dropped_total"] >= 1


def test_on_drop_callback_called():
    drops = []
    writer = RequestMetricWriter(
        lambda b: None,
        queue_size=1,
        flush_interval_seconds=9999,
        on_drop=drops.append,
    )
    writer.enqueue(_metric())
    writer.enqueue(_metric())  # triggers drop
    assert len(drops) >= 1


def test_stop_flushes_remaining():
    collected: list = []
    writer = RequestMetricWriter(
        flush_fn=collected.extend,
        flush_interval_seconds=999,  # won't fire automatically
    )
    writer.start()
    writer.enqueue(_metric())
    writer.stop()  # should flush on stop
    assert len(collected) == 1


def test_snapshot_shape():
    writer = RequestMetricWriter(lambda b: None)
    snap = writer.snapshot()
    assert "queue_depth" in snap
    assert "dropped_total" in snap
    assert "worker_running" in snap
    assert "last_flush_monotonic" in snap


def test_worker_running_after_start():
    writer = RequestMetricWriter(lambda b: None)
    assert writer.snapshot()["worker_running"] is False
    writer.start()
    assert writer.snapshot()["worker_running"] is True
    writer.stop()


def test_start_is_idempotent():
    writer = RequestMetricWriter(lambda b: None)
    writer.start()
    t1 = writer._thread
    writer.start()
    assert writer._thread is t1
    writer.stop()


def test_flush_fn_exception_does_not_propagate():
    def bad_flush(batch):
        raise RuntimeError("db down")

    writer = RequestMetricWriter(bad_flush, flush_interval_seconds=0.1)
    writer.start()
    writer.enqueue(_metric())
    time.sleep(0.3)
    writer.stop()  # must not raise


def test_batch_size_respected():
    batches: list[list] = []

    def capture(b):
        batches.append(list(b))

    writer = RequestMetricWriter(
        capture,
        batch_size=3,
        flush_interval_seconds=0.1,
    )
    writer.start()
    for _ in range(7):
        writer.enqueue(_metric())
    time.sleep(0.3)
    writer.stop()
    for b in batches:
        assert len(b) <= 3
    assert sum(len(b) for b in batches) == 7
