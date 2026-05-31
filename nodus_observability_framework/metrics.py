"""AIMetrics — pre-built universal AI system metric set.

Extracted from A.I.N.D.Y.'s metrics.py (9 of 41 metric families that are
universally applicable to any AI system, as opposed to AINDY-specific).

All metrics use a caller-provided CollectorRegistry — never the default
global registry.  This prevents metric name conflicts across libraries and
test runs.

Usage::

    from nodus_observability import create_registry
    from nodus_observability_framework import AIMetrics, register_llm_provider

    registry = create_registry()
    metrics = AIMetrics.create(registry, prefix="myapp")

    # Record an execution
    metrics.execution_total.labels(route="flow.run", status="success").inc()

    # Wire circuit breaker (nodus-circuit-breaker on_state_change hook)
    def cb_hook(name, prev, new):
        value = {"closed": 0, "half_open": 1, "open": 2}.get(new, -1)
        metrics.ai_circuit_breaker_state.labels(provider=name).set(value)

    # Register an LLM provider
    openai = register_llm_provider("openai", registry)
    openai["retries_total"].labels(call_type="chat").inc()
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    CollectorRegistry = None  # type: ignore[assignment,misc]
    Counter = None  # type: ignore[assignment,misc]
    Gauge = None  # type: ignore[assignment,misc]
    Histogram = None  # type: ignore[assignment,misc]
    _PROMETHEUS_AVAILABLE = False

# Bucket presets mirror A.I.N.D.Y. values
_EXECUTION_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
_EMBEDDING_BUCKETS = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0]
_EVENT_HANDLER_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]


@dataclass(frozen=True)
class AIMetrics:
    """Pre-instantiated universal AI system metric set.

    All metrics are registered to a caller-provided ``CollectorRegistry``.
    Create via ``AIMetrics.create(registry, prefix=...)``.

    Metrics
    -------
    Execution pipeline:
        execution_total [route, status]        — outcome counter
        execution_duration_seconds [route]     — latency histogram
        active_executions_total                — concurrency gauge

    Embedding / generation:
        embedding_generation_total [outcome]   — success/failure counter
        embedding_generation_latency_seconds   — latency histogram

    Event handling:
        event_handler_timeouts_total [event_type]              — timeout counter
        event_handler_duration_seconds [event_type, result]    — latency histogram

    Circuit breaker (wire via nodus-circuit-breaker on_state_change):
        ai_circuit_breaker_state [provider]    — 0=closed 1=half_open 2=open
    """

    execution_total: "Counter"
    execution_duration_seconds: "Histogram"
    active_executions_total: "Gauge"
    embedding_generation_total: "Counter"
    embedding_generation_latency_seconds: "Histogram"
    event_handler_timeouts_total: "Counter"
    event_handler_duration_seconds: "Histogram"
    ai_circuit_breaker_state: "Gauge"

    @classmethod
    def create(
        cls,
        registry: "CollectorRegistry",
        *,
        prefix: str = "nodus",
    ) -> "AIMetrics":
        """Instantiate all metrics registered to *registry*.

        Args:
            registry: A ``CollectorRegistry`` (from ``nodus_observability.create_registry()``
                or ``prometheus_client.CollectorRegistry()``).
            prefix:   Metric name prefix (default: ``"nodus"``).

        Raises:
            ImportError: If ``prometheus-client`` is not installed.
        """
        if not _PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus-client is required for AIMetrics. "
                "Install with: pip install 'nodus-observability-framework[metrics]'"
            )
        p = prefix.rstrip("_")
        return cls(
            execution_total=Counter(
                f"{p}_execution_total",
                "Total executions by route and outcome",
                ["route", "status"],
                registry=registry,
            ),
            execution_duration_seconds=Histogram(
                f"{p}_execution_duration_seconds",
                "Execution handler duration in seconds",
                ["route"],
                buckets=_EXECUTION_BUCKETS,
                registry=registry,
            ),
            active_executions_total=Gauge(
                f"{p}_active_executions_total",
                "Active executions across all tenants (in-memory counter)",
                registry=registry,
            ),
            embedding_generation_total=Counter(
                f"{p}_embedding_generation_total",
                "Total embedding generation attempts",
                ["outcome"],  # success | failure
                registry=registry,
            ),
            embedding_generation_latency_seconds=Histogram(
                f"{p}_embedding_generation_latency_seconds",
                "Embedding generation latency in seconds",
                buckets=_EMBEDDING_BUCKETS,
                registry=registry,
            ),
            event_handler_timeouts_total=Counter(
                f"{p}_event_handler_timeouts_total",
                "Total event handler timeouts",
                ["event_type"],
                registry=registry,
            ),
            event_handler_duration_seconds=Histogram(
                f"{p}_event_handler_duration_seconds",
                "Event handler execution duration in seconds",
                ["event_type", "result"],
                buckets=_EVENT_HANDLER_BUCKETS,
                registry=registry,
            ),
            ai_circuit_breaker_state=Gauge(
                f"{p}_ai_circuit_breaker_state",
                "AI provider circuit breaker state (0=closed, 1=half_open, 2=open)",
                ["provider"],
                registry=registry,
            ),
        )


def register_llm_provider(
    name: str,
    registry: "CollectorRegistry",
    *,
    call_types: list[str] | None = None,
    prefix: str = "nodus",
) -> dict[str, "Counter"]:
    """Create retry and error counters for an LLM provider.

    Registers ``{prefix}_{name}_retries_total`` and
    ``{prefix}_{name}_errors_total`` with label ``call_type``.

    Args:
        name:       Provider name (e.g. ``"openai"``, ``"deepseek"``).
        registry:   Prometheus CollectorRegistry.
        call_types: Label values for ``call_type`` (default: ``["chat", "embedding"]``).
        prefix:     Metric name prefix (default: ``"nodus"``).

    Returns:
        Dict with ``"retries_total"`` and ``"errors_total"`` Counter instances.

    Raises:
        ImportError: If ``prometheus-client`` is not installed.
    """
    if not _PROMETHEUS_AVAILABLE:
        raise ImportError(
            "prometheus-client is required. "
            "Install with: pip install 'nodus-observability-framework[metrics]'"
        )
    _ = call_types  # label values are informational only — Prometheus creates them on use
    p = prefix.rstrip("_")
    safe_name = name.lower().replace("-", "_").replace(".", "_")
    return {
        "retries_total": Counter(
            f"{p}_{safe_name}_retries_total",
            f"Total {name} API call retries",
            ["call_type"],
            registry=registry,
        ),
        "errors_total": Counter(
            f"{p}_{safe_name}_errors_total",
            f"Total {name} API call failures after all retries exhausted",
            ["call_type"],
            registry=registry,
        ),
    }
