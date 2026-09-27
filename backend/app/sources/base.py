"""
Adapter base class: cadence, retries, exponential backoff, status.

A source failing never stops ATHER — its adapter goes DEGRADED/DOWN, the
dashboard shows that, and every other source keeps flowing.
"""
import asyncio
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable, List, Optional

from app.pipeline.models import ObservationIn

log = logging.getLogger("ather.sources")

OBSERVATION = "OBSERVATION"
REFERENCE = "REFERENCE"

ACTIVE = "ACTIVE"
DEGRADED = "DEGRADED"        # recent failures, retrying with backoff
DOWN = "DOWN"                # repeated failures
DISABLED = "DISABLED"        # switched off by configuration
NOT_CONFIGURED = "NOT_CONFIGURED"  # needs credentials / endpoint the deployment lacks
STARTING = "STARTING"

Emit = Callable[[List[ObservationIn]], Awaitable[None]]
StatusCallback = Callable[["SourceStatus", Optional[str]], None]


@dataclass
class SourceStatus:
    name: str
    label: str
    kind: str
    state: str = STARTING
    cadence_s: float = 300.0
    simulated: bool = False
    last_attempt_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    next_attempt_at: Optional[float] = None
    items_total: int = 0
    last_batch_size: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["age_s"] = round(time.time() - self.last_success_at, 1) if self.last_success_at else None
        return d


class SourceAdapter:
    name = "base"
    label = "Base adapter"
    kind = OBSERVATION
    simulated = False
    cadence_s = 300.0
    max_backoff_s = 3600.0
    down_after_failures = 3

    def __init__(self):
        self.status = SourceStatus(self.name, self.label, self.kind, cadence_s=self.cadence_s, simulated=self.simulated)
        self._on_status: Optional[StatusCallback] = None
        self._stopping = False

    # Subclasses override one of these.
    def configured(self) -> Optional[str]:
        """Return a reason string if the adapter cannot run in this deployment."""
        return None

    async def poll(self) -> List[ObservationIn]:
        raise NotImplementedError

    # ── lifecycle ───────────────────────────────────────────────────────
    def set_status_callback(self, cb: StatusCallback) -> None:
        self._on_status = cb

    def _set_state(self, state: str, reason: Optional[str] = None) -> None:
        changed = state != self.status.state
        self.status.state = state
        if changed and self._on_status:
            try:
                self._on_status(self.status, reason)
            except Exception:
                log.exception("status callback failed")

    def stop(self) -> None:
        self._stopping = True

    def backoff_delay(self) -> float:
        n = self.status.consecutive_failures
        base = min(self.max_backoff_s, max(5.0, self.cadence_s / 4.0) * (2 ** (n - 1)))
        return base * random.uniform(0.8, 1.2)

    async def run(self, emit: Emit) -> None:
        reason = self.configured()
        if reason:
            self.status.note = reason
            self._set_state(NOT_CONFIGURED, reason)
            return
        while not self._stopping:
            self.status.last_attempt_at = time.time()
            try:
                items = await self.poll()
                self.status.last_success_at = time.time()
                self.status.consecutive_failures = 0
                self.status.last_error = None
                self.status.last_batch_size = len(items)
                self.status.items_total += len(items)
                self._set_state(ACTIVE)
                if items and self.kind == OBSERVATION:
                    await emit(items)
                delay = self.cadence_s
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status.consecutive_failures += 1
                self.status.last_error = f"{type(e).__name__}: {e}"[:300]
                state = DOWN if self.status.consecutive_failures >= self.down_after_failures else DEGRADED
                self._set_state(state, self.status.last_error)
                delay = self.backoff_delay()
                log.warning("%s poll failed (%s); retrying in %.0fs", self.name, self.status.last_error, delay)
            self.status.next_attempt_at = time.time() + delay
            await asyncio.sleep(delay)
