"""
S4 — Spatial Clustering & Event Fingerprinting: read-only validation
against the real historical Indian weather dataset.

PROVENANCE (must never be described otherwise): see
spatial_audit/README.md and the S1/S2/S3 validation scripts' docstrings.
ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv is of
UNCERTAIN provenance -- NOT confirmed AWS telemetry, NOT confirmed IMD AWS
telemetry, has NO ground-truth event labels. This script does NOT claim
clustering accuracy.

CRITICAL: NO FALSE SIMULTANEOUS EVENTS. Exactly like
robust_statistics_validation.py and regional_attribution_validation.py,
this uses ONE representative (first-row) reading per city -- these are NOT
synchronized to the same real-world timestamp. Any cluster this script
finds reflects the S4 clustering ENGINE's computation on real
magnitudes/real geography from UNSYNCHRONIZED rows, never a claim that a
real simultaneous regional weather event occurred. This is stated in the
output's own provenance/method disclaimers, not just in this docstring.

WHAT THIS VALIDATES: clustering computability (no crashes/NaN across real
station geography and magnitudes), determinism (same input -> same
clusters/fingerprints, reversed order -> same result), coordinate handling,
and fingerprint generation -- NOT clustering "accuracy" (there is no
ground truth to measure accuracy against).

MEMORY SAFETY: reuses the same bounded, chunked, narrow-column extraction
already built for S2/S3 (robust_statistics_validation.py) -- only ~175
AWSReading objects are ever held in memory. The full detector pipeline
(S1-S4) then runs entirely in memory over that small set; no further file
I/O happens during clustering.

Run:
    cd backend
    python3 -m spatial_audit.spatial_clustering_validation
"""
import json
import math
import sys
import time
from pathlib import Path
from typing import Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.anomaly.detector import AnomalyDetector
from .robust_statistics_validation import extract_one_reading_per_city, RAW_CSV_PATH

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_clustering_validation.json"


def run_validation() -> Dict:
    t0 = time.time()
    readings = extract_one_reading_per_city(RAW_CSV_PATH)
    extract_seconds = time.time() - t0

    all_readings = list(readings.values())

    det = AnomalyDetector()
    det.update_spatial_pool(all_readings)
    t1 = time.time()
    for r in all_readings:
        det.evaluate_reading(r)
    evaluate_seconds = time.time() - t1

    t2 = time.time()
    events = det.compute_spatial_events()
    events_repeat = det.compute_spatial_events()
    cluster_seconds = time.time() - t2

    determinism_ok = events == events_repeat

    non_finite = 0
    for c in events["clusters"]:
        vals = [c["coherence"], c["centroid"]["lat"], c["centroid"]["lon"], c["spatial_extent_km"]]
        if not all(math.isfinite(v) for v in vals):
            non_finite += 1

    cluster_sizes = [c["member_count"] for c in events["clusters"]]

    report = {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance. NOT "
            "confirmed AWS telemetry. NOT confirmed IMD AWS telemetry. NO "
            "ground-truth event labels exist for this data -- this script "
            "does NOT and CANNOT measure clustering accuracy."
        ),
        "method_disclaimer": (
            "Each city contributes ONE representative reading (its own "
            "first row in the file) -- these are UNSYNCHRONIZED, NOT "
            "simultaneous real-world observations. Any cluster reported "
            "below is a computability/determinism check of the S4 engine "
            "on real magnitudes/geography, NOT a claim that a real, "
            "simultaneous regional weather event occurred."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "extract_seconds": round(extract_seconds, 2),
        "evaluate_seconds_all_stations": round(evaluate_seconds, 2),
        "cluster_seconds": round(cluster_seconds, 4),
        "unique_locations_extracted": len(all_readings),
        "candidates_considered": events["candidates_considered"],
        "cluster_count": events["cluster_count"],
        "largest_cluster_size": events["largest_cluster_size"],
        "cluster_sizes": sorted(cluster_sizes, reverse=True),
        "unclustered_candidate_count": len(events["unclustered_candidate_ids"]),
        "non_finite_fingerprint_values_detected": non_finite,
        "determinism_verified": determinism_ok,
        "parameters": events["parameters"],
        "method": (
            "Runs the REAL production pipeline: AnomalyDetector.evaluate_reading() "
            "(S1 KNN + S2 robust stats + S3 attribution) for each of the real city "
            "locations, then AnomalyDetector.compute_spatial_events() (S4 DBSCAN "
            "clustering, real production code) ONCE over the resulting candidate set -- "
            "not a reimplemented or simplified clustering pass."
        ),
    }
    return report


def main():
    report = run_validation()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\nWritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
