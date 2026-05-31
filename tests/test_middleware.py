from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodus_observability_framework import (
    PendingMetric,
    RequestMetricWriter,
    make_request_metrics_middleware,
)


def _make_app(writer: RequestMetricWriter, **kwargs) -> FastAPI:
    app = FastAPI()

    @app.get("/api/test")
    def _route():
        return {"ok": True}

    @app.get("/health")
    def _health():
        return {"status": "ok"}

    app.add_middleware(make_request_metrics_middleware(writer, **kwargs))
    return app


# ── Basic enqueue behaviour ───────────────────────────────────────────────────

def test_request_enqueues_metric():
    enqueued: list[PendingMetric] = []

    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = enqueued.append

    client = TestClient(_make_app(writer))
    resp = client.get("/api/test")
    assert resp.status_code == 200
    assert len(enqueued) == 1
    m = enqueued[0]
    assert m.method == "GET"
    assert m.path == "/api/test"
    assert m.status_code == 200
    assert m.duration_ms >= 0


def test_excluded_path_not_enqueued():
    enqueued: list = []

    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = enqueued.append

    client = TestClient(_make_app(writer))
    client.get("/health")
    assert len(enqueued) == 0


def test_custom_excluded_paths():
    enqueued: list = []

    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = enqueued.append

    app = FastAPI()

    @app.get("/internal")
    def _internal():
        return {}

    @app.get("/api/data")
    def _data():
        return {}

    app.add_middleware(
        make_request_metrics_middleware(
            writer, excluded_paths=frozenset({"/internal"})
        )
    )

    client = TestClient(app)
    client.get("/internal")
    assert len(enqueued) == 0

    client.get("/api/data")
    assert len(enqueued) == 1


# ── Callback injection ────────────────────────────────────────────────────────

def test_get_user_id_fn_called():
    enqueued: list[PendingMetric] = []

    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = enqueued.append

    def extract_user(request):
        return "user-42"

    app = _make_app(writer, get_user_id_fn=extract_user)
    TestClient(app).get("/api/test")

    assert enqueued[0].user_id == "user-42"


def test_get_trace_id_fn_called():
    enqueued: list[PendingMetric] = []

    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = enqueued.append

    def get_trace():
        return "trace-from-ctx"

    app = _make_app(writer, get_trace_id_fn=get_trace)
    TestClient(app).get("/api/test")

    assert enqueued[0].trace_id == "trace-from-ctx"


def test_enqueue_error_does_not_crash_request():
    writer = MagicMock(spec=RequestMetricWriter)
    writer.enqueue.side_effect = RuntimeError("queue failed")

    client = TestClient(_make_app(writer))
    resp = client.get("/api/test")
    assert resp.status_code == 200  # request still succeeds
