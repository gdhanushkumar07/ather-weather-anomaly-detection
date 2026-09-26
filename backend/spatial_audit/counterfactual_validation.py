"""
S6 — Counterfactual Verification: read-only validation.

PROVENANCE (must never be described otherwise): see spatial_audit/README.md
and the S1-S5 validation scripts' docstrings. ATHER_DATA/indian_weather_
1996_2026/Indian_Weather_Dataset.csv is of UNCERTAIN provenance -- NOT
confirmed AWS telemetry, NOT confirmed IMD AWS telemetry, NO ground-truth
labels of "genuinely regional" vs "genuinely isolated" exist for it. This
script does NOT and CANNOT measure real-world counterfactual-verification
accuracy.

WHY THIS REUSES THE S2/S3/S4-STYLE ONE-ROW-PER-CITY EXTRACTION (NOT S5's
temporally-aligned approach): S6, like S2/S3/S4, is a SINGLE-SNAPSHOT
spatial mechanism -- it answers "do CURRENTLY OBSERVED neighbors support or
contradict this one reading?" using only the neighbor pool available at
one instant. It has no temporal dimension of its own (unlike S5, which
specifically needs chronological ordering across snapshots). Using one
representative row per city is therefore appropriate here, exactly as it
was for S2/S3/S4's own validation scripts, and is explicitly NOT presented
as a claim about simultaneous real-world conditions.

This script validates:
  1. Controlled synthetic scenarios (via the unit/integration tests
     already in tests/test_spatial_counterfactual.py -- re-run here only
     as a pass/fail summary, not re-implemented).
  2. Existing simulation scenarios (SPATIAL_OUTLIER, REGIONAL_WEATHER_EVENT,
     COMBINED_SENSOR_FAILURE) through the real Test Lab simulation service.
  3. Production-shaped station data (data/stations.json).
  4. The real historical dataset, as a computability/determinism check only.
  5. Determinism (repeated calls, reversed neighbor order).
  6. Finite numeric outputs.
  7. Performance.

Run:
    cd backend
    python3 -m spatial_audit.counterfactual_validation
"""
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import math

from app.anomaly.detector import AnomalyDetector
from app.simulation.service import run_simulation
from schema import AWSReading
from .robust_statistics_validation import extract_one_reading_per_city, RAW_CSV_PATH

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_counterfactual_validation.json"


def run_unit_test_summary() -> Dict[str, Any]:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_spatial_counterfactual")
    result = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(suite)
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "all_passed": result.wasSuccessful(),
    }


def run_simulation_scenarios_check() -> Dict[str, Any]:
    scenarios = ["SPATIAL_OUTLIER", "REGIONAL_WEATHER_EVENT", "COMBINED_SENSOR_FAILURE"]
    out = {}
    for name in scenarios:
        result = run_simulation(name)
        cv = result["diagnostics"]["spatial"]["details"].get("counterfactual_verification")
        out[name] = {
            "counterfactual_verification_present": cv is not None,
            "overall_status": cv.get("overall_status") if cv else None,
            "channels_reported": list(cv.get("channels", {}).keys()) if cv else [],
        }
    return out


def run_production_shape_check() -> Dict[str, Any]:
    with open(BACKEND_DIR.parent / "data" / "stations.json") as f:
        raw = json.load(f)
    readings = [
        AWSReading(station_id=s["id"], lat=s["latitude"], lon=s["longitude"],
                   temperature_c=s.get("temperature"), pressure_hpa=s.get("pressure"),
                   humidity_pct=s.get("humidity"))
        for s in raw
    ]
    det = AnomalyDetector()
    det.update_spatial_pool(readings)

    t0 = time.perf_counter()
    non_finite = 0
    statuses_seen = set()
    sample_size = min(300, len(readings))
    for r in readings[:sample_size]:
        alert = det.evaluate_reading(r)
        cv = alert.layer_details["spatial"].get("counterfactual_verification")
        if cv is None:
            continue
        statuses_seen.add(cv["overall_status"])
        for ch in cv["channels"].values():
            if ch["evidence_strength"] is not None and not math.isfinite(ch["evidence_strength"]):
                non_finite += 1
    elapsed = time.perf_counter() - t0

    # Determinism: repeat the very first reading's evaluation and compare its S6 result.
    r0 = readings[0]
    a1 = det.evaluate_reading(r0)
    a2 = det.evaluate_reading(r0)
    determinism_ok = (a1.layer_details["spatial"]["counterfactual_verification"]
                       == a2.layer_details["spatial"]["counterfactual_verification"])

    return {
        "stations_evaluated": sample_size,
        "elapsed_seconds": round(elapsed, 3),
        "ms_per_station": round(elapsed / sample_size * 1000, 3),
        "overall_statuses_observed": sorted(statuses_seen),
        "non_finite_evidence_strength_detected": non_finite,
        "determinism_verified_repeat_call": determinism_ok,
    }


def run_historical_computability_check() -> Dict[str, Any]:
    t0 = time.time()
    readings_map = extract_one_reading_per_city(RAW_CSV_PATH)
    extract_seconds = time.time() - t0
    all_readings = list(readings_map.values())

    det = AnomalyDetector()
    det.update_spatial_pool(all_readings)

    errors = 0
    non_finite = 0
    statuses_seen = set()
    t1 = time.time()
    for r in all_readings:
        try:
            alert = det.evaluate_reading(r)
        except Exception:
            errors += 1
            continue
        cv = alert.layer_details["spatial"].get("counterfactual_verification")
        if cv is None:
            continue
        statuses_seen.add(cv["overall_status"])
        for ch in cv["channels"].values():
            if ch["evidence_strength"] is not None and not math.isfinite(ch["evidence_strength"]):
                non_finite += 1
    evaluate_seconds = time.time() - t1

    # Determinism across a full second pass with reversed pool order.
    det2 = AnomalyDetector()
    det2.update_spatial_pool(list(reversed(all_readings)))
    r0 = all_readings[0]
    cv1 = det.evaluate_reading(r0).layer_details["spatial"].get("counterfactual_verification")
    cv2 = det2.evaluate_reading(r0).layer_details["spatial"].get("counterfactual_verification")
    determinism_ok = cv1 == cv2

    return {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance. NOT confirmed AWS "
            "telemetry. NOT confirmed IMD AWS telemetry. NO ground-truth labels exist for "
            "'genuinely regional' vs 'genuinely isolated' readings -- this checks "
            "computability/determinism only, never real-world verification accuracy."
        ),
        "method_disclaimer": (
            "One representative (first-row) reading per city -- NOT simultaneous "
            "cross-city observations, same scope limitation as the S2/S3/S4 validation "
            "scripts (S6 is a single-snapshot mechanism with no temporal dimension of "
            "its own, unlike S5)."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "extract_seconds": round(extract_seconds, 2),
        "evaluate_seconds": round(evaluate_seconds, 2),
        "unique_locations": len(all_readings),
        "evaluation_errors": errors,
        "non_finite_evidence_strength_detected": non_finite,
        "overall_statuses_observed": sorted(statuses_seen),
        "determinism_verified_reversed_pool_order": determinism_ok,
    }


def run_validation() -> Dict[str, Any]:
    return {
        "unit_tests": run_unit_test_summary(),
        "simulation_scenarios": run_simulation_scenarios_check(),
        "production_shape": run_production_shape_check(),
        "historical_computability": run_historical_computability_check(),
        "method": (
            "Runs the REAL production pipeline (S1 KNN + S2 robust stats + S3 attribution "
            "+ S6 counterfactual verification, all real production code) via "
            "AnomalyDetector.evaluate_reading() -- not a reimplemented or simplified pass."
        ),
    }


def main():
    report = run_validation()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
