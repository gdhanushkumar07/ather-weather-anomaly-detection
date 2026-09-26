"""
Pipeline data contracts.

ObservationIn is the ONE inbound shape every source adapter and the push API
produce. Schema validation here is deliberately about *well-formedness*
(types, finiteness, timestamps, identifiers) — never about physical
plausibility. A physically impossible reading (RH 130 %) is a valid payload
that must reach Layer 1 so ATHER can flag the sensor; only corrupt payloads
(non-numeric, NaN, 1e12) are rejected here.
"""
import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Parameters an observation may carry, in ATHER canonical units after
# normalization (see normalize.py for accepted input units).
PARAMETERS = (
    "temperature",      # °C
    "humidity",         # % RH
    "pressure",         # hPa
    "wind_speed",       # km/h
    "wind_direction",   # degrees
    "rainfall",         # mm since previous observation
    "dew_point",        # °C (only when the station reports it)
)

# Anything beyond this magnitude is a corrupt payload, not a sensor reading.
_CORRUPT_ABS_LIMIT = 1.0e5


class StationMetaIn(BaseModel):
    """Optional metadata for a station not yet in the catalogue (e.g. a NOAA
    ISD station discovered from its own feed)."""
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = Field(None, max_length=200)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation: Optional[float] = Field(None, ge=-500, le=9000)
    region: Optional[str] = Field(None, max_length=120)
    country: Optional[str] = Field(None, max_length=120)
    network: Optional[str] = Field(None, max_length=60)


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")
    observed_at: datetime
    source: str = Field(..., max_length=40)
    adapter: str = Field("push", max_length=40)

    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    rainfall: Optional[float] = None
    dew_point: Optional[float] = None

    # Input units per parameter when they differ from the canonical ones,
    # e.g. {"temperature": "degF", "pressure": "Pa", "wind_speed": "m/s"}.
    units: Dict[str, str] = Field(default_factory=dict)
    station: Optional[StationMetaIn] = None
    # Internal provenance (e.g. an injected Test Lab fault). The push API
    # strips this so external callers cannot forge it.
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator(*PARAMETERS, mode="before")
    @classmethod
    def _finite_or_none(cls, v: Any) -> Optional[float]:
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            raise ValueError("boolean is not a numeric reading")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"not numeric: {v!r}")
        if math.isnan(f) or math.isinf(f):
            return None  # sensor reported NaN/inf -> treat the channel as missing
        if abs(f) > _CORRUPT_ABS_LIMIT:
            raise ValueError(f"corrupt magnitude: {f}")
        return f

    @field_validator("units")
    @classmethod
    def _known_unit_keys(cls, v: Dict[str, str]) -> Dict[str, str]:
        unknown = set(v) - set(PARAMETERS)
        if unknown:
            raise ValueError(f"units given for unknown parameters: {sorted(unknown)}")
        return v


@dataclass
class NormalizedObservation:
    """An observation that passed validation and normalization and is ready
    for the stream. Values are in ATHER canonical units."""
    observation_id: str
    station_id: str
    observed_at: datetime
    received_at: datetime
    source: str
    adapter: str
    values: Dict[str, Optional[float]]
    flags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    cadence_s: float = 300.0
    enqueued_at: Optional[float] = None  # monotonic time, set by the stream

    @staticmethod
    def make_id(station_id: str, source: str, observed_at: datetime) -> str:
        """Deterministic id: the same station/source/time is the same
        observation, which is what makes duplicate delivery idempotent."""
        key = f"{station_id}|{source}|{observed_at.astimezone(timezone.utc).isoformat()}"
        return "obs_" + hashlib.sha1(key.encode()).hexdigest()[:20]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "station_id": self.station_id,
            "observed_at": self.observed_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "source": self.source,
            "adapter": self.adapter,
            "values": self.values,
            "flags": self.flags,
        }


class RejectedObservation(Exception):
    """Raised by ingestion when an observation cannot enter the stream."""

    def __init__(self, code: str, message: str, station_id: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.station_id = station_id

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "station_id": self.station_id}


# Spec §7 overall status vocabulary, derived from the engine's own status.
OVERALL_STATUSES = ("nominal", "suspect", "degraded", "anomaly")

LAYER_KEYS = [
    ("L1", "physics"),
    ("L2", "temporal"),
    ("L3", "multivariate"),
    ("L4", "spatial"),
    ("L5", "sensor_health"),
]
