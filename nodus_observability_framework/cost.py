"""CostTracker — per-run LLM token usage and cost attribution."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TokenUsage:
    """Token counts for one LLM call.

    Attributes
    ----------
    input_tokens:       Tokens in the prompt.
    output_tokens:      Tokens in the completion.
    cache_read_tokens:  Tokens served from prompt cache.
    cache_write_tokens: Tokens written to prompt cache.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass
class CostAttribution:
    """One LLM call's token usage and optional cost attribution.

    Attributes
    ----------
    run_id:    Execution run this attribution belongs to.
    model:     Model name (e.g. ``"claude-opus-4-6"``).
    provider:  Provider name (e.g. ``"anthropic"``).
    usage:     Token counts for this call.
    cost_usd:  Estimated USD cost (None when pricing not available).
    timestamp: UTC timestamp of the call.
    """

    run_id: str
    model: str
    provider: str
    usage: TokenUsage
    cost_usd: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CostTracker:
    """Aggregate per-run LLM usage and cost attributions.

    Usage::

        tracker = CostTracker()
        tracker.record(CostAttribution(
            run_id="run-1",
            model="claude-opus-4-6",
            provider="anthropic",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            cost_usd=0.0045,
        ))
        total = tracker.total_for_run("run-1")
        print(total.usage.total_tokens)  # 150
    """

    def __init__(self) -> None:
        self._attributions: list[CostAttribution] = []
        self._lock = threading.Lock()

    def record(self, attribution: CostAttribution) -> None:
        with self._lock:
            self._attributions.append(attribution)

    def total_for_run(self, run_id: str) -> CostAttribution:
        """Return aggregated attribution for *run_id*.

        Returns a zero-usage attribution when no records exist for the run.
        """
        with self._lock:
            records = [a for a in self._attributions if a.run_id == run_id]

        if not records:
            return CostAttribution(
                run_id=run_id, model="", provider="", usage=TokenUsage()
            )

        combined_usage = TokenUsage()
        total_cost: Optional[float] = None
        providers = set()
        models = set()

        for r in records:
            combined_usage = combined_usage + r.usage
            if r.cost_usd is not None:
                total_cost = (total_cost or 0.0) + r.cost_usd
            providers.add(r.provider)
            models.add(r.model)

        return CostAttribution(
            run_id=run_id,
            model=", ".join(sorted(models)),
            provider=", ".join(sorted(providers)),
            usage=combined_usage,
            cost_usd=total_cost,
        )

    def list_for_run(self, run_id: str) -> list[CostAttribution]:
        with self._lock:
            return [a for a in self._attributions if a.run_id == run_id]

    def snapshot(self) -> dict:
        """Return a summary snapshot."""
        with self._lock:
            total_calls = len(self._attributions)
            total_tokens = sum(a.usage.total_tokens for a in self._attributions)
            total_cost = sum(
                a.cost_usd for a in self._attributions if a.cost_usd is not None
            )
        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._attributions)
