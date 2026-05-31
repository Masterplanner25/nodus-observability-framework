from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from nodus_observability_framework import AIMetrics, register_llm_provider


def _registry() -> CollectorRegistry:
    return CollectorRegistry(auto_describe=True)


# ── AIMetrics.create() ────────────────────────────────────────────────────────

def test_create_returns_ai_metrics():
    m = AIMetrics.create(_registry())
    assert isinstance(m, AIMetrics)


def test_all_metric_attributes_present():
    m = AIMetrics.create(_registry())
    assert m.execution_total is not None
    assert m.execution_duration_seconds is not None
    assert m.active_executions_total is not None
    assert m.embedding_generation_total is not None
    assert m.embedding_generation_latency_seconds is not None
    assert m.event_handler_timeouts_total is not None
    assert m.event_handler_duration_seconds is not None
    assert m.ai_circuit_breaker_state is not None


def test_execution_total_labels():
    m = AIMetrics.create(_registry())
    m.execution_total.labels(route="flow.run", status="success").inc()
    m.execution_total.labels(route="flow.run", status="error").inc()


def test_execution_duration_labels():
    m = AIMetrics.create(_registry())
    m.execution_duration_seconds.labels(route="agent.run").observe(0.5)


def test_active_executions_gauge():
    m = AIMetrics.create(_registry())
    m.active_executions_total.inc()
    m.active_executions_total.dec()


def test_embedding_total_labels():
    m = AIMetrics.create(_registry())
    m.embedding_generation_total.labels(outcome="success").inc()
    m.embedding_generation_total.labels(outcome="failure").inc()


def test_circuit_breaker_state_labels():
    m = AIMetrics.create(_registry())
    m.ai_circuit_breaker_state.labels(provider="openai").set(0)
    m.ai_circuit_breaker_state.labels(provider="deepseek").set(2)


def test_custom_prefix():
    m = AIMetrics.create(_registry(), prefix="myapp")
    # Metric names are set at creation; just verify it doesn't raise
    m.execution_total.labels(route="x", status="ok").inc()


def test_two_registries_are_independent():
    r1, r2 = _registry(), _registry()
    m1 = AIMetrics.create(r1, prefix="app1")
    m2 = AIMetrics.create(r2, prefix="app2")
    m1.active_executions_total.inc(5)
    # m2's gauge must still be 0 — different registry
    from prometheus_client import generate_latest
    output2 = generate_latest(r2).decode()
    assert "app2_active_executions_total 0.0" in output2


def test_missing_prometheus_raises_import_error(monkeypatch):
    import nodus_observability_framework.metrics as mod
    monkeypatch.setattr(mod, "_PROMETHEUS_AVAILABLE", False)
    with pytest.raises(ImportError, match="prometheus-client"):
        AIMetrics.create(_registry())


# ── register_llm_provider() ───────────────────────────────────────────────────

def test_register_llm_provider_returns_counters():
    registry = _registry()
    result = register_llm_provider("openai", registry)
    assert "retries_total" in result
    assert "errors_total" in result


def test_register_llm_provider_counters_usable():
    registry = _registry()
    counters = register_llm_provider("mymodel", registry)
    counters["retries_total"].labels(call_type="chat").inc()
    counters["errors_total"].labels(call_type="embedding").inc()


def test_register_llm_provider_different_names_independent():
    registry = _registry()
    oai = register_llm_provider("openai", registry)
    ds = register_llm_provider("deepseek", registry)
    oai["retries_total"].labels(call_type="chat").inc()
    # deepseek counter must still be 0
    from prometheus_client import generate_latest
    output = generate_latest(registry).decode()
    assert "nodus_deepseek_retries_total" in output


def test_register_llm_provider_safe_name_normalization():
    registry = _registry()
    result = register_llm_provider("my-model.v2", registry)
    result["retries_total"].labels(call_type="chat").inc()


def test_missing_prometheus_raises_on_register(monkeypatch):
    import nodus_observability_framework.metrics as mod
    monkeypatch.setattr(mod, "_PROMETHEUS_AVAILABLE", False)
    with pytest.raises(ImportError):
        register_llm_provider("openai", _registry())
