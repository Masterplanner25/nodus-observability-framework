"""FastAPI/Starlette request metrics middleware factory.

Extracted from AINDY/middleware.py log_requests() with the user_id extractor
and writer made pluggable.

Usage::

    from fastapi import FastAPI
    from nodus_observability_framework import (
        RequestMetricWriter, make_request_metrics_middleware,
    )

    writer = RequestMetricWriter(flush_fn=my_flush_fn)
    writer.start()

    app = FastAPI()
    app.add_middleware(
        make_request_metrics_middleware(writer),
    )
"""
from __future__ import annotations

import time
import logging
from typing import Any, Callable, Optional

from .writer import PendingMetric, RequestMetricWriter

logger = logging.getLogger(__name__)

_DEFAULT_EXCLUDED = frozenset({"/health", "/ready", "/metrics", "/healthz"})


def make_request_metrics_middleware(
    writer: RequestMetricWriter,
    *,
    get_user_id_fn: Optional[Callable[[Any], Any]] = None,
    excluded_paths: frozenset[str] = _DEFAULT_EXCLUDED,
    get_trace_id_fn: Optional[Callable[[], Optional[str]]] = None,
) -> type:
    """Return a Starlette ``BaseHTTPMiddleware`` class wired to *writer*.

    Register with FastAPI via::

        app.add_middleware(make_request_metrics_middleware(writer))

    Args:
        writer:           A started ``RequestMetricWriter``.
        get_user_id_fn:   Callable that receives the raw ``Request`` and returns
                          the user/tenant ID (or None).  Use this to extract a JWT
                          sub or API key identity.
        excluded_paths:   Paths that are not tracked (health, metrics, etc.).
        get_trace_id_fn:  Zero-argument callable that returns the current trace ID
                          (e.g. ``nodus_observability.get_trace_id``).
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
    except ImportError as exc:
        raise ImportError(
            "fastapi (starlette) is required for request metrics middleware. "
            "Install with: pip install 'nodus-observability-framework[fastapi]'"
        ) from exc

    _writer = writer
    _get_user_id = get_user_id_fn or (lambda _req: None)
    _get_trace_id = get_trace_id_fn or (lambda: None)
    _excluded = frozenset(excluded_paths)

    class _RequestMetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            if request.url.path in _excluded:
                return await call_next(request)

            t_start = time.monotonic()
            response = await call_next(request)
            duration_ms = (time.monotonic() - t_start) * 1000.0

            try:
                trace_id = _get_trace_id() or str(request.headers.get("x-trace-id") or "")
                user_id = _get_user_id(request)
                _writer.enqueue(
                    PendingMetric(
                        request_id=trace_id or str(id(request)),
                        trace_id=trace_id,
                        user_id=user_id,
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                    )
                )
            except Exception as exc:
                logger.debug("[RequestMetricsMiddleware] enqueue failed: %s", exc)

            return response

    return _RequestMetricsMiddleware
