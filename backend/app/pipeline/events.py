"""
EventBroker — in-process publish/subscribe feeding the SSE endpoint.

- Every event gets a monotonically increasing id. The dashboard's initial
  snapshot (/api/network/state) returns the current id, and the SSE client
  subscribes "since" that id, so no event between snapshot and subscribe is
  lost. Reconnecting clients send Last-Event-ID and get the gap replayed
  from a ring buffer.
- publish() is thread-safe: the detector runs on a worker thread and API
  handlers run on the threadpool, but asyncio queues are only touched on
  the event loop thread.
- A slow client never blocks the pipeline: its bounded queue drops the
  oldest events and it receives RESYNC_REQUIRED, telling it to refetch the
  snapshot instead of silently showing stale state.
"""
import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

# Event types (spec §17), plus a few operational ones.
STATION_UPDATED = "STATION_UPDATED"
ANOMALY_DETECTED = "ANOMALY_DETECTED"
STATION_RECOVERED = "STATION_RECOVERED"
WEATHER_EVENT_DETECTED = "WEATHER_EVENT_DETECTED"
STATION_STALE = "STATION_STALE"
INCIDENT_CREATED = "INCIDENT_CREATED"
INCIDENT_UPDATED = "INCIDENT_UPDATED"
DATA_SOURCE_STATUS_CHANGED = "DATA_SOURCE_STATUS_CHANGED"
SYSTEM_METRICS = "SYSTEM_METRICS"
FAULT_INJECTED = "FAULT_INJECTED"
FAULT_CLEARED = "FAULT_CLEARED"
REPLAY_STEP = "REPLAY_STEP"
REPLAY_COMPLETED = "REPLAY_COMPLETED"
PROCESSING_ERROR = "PROCESSING_ERROR"
RESYNC_REQUIRED = "RESYNC_REQUIRED"


@dataclass
class Event:
    id: int
    type: str
    ts: float
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type, "ts": self.ts, "data": self.data}


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue
    types: Optional[Set[str]] = None
    dropped: int = 0
    connected_at: float = field(default_factory=time.time)

    def wants(self, ev: Event) -> bool:
        return self.types is None or ev.type in self.types or ev.type == RESYNC_REQUIRED


class EventBroker:
    def __init__(self, history_size: int = 2000, subscriber_queue_size: int = 1000):
        self._lock = threading.Lock()
        self._seq = 0
        self._history: Deque[Event] = deque(maxlen=history_size)
        self._subs: List[Subscription] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[int] = None
        self.subscriber_queue_size = subscriber_queue_size
        self.published_total = 0

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._loop_thread = threading.get_ident()

    @property
    def last_event_id(self) -> int:
        return self._seq

    def publish(self, type_: str, data: Dict[str, Any]) -> Event:
        with self._lock:
            self._seq += 1
            ev = Event(self._seq, type_, time.time(), data)
            self._history.append(ev)
            self.published_total += 1
        loop = self._loop
        if loop is not None and loop.is_running() and threading.get_ident() != self._loop_thread:
            try:
                loop.call_soon_threadsafe(self._deliver, ev)
            except RuntimeError:
                pass  # loop closed during shutdown
        else:
            self._deliver(ev)
        return ev

    def _deliver(self, ev: Event) -> None:
        for sub in list(self._subs):
            if not sub.wants(ev):
                continue
            self._offer(sub, ev)

    def _offer(self, sub: Subscription, ev: Event) -> None:
        try:
            sub.queue.put_nowait(ev)
        except asyncio.QueueFull:
            # Drop the oldest queued events and tell the client to resync.
            sub.dropped += 1
            for _ in range(max(1, sub.queue.maxsize // 10)):
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            resync = Event(ev.id, RESYNC_REQUIRED, time.time(), {"reason": "client too slow; events dropped"})
            try:
                sub.queue.put_nowait(resync)
            except asyncio.QueueFull:
                pass

    def subscribe(self, since_id: Optional[int] = None, types: Optional[Set[str]] = None) -> Subscription:
        """Must be called on the event loop thread."""
        sub = Subscription(queue=asyncio.Queue(maxsize=self.subscriber_queue_size), types=types)
        with self._lock:
            backlog = list(self._history)
            oldest = backlog[0].id if backlog else self._seq + 1
            self._subs.append(sub)
        if since_id is not None and since_id < self._seq:
            if since_id + 1 < oldest:
                self._offer(sub, Event(self._seq, RESYNC_REQUIRED, time.time(),
                                       {"reason": "requested events are older than the replay buffer"}))
            else:
                for ev in backlog:
                    if ev.id > since_id and sub.wants(ev):
                        self._offer(sub, ev)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def recent(self, limit: int = 50, types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = [e for e in self._history if types is None or e.type in types]
        return [e.to_dict() for e in items[-limit:]][::-1]

    def stats(self) -> Dict[str, Any]:
        return {
            "subscribers": len(self._subs),
            "last_event_id": self._seq,
            "published_total": self.published_total,
            "replay_buffer": len(self._history),
            "slow_client_drops": sum(s.dropped for s in self._subs),
        }
