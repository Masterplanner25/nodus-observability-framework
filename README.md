# nodus-observability-framework

Single-install observability for AI systems. Wires OTel distributed tracing, Prometheus metrics, structured JSON logging, per-request metric writing, and a health router together with intelligent noop fallbacks — all from a single `init_observability()` call.

Builds on `nodus-observability` (the low-level library).

## Install

```bash
pip install nodus-observability-framework                    # core only
pip install "nodus-observability-framework[metrics]"         # + prometheus-client
pip install "nodus-observability-framework[fastapi]"         # + fastapi + pfi
pip install "nodus-observability-framework[otel]"            # + opentelemetry stack
pip install "nodus-observability-framework[all]"             # everything
```

## Quickstart — single call

```python
from fastapi import FastAPI
from nodus_observability_framework import init_observability

app = FastAPI()

ctx = init_observability(
    app,
    service_name="my-ai-service",
    env="production",
    flush_fn=my_db_flush_fn,         # persist request metrics
    get_trace_id_fn=get_trace_id,    # from nodus_observability
    health_check_fns={
        "database": lambda: db.ping(),
        "redis": lambda: redis.ping(),
    },
)
# ctx.registry  → Prometheus CollectorRegistry
# ctx.metrics   → AIMetrics with pre-built metric set
# ctx.writer    → RequestMetricWriter (already started)
```

## AIMetrics

```python
from nodus_observability import create_registry
from nodus_observability_framework import AIMetrics, register_llm_provider

registry = create_registry()
metrics = AIMetrics.create(registry, prefix="myapp")

# Record execution outcome
metrics.execution_total.labels(route="flow.run", status="success").inc()
with metrics.execution_duration_seconds.labels(route="flow.run").time():
    run_my_flow()

# Wire circuit breaker (nodus-circuit-breaker on_state_change hook)
def cb_hook(name, prev, new):
    value = {"closed": 0, "half_open": 1, "open": 2}.get(new, -1)
    metrics.ai_circuit_breaker_state.labels(provider=name).set(value)

# Register an LLM provider
openai = register_llm_provider("openai", registry)
openai["retries_total"].labels(call_type="chat").inc()
```

## RequestMetricWriter

```python
from nodus_observability_framework import RequestMetricWriter, PendingMetric

def flush_to_db(batch: list[PendingMetric]) -> None:
    # Your persistence code here — SQL, HTTP, file, etc.
    for m in batch:
        db.insert(method=m.method, path=m.path, status=m.status_code, ...)

writer = RequestMetricWriter(flush_fn=flush_to_db)
writer.start()
writer.enqueue(PendingMetric("req-1", "trace-1", "user-42", "GET", "/api", 200, 12.5))
writer.stop()
```

## Health router

```python
from fastapi import FastAPI
from nodus_observability_framework import make_health_router

app = FastAPI()
app.include_router(make_health_router(
    version="1.0.0",
    check_fns={"db": db_ping, "redis": redis_ping},
))
# GET /health → 200 {"status": "healthy", "checks": {"db": true, "redis": true}}
# GET /ready  → 200 {"status": "ready"}
```

## FastAPI instrumentation

```python
from nodus_observability_framework import instrument_fastapi

instrument_fastapi(app, registry=registry, service_name="my-service")
# Now: OTel spans on all routes + GET /metrics → Prometheus data
```

## Extracted from

`AINDY/core/request_metric_writer.py`, `AINDY/platform_layer/metrics.py`, `AINDY/middleware.py`, and `AINDY/routes/health_router.py` in the A.I.N.D.Y. runtime.
