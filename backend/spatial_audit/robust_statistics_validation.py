"""
S2 — Robust Spatial Statistics: read-only validation against the real
historical Indian weather dataset.

PROVENANCE (must never be described otherwise): see
spatial_audit/README.md and neighborhood_audit.py's module docstring.
ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv is of
UNCERTAIN provenance -- NOT confirmed AWS telemetry, NOT confirmed IMD AWS
telemetry. It is used here ONLY to check that the S2 robust-statistics
pipeline (engine/spatial_statistics.py, wired through
engine/layer4_spatial.py) actually computes on real channel magnitudes and
real spatial neighbor structure, not synthetic fixtures -- NOT as a claim
about regional weather coherence, NOT as ground truth for any accuracy
number.

WHAT THIS DOES NOT CLAIM: this script does not attempt to build a
time-synchronized cross-city snapshot (the raw file stores each city's rows
as one contiguous block, not interleaved by time -- see
neighborhood_audit.py). It takes ONE representative real reading per city
(that city's own first row in the file) and runs the real production
Spatial evaluate() pipeline treating each city as a target against the
other 174 cities' own single readings as its candidate neighbor pool. This
is a COMPUTABILITY AND BEHAVIOR check (does the robust-statistics code path
run correctly and sensibly on real magnitudes/real geography?), NOT a
regional-event or simultaneous-weather-coherence analysis -- those remain
S3+ scope and are explicitly not attempted here.

MEMORY SAFETY: reads ONLY city/lat/lon/temperature_C/humidity_pct/
pressure_hPa (never the other columns) in chunks; keeps only one row per
city (~175 rows total) in memory. The raw CSV is opened read-only and never
modified, copied, or committed.

Run:
    cd backend
    python3 -m spatial_audit.robust_statistics_validation
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd

from config import CONFIG
from schema import AWSReading
from engine.layer4_spatial import SpatialNeighborLayer
from engine.spatial_neighbors import is_valid_coordinate

RAW_CSV_PATH = Path(
    "~/Desktop/sih win/ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv"
).expanduser()
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_robust_statistics_validation.json"
CHUNK_SIZE = 1_000_000
COLUMNS = ["city", "lat", "lon", "temperature_C", "humidity_pct", "pressure_hPa"]


def extract_one_reading_per_city(csv_path: Path, chunk_size: int = CHUNK_SIZE) -> Dict[str, AWSReading]:
    """
    Full single pass (city-blocked file, see neighborhood_audit.py), but
    ONLY 6 narrow columns and only the FIRST valid row kept per city, so
    memory stays at ~175 AWSReading objects regardless of file size.
    """
    readings: Dict[str, AWSReading] = {}
    for chunk in pd.read_csv(csv_path, usecols=COLUMNS, chunksize=chunk_size):
        for row in chunk.itertuples(index=False):
            city = row.city
            if city in readings:
                continue
            lat, lon = row.lat, row.lon
            if pd.isna(lat) or pd.isna(lon) or not is_valid_coordinate(lat, lon):
                continue
            temp = None if pd.isna(row.temperature_C) else float(row.temperature_C)
            rh = None if pd.isna(row.humidity_pct) else float(row.humidity_pct)
            press = None if pd.isna(row.pressure_hPa) else float(row.pressure_hPa)
            readings[city] = AWSReading(
                station_id=city, lat=float(lat), lon=float(lon),
                temperature_c=temp, pressure_hpa=press, humidity_pct=rh,
            )
    return readings


def _distribution(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return {"min": round(s[0], 3), "median": round(s[n // 2], 3), "max": round(s[-1], 3), "mean": round(sum(s) / n, 3)}


def run_validation() -> Dict:
    t0 = time.time()
    readings = extract_one_reading_per_city(RAW_CSV_PATH)
    extract_seconds = time.time() - t0

    all_readings = list(readings.values())
    layer = SpatialNeighborLayer(CONFIG.spatial)

    channels = ["temperature_c", "pressure_hpa", "humidity_pct"]
    per_channel = {ch: {"computed": 0, "insufficient": 0, "idw_z": [], "robust_z_abs": [],
                          "mad_zero_fallback_count": 0} for ch in channels}
    evaluated_locations = 0
    insufficient_locations = 0
    non_finite_detected = 0
    determinism_ok = True

    for target in all_readings:
        score, consensus, reason, detail = layer.evaluate(target, all_readings)
        result_repeat = layer.evaluate(target, list(reversed(all_readings)))

        if detail["status"] == "INSUFFICIENT_NEIGHBORS":
            insufficient_locations += 1
            continue
        evaluated_locations += 1

        for ch in channels:
            ch_res = detail["channel_results"].get(ch, {})
            if "regional_median" not in ch_res:
                per_channel[ch]["insufficient"] += 1
                continue
            per_channel[ch]["computed"] += 1
            per_channel[ch]["idw_z"].append(ch_res["idw_z"])
            per_channel[ch]["robust_z_abs"].append(abs(ch_res["robust_z"]))
            if ch_res["robust_z_method"] == "MIN_SCALE_FALLBACK":
                per_channel[ch]["mad_zero_fallback_count"] += 1
            import math
            if not (math.isfinite(ch_res["regional_median"]) and math.isfinite(ch_res["regional_mad"])
                    and math.isfinite(ch_res["robust_z"])):
                non_finite_detected += 1

            repeat_res = result_repeat[3]["channel_results"].get(ch, {})
            if repeat_res.get("regional_median") != ch_res.get("regional_median") or \
               repeat_res.get("robust_z") != ch_res.get("robust_z"):
                determinism_ok = False

    report = {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance. NOT "
            "confirmed AWS telemetry. NOT confirmed IMD AWS telemetry. This "
            "is a COMPUTABILITY/BEHAVIOR check of the S2 robust-statistics "
            "pipeline on real magnitudes and real geography, NOT a "
            "regional-event or simultaneous-weather-coherence claim, and "
            "NOT an accuracy measurement of any kind."
        ),
        "method_disclaimer": (
            "Each city contributes ONE representative reading (its own "
            "first row in the file) -- these are NOT simultaneous "
            "cross-city observations. This validates that the robust "
            "statistics pipeline runs correctly on real values/real "
            "geography, not a claim about real-time regional coherence."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "extract_seconds": round(extract_seconds, 2),
        "unique_locations_extracted": len(all_readings),
        "spatial_config_used": {
            "radius_km_max": CONFIG.spatial.neighbor_distance_km_max,
            "k_neighbors": CONFIG.spatial.spatial_k_neighbors,
            "min_neighbors_required": CONFIG.spatial.min_neighbors_required,
        },
        "locations_evaluated_with_sufficient_neighbors": evaluated_locations,
        "locations_insufficient_neighbors": insufficient_locations,
        "non_finite_robust_values_detected": non_finite_detected,
        "determinism_verified": determinism_ok,
        "per_channel": {
            ch: {
                "channels_computed": per_channel[ch]["computed"],
                "channels_insufficient_valid_neighbors": per_channel[ch]["insufficient"],
                "mad_zero_fallback_count": per_channel[ch]["mad_zero_fallback_count"],
                "idw_z_distribution": _distribution(per_channel[ch]["idw_z"]),
                "robust_z_abs_distribution": _distribution(per_channel[ch]["robust_z_abs"]),
            }
            for ch in channels
        },
        "method": (
            "Runs the REAL production engine.layer4_spatial.SpatialNeighborLayer."
            "evaluate() (which internally uses the real S1 "
            "select_k_nearest_neighbors() and the real S2 "
            "compute_robust_spatial_evidence()) for each of the 175 real "
            "city locations as a target against the other 174 real "
            "locations as its candidate neighbor pool, using the real "
            "CONFIG.spatial values -- not a reimplemented calculation."
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
