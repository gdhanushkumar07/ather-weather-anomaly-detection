"""
OpenMeteoReferenceAdapter — the ONE background poller for Open-Meteo.

This adapter never emits observations. Open-Meteo is model output, so it is
used only as a comparison layer (spec §13) and as the baseline the simulated
feed is seeded from; readers only ever read the local cache.

All upstream discipline (multi-location batches, de-duplication, one call at
a time, 429/Retry-After handling, quota cooldowns) lives in
app.weather.open_meteo. This adapter decides WHEN to refresh:

  * every WEATHER_POLL_INTERVAL_SECONDS (default 3600 — the model's cadence)
  * sooner (WEATHER_PARTIAL_RETRY_SECONDS, default 600) when some locations
    could not be refreshed, so only those are retried
  * after an hourly/daily quota stop, not before the quota resets
When nothing could be refreshed the cache keeps serving the last values,
marked with their age, and detection continues unaffected.
"""
import asyncio
import os
import random
import time
from typing import Callable, List, Tuple

from .base import REFERENCE, SourceAdapter


class ReferenceUnavailable(Exception):
    pass


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class OpenMeteoReferenceAdapter(SourceAdapter):
    name = "open_meteo_reference"
    label = "Open-Meteo NWP reference"
    kind = REFERENCE
    cadence_s = 3600.0
    max_backoff_s = 3600.0

    def __init__(self, coords_provider: Callable[[], List[Tuple[float, float]]], enabled: bool = True):
        self.cadence_s = _env_f("WEATHER_POLL_INTERVAL_SECONDS", 3600.0)
        self.partial_retry_s = _env_f("WEATHER_PARTIAL_RETRY_SECONDS", 600.0)
        super().__init__()
        self.coords_provider = coords_provider
        self.enabled = enabled
        self.status.note = ("Model/reference data used only for observed-vs-NWP comparison. "
                            "Never treated as a station observation.")

    def configured(self):
        return None if self.enabled else "Disabled by ATHER_REFERENCE_ENABLED=0"

    @property
    def available(self) -> bool:
        return self.status.state in ("ACTIVE", "STARTING")

    @staticmethod
    def _service():
        from app.weather.open_meteo import open_meteo_service
        return open_meteo_service

    def _cooldown_left(self) -> float:
        return max(0.0, self._service().blocked_until - time.time())

    def success_delay(self) -> float:
        report = self._service().last_report or {}
        if report.get("failed_locations") or report.get("deferred_locations"):
            return max(self._cooldown_left(), min(self.cadence_s, self.partial_retry_s)) * random.uniform(1.0, 1.1)
        return self.cadence_s

    def backoff_delay(self) -> float:
        left = self._cooldown_left()
        if left > 0:
            return left * random.uniform(1.0, 1.05) + 5.0
        return super().backoff_delay()

    async def poll(self):
        svc = self._service()
        coords = self.coords_provider()
        if not coords:
            return []
        await asyncio.to_thread(svc.get_batch_weather, coords)
        report = svc.last_report or {}
        if report.get("to_fetch") and not report.get("fetched") and (report.get("errors") or report.get("skipped") == "cooldown"):
            raise ReferenceUnavailable(report.get("last_error") or "Open-Meteo request failed")
        fresh = report.get("unique", report.get("requested", 0)) - report.get("to_fetch", 0)
        missing = report.get("failed_locations", 0) + report.get("deferred_locations", 0)
        self.status.note = (
            f"Refreshed {report.get('fetched', 0)} of {report.get('unique', report.get('requested', 0))} locations "
            f"in {report.get('batches', 0)} batched request(s); {fresh} still fresh in cache"
            + (f"; {missing} not refreshed this cycle (last values kept, retried shortly)" if missing else "")
            + ". Model/reference data — never treated as an observation."
        )
        return []
