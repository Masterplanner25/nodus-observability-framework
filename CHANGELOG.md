# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-05-31

Initial release.

### Added

- **`init_observability(app, service_name, env, flush_fn?, get_trace_id_fn?,
  health_check_fns?)`** — single call that wires OTel, Prometheus, structured
  logging, request metric writing, and a health router together.
  Returns `ObservabilityContext` holding all components.

- **`ObservabilityContext`** — holds `metrics`, `writer`, `registry`, `tracer`.

- **`AIMetrics`** — pre-built AI metric set. Counters and histograms for:
  execution runs (total, duration, status), embedding calls, event handling,
  circuit breaker state gauge. `register_llm_provider(name)` adds retry and
  error counters for any LLM provider name.

- **`RequestMetricWriter`** — async batch writer that buffers `PendingMetric`
  records and flushes via a caller-provided `FlushFn`. Thread-safe.
  `write(metric)`, `flush()`, `start()` / `stop()`.

- **`make_request_metrics_middleware(writer, get_trace_id_fn?)`** — ASGI
  middleware factory. Records HTTP method, path, status, and duration for
  every request; injects trace ID from ContextVar.

- **`instrument_fastapi(app, registry, tracer?)`** — wires OTel FastAPI
  instrumentation and Prometheus FastAPI instrumentator onto a FastAPI app.

- **`make_health_router(health_check_fns?, prefix?)`** — FastAPI `APIRouter`
  with `GET /health` and `GET /ready`. Each registered check function is called;
  returns 200 if all pass, 503 if any fail.

- **`ExecutionBlock`** — typed real-time event from one execution run. Fields:
  `run_id`, `block_type`, `content`, `timestamp`, `metadata`.

- **`BlockStream`** — thread-safe broadcast stream for one run. `emit(block)`,
  `subscribe()` → iterator, `close()`.

- **`BlockStreamRegistry`** — process-level registry of active streams.
  `create(run_id)`, `get(run_id)`, `close(run_id)`.

- **`get_stream_registry()`** — module-level singleton `BlockStreamRegistry`.

- **`emit_block(run_id, block_type, content, metadata?)`** — convenience
  function to emit to a named stream in the singleton registry.

- **`CostTracker` / `CostAttribution` / `TokenUsage`** — token usage and cost
  attribution tracking per execution run.

- **57 tests** across 5 test files (health, metrics, middleware, stream, writer).

- **One required dependency:** `nodus-observability>=0.1.0`.
  Optional: `[fastapi]`, `[otel]`, `[metrics]`.

[0.1.0]: https://github.com/Masterplanner25/nodus-observability-framework/releases/tag/v0.1.0
