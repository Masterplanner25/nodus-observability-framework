"""FastAPI instrumentation wiring — OTel spans + Prometheus metrics endpoint.

Usage::

    from fastapi import FastAPI
    from nodus_observability import create_registry
    from nodus_observability_framework import instrument_fastapi

    app = FastAPI()
    registry = create_registry()
    instrument_fastapi(app, registry=registry, service_name="my-service")
    # Now: all routes emit OTel spans; GET /metrics returns Prometheus data
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def instrument_fastapi(
    app: Any,
    *,
    registry: Any,
    service_name: str = "app",
    metrics_endpoint: str = "/metrics",
    excluded_paths: Optional[set[str]] = None,
    instrument_otel: bool = True,
    instrument_prometheus: bool = True,
) -> None:
    """Wire OTel spans and Prometheus metrics onto a FastAPI application.

    Both instrumentors are optional: gracefully skipped if the relevant
    packages are not installed.

    Args:
        app:                    FastAPI application instance.
        registry:               Prometheus ``CollectorRegistry``
                                (from ``nodus_observability.create_registry()``).
        service_name:           OTel service name (used for span attributes).
        metrics_endpoint:       URL path where Prometheus metrics are exposed
                                (default: ``"/metrics"``).
        excluded_paths:         URL paths excluded from OTel instrumentation.
        instrument_otel:        Set to False to skip OTel even if installed.
        instrument_prometheus:  Set to False to skip Prometheus even if installed.

    OTel instrumentation
    --------------------
    Uses ``opentelemetry-instrumentation-fastapi`` to create spans for every
    route.  Install with::

        pip install 'nodus-observability-framework[otel]'

    Prometheus instrumentation
    --------------------------
    Uses ``prometheus-fastapi-instrumentator`` to expose the custom registry
    at *metrics_endpoint* and add per-route ``http_request_duration_seconds``
    histograms.  Install with::

        pip install 'nodus-observability-framework[fastapi]'
    """
    _excluded = excluded_paths or set()

    if instrument_otel:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa

            excluded_str = ",".join(_excluded) if _excluded else None
            FastAPIInstrumentor.instrument_app(
                app,
                **({"excluded_urls": excluded_str} if excluded_str else {}),
            )
            logger.info(
                "[instrument_fastapi] OTel FastAPI instrumentation enabled (service=%s)",
                service_name,
            )
        except ImportError:
            logger.info(
                "[instrument_fastapi] opentelemetry-instrumentation-fastapi not installed "
                "— OTel span instrumentation skipped. "
                "Install with: pip install 'nodus-observability-framework[otel]'"
            )
        except Exception as exc:
            logger.warning("[instrument_fastapi] OTel instrumentation failed: %s", exc)

    if instrument_prometheus:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator  # noqa

            Instrumentator(registry=registry).instrument(app).expose(
                app,
                endpoint=metrics_endpoint,
                include_in_schema=False,
            )
            logger.info(
                "[instrument_fastapi] Prometheus metrics exposed at %s", metrics_endpoint
            )
        except ImportError:
            logger.info(
                "[instrument_fastapi] prometheus-fastapi-instrumentator not installed "
                "— /metrics endpoint skipped. "
                "Install with: pip install 'nodus-observability-framework[fastapi]'"
            )
        except Exception as exc:
            logger.warning(
                "[instrument_fastapi] Prometheus instrumentation failed: %s", exc
            )
