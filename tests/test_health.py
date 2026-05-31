from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodus_observability_framework import make_health_router


def _make_app(**kwargs) -> FastAPI:
    app = FastAPI()
    app.include_router(make_health_router(**kwargs))
    return app


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_200_no_checks():
    client = TestClient(_make_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_health_returns_200_all_checks_pass():
    client = TestClient(_make_app(check_fns={"db": lambda: True, "cache": lambda: True}))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["checks"]["db"] is True
    assert body["checks"]["cache"] is True


def test_health_returns_503_when_check_fails():
    client = TestClient(
        _make_app(check_fns={"db": lambda: True, "redis": lambda: False}),
        raise_server_exceptions=False,
    )
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"
    assert resp.json()["checks"]["redis"] is False


def test_health_treats_exception_as_unhealthy():
    def bad_check():
        raise RuntimeError("connection refused")

    client = TestClient(
        _make_app(check_fns={"service": bad_check}),
        raise_server_exceptions=False,
    )
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"]["service"] is False


def test_health_includes_version():
    client = TestClient(_make_app(version="2.3.1"))
    resp = client.get("/health")
    assert resp.json()["version"] == "2.3.1"


# ── /ready ────────────────────────────────────────────────────────────────────

def test_ready_returns_200_no_checks():
    client = TestClient(_make_app())
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_ready_returns_503_when_check_fns_fail():
    client = TestClient(
        _make_app(check_fns={"db": lambda: False}),
        raise_server_exceptions=False,
    )
    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_uses_dedicated_ready_check_fn():
    client = TestClient(
        _make_app(
            check_fns={"db": lambda: True},      # health passes
            ready_check_fn=lambda: False,          # but NOT ready
        ),
        raise_server_exceptions=False,
    )
    resp = client.get("/health")
    assert resp.status_code == 200  # health is OK

    resp = client.get("/ready")
    assert resp.status_code == 503  # but not ready


def test_ready_fn_exception_returns_503():
    def bad():
        raise RuntimeError("not initialized")

    client = TestClient(
        _make_app(ready_check_fn=bad),
        raise_server_exceptions=False,
    )
    resp = client.get("/ready")
    assert resp.status_code == 503
