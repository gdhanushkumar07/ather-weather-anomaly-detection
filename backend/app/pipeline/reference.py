"""
NWP reference comparison (spec §13).

Reads ONLY the local Open-Meteo cache (populated in the background by
OpenMeteoReferenceAdapter) — the detection hot path never makes a network
call. The comparison is supporting evidence for an operator, never ground
truth, and it is never fed into the five layers.
"""
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

REFERENCE_LABEL = "Open-Meteo NWP (model/reference data — not a physical observation)"
REFERENCE_MAX_AGE_S = 3 * 3600

_FIELDS = (
    ("temperature", "temperature", "°C"),
    ("humidity", "humidity", "%"),
    ("pressure", "pressure", "hPa"),
    ("wind_speed", "windSpeed", "km/h"),
)


def _cache_entry(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    try:
        from app.weather.open_meteo import open_meteo_service
    except Exception:
        return None
    return open_meteo_service.cache.get(f"{round(lat, 3)}_{round(lon, 3)}")


def compare(
    observed: Dict[str, Optional[float]],
    lat: float,
    lon: float,
    observation_source: str,
    reference_available: bool = True,
) -> Dict[str, Any]:
    entry = _cache_entry(lat, lon)
    if not entry:
        return {
            "available": False,
            "label": REFERENCE_LABEL,
            "reason": "Reference source unavailable" if not reference_available else "No reference fetched for this location yet",
        }
    data = entry.get("data") or {}
    fetched_at = entry.get("cached_at")
    age_s = time.time() - fetched_at if fetched_at else None
    params: Dict[str, Any] = {}
    for key, ref_key, unit in _FIELDS:
        obs_v, ref_v = observed.get(key), data.get(ref_key)
        if ref_v is None:
            continue
        params[key] = {
            "observed": obs_v,
            "reference": ref_v,
            "difference": round(obs_v - ref_v, 2) if obs_v is not None else None,
            "unit": unit,
        }
    note = "Supporting evidence only. Model grid cells smooth local extremes; differences of a few °C are normal."
    if observation_source == "SIMULATED_AWS":
        note += (" This station's simulated feed is seeded from this same reference, so agreement here is "
                 "NOT independent validation.")
    if "pressure" in params:
        note += " Reference pressure is mean-sea-level; compare with station pressure only after altitude reduction."
    return {
        "available": True,
        "label": REFERENCE_LABEL,
        "model_time": data.get("timestamp"),
        "fetched_at": datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat() if fetched_at else None,
        "stale": bool(age_s is not None and age_s > REFERENCE_MAX_AGE_S),
        "reference_source_status": "AVAILABLE" if reference_available else "UNAVAILABLE (showing last cached value)",
        "parameters": params,
        "note": note,
    }
