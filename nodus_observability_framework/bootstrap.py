"""Single-call observability bootstrap.

Usage::

    from fastapi import FastAPI
    from nodus_observability_framework import init_observability

    app = FastAPI()
    ctx = init_observability(
        app,
        service_name="my-ai-service",
        env="production",
        flush_fn=my_db_flush,
        get_trace_id_fn=get_trace_id,
        health_check_fns={"db": db_ping, "redis": redis_ping},
    )
    # ctx.registry   → Prometheus CollectorRegistry
    # ctx.metrics    → AIMetrics with pre-built metric set
    # ctx.writer     → RequestMetricWriter (already started)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .metrics import AIMetrics
from .stream import BlockStreamRegistry, get_stream_registry
from .writer import FlushFn, PendingMetric, RequestMetricWriter  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)


@dataclass
class ObservabilityContext:
    """Returned by ``init_observability()``.  Holds all initialized components.

    Attributes
    ----------
    registry:        Prometheus ``CollectorRegistry``.  None if prometheus-client
                     is not installed.
    metrics:         Pre-built ``AIMetrics`` set.  None if prometheus-client is absent.
    writer:          Started ``RequestMetricWriter``.  None if no *flush_fn* was provided.
    service_name:    The service name used for OTel + logging.
    stream_registry: :class:`BlockStreamRegistry` for real-time execution block streaming.
                     Always present (defaults to the module-level singleton).
    """

    registry: Any  # CollectorRegistry | None
    metrics: Optional[AIMetrics]
    writer: Optional[RequestMetricWriter]
    service_name: str
    stream_registry: BlockStreamRegistry = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.stream_registry is None:
            self.stream_registry = get_stream_registry()


def init_observability(
    app: Any = None,
    *,
    service_name: str = "app",
    env: str = "development",
    log_level: str = "INFO",
    flush_fn: Optional[FlushFn] = None,
    get_user_id_fn: Optional[Callable[[Any], Any]] = None,
    get_trace_id_fn: Optional[Callable[[], Optional[str]]] = None,
    excluded_paths: Optional[set[str]] = None,
    health_check_fns: Optional[dict[str, Callable[[], bool]]] = None,
    include_health_router: bool = True,
    metrics_prefix: str = "nodus",
    writer_queue_size: int = 10_000,
    writer_batch_size: int = 200,
    writer_flush_interval_seconds: float = 5.0,
    stream_registry: Optional[BlockStreamRegistry] = None,
) -> ObservabilityContext:
    """Bootstrap the full observability stack in a single call.

    Execution order
    ---------------
    1. ``init_otel(service_name)``             — OTel TracerProvider (noop without endpoint)
    2. ``configure_logging(env, ...)``          — structured JSON logging
    3. ``create_registry()``                    — Prometheus CollectorRegistry
    4. ``AIMetrics.create(registry, ...)``      — pre-built AI metric set
    5. If *app* provided:
       a. ``instrument_fastapi(app, ...)``      — OTel + Prometheus wiring
       b. ``app.add_middleware(...)``           — request metrics middleware
       c. ``app.include_router(...)``           — health router (if enabled)
    6. If *flush_fn* provided:
       ``RequestMetricWriter(flush_fn).start()``

    Noop fallbacks
    --------------
    - OTel: no-op if ``opentelemetry`` packages are absent or OTLP endpoint unset
    - Prometheus: metrics is None in returned context if ``prometheus-client`` absent
    - RequestMetricWriter: writer is None if no flush_fn provided
    - Middleware/health router: skipped if ``fastapi`` absent or app is None

    Args:
        app:                      Optional FastAPI instance.
        service_name:             OTel service name + log context label.
        env:                      Deployment environment (``"development"``, ``"production"``).
        log_level:                Root log level string.
        flush_fn:                 Callback ``fn(batch: list[PendingMetric]) -> None``
                                  for persisting request metrics.  Pass None to disable.
        get_user_id_fn:           Extract user_id from ``Request``; passed to middleware.
        get_trace_id_fn:          Zero-arg callable returning current trace ID.
        excluded_paths:           URL paths excluded from middleware + OTel spans.
        health_check_fns:         Component health checks for ``/health`` endpoint.
        include_health_router:    Whether to mount ``/health`` and ``/ready`` on *app*.
        metrics_prefix:           Prefix for all ``AIMetrics`` metric names.
        writer_queue_size:        ``RequestMetricWriter`` queue capacity.
        writer_batch_size:        ``RequestMetricWriter`` flush batch size.
        writer_flush_interval_seconds: ``RequestMetricWriter`` flush cadence.
        stream_registry:          Optional :class:`BlockStreamRegistry` to use for
                                  execution block streaming.  Defaults to the
                                  module-level singleton from ``get_stream_registry()``.

    Returns:
        ``ObservabilityContext`` with all initialized components.
    """
    # ── Step 1: OTel ──────────────────────────────────────────────────────────
    try:
        from nodus_observability import init_otel
        init_otel(service_name=service_name)
    except Exception as exc:
        logger.debug("[init_observability] OTel init skipped: %s", exc)

    # ── Step 2: Structured logging ────────────────────────────────────────────
    try:
        from nodus_observability import configure_logging
        configure_logging(
            env=env,
            log_level=log_level,
            get_trace_id_fn=get_trace_id_fn,
        )
    except Exception as exc:
        logger.debug("[init_observability] Logging config skipped: %s", exc)

    # ── Step 3: Prometheus registry ───────────────────────────────────────────
    registry = None
    try:
        from nodus_observability import create_registry
        registry = create_registry()
    except Exception as exc:
        logger.debug("[init_observability] Prometheus registry skipped: %s", exc)

    # ── Step 4: AI metrics ────────────────────────────────────────────────────
    metrics: Optional[AIMetrics] = None
    if registry is not None:
        try:
            metrics = AIMetrics.create(registry, prefix=metrics_prefix)
        except Exception as exc:
            logger.debug("[init_observability] AIMetrics creation skipped: %s", exc)

    # ── Step 5: RequestMetricWriter ───────────────────────────────────────────
    writer: Optional[RequestMetricWriter] = None
    if flush_fn is not None:
        drop_counter = None
        if metrics is not None:
            try:
                from nodus_observability import create_registry as _cr  # noqa
                _drops = metrics  # just a reference check
                # If metrics has a drops counter we could wire it; for now noop
            except Exception:
                pass
        writer = RequestMetricWriter(
            flush_fn,
            queue_size=writer_queue_size,
            batch_size=writer_batch_size,
            flush_interval_seconds=writer_flush_interval_seconds,
        )
        writer.start()

    # ── Step 6: FastAPI wiring ────────────────────────────────────────────────
    if app is not None:
        _excluded = excluded_paths or {"/health", "/ready", "/metrics"}

        # 6a: OTel + Prometheus instrumentation
        if registry is not None:
            try:
                from .fastapi import instrument_fastapi
                instrument_fastapi(
                    app,
                    registry=registry,
                    service_name=service_name,
                    excluded_paths=_excluded,
                )
            except Exception as exc:
                logger.debug("[init_observability] instrument_fastapi skipped: %s", exc)

        # 6b: Request metrics middleware
        if writer is not None:
            try:
                from .middleware import make_request_metrics_middleware
                app.add_middleware(
                    make_request_metrics_middleware(
                        writer,
                        get_user_id_fn=get_user_id_fn,
                        excluded_paths=frozenset(_excluded),
                        get_trace_id_fn=get_trace_id_fn,
                    )
                )
            except Exception as exc:
                logger.debug("[init_observability] request metrics middleware skipped: %s", exc)

        # 6c: Health router
        if include_health_router:
            try:
                from .health import make_health_router
                app.include_router(make_health_router(check_fns=health_check_fns))
            except Exception as exc:
                logger.debug("[init_observability] health router skipped: %s", exc)

    return ObservabilityContext(
        registry=registry,
        metrics=metrics,
        writer=writer,
        service_name=service_name,
        stream_registry=stream_registry if stream_registry is not None else get_stream_registry(),
    )
