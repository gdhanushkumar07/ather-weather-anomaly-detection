"""
OpenMeteoReferenceAdapter — keeps the NWP REFERENCE cache warm.

This adapter never emits observations. Open-Meteo is model output, so it is
used only as a comparison layer (spec §13): the processor reads the cache to
show "observed vs model" as supporting evidence.

Rate-limit discipline: one batched request per 50 stations, refreshed at the
model's own hourly cadence (never faster), 0.4 s pacing between chunks, 429
retry, and exponential backoff on failure. When the API is down the cache
keeps serving the last values, marked with their age, and the dashboard
shows "Reference source unavailable" while detection continues.
"""
import asyncio
from typing import Callable, List, Tuple

from .base import REFERENCE, SourceAdapter


class ReferenceUnavailable(Exception):
    pass


class OpenMeteoReferenceAdapter(SourceAdapter):
    name = "open_meteo_reference"
    label = "Open-Meteo NWP reference"
    kind = REFERENCE
    cadence_s = 3600.0
    max_backoff_s = 3600.0

    def __init__(self, coords_provider: Callable[[], List[Tuple[float, float]]], enabled: bool = True):
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

    async def poll(self):
        from app.weather.open_meteo import open_meteo_service
        coords = self.coords_provider()
        if not coords:
            return []
        await asyncio.to_thread(open_meteo_service.get_batch_weather, coords, 50)
        report = open_meteo_service.last_report or {}
        if report.get("to_fetch") and not report.get("fetched") and report.get("errors"):
            raise ReferenceUnavailable(report.get("last_error") or "Open-Meteo request failed")
        self.status.note = (
            f"Refreshed {report.get('fetched', 0)} of {report.get('requested', 0)} locations "
            f"({report.get('requested', 0) - report.get('to_fetch', 0)} still fresh in cache). "
            "Model/reference data — never treated as an observation."
        )
        return []
