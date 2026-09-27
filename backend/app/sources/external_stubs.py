"""
Adapters for AWS networks that need credentials or a data-sharing agreement.

They are registered so the System view shows every intended source and why
it is not flowing — never a fabricated feed in its place.
"""
import asyncio
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional

from app.pipeline.models import ObservationIn

from .base import OBSERVATION, SourceAdapter


class IMDAWSAdapter(SourceAdapter):
    name = "imd_aws"
    label = "IMD AWS / ARG network"
    kind = OBSERVATION
    cadence_s = 900.0

    def configured(self) -> Optional[str]:
        return ("IMD does not publish a public machine-readable real-time AWS API. Integrate through a "
                "data-sharing feed that POSTs to /api/observations (source=AWS_IN_SITU).")


class WeatherUnionAdapter(SourceAdapter):
    """Weather Union (Zomato) locality telemetry, v0 external API.

    Implemented against the publicly documented v0 endpoint; NOT verified in
    this environment (no key). The API has no observation timestamp, so the
    fetch time is used and flagged; it has no pressure channel. The free tier
    is rate-limited, so polling rotates through the catalogue within a daily
    call budget instead of hitting every locality each cycle.
    """
    name = "weather_union"
    label = "Weather Union locality AWS"
    kind = OBSERVATION
    cadence_s = 900.0
    URL = "https://www.weatherunion.com/gw/weather/external/v0/get_locality_weather_data"

    def __init__(self, locality_ids_provider):
        super().__init__()
        self.key = os.environ.get("WEATHERUNION_API_KEY", "")
        self.daily_budget = int(os.environ.get("ATHER_WEATHERUNION_DAILY_CALLS", "900"))
        self.locality_ids_provider = locality_ids_provider
        self._cursor = 0

    def configured(self) -> Optional[str]:
        if not self.key:
            return "Set WEATHERUNION_API_KEY (server-side only) to poll real Weather Union telemetry."
        return None

    def _per_cycle(self) -> int:
        cycles_per_day = 86400.0 / self.cadence_s
        return max(1, int(self.daily_budget / cycles_per_day))

    def _fetch_one(self, locality_id: str) -> Optional[ObservationIn]:
        req = urllib.request.Request(f"{self.URL}?locality_id={locality_id}",
                                     headers={"x-zomato-api-key": self.key})
        from app.weather.open_meteo import _tls_context
        with urllib.request.urlopen(req, context=_tls_context(), timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
        d = body.get("locality_weather_data") or {}
        if not d:
            return None
        return ObservationIn(
            station_id=locality_id,
            observed_at=datetime.fromtimestamp(int(time.time()), tz=timezone.utc),
            source="AWS_IN_SITU",
            adapter=self.name,
            temperature=d.get("temperature"),
            humidity=d.get("humidity"),
            wind_speed=d.get("wind_speed"),
            wind_direction=d.get("wind_direction"),
            units={"wind_speed": "m/s"},
            meta={"flags": ["TIMESTAMP_IS_RECEIPT_TIME"]},
        )

    async def poll(self) -> List[ObservationIn]:
        ids = self.locality_ids_provider()
        if not ids:
            return []
        n = self._per_cycle()
        batch = [ids[(self._cursor + i) % len(ids)] for i in range(min(n, len(ids)))]
        self._cursor = (self._cursor + len(batch)) % len(ids)
        out = []
        for lid in batch:
            obs = await asyncio.to_thread(self._fetch_one, lid)
            if obs:
                out.append(obs)
        return out
