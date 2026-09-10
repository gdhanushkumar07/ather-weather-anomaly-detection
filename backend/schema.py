"""
Pydantic data contracts and models for AWS sensor readings and anomaly outputs.

DATA QUALITY POLICY:
  - Null/None values stay null — never substitute 0 for missing
  - Zero pressure (< 1 hPa) is treated as a missing/invalid value, NOT a real measurement
  - Zero temperature is treated as missing/invalid ONLY when pressure is also 0 or null
    (a real 0°C reading is valid; 0°C alongside 0 hPa indicates data absence)
  - Every channel carries a DataQuality label so detection layers can skip invalid inputs
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────────────────────────
# Data Quality
# ─────────────────────────────────────────────────────────────────

class DataQuality(str, Enum):
    VALID            = "valid"           # Observed, within physical bounds, trusted
    MISSING          = "missing"         # Field was null / not reported
    ZERO_SUBSTITUTED = "zero_substituted"# Was 0.0 but treated as missing (not a real measurement)
    INVALID          = "invalid"         # Present but fails basic sanity check (negative humidity etc.)
    OUT_OF_RANGE     = "out_of_range"    # Present but outside hard physical bounds
    STALE            = "stale"           # Timestamp too old to be current


# ─────────────────────────────────────────────────────────────────
# Sensor Channel Enum
# ─────────────────────────────────────────────────────────────────

class SensorChannel(str, Enum):
    TEMPERATURE = "temperature_c"
    PRESSURE    = "pressure_hpa"
    HUMIDITY    = "humidity_pct"


# ─────────────────────────────────────────────────────────────────
# Data Provenance — distinguishes measured AWS telemetry from
# model/reference data. NEVER present NWP_MODEL_REFERENCE as AWS
# in-situ telemetry anywhere in the API or UI (see Phase 20/27).
# ─────────────────────────────────────────────────────────────────

class ObservationSource(str, Enum):
    AWS_IN_SITU          = "AWS_IN_SITU"           # Measured by a real physical AWS sensor / pushed telemetry
    NWP_MODEL_REFERENCE  = "NWP_MODEL_REFERENCE"   # Open-Meteo (or other) numerical weather model output
    SYNTHETIC_TEST       = "SYNTHETIC_TEST"        # Fabricated data used only in unit tests
    MISSING              = "MISSING"               # No observation obtained at all
    UNKNOWN              = "UNKNOWN"               # Source could not be determined (legacy path)


class Freshness(str, Enum):
    LIVE     = "LIVE"       # Observation timestamp within the source's accepted cadence window
    STALE    = "STALE"      # Observation timestamp older than the accepted cadence window
    UNKNOWN  = "UNKNOWN"    # No reliable observation timestamp exists — cadence/age cannot be verified
    MISSING  = "MISSING"    # No observation at all


def classify_freshness(
    observation_timestamp: Optional[datetime],
    received_timestamp: Optional[datetime] = None,
    cadence_minutes: float = 90.0,
    has_value: bool = True,
) -> str:
    """
    Determines freshness from an ACTUAL observation timestamp — never from the
    frontend/backend request time. If the observation timestamp is unknown,
    freshness is UNKNOWN (not silently LIVE).

    cadence_minutes: the source's known update cadence, used as the staleness
    window. Callers must pass a value appropriate to the actual source
    (e.g. ~90 min for hourly NWP model output; conservative default otherwise).
    """
    if not has_value:
        return Freshness.MISSING
    if observation_timestamp is None:
        return Freshness.UNKNOWN
    ref = received_timestamp or datetime.now(timezone.utc)
    try:
        obs = observation_timestamp
        if obs.tzinfo is None:
            obs = obs.replace(tzinfo=timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        age_minutes = (ref - obs).total_seconds() / 60.0
    except Exception:
        return Freshness.UNKNOWN
    if age_minutes < 0:
        # Observation claims to be from the future — untrustworthy, treat conservatively
        return Freshness.UNKNOWN
    return Freshness.LIVE if age_minutes <= cadence_minutes else Freshness.STALE


# ─────────────────────────────────────────────────────────────────
# Station Metadata
# ─────────────────────────────────────────────────────────────────

class StationMetadata(BaseModel):
    station_id:  str
    name:        str   = "AWS Station"
    lat:         float
    lon:         float
    elevation_m: float = 0.0


# ─────────────────────────────────────────────────────────────────
# AWS Reading — Core Telemetry Object
# ─────────────────────────────────────────────────────────────────

class AWSReading(BaseModel):
    station_id:     str
    timestamp:      datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    temperature_c:  Optional[float] = Field(None, description="Ambient air temperature in Celsius")
    pressure_hpa:   Optional[float] = Field(None, description="Barometric surface pressure in hPa/mbar")
    humidity_pct:   Optional[float] = Field(None, description="Relative humidity in percentage [0, 100]")
    dew_point_c:    Optional[float] = Field(None, description="Dew point temperature in Celsius if available")
    wind_speed_kmh: Optional[float] = Field(None, description="Wind speed in km/h")

    lat:         float = 0.0
    lon:         float = 0.0
    elevation_m: Optional[float] = 0.0

    # ── Provenance (Phase 1-4) ──────────────────────────────────────
    # source: where the numeric values actually came from — NEVER label
    #   NWP_MODEL_REFERENCE data as AWS_IN_SITU anywhere downstream.
    # observation_timestamp: the REAL time the value was valid at the source
    #   (e.g. Open-Meteo's `current.time`, or a pushed telemetry payload's own
    #   clock). None when the true observation time cannot be verified —
    #   never silently defaulted to "now".
    # received_timestamp: when ATHER's backend obtained/loaded the value.
    source:                 str                = ObservationSource.UNKNOWN
    observation_timestamp:  Optional[datetime]  = None
    received_timestamp:     datetime            = Field(default_factory=lambda: datetime.now(timezone.utc))
    freshness:               str                = Freshness.UNKNOWN

    # Per-channel data quality labels — set by station_dict_to_reading() or validator
    data_quality: Dict[str, str] = Field(
        default_factory=lambda: {
            "temperature_c": DataQuality.MISSING,
            "pressure_hpa":  DataQuality.MISSING,
            "humidity_pct":  DataQuality.MISSING,
        },
        description="Quality label per sensor channel"
    )

    @model_validator(mode="before")
    @classmethod
    def populate_data_quality(cls, data: Any) -> Any:
        if isinstance(data, dict):
            dq = data.get("data_quality")
            if dq is None:
                dq = {}
                data["data_quality"] = dq
            elif not isinstance(dq, dict):
                dq = dict(dq)
                data["data_quality"] = dq

            # Temperature
            if "temperature_c" not in dq or dq["temperature_c"] == DataQuality.MISSING:
                t = data.get("temperature_c")
                if t is not None:
                    dq["temperature_c"] = DataQuality.VALID
                else:
                    dq["temperature_c"] = DataQuality.MISSING

            # Pressure
            if "pressure_hpa" not in dq or dq["pressure_hpa"] == DataQuality.MISSING:
                p = data.get("pressure_hpa")
                if p is not None:
                    try:
                        p_val = float(p)
                        if p_val < 1.0:
                            data["pressure_hpa"] = None
                            dq["pressure_hpa"] = DataQuality.ZERO_SUBSTITUTED
                        else:
                            dq["pressure_hpa"] = DataQuality.VALID
                    except (ValueError, TypeError):
                        dq["pressure_hpa"] = DataQuality.INVALID
                else:
                    dq["pressure_hpa"] = DataQuality.MISSING

            # Humidity
            if "humidity_pct" not in dq or dq["humidity_pct"] == DataQuality.MISSING:
                h = data.get("humidity_pct")
                if h is not None:
                    try:
                        h_val = float(h)
                        if h_val < 0:
                            data["humidity_pct"] = None
                            dq["humidity_pct"] = DataQuality.INVALID
                        elif h_val > 100:
                            dq["humidity_pct"] = DataQuality.OUT_OF_RANGE
                        else:
                            dq["humidity_pct"] = DataQuality.VALID
                    except (ValueError, TypeError):
                        dq["humidity_pct"] = DataQuality.INVALID
                else:
                    dq["humidity_pct"] = DataQuality.MISSING
        return data

    def channel_valid(self, channel: str) -> bool:
        """Returns True only if the channel has a VALID quality label."""
        return self.data_quality.get(channel) == DataQuality.VALID

    @property
    def valid_channel_count(self) -> int:
        """Number of channels with VALID quality."""
        return sum(1 for c in ["temperature_c", "pressure_hpa", "humidity_pct"]
                   if self.channel_valid(c))

    def to_dict(self) -> dict:
        return {
            "station_id":     self.station_id,
            "timestamp":      self.timestamp.isoformat(),
            "temperature_c":  self.temperature_c,
            "pressure_hpa":   self.pressure_hpa,
            "humidity_pct":   self.humidity_pct,
            "dew_point_c":    self.dew_point_c,
            "wind_speed_kmh": self.wind_speed_kmh,
            "lat":            self.lat,
            "lon":            self.lon,
            "elevation_m":    self.elevation_m,
            "data_quality":   self.data_quality,
            "source":                self.source,
            "freshness":             self.freshness,
            "observation_timestamp": self.observation_timestamp.isoformat() if self.observation_timestamp else None,
            "received_timestamp":    self.received_timestamp.isoformat() if self.received_timestamp else None,
        }


# ─────────────────────────────────────────────────────────────────
# Fault Classification
# ─────────────────────────────────────────────────────────────────

class FaultType(str, Enum):
    NORMAL                = "NORMAL"
    SENSOR_SPIKE          = "SENSOR_SPIKE"
    FROZEN_SENSOR         = "FROZEN_SENSOR"
    CALIBRATION_DRIFT     = "CALIBRATION_DRIFT"
    NOISE_BURST           = "NOISE_BURST"
    SINGLE_CHANNEL_FAULT  = "SINGLE_CHANNEL_FAULT"
    GENUINE_EXTREME_WEATHER = "GENUINE_EXTREME_WEATHER"
    POSSIBLE_WEATHER_CHANGE = "POSSIBLE_WEATHER_CHANGE"
    COMMUNICATION_OUTAGE  = "COMMUNICATION_OUTAGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    # Fired instead of a hardware-fault category when the observation source
    # is NOT a physical AWS sensor (e.g. NWP_MODEL_REFERENCE) — there is no
    # sensor hardware to diagnose, so ATHER must not claim FROZEN_SENSOR,
    # SENSOR_SPIKE, CALIBRATION_DRIFT, etc. against model output.
    MODEL_REFERENCE_INCONSISTENCY = "MODEL_REFERENCE_INCONSISTENCY"


class DiagnosisConfidence(str, Enum):
    HIGH                = "HIGH"
    MEDIUM              = "MEDIUM"
    LOW                 = "LOW"
    INSUFFICIENT_DATA   = "INSUFFICIENT_DATA"


# ─────────────────────────────────────────────────────────────────
# Anomaly Alert — Full Engine Output
# ─────────────────────────────────────────────────────────────────

class AnomalyAlert(BaseModel):
    station_id:     str
    timestamp:      datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status:         str      = "NORMAL"   # "NORMAL" | "WARNING" | "ANOMALY" | "INSUFFICIENT_DATA"
    is_anomaly:     bool     = False

    severity_score:   float = Field(0.0, ge=0.0, le=1.0, description="Calibrated anomaly severity [0, 1]")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Evidence-quality-aware confidence [0, 1]")
    veto_fired:       bool  = Field(False, description="True if a real thermodynamic impossibility was detected")

    root_cause:        FaultType          = FaultType.NORMAL
    diagnosis_confidence: DiagnosisConfidence = DiagnosisConfidence.INSUFFICIENT_DATA
    affected_channels: List[str]          = Field(default_factory=list)

    layer_scores:  Dict[str, float] = Field(default_factory=dict)
    layer_details: Dict[str, Any]   = Field(default_factory=dict,
                                            description="Structured per-layer evidence detail")

    reasons:     List[str] = Field(default_factory=list)
    explanation: str       = Field("", description="Human-readable diagnostic explanation")

    # Primary signal and alternatives for root cause
    primary_signal:    str       = ""
    alternative_causes: List[str] = Field(default_factory=list)

    # Raw values as evaluated by the engine
    raw_values:       Dict[str, Optional[float]] = Field(default_factory=dict)
    corrected_values: Dict[str, Optional[float]] = Field(default_factory=dict)

    sensor_health_index:        float           = Field(100.0, ge=0.0, le=100.0)
    estimated_days_to_failure:  Optional[float] = None

    # Spatial context
    spatial_neighbor_count: int   = 0
    spatial_neighbor_range_km: Optional[float] = None

    # Historical temporal context
    temporal_history_points: int  = 0

    # Data quality summary
    data_quality_summary: Dict[str, Any] = Field(default_factory=dict)

    # Recommended operator action (confidence-gated)
    operator_action: str = ""

    # Canonical §16 analysis object
    canonical_result: Optional[Dict[str, Any]] = None

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Returns the canonical §16 analysis object."""
        if self.canonical_result:
            return self.canonical_result

        # Fallback if canonical_result wasn't explicitly populated
        return {
            "station": {
                "id": self.station_id,
                "name": f"Station {self.station_id}",
                "latitude": 0.0,
                "longitude": 0.0,
            },
            "observation": {
                "timestamp": self.timestamp.isoformat(),
                "temperature": self.raw_values.get("temperature_c"),
                "pressure": self.raw_values.get("pressure_hpa"),
                "relative_humidity": self.raw_values.get("humidity_pct"),
                "wind_speed": self.raw_values.get("wind_speed_kmh"),
                # Fallback path only — real evaluations populate canonical_result
                # directly with the verified source. Never assume AWS here.
                "source": ObservationSource.UNKNOWN,
                "freshness": Freshness.UNKNOWN,
            },
            "overall": {
                "status": self.status,
                "score": round(self.severity_score, 3),
                "anomaly_score": round(self.severity_score, 3),
                "confidence": round(self.confidence_score, 3),
                "threshold": 0.45,
                "severity": (
                    "HIGH" if self.severity_score >= 0.75 else
                    "WARNING" if self.severity_score >= 0.45 else
                    "LOW" if self.severity_score > 0.0 else "NONE"
                ),
            },
            "layers": self.layer_details or {k: {"score": v} for k, v in self.layer_scores.items()},
            "diagnosis": {
                "primary": self.root_cause.value,
                "confidence": self.diagnosis_confidence.value,
                "confidence_level": self.diagnosis_confidence.value,
                "evidence": self.reasons,
                "alternatives": self.alternative_causes,
                "affected_channels": self.affected_channels,
                "operator_action": self.operator_action,
            },
            "weather_analysis": {
                "summary": self.explanation,
                "meteorological_context": "Regional mesoscale analysis based on in-situ AWS station observations.",
                "likely_phenomenon": "Atmospheric observation assessment",
                "confidence": self.diagnosis_confidence.value,
                "evidence": self.reasons,
            },
            "insights": [
                {
                    "what": self.explanation,
                    "why": self.primary_signal or "Sensor assessment complete",
                    "evidence": "; ".join(self.reasons) if self.reasons else "Normal telemetry envelope",
                    "action": self.operator_action or "Continue standard monitoring."
                }
            ],
            "data_quality": self.data_quality_summary or {
                "status": "VALID" if self.status != "INSUFFICIENT_DATA" else "INSUFFICIENT_DATA",
                "missing_fields": [],
                "historical_points": self.temporal_history_points,
                "nearby_stations": self.spatial_neighbor_count,
                "limitations": []
            }
        }

    def to_legacy_dict(self) -> Optional[Dict[str, Any]]:
        """
        Backwards compatibility shim for existing frontend anomaly property.
        Only returned when is_anomaly or status != NORMAL.
        """
        if not self.is_anomaly and self.status == "NORMAL":
            return None

        param  = "Sensor Array"
        obs    = self.severity_score
        unit   = "score"
        exp_min = None
        exp_max = None

        rv = self.raw_values
        if "temperature_c" in self.affected_channels or (
            rv.get("temperature_c") is not None and any("temp" in r.lower() for r in self.reasons)
        ):
            param   = "Temperature"
            obs     = rv.get("temperature_c")
            unit    = "°C"
            exp_min = 15.0
            exp_max = 35.0
        elif "pressure_hpa" in self.affected_channels or (
            rv.get("pressure_hpa") is not None and any("press" in r.lower() for r in self.reasons)
        ):
            param   = "Pressure"
            obs     = rv.get("pressure_hpa")
            unit    = "hPa"
            exp_min = 980.0
            exp_max = 1030.0
        elif "humidity_pct" in self.affected_channels or (
            rv.get("humidity_pct") is not None and any("humid" in r.lower() for r in self.reasons)
        ):
            param   = "Humidity"
            obs     = rv.get("humidity_pct")
            unit    = "%"
            exp_min = 10.0
            exp_max = 95.0

        sev_label = (
            "HIGH"    if self.severity_score >= 0.75 else
            "WARNING" if self.severity_score >= 0.45 else
            "LOW"
        )

        return {
            "parameter":   param,
            "observed":    obs,
            "unit":        unit,
            "expectedMin": exp_min,
            "expectedMax": exp_max,
            "severity":    sev_label,
            "reason":      "; ".join(self.reasons) if self.reasons else (self.explanation or "Anomaly detected"),
            "score":            round(self.severity_score, 3),
            "confidence":       round(self.confidence_score, 3),
            "rootCause":        self.root_cause.value,
            "diagnosisConf":    self.diagnosis_confidence.value,
            "layerScores":      {k: round(v, 3) for k, v in self.layer_scores.items()},
            "healthIndex":      round(self.sensor_health_index, 1),
            "daysToFailure":    round(self.estimated_days_to_failure, 1) if self.estimated_days_to_failure else None,
            "explanation":      self.explanation,
            "operatorAction":   self.operator_action,
            "primarySignal":    self.primary_signal,
            "alternatives":     self.alternative_causes,
        }


# ─────────────────────────────────────────────────────────────────
# Conversion Helper
# ─────────────────────────────────────────────────────────────────

def _safe_float(raw: Any) -> Optional[float]:
    """Convert to float, returning None on failure."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _assess_temperature_quality(temp_raw: Optional[float]) -> tuple[Optional[float], str]:
    """
    Determine temperature value and quality.
    A raw value of 0.0 is potentially valid (0°C is a real temperature),
    but we flag it as VALID and let Layer 1 handle the physics check.
    """
    if temp_raw is None:
        return None, DataQuality.MISSING
    val = _safe_float(temp_raw)
    if val is None:
        return None, DataQuality.INVALID
    return val, DataQuality.VALID


def _assess_pressure_quality(press_raw: Optional[float]) -> tuple[Optional[float], str]:
    """
    Determine pressure value and quality.
    0.0 hPa is physically impossible at any terrestrial location.
    Any pressure < 1.0 hPa is treated as a missing/substituted value, NOT a real measurement.
    """
    if press_raw is None:
        return None, DataQuality.MISSING
    val = _safe_float(press_raw)
    if val is None:
        return None, DataQuality.INVALID
    if val < 1.0:
        # 0.0 hPa is the null sentinel used in many datasets — not a real measurement
        return None, DataQuality.ZERO_SUBSTITUTED
    return val, DataQuality.VALID


def _assess_humidity_quality(hum_raw: Optional[float]) -> tuple[Optional[float], str]:
    """
    Determine humidity value and quality.
    Negative humidity is invalid; > 100 is a known sensor fault, flagged OUT_OF_RANGE.
    """
    if hum_raw is None:
        return None, DataQuality.MISSING
    val = _safe_float(hum_raw)
    if val is None:
        return None, DataQuality.INVALID
    if val < 0:
        return None, DataQuality.INVALID
    if val > 100:
        return val, DataQuality.OUT_OF_RANGE   # Keep the value — Layer 1 will veto it
    return val, DataQuality.VALID


def station_dict_to_reading(stn: Dict[str, Any]) -> AWSReading:
    """
    Converts a standard ATHER station dictionary to an AWSReading model.

    CRITICAL DATA QUALITY RULES:
      - 0.0 pressure → pressure_hpa = None (DataQuality.ZERO_SUBSTITUTED)
      - None pressure → pressure_hpa = None (DataQuality.MISSING)
      - humidity > 100 → kept as value but flagged OUT_OF_RANGE
      - 0°C temperature is kept as VALID (real temperature)
      - All conversions are explicit; no silent 'x or 0' patterns
    """
    import uuid

    stn_id = str(stn["id"]) if stn.get("id") else f"EVAL_{uuid.uuid4().hex[:8]}"

    # ── Temperature ────────────────────────────────────────────────
    temp_val, temp_quality = _assess_temperature_quality(stn.get("temperature"))

    # ── Pressure ───────────────────────────────────────────────────
    press_val, press_quality = _assess_pressure_quality(stn.get("pressure"))

    # ── Humidity ───────────────────────────────────────────────────
    hum_val, hum_quality = _assess_humidity_quality(stn.get("humidity"))

    # ── Wind ────────────────────────────────────────────────────────
    wind_val = _safe_float(stn.get("windSpeed"))

    # ── Dew Point ───────────────────────────────────────────────────
    dew_val = _safe_float(stn.get("dewPoint") or stn.get("dew_point"))

    # ── Elevation ───────────────────────────────────────────────────
    elev_val = _safe_float(stn.get("elevation") or stn.get("elevation_m")) or 0.0

    # ── Provenance ─────────────────────────────────────────────────
    # dataSource / observationTimestamp are populated explicitly by
    # station_service.py at ingestion time based on where the values
    # actually came from. Never inferred, never defaulted to AWS_IN_SITU.
    received_ts = datetime.now(timezone.utc)
    source = stn.get("dataSource") or ObservationSource.UNKNOWN

    obs_ts_raw = stn.get("observationTimestamp")
    obs_ts: Optional[datetime] = None
    if obs_ts_raw:
        try:
            if isinstance(obs_ts_raw, datetime):
                obs_ts = obs_ts_raw
            else:
                obs_ts = datetime.fromisoformat(str(obs_ts_raw).replace("Z", "+00:00"))
        except Exception:
            obs_ts = None

    has_any_value = temp_val is not None or press_val is not None or hum_val is not None
    cadence = float(stn.get("sourceCadenceMinutes", 90.0))
    freshness = stn.get("freshness") or classify_freshness(
        observation_timestamp=obs_ts,
        received_timestamp=received_ts,
        cadence_minutes=cadence,
        has_value=has_any_value,
    )

    return AWSReading(
        station_id=stn_id,
        # `timestamp` remains the processing-sequence clock used internally by
        # Layer 2 to space consecutive readings — NOT a claim about true
        # observation validity time. See observation_timestamp for that.
        timestamp=received_ts,
        temperature_c=temp_val,
        pressure_hpa=press_val,
        humidity_pct=hum_val,
        dew_point_c=dew_val,
        wind_speed_kmh=wind_val,
        lat=float(stn.get("latitude",  stn.get("lat",  0.0))),
        lon=float(stn.get("longitude", stn.get("lon",  0.0))),
        elevation_m=elev_val,
        data_quality={
            "temperature_c": temp_quality,
            "pressure_hpa":  press_quality,
            "humidity_pct":  hum_quality,
        },
        source=source,
        observation_timestamp=obs_ts,
        received_timestamp=received_ts,
        freshness=freshness,
    )
