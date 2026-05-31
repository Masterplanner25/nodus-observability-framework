"""Lightweight health and readiness router for FastAPI.

Extracted from AINDY/routes/health_router.py — the minimal universal subset:
/health (liveness) and /ready (readiness) with extensible check hooks.

Usage::

    from fastapi import FastAPI
    from nodus_observability_framework import make_health_router

    app = FastAPI()
    app.include_router(
        make_health_router(
            version="1.0.0",
            check_fns={
                "database": lambda: db.ping(),
                "redis": lambda: redis.ping(),
            },
        )
    )
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


def make_health_router(
    *,
    version: str = "unknown",
    check_fns: Optional[dict[str, Callable[[], bool]]] = None,
    ready_check_fn: Optional[Callable[[], bool]] = None,
    prefix: str = "",
) -> "APIRouter":
    """Return a FastAPI ``APIRouter`` with ``/health`` and ``/ready`` endpoints.

    Args:
        version:        Application version string included in responses.
        check_fns:      Mapping of ``component_name → health_check``.  Each
                        callable must return ``True`` (healthy) or ``False``
                        (unhealthy).  Exceptions are caught and treated as unhealthy.
        ready_check_fn: Optional single check for the ``/ready`` endpoint.
                        When None, readiness is inferred from ``check_fns``.
        prefix:         Router prefix (default: ``""`` — mounts at root).

    Endpoint behaviour
    ------------------
    ``GET /health``  — Returns 200 with ``{"status": "healthy"}`` when all
                       checks pass; 503 with ``{"status": "unhealthy"}`` otherwise.

    ``GET /ready``   — Returns 200 when ready; 503 when not ready.

    Response body::

        {
            "status": "healthy" | "unhealthy",
            "version": "1.0.0",
            "checks": {"database": true, "redis": false}
        }
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "fastapi is required for make_health_router(). "
            "Install with: pip install 'nodus-observability-framework[fastapi]'"
        )

    _checks = dict(check_fns or {})
    _ready_fn = ready_check_fn
    router = APIRouter(prefix=prefix)

    def _run_checks() -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, fn in _checks.items():
            try:
                results[name] = bool(fn())
            except Exception:
                results[name] = False
        return results

    @router.get("/health")
    def health() -> JSONResponse:
        checks = _run_checks()
        healthy = all(checks.values()) if checks else True
        status_code = 200 if healthy else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if healthy else "unhealthy",
                "version": version,
                "checks": checks,
            },
        )

    @router.get("/ready")
    def ready() -> JSONResponse:
        if _ready_fn is not None:
            try:
                is_ready = bool(_ready_fn())
            except Exception:
                is_ready = False
        elif _checks:
            results = _run_checks()
            is_ready = all(results.values())
        else:
            is_ready = True

        status_code = 200 if is_ready else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ready" if is_ready else "not_ready", "version": version},
        )

    return router
