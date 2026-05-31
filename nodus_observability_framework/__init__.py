"""nodus-observability-framework — single-install observability for AI systems.

Builds on ``nodus-observability`` (OTel bootstrap, Prometheus registry helper,
structured logging, trace ContextVars) and adds the opinionated wiring layer:

Metrics:
    AIMetrics                    — pre-built AI metric set (execution, embedding,
                                   event handling, circuit breaker state)
    register_llm_provider()      — create retry/error counters for any LLM provider

Request metric writer:
    PendingMetric                — HTTP request metric dataclass
    FlushFn                      — type alias for the flush callback
    RequestMetricWriter          — async batch writer; persistence via flush_fn

FastAPI integration:
    make_request_metrics_middleware()  — ASGI middleware factory
    instrument_fastapi()               — OTel + Prometheus wiring
    make_health_router()               — /health + /ready with extensible checks

Execution block streaming:
    ExecutionBlock               — typed real-time event from one execution run
    BlockStream                  — thread-safe broadcast stream for one run
    BlockStreamRegistry          — process-level registry of active streams
    get_stream_registry()        — module-level singleton registry
    emit_block()                 — convenience: emit to a named stream

Bootstrap:
    init_observability()         — single call that wires everything together
    ObservabilityContext         — returned context holding all components
"""
from .bootstrap import ObservabilityContext, init_observability
from .cost import CostAttribution, CostTracker, TokenUsage
from .fastapi import instrument_fastapi
from .health import make_health_router
from .metrics import AIMetrics, register_llm_provider
from .middleware import make_request_metrics_middleware
from .stream import (
    BlockStream,
    BlockStreamRegistry,
    ExecutionBlock,
    emit_block,
    get_stream_registry,
)
from .writer import FlushFn, PendingMetric, RequestMetricWriter

__all__ = [
    # Bootstrap
    "init_observability",
    "ObservabilityContext",
    # Metrics
    "AIMetrics",
    "register_llm_provider",
    # Writer
    "PendingMetric",
    "FlushFn",
    "RequestMetricWriter",
    # FastAPI
    "make_request_metrics_middleware",
    "instrument_fastapi",
    "make_health_router",
    # Streaming
    "ExecutionBlock",
    "BlockStream",
    "BlockStreamRegistry",
    "get_stream_registry",
    "emit_block",
    # Cost tracking
    "TokenUsage",
    "CostAttribution",
    "CostTracker",
]
