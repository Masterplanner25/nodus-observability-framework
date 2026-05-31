"""ExecutionBlock streaming — real-time typed execution event emission."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

BLOCK_TYPES = frozenset({
    "start", "text", "tool_use", "tool_result", "thinking", "error", "end"
})


@dataclass
class ExecutionBlock:
    type: str
    run_id: str
    content: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BlockStream:
    _SENTINEL = object()

    def __init__(self, run_id: str, buffer_size: int = 1000) -> None:
        self._run_id = run_id
        self._buffer_size = buffer_size
        self._blocks: list[ExecutionBlock] = []
        self._subscriber_queues: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def is_closed(self) -> bool:
        return self._closed

    def emit(self, block: ExecutionBlock) -> None:
        with self._lock:
            if self._closed:
                return
            if len(self._blocks) < self._buffer_size:
                self._blocks.append(block)
            for q in self._subscriber_queues:
                try:
                    q.put_nowait(block)
                except queue.Full:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for q in self._subscriber_queues:
                try:
                    q.put_nowait(self._SENTINEL)
                except queue.Full:
                    pass

    def subscribe(self) -> Iterator[ExecutionBlock]:
        q: queue.Queue = queue.Queue(maxsize=self._buffer_size)
        with self._lock:
            for block in self._blocks:
                try:
                    q.put_nowait(block)
                except queue.Full:
                    break
            if self._closed:
                try:
                    q.put_nowait(self._SENTINEL)
                except queue.Full:
                    pass
            else:
                self._subscriber_queues.append(q)
        try:
            while True:
                item = q.get()
                if item is self._SENTINEL:
                    break
                yield item
        finally:
            with self._lock:
                try:
                    self._subscriber_queues.remove(q)
                except ValueError:
                    pass


class BlockStreamRegistry:
    def __init__(self) -> None:
        self._streams: dict[str, BlockStream] = {}
        self._lock = threading.Lock()

    def create(self, run_id: str, *, buffer_size: int = 1000) -> BlockStream:
        stream = BlockStream(run_id, buffer_size=buffer_size)
        with self._lock:
            self._streams[run_id] = stream
        return stream

    def get(self, run_id: str) -> Optional[BlockStream]:
        with self._lock:
            return self._streams.get(run_id)

    def close(self, run_id: str) -> None:
        with self._lock:
            stream = self._streams.pop(run_id, None)
        if stream is not None:
            stream.close()

    def active_run_ids(self) -> list[str]:
        with self._lock:
            return list(self._streams.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._streams)


_REGISTRY: Optional[BlockStreamRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_stream_registry() -> BlockStreamRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = BlockStreamRegistry()
    return _REGISTRY


def emit_block(run_id: str, block_type: str, content: Any) -> bool:
    stream = get_stream_registry().get(run_id)
    if stream is None:
        return False
    block = ExecutionBlock(type=block_type, run_id=run_id, content=content)
    stream.emit(block)
    return True
