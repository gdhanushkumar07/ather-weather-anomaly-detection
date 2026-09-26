"""
Pipeline metrics (spec §18): latency distributions and throughput.

    ingestion latency   = received_at - observed_at   (source + transport delay)
    queue wait          = dequeued - enqueued          (stream lag)
    processing latency  = engine + persistence time per observation
    end-to-end latency  = event published - observed_at
"""
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional


class LatencyWindow:
    def __init__(self, size: int = 2000):
        self._v: Deque[float] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, value_ms: float) -> None:
        with self._lock:
            self._v.append(value_ms)

    def snapshot(self) -> Dict[str, Optional[float]]:
        with self._lock:
            vals = sorted(self._v)
        if not vals:
            return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}

        def pct(p: float) -> float:
            return round(vals[min(len(vals) - 1, int(p * len(vals)))], 1)

        return {"count": len(vals), "p50_ms": pct(0.50), "p95_ms": pct(0.95), "max_ms": round(vals[-1], 1)}


class RateCounter:
    """Events per minute over a sliding 60 s window."""

    def __init__(self):
        self._t: Deque[float] = deque()
        self._lock = threading.Lock()
        self.total = 0

    def add(self, n: int = 1) -> None:
        now = time.monotonic()
        with self._lock:
            self.total += n
            for _ in range(n):
                self._t.append(now)
            self._trim(now)

    def _trim(self, now: float) -> None:
        while self._t and now - self._t[0] > 60.0:
            self._t.popleft()

    def per_minute(self) -> int:
        with self._lock:
            self._trim(time.monotonic())
            return len(self._t)


class PipelineMetrics:
    def __init__(self):
        self.ingestion_latency = LatencyWindow()
        self.queue_wait = LatencyWindow()
        self.processing = LatencyWindow()
        self.end_to_end = LatencyWindow()
        self.received = RateCounter()
        self.processed = RateCounter()
        self.duplicates = RateCounter()
        self.late = RateCounter()
        self.rejected = RateCounter()
        self.errors = RateCounter()
        self.anomalies = RateCounter()
        self.incidents_created = RateCounter()
        self.last_processed_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.started_at = time.time()

    def snapshot(self) -> Dict:
        return {
            "uptime_s": round(time.time() - self.started_at),
            "latency": {
                "ingestion": self.ingestion_latency.snapshot(),
                "queue_wait": self.queue_wait.snapshot(),
                "processing": self.processing.snapshot(),
                "end_to_end": self.end_to_end.snapshot(),
            },
            "throughput_per_min": {
                "received": self.received.per_minute(),
                "processed": self.processed.per_minute(),
                "anomalies": self.anomalies.per_minute(),
            },
            "totals": {
                "received": self.received.total,
                "processed": self.processed.total,
                "duplicates": self.duplicates.total,
                "late": self.late.total,
                "rejected": self.rejected.total,
                "errors": self.errors.total,
                "anomalies": self.anomalies.total,
                "incidents_created": self.incidents_created.total,
            },
            "last_processed_at": self.last_processed_at,
            "last_error": self.last_error,
        }
