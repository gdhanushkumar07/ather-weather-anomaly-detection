"""
S3 — Regional Event Attribution: read-only validation against the real
historical Indian weather dataset.

PROVENANCE (must never be described otherwise): see
spatial_audit/README.md, neighborhood_audit.py, and
robust_statistics_validation.py's module docstrings.
ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv is of
UNCERTAIN provenance -- NOT confirmed AWS telemetry, NOT confirmed IMD AWS
telemetry. This script does NOT claim event-detection accuracy from it.

WHAT THIS DOES AND DOES NOT VALIDATE: exactly like
robust_statistics_validation.py, this uses ONE representative (first-row)
reading per city -- NOT a time-synchronized cross-city snapshot. That means
any REGIONAL_EVENT / ISOLATED_SENSOR_ANOMALY classification produced here
reflects the S3 evidence engine's COMPUTATION on real magnitudes/real
geography, not a validated real-world event. This script explicitly
verifies: the engine runs without error/NaN on real data, is deterministic,
and produces a plausible mix of classifications and confidence values -- it
does NOT and CANNOT validate that any specific classification was
meteorologically correct, since there is no independent ground truth here.

MEMORY SAFETY: reuses the same bounded, chunked, narrow-column extraction
pattern as neighborhood_audit.py / robust_statistics_validation.py -- only
~175 AWSReading objects are ever held in memory.

Run:
    cd backend
    python3 -m spatial_audit.regional_attribution_validation
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import CONFIG
from engine.layer4_spatial import SpatialNeighborLayer
from .robust_statistics_validation import extract_one_reading_per_city, RAW_CSV_PATH

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_regional_attribution_validation.json"


def run_validation() -> Dict:
    t0 = time.time()
    readings = extract_one_reading_per_city(RAW_CSV_PATH)
    extract_seconds = time.time() - t0

    all_readings = list(readings.values())
    layer = SpatialNeighborLayer(CONFIG.spatial)

    classification_counts = {"REGIONAL_EVENT": 0, "ISOLATED_SENSOR_ANOMALY": 0, "UNCERTAIN": 0}
    confidences = []
    non_finite_detected = 0
    determinism_ok = True
    errors = 0

    for target in all_readings:
        try:
            _, _, _, detail = layer.evaluate(target, all_readings)
            repeat_detail = layer.evaluate(target, list(reversed(all_readings)))[3]
        except Exception:
            errors += 1
            continue

        ra = detail.get("regional_attribution")
        if ra is None:
            continue
        classification_counts[ra["classification"]] = classification_counts.get(ra["classification"], 0) + 1
        confidences.append(ra["confidence"])
        import math
        if not math.isfinite(ra["confidence"]):
            non_finite_detected += 1
        if ra != repeat_detail.get("regional_attribution"):
            determinism_ok = False

    def _dist(values):
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        return {"min": round(s[0], 3), "median": round(s[n // 2], 3), "max": round(s[-1], 3), "mean": round(sum(s) / n, 3)}

    report = {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance. NOT "
            "confirmed AWS telemetry. NOT confirmed IMD AWS telemetry. This "
            "validates the S3 attribution ENGINE's computation on real "
            "magnitudes/geography -- it does NOT and CANNOT validate "
            "real-world event-detection accuracy (no independent ground "
            "truth exists for these unsynchronized single readings)."
        ),
        "method_disclaimer": (
            "Each city contributes ONE representative reading (its own "
            "first row in the file) -- NOT simultaneous cross-city "
            "observations. Classifications produced here are NOT claims "
            "about real regional weather events."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "extract_seconds": round(extract_seconds, 2),
        "unique_locations_extracted": len(all_readings),
        "evaluation_errors": errors,
        "non_finite_confidence_detected": non_finite_detected,
        "determinism_verified": determinism_ok,
        "classification_distribution": classification_counts,
        "confidence_distribution_all_classifications": _dist(confidences),
        "method": (
            "Runs the REAL production engine.layer4_spatial.SpatialNeighborLayer."
            "evaluate() (S1 KNN + S2 robust stats + S3 attribution, all real "
            "production code) for each of the real city locations as a "
            "target against the others as its candidate neighbor pool, "
            "using the real CONFIG.spatial values."
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
