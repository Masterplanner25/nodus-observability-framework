"""Tests for ExecutionBlock streaming and CostTracker."""
import threading, time
import pytest
from nodus_observability_framework import (
    BlockStream, BlockStreamRegistry, CostAttribution, CostTracker,
    ExecutionBlock, TokenUsage, emit_block, get_stream_registry,
)

def test_execution_block_fields():
    b = ExecutionBlock(type="text", run_id="run-1", content={"text": "hello"})
    assert b.type == "text" and b.run_id == "run-1"
    assert b.content["text"] == "hello"

def test_stream_emit_and_subscribe():
    stream = BlockStream("run-1"); received = []
    def sub():
        for block in stream.subscribe(): received.append(block)
    t = threading.Thread(target=sub, daemon=True); t.start(); time.sleep(0.02)
    stream.emit(ExecutionBlock("text", "run-1", {}))
    stream.emit(ExecutionBlock("end",  "run-1", {}))
    stream.close(); t.join(timeout=2)
    assert len(received) == 2

def test_stream_replays_to_late_subscriber():
    stream = BlockStream("run-2")
    stream.emit(ExecutionBlock("start", "run-2", {}))
    stream.emit(ExecutionBlock("text",  "run-2", {}))
    stream.close()
    assert len(list(stream.subscribe())) == 2

def test_stream_closed_after_close():
    s = BlockStream("r"); s.close()
    assert s.is_closed is True

def test_registry_create_and_get():
    reg = BlockStreamRegistry()
    s = reg.create("run-1")
    assert reg.get("run-1") is s

def test_registry_close_removes():
    reg = BlockStreamRegistry()
    reg.create("r"); reg.close("r")
    assert reg.get("r") is None

def test_registry_len():
    reg = BlockStreamRegistry()
    assert len(reg) == 0
    reg.create("a"); assert len(reg) == 1

def test_emit_block_no_stream():
    assert emit_block("no-such-run", "text", {}) is False

def test_emit_block_delivers():
    reg = get_stream_registry()
    reg.create("emit-test")
    assert emit_block("emit-test", "text", {"t": "hi"}) is True
    reg.close("emit-test")

def test_token_usage_total():
    u = TokenUsage(input_tokens=100, output_tokens=50)
    assert u.total_tokens == 150

def test_token_usage_addition():
    a = TokenUsage(10, 5); b = TokenUsage(20, 10)
    c = a + b
    assert c.input_tokens == 30 and c.output_tokens == 15

def _attr(run_id, input_t=100, output_t=50, cost=0.01):
    return CostAttribution(run_id=run_id, model="m", provider="p",
        usage=TokenUsage(input_t, output_t), cost_usd=cost)

def test_cost_tracker_total():
    t = CostTracker()
    t.record(_attr("r1", 100, 50, 0.01))
    t.record(_attr("r1", 200, 100, 0.02))
    total = t.total_for_run("r1")
    assert total.usage.input_tokens == 300
    assert abs(total.cost_usd - 0.03) < 0.0001

def test_cost_tracker_empty():
    t = CostTracker()
    total = t.total_for_run("x")
    assert total.usage.total_tokens == 0 and total.cost_usd is None

def test_cost_tracker_snapshot():
    t = CostTracker()
    t.record(_attr("r1", cost=0.01)); t.record(_attr("r2", cost=0.02))
    snap = t.snapshot()
    assert snap["total_calls"] == 2
    assert abs(snap["total_cost_usd"] - 0.03) < 0.0001