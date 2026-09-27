"""
NOAAISDAdapter — real hourly surface observations from NOAA's Integrated
Surface Database (global-hourly), via the public NCEI Access Data Service.

Opt-in: set ATHER_NOAA_STATIONS to a comma-separated list of 11-digit
USAF+WBAN ids (e.g. Indian synoptic stations from the ISD station history
file). Station ids are deliberately NOT hard-coded here — they must be
checked against the ISD station list for the deployment.

Honest limits: ISD is an archive with a publication lag (often hours), so
this source is "near-real-time", and freshness is shown per observation.
Each poll fetches a trailing window; the processor's idempotent
observation_id makes re-fetching the same hours harmless.

Encoding (ISD format document, mandatory data section):
  TMP "+0285,1"            air temperature, tenths °C, quality code
  DEW "+0213,1"            dew point, tenths °C
  SLP "10132,1"            sea-level pressure, tenths hPa
  WND "270,1,N,0046,1"     direction°, q, type, speed tenths m/s, q
  missing sentinels: +9999 / 99999 / 999 / 9999
Relative humidity is not in the mandatory section; it is DERIVED from T and
Td (flagged RH_DERIVED) so Layer 3 is not credited with an independent check.
"""
import asyncio
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.pipeline.models import ObservationIn

from .base import OBSERVATION, SourceAdapter

NCEI_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
BAD_QUALITY = {"2", "3", "6", "7"}  # ISD suspect/erroneous quality codes


def _field(raw: Optional[str], idx: int = 0) -> Optional[str]:
    if not raw:
        return None
    parts = raw.split(",")
    return parts[idx] if idx < len(parts) else None


def _scaled(raw: Optional[str], missing: str, scale: float) -> Optional[float]:
    """Parses '+0285,1' style fields; None for missing or bad-quality values."""
    if not raw:
        return None
    parts = raw.split(",")
    value, quality = parts[0], (parts[1] if len(parts) > 1 else "1")
    if value.lstrip("+-") == missing.lstrip("+-") or quality in BAD_QUALITY:
        return None
    try:
        return int(value) / scale
    except ValueError:
        return None


def _rh(t: Optional[float], td: Optional[float]) -> Optional[float]:
    if t is None or td is None:
        return None
    a, b = 17.62, 243.12
    return round(100.0 * math.exp(a * td / (b + td) - a * t / (b + t)), 1)


def parse_isd_record(rec: Dict[str, Any]) -> Optional[ObservationIn]:
    station = rec.get("STATION")
    date = rec.get("DATE")
    if not station or not date:
        return None
    t = _scaled(rec.get("TMP"), "9999", 10.0)
    td = _scaled(rec.get("DEW"), "9999", 10.0)
    slp = _scaled(rec.get("SLP"), "99999", 10.0)
    wnd = rec.get("WND")
    wdir = wspd = None
    if wnd:
        parts = wnd.split(",")
        if len(parts) >= 5:
            if parts[0] != "999" and parts[1] not in BAD_QUALITY:
                wdir = float(parts[0])
            if parts[3] != "9999" and parts[4] not in BAD_QUALITY:
                wspd = int(parts[3]) / 10.0 * 3.6  # tenths m/s -> km/h
    try:
        lat, lon = float(rec.get("LATITUDE")), float(rec.get("LONGITUDE"))
    except (TypeError, ValueError):
        return None
    elev = rec.get("ELEVATION")
    return ObservationIn(
        station_id=f"ISD-{station}",
        observed_at=datetime.fromisoformat(date).replace(tzinfo=timezone.utc),
        source="AWS_IN_SITU",
        adapter="noaa_isd",
        temperature=t,
        dew_point=td,
        humidity=_rh(t, td),
        pressure=slp,
        wind_speed=wspd,
        wind_direction=wdir,
        station={
            "name": (rec.get("NAME") or f"ISD {station}").title(),
            "latitude": lat,
            "longitude": lon,
            "elevation": float(elev) if elev not in (None, "") else None,
            "network": "NOAA_ISD",
            "country": "India" if 6 <= lat <= 38 and 68 <= lon <= 98 else None,
        },
        meta={"flags": ["RH_DERIVED"]},
    )


class NOAAISDAdapter(SourceAdapter):
    name = "noaa_isd"
    label = "NOAA ISD global-hourly (NCEI)"
    kind = OBSERVATION
    cadence_s = 1800.0          # ISD is hourly; poll twice an hour
    lookback_h = 6

    def __init__(self):
        super().__init__()
        self.stations = [s.strip() for s in os.environ.get("ATHER_NOAA_STATIONS", "").split(",") if s.strip()]
        self.status.note = "Real in-situ synoptic observations; hourly with archive publication lag."

    def configured(self) -> Optional[str]:
        if not self.stations:
            return "Set ATHER_NOAA_STATIONS (USAF+WBAN ids) to enable real NOAA ISD observations."
        return None

    def _fetch(self) -> List[Dict[str, Any]]:
        from app.weather.open_meteo import _tls_context
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=self.lookback_h)
        params = {
            "dataset": "global-hourly",
            "stations": ",".join(self.stations),
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "format": "json",
            "includeStationName": "true",
            "includeStationLocation": "1",
        }
        req = urllib.request.Request(f"{NCEI_URL}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "ATHER-AWS-QC/1.0"})
        with urllib.request.urlopen(req, context=_tls_context(), timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    async def poll(self) -> List[ObservationIn]:
        records = await asyncio.to_thread(self._fetch)
        out = []
        for rec in records if isinstance(records, list) else []:
            obs = parse_isd_record(rec)
            if obs is not None:
                out.append(obs)
        return out
