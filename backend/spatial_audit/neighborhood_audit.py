"""
S1 — Data Audit & Neighborhood Foundation: lightweight, read-only spatial
neighborhood audit against the real historical Indian weather dataset.

PROVENANCE (must never be described otherwise):
ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv is historical
Indian weather data of UNCERTAIN provenance. It is NOT confirmed AWS
telemetry and NOT confirmed IMD AWS telemetry (documented in the earlier
real-weather-audit workstream as likely model/reanalysis-derived, given
data characteristics -- zero missing values, zero malformed rows, near-
perfect 30-year hourly continuity -- that are atypical of raw physical
sensor telemetry). It is used here ONLY to audit whether the new S1
K-nearest-neighbor spatial-selection foundation (engine/spatial_neighbors.py)
behaves sensibly against a real, geographically distributed set of
station-like locations -- NOT as production input, NOT as AWS ground truth,
NOT for regional-event/clustering conclusions (those are later stages).

MEMORY SAFETY: the raw CSV is ~7.2GB / ~46M rows and lives OUTSIDE this
repository. This audit needs only UNIQUE (city, lat, lon) locations, not
every hourly observation -- so it reads just the 3 required columns
(city, lat, lon) in bounded chunks and stops as soon as a full chunk adds no
new city, rather than scanning the whole file. The raw CSV is opened
read-only; it is never modified, copied into the repo, or committed.

METHOD: once the unique locations are extracted, this script builds one
schema.AWSReading per location and runs the SAME production
engine.spatial_neighbors.select_k_nearest_neighbors() used by the real
Spatial layer -- not a separate/duplicated distance implementation -- using
the real CONFIG.spatial.neighbor_distance_km_max / spatial_k_neighbors
values, so the audit measures the actual shipped behavior.

Run:
    cd backend
    python3 -m spatial_audit.neighborhood_audit
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd

from config import CONFIG
from schema import AWSReading
from engine.spatial_neighbors import select_k_nearest_neighbors, is_valid_coordinate

RAW_CSV_PATH = Path(
    "~/Desktop/sih win/ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv"
).expanduser()
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_neighborhood_audit.json"
CHUNK_SIZE = 1_000_000
# Safety cap only. The raw CSV stores each city's ~264,840 hourly rows as one
# CONTIGUOUS block (verified empirically), NOT interleaved by time across
# cities -- so a "stop once a chunk adds zero new cities" heuristic is
# unsound here (a whole 1M-row chunk can land entirely inside one city's
# block). Because only 3 narrow columns are read (city, lat, lon), a full
# single-pass scan of all ~46M rows measured at ~10s per 20M rows (~23s for
# the full file) -- cheap enough to just read the whole file once rather
# than rely on a fragile early-stop heuristic. MAX_CHUNKS is a generous cap
# well above the ~47 chunks actually needed, purely as a runaway guard.
MAX_CHUNKS = 60


def extract_unique_locations(
    csv_path: Path, chunk_size: int = CHUNK_SIZE, max_chunks: int = MAX_CHUNKS
) -> Tuple[Dict[str, Tuple[float, float]], int, int, int]:
    """
    Reads ONLY city/lat/lon (never the other 19 columns) in bounded chunks
    across the full file. Returns (locations, total_rows_scanned,
    chunks_read, invalid_or_missing_coordinate_rows_skipped).
    """
    seen: Dict[str, Tuple[float, float]] = {}
    invalid_coord_rows = 0
    total_rows_scanned = 0
    chunks_read = 0

    for chunk in pd.read_csv(csv_path, usecols=["city", "lat", "lon"], chunksize=chunk_size):
        chunks_read += 1
        total_rows_scanned += len(chunk)
        for city, lat, lon in zip(chunk["city"], chunk["lat"], chunk["lon"]):
            if city in seen:
                continue
            if pd.isna(lat) or pd.isna(lon) or not is_valid_coordinate(lat, lon):
                invalid_coord_rows += 1
                continue
            seen[city] = (float(lat), float(lon))
        if chunks_read >= max_chunks:
            break

    return seen, total_rows_scanned, chunks_read, invalid_coord_rows


def _distribution(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return {
        "min": round(s[0], 2),
        "median": round(s[n // 2], 2),
        "max": round(s[-1], 2),
        "mean": round(sum(s) / n, 2),
    }


def run_audit() -> Dict:
    t0 = time.time()
    locations, rows_scanned, chunks_read, invalid_coord_rows = extract_unique_locations(RAW_CSV_PATH)
    extract_seconds = time.time() - t0

    readings = {
        city: AWSReading(station_id=city, lat=lat, lon=lon)
        for city, (lat, lon) in locations.items()
    }
    all_readings = list(readings.values())
    radius_km = CONFIG.spatial.neighbor_distance_km_max
    k = CONFIG.spatial.spatial_k_neighbors

    neighbor_counts_uncapped = []  # within radius, no K cap (true population)
    neighbor_counts_capped = []    # within radius, after the real K cap
    nn_distances = []              # nearest-neighbor distance per location
    determinism_ok = True

    for reading in all_readings:
        capped = select_k_nearest_neighbors(reading, all_readings, radius_km=radius_km, k=k)
        uncapped = select_k_nearest_neighbors(reading, all_readings, radius_km=radius_km, k=len(all_readings))

        neighbor_counts_capped.append(len(capped.neighbors))
        neighbor_counts_uncapped.append(len(uncapped.neighbors))
        if uncapped.neighbors:
            nn_distances.append(uncapped.neighbors[0].distance_km)

        # Determinism check: re-run selection for this same location and
        # confirm the ordered neighbor id list is byte-identical.
        repeat = select_k_nearest_neighbors(reading, all_readings, radius_km=radius_km, k=k)
        if [n.station_id for n in capped.neighbors] != [n.station_id for n in repeat.neighbors]:
            determinism_ok = False

    n_locations = len(all_readings)
    report = {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance (documented "
            "as likely model/reanalysis-derived). NOT confirmed AWS telemetry. "
            "NOT confirmed IMD AWS telemetry. Used only to audit the S1 spatial "
            "neighbor-selection foundation -- not production input, not a "
            "regional-event or clustering conclusion."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "extract_seconds": round(extract_seconds, 2),
        "rows_scanned_of_full_file": rows_scanned,
        "chunks_read": chunks_read,
        "chunk_size": CHUNK_SIZE,
        "note_on_scan_scope": (
            "Only city/lat/lon were read (not the full ~22-column file) -- "
            "this audit does not need per-hour observations, only unique "
            "geography. A full single pass was required (rather than an "
            "early-stop heuristic) because each city's rows are stored as "
            "one contiguous block in this file, not interleaved by time; "
            "reading only these 3 narrow columns kept the full pass to "
            "~23 seconds."
        ),
        "unique_locations_found": n_locations,
        "invalid_or_missing_coordinate_rows_skipped": invalid_coord_rows,
        "spatial_config_used": {
            "radius_km_max": radius_km,
            "k_neighbors": k,
            "source": "CONFIG.spatial (production config, unmodified)",
        },
        "locations_with_ge_1_neighbor_within_radius": sum(1 for c in neighbor_counts_uncapped if c >= 1),
        "locations_with_ge_2_neighbors_within_radius": sum(1 for c in neighbor_counts_uncapped if c >= 2),
        "locations_with_zero_neighbors_within_radius": sum(1 for c in neighbor_counts_uncapped if c == 0),
        "neighbor_count_distribution_before_k_cap": _distribution(neighbor_counts_uncapped),
        "neighbor_count_distribution_after_k_cap": _distribution(neighbor_counts_capped),
        "nearest_neighbor_distance_km_distribution": _distribution(nn_distances),
        "k_nearest_selection_determinism_verified": determinism_ok,
        "method": (
            "Uses the SAME production select_k_nearest_neighbors()/"
            "is_valid_coordinate() implementation from "
            "engine/spatial_neighbors.py against each unique location's real "
            "AWSReading(lat, lon), and the real CONFIG.spatial radius/K "
            "values -- not a separate ad hoc distance calculation."
        ),
    }
    return report


def main():
    report = run_audit()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\nWritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
