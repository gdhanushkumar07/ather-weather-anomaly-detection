"""
Observation stream between ingestion and detection.

InMemoryObservationStream is a bounded asyncio queue. It decouples source
adapters from the detector (a slow detector applies back-pressure instead of
losing data) and gives the consumer micro-batches, which the processor uses
to build a time-synchronous spatial snapshot for Layer 4.

Scale-out path: a RedisObservationStream (XADD / XREADGROUP with a consumer
group, XACK after persistence) implements the same three methods and gives
at-least-once delivery across processes; the processor is already
idempotent on observation_id, so redelivery is harmless. Kafka is the next
step only if a single consumer group can no longer keep up (see
docs/REALTIME_ARCHITECTURE.md for the numbers).
"""
import asyncio
import time
from typing import List, Optional

from .models import NormalizedObservation


class StreamFull(Exception):
    pass


class InMemoryObservationStream:
    def __init__(self, maxsize: int = 20000):
        self.maxsize = maxsize
        self._queue: Optional[asyncio.Queue] = None
        self.enqueued_total = 0
        self.dropped_total = 0

    def _q(self) -> asyncio.Queue:
        # Created lazily so it binds to the running event loop.
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.maxsize)
        return self._queue

    async def put(self, obs: NormalizedObservation) -> None:
        """Waits for room (back-pressure) — used by internal adapters."""
        obs.enqueued_at = time.monotonic()
        await self._q().put(obs)
        self.enqueued_total += 1

    def put_nowait(self, obs: NormalizedObservation) -> None:
        """Fails fast when full — used by the push API (caller gets a 503)."""
        obs.enqueued_at = time.monotonic()
        try:
            self._q().put_nowait(obs)
        except asyncio.QueueFull:
            self.dropped_total += 1
            raise StreamFull(f"observation stream is full ({self.maxsize})")
        self.enqueued_total += 1

    async def get_batch(self, max_items: int = 500, timeout: float = 1.0) -> List[NormalizedObservation]:
        """Blocks up to `timeout` for the first item, then drains whatever is
        already queued (up to max_items) without waiting further."""
        q = self._q()
        try:
            first = await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return []
        batch = [first]
        while len(batch) < max_items:
            try:
                batch.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    @property
    def depth(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    def stats(self) -> dict:
        return {
            "backend": "in-memory asyncio.Queue",
            "depth": self.depth,
            "capacity": self.maxsize,
            "enqueued_total": self.enqueued_total,
            "rejected_full_total": self.dropped_total,
        }
