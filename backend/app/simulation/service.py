"""
ATHER Test Lab — Simulation Engine
===================================
Runs predefined (or custom) fault-injection scenarios through the REAL
ATHER 5-layer diagnostic engine, fusion, and root-cause classifier — the
exact same code path production uses (app.anomaly.detector.AnomalyDetector).

ISOLATION GUARANTEE (Phase 7/9/24 of the Test Lab spec):
  - Every simulation run constructs a BRAND NEW AnomalyDetector() instance.
    It never touches the global production `detector` singleton, its layer
    buffers, its alert/canonical caches, or its spatial pool.
  - Simulated stations always use a "SIM-" station id prefix and are never
    written into station_service._stations (production station registry).
  - A real station may be READ (never written) to inherit realistic
    baseline metadata (location, elevation, current values) for the
    simulation's starting point.
  - Every observation constructed here is tagged
    ObservationSource.SYNTHETIC_TEST so it can never be confused with a real
    AWS or NWP reading anywhere downstream.

THIS IS NOT A FAKE TEST ENGINE (Phase 9): there is no
`if scenario == "x": return "ANOMALY"` anywhere in this file. Every
diagnostic conclusion below is produced by literally calling
`AnomalyDetector.evaluate_reading()` — the same function station_service.py
calls for every real observation.
"""
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from schema import AWSReading, ObservationSource, FaultType, DiagnosisConfidence
from app.anomaly.detector import AnomalyDetector
from app.stations.service import station_service
from .scenarios import Scenario, ScenarioStep, get_scenario, list_scenarios as _list_scenarios

DEFAULT_LAT = 17.3850
DEFAULT_LON = 78.4867
DEFAULT_ELEVATION_M = 500.0


def _new_sim_station_id() -> str:
    suffix = "".join(random.choices(string.digits, k=3))
    return f"SIM-AWS-{suffix}"


def _bucket_for_alert(alert) -> str:
    """
    Maps the REAL engine's diagnosis onto one of five broad outcome buckets
    used purely for the Test Lab's expected-vs-actual comparison. This never
    feeds back into the diagnosis itself.
    """
    if not alert.is_anomaly and alert.status == "NORMAL":
        return "NORMAL"
    if alert.veto_fired:
        return "DATA_QUALITY_VIOLATION"
    if alert.diagnosis_confidence == DiagnosisConfidence.INSUFFICIENT_DATA or alert.root_cause in (
        FaultType.INSUFFICIENT_EVIDENCE, FaultType.COMMUNICATION_OUTAGE,
    ):
        return "INSUFFICIENT_EVIDENCE"
    if alert.root_cause in (FaultType.GENUINE_EXTREME_WEATHER, FaultType.POSSIBLE_WEATHER_CHANGE):
        return "POSSIBLE_WEATHER_EVENT"
    if alert.root_cause in (
        FaultType.SENSOR_SPIKE, FaultType.FROZEN_SENSOR, FaultType.CALIBRATION_DRIFT,
        FaultType.SINGLE_CHANNEL_FAULT, FaultType.NOISE_BURST, FaultType.MODEL_REFERENCE_INCONSISTENCY,
    ):
        return "LIKELY_SENSOR_ANOMALY"
    return "UNCLASSIFIED"


def _resolve_baseline(base_station_id: Optional[str]) -> Dict[str, Any]:
    """Read-only inheritance of realistic metadata from a real station. Never
    mutates the real station and never uses its exact live values as if they
    were themselves a simulation input — only location/elevation are used
    for spatial realism; scenario values always come from the scenario def."""
    if base_station_id:
        stn = station_service.get_station(base_station_id)
        if stn:
            return {
                "lat": float(stn.get("latitude", DEFAULT_LAT)),
                "lon": float(stn.get("longitude", DEFAULT_LON)),
                "elevation_m": float(stn.get("elevation", DEFAULT_ELEVATION_M) or DEFAULT_ELEVATION_M),
                "base_station_id": base_station_id,
                "base_station_name": stn.get("name"),
            }
    return {
        "lat": DEFAULT_LAT, "lon": DEFAULT_LON, "elevation_m": DEFAULT_ELEVATION_M,
        "base_station_id": None, "base_station_name": None,
    }


def _step_to_reading(
    station_id: str, step: ScenarioStep, lat: float, lon: float, elevation_m: float, ts: datetime,
) -> AWSReading:
    return AWSReading(
        station_id=station_id,
        timestamp=ts,
        temperature_c=step.temperature_c,
        pressure_hpa=step.pressure_hpa,
        humidity_pct=step.humidity_pct,
        lat=lat,
        lon=lon,
        elevation_m=elevation_m,
        source=ObservationSource.SYNTHETIC_TEST,
        observation_timestamp=ts,
        received_timestamp=ts,
        freshness="LIVE",
    )


def run_simulation(scenario_id: str, base_station_id: Optional[str] = None) -> Dict[str, Any]:
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario '{scenario_id}'. See /api/simulation/scenarios.")

    baseline = _resolve_baseline(base_station_id)
    sim_station_id = _new_sim_station_id()

    # A BRAND NEW, throwaway detector instance — this is the isolation
    # boundary. Nothing here can leak into production state.
    sim_detector = AnomalyDetector()

    now = datetime.now(timezone.utc)
    step_count = len(scenario.steps)
    base_ts = now - timedelta(minutes=scenario.interval_minutes * (step_count - 1))

    # Build synthetic neighbor readings per target-step index (constant if
    # the neighbor's own step list is shorter than the target's).
    neighbor_series: List[List[AWSReading]] = []
    for n_idx, neighbor in enumerate(scenario.neighbors):
        n_id = f"{sim_station_id}-N{n_idx+1}"
        series = []
        for i in range(step_count):
            step = neighbor.steps[min(i, len(neighbor.steps) - 1)]
            ts = base_ts + timedelta(minutes=scenario.interval_minutes * i)
            series.append(_step_to_reading(
                n_id, step, baseline["lat"] + neighbor.lat_offset, baseline["lon"] + neighbor.lon_offset,
                baseline["elevation_m"], ts,
            ))
        neighbor_series.append(series)

    observations: List[Dict[str, Any]] = []
    alert = None
    for i, step in enumerate(scenario.steps):
        ts = base_ts + timedelta(minutes=scenario.interval_minutes * i)
        reading = _step_to_reading(sim_station_id, step, baseline["lat"], baseline["lon"], baseline["elevation_m"], ts)
        neighbors_at_step = [series[i] for series in neighbor_series]
        alert = sim_detector.evaluate_reading(reading, neighbors=neighbors_at_step)
        observations.append({
            "step": i + 1,
            "timestamp": ts.isoformat(),
            "temperature": step.temperature_c,
            "pressure": step.pressure_hpa,
            "humidity": step.humidity_pct,
            "status": alert.status,
            "is_anomaly": alert.is_anomaly,
        })

    assert alert is not None  # scenarios always have >= 1 step

    actual_bucket = _bucket_for_alert(alert)
    expected_bucket = scenario.expected_bucket
    test_passed = actual_bucket == expected_bucket

    layers_agreeing = sum(
        1 for k, v in alert.layer_scores.items()
        if (v >= 0.5) == (actual_bucket in ("LIKELY_SENSOR_ANOMALY", "DATA_QUALITY_VIOLATION", "POSSIBLE_WEATHER_EVENT"))
    )

    canonical = alert.canonical_result or alert.to_canonical_dict()

    return {
        "simulation": True,
        "station": {
            "id": sim_station_id,
            "name": f"Virtual AWS Station ({scenario.name})",
            "latitude": baseline["lat"],
            "longitude": baseline["lon"],
            "elevation_m": baseline["elevation_m"],
            "inherited_from": baseline["base_station_id"],
            "inherited_from_name": baseline["base_station_name"],
        },
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "description": scenario.description,
            "expected_bucket": expected_bucket,
            "expected_root_cause_hint": scenario.expected_root_cause_hint,
        },
        "observations": observations,
        "final_observation": {
            "temperature": alert.raw_values.get("temperature_c"),
            "pressure": alert.raw_values.get("pressure_hpa"),
            "humidity": alert.raw_values.get("humidity_pct"),
        },
        "diagnostics": canonical.get("layers", {}),
        "fusion": {
            "status": alert.status,
            "score": round(alert.severity_score, 3),
            "confidence": round(alert.confidence_score, 3),
            "interpretation": alert.explanation,
            "veto_fired": alert.veto_fired,
        },
        "root_cause": {
            "category": alert.root_cause.value,
            "confidence": alert.diagnosis_confidence.value,
            "evidence": alert.reasons,
            "primary_signal": alert.primary_signal,
            "alternatives": alert.alternative_causes,
        },
        "recommended_action": alert.operator_action,
        "insight": canonical.get("insights", []),
        "weather_analysis": canonical.get("weather_analysis", {}),
        "test_result": {
            "expected_bucket": expected_bucket,
            "actual_bucket": actual_bucket,
            "passed": test_passed,
            "layers_agreeing": layers_agreeing,
            "layers_total": len(alert.layer_scores),
            "note": (
                "Actual diagnosis matches the scenario hypothesis."
                if test_passed else
                "The real engine reached a different (but not necessarily wrong) conclusion "
                "than the scenario's hypothesis. This is reported honestly rather than forced to PASS."
            ),
        },
        "performance_label": "SYNTHETIC TEST PERFORMANCE — not a measure of real-world operational accuracy.",
    }


def list_scenarios() -> List[Dict[str, Any]]:
    return _list_scenarios()
