"""
Normalization: unit conversion, timestamp validation, missing-value flags.

Pure functions — no I/O — so every rule here is unit-testable.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .models import NormalizedObservation, ObservationIn, PARAMETERS, RejectedObservation

# Accepted input units -> converter to the canonical unit.
_CONVERTERS: Dict[str, Dict[str, Callable[[float], float]]] = {
    "temperature": {
        "degC": lambda v: v, "C": lambda v: v, "celsius": lambda v: v,
        "degF": lambda v: (v - 32.0) * 5.0 / 9.0, "F": lambda v: (v - 32.0) * 5.0 / 9.0,
        "K": lambda v: v - 273.15, "kelvin": lambda v: v - 273.15,
        "tenths_degC": lambda v: v / 10.0,
    },
    "dew_point": {
        "degC": lambda v: v, "C": lambda v: v,
        "degF": lambda v: (v - 32.0) * 5.0 / 9.0, "F": lambda v: (v - 32.0) * 5.0 / 9.0,
        "K": lambda v: v - 273.15, "tenths_degC": lambda v: v / 10.0,
    },
    "humidity": {
        "%": lambda v: v, "pct": lambda v: v, "percent": lambda v: v,
        "fraction": lambda v: v * 100.0,
    },
    "pressure": {
        "hPa": lambda v: v, "mbar": lambda v: v, "mb": lambda v: v,
        "Pa": lambda v: v / 100.0, "kPa": lambda v: v * 10.0,
        "inHg": lambda v: v * 33.8638866667, "mmHg": lambda v: v * 1.33322368,
        "tenths_hPa": lambda v: v / 10.0,
    },
    "wind_speed": {
        "km/h": lambda v: v, "kmh": lambda v: v,
        "m/s": lambda v: v * 3.6, "ms": lambda v: v * 3.6,
        "kt": lambda v: v * 1.852, "knots": lambda v: v * 1.852,
        "mph": lambda v: v * 1.609344,
    },
    "wind_direction": {"deg": lambda v: v % 360.0, "degrees": lambda v: v % 360.0},
    "rainfall": {"mm": lambda v: v, "in": lambda v: v * 25.4, "cm": lambda v: v * 10.0},
}

# Observations more than this far in the future are clock errors and rejected.
MAX_FUTURE_SKEW = timedelta(minutes=5)
# Older than this, an observation is still archived but flagged LATE.
MAX_ON_TIME_AGE = timedelta(hours=6)


def convert(parameter: str, value: Optional[float], unit: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    if not unit:
        return value
    table = _CONVERTERS.get(parameter, {})
    fn = table.get(unit)
    if fn is None:
        raise RejectedObservation(
            "UNSUPPORTED_UNIT", f"Unit '{unit}' is not supported for {parameter}. Accepted: {sorted(table)}"
        )
    return fn(value)


def validate_timestamp(observed_at: datetime, received_at: datetime) -> Tuple[datetime, List[str]]:
    """Returns the UTC timestamp and quality flags, or raises for clock errors."""
    flags: List[str] = []
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
        flags.append("TIMESTAMP_ASSUMED_UTC")
    observed_at = observed_at.astimezone(timezone.utc)
    if observed_at - received_at > MAX_FUTURE_SKEW:
        raise RejectedObservation(
            "FUTURE_TIMESTAMP",
            f"observed_at {observed_at.isoformat()} is ahead of receipt time by "
            f"{(observed_at - received_at).total_seconds():.0f}s (clock error)",
        )
    if received_at - observed_at > MAX_ON_TIME_AGE:
        flags.append("LATE_ARRIVAL")
    return observed_at, flags


def normalize(
    obs: ObservationIn,
    received_at: Optional[datetime] = None,
    cadence_s: float = 300.0,
) -> NormalizedObservation:
    received_at = received_at or datetime.now(timezone.utc)
    observed_at, flags = validate_timestamp(obs.observed_at, received_at)

    values: Dict[str, Optional[float]] = {}
    for p in PARAMETERS:
        values[p] = convert(p, getattr(obs, p), obs.units.get(p))

    if all(values[p] is None for p in ("temperature", "humidity", "pressure")):
        # Still a meaningful event (the station is alive but its core sensors
        # returned nothing) — pass it on so the engine reports it honestly.
        flags.append("NO_CORE_CHANNELS")
    for p in ("temperature", "humidity", "pressure"):
        if values[p] is None:
            flags.append(f"MISSING_{p.upper()}")

    return NormalizedObservation(
        observation_id=NormalizedObservation.make_id(obs.station_id, obs.source, observed_at),
        station_id=obs.station_id,
        observed_at=observed_at,
        received_at=received_at,
        source=obs.source,
        adapter=obs.adapter,
        values=values,
        flags=flags,
        meta=dict(obs.meta),
        cadence_s=cadence_s,
    )


def dew_point_c(temp_c: Optional[float], rh: Optional[float]) -> Optional[float]:
    """Magnus-Tetens dew point, used only to DISPLAY a derived dew point on
    charts; never fed back to the engine as if it were measured."""
    import math
    if temp_c is None or rh is None or rh <= 0 or rh > 100:
        return None
    a, b = 17.62, 243.12
    g = math.log(rh / 100.0) + a * temp_c / (b + temp_c)
    return round(b * g / (a - g), 2)
