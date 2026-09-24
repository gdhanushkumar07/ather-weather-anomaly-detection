"""
S5 — Event Evolution: read-only validation against the real historical
Indian weather dataset, using GENUINE TEMPORAL ORDERING (not one arbitrary
row per city, unlike the S2/S3/S4 validation scripts).

PROVENANCE (must never be described otherwise): see spatial_audit/README.md
and the S1-S4 validation scripts' docstrings. ATHER_DATA/indian_weather_
1996_2026/Indian_Weather_Dataset.csv is of UNCERTAIN provenance -- NOT
confirmed AWS telemetry, NOT confirmed IMD AWS telemetry, NO ground-truth
event-evolution labels exist. This script does NOT and CANNOT measure
event-tracking accuracy.

WHY THIS SCRIPT READS DIFFERENTLY FROM THE S2/S3/S4 VALIDATION SCRIPTS:
S5 needs an actual chronological SEQUENCE of observations per city (to
feed successive real timestamps into SpatialEventTracker.update()), not a
single representative row. This script:
  1. First does the SAME lightweight city/lat/lon-only pass the S1 audit
     uses (spatial_audit/neighborhood_audit.py) to find a small, genuinely
     nearby group of real cities (within the S4 clustering eps).
  2. Then does a SECOND, TARGETED pass reading city/datetime/temperature_C/
     humidity_pct/pressure_hPa ONLY for rows belonging to that small city
     set, collecting a bounded number of their earliest available
     consecutive hourly rows (never the whole file's values, never more
     than needed for a modest multi-day window).
No row is resampled, interpolated, or reordered -- rows are used exactly
as they appear, in their own real datetime order, per city.

CADENCE MISMATCH -- WHY THE GAP POLICY IS OVERRIDDEN FOR THIS SCRIPT ONLY:
This dataset is HOURLY. SpatialEventTracker's DEFAULT gap policy
(CONFIG.lstm_temporal.max_gap_minutes = 15.0) is calibrated for ATHER's
assumed ~10-minute NATIVE AWS cadence (see spatial_event_tracking.py's own
module docstring) -- applying it unchanged to hourly-spaced real data would
make EVERY successive hourly step exceed the gap policy, so no event could
ever be observed persisting even once. This script therefore explicitly
constructs its tracker with max_observation_gap_minutes=90.0 -- NOT a new
invented number, but the SAME existing 90-minute cadence window
schema.py's classify_freshness() already uses as its own documented
default for hourly NWP-model-sourced data. This override is scoped to
THIS validation script only; the production default is untouched.

NO GROUND TRUTH: any GROWING/SHRINKING/MOVING/INTENSIFYING/WEAKENING flag
observed below describes the tracker's OWN deterministic comparison of
consecutive real snapshots -- it is not, and cannot be, validated against
an independent record of what actually happened meteorologically.

Run:
    cd backend
    python3 -m spatial_audit.event_evolution_validation
"""
import json
import sys
import time
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd

from app.anomaly.detector import AnomalyDetector
from engine.spatial_event_tracking import SpatialEventTracker
from engine.spatial_neighbors import is_valid_coordinate, haversine_distance_km
from schema import AWSReading
from .neighborhood_audit import extract_unique_locations, RAW_CSV_PATH as GEOMETRY_CSV_PATH
from .robust_statistics_validation import RAW_CSV_PATH

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_event_evolution_validation.json"

TARGET_GROUP_SIZE = 11          # how many nearby cities to select (11 is the actual maximum available within
                                 # GROUP_SEARCH_RADIUS_KM of the densest real hub in this dataset -- confirmed
                                 # empirically, not an arbitrary round number)
MAX_HOURS_PER_CITY = 2000       # bounded time-series window (~83 days, to span more real weather variation)
GROUP_SEARCH_RADIUS_KM = 125.0  # same as the S4 clustering eps -- select cities that could plausibly cluster
HOURLY_GAP_MINUTES_OVERRIDE = 90.0  # see module docstring's "CADENCE MISMATCH" section


def select_nearby_city_group(radius_km: float, group_size: int) -> List[Tuple[str, float, float]]:
    """Reuses the S1 audit's own lightweight city/lat/lon extraction, then
    picks the city with the most other cities within radius_km, plus that
    many nearest neighbors -- a real, densest available nearby group."""
    locations, _, _, _ = extract_unique_locations(GEOMETRY_CSV_PATH)
    items = list(locations.items())

    best_city, best_neighbors = None, []
    for city, (lat, lon) in items:
        neighbors = []
        for other_city, (o_lat, o_lon) in items:
            if other_city == city:
                continue
            d = haversine_distance_km(lat, lon, o_lat, o_lon)
            if d <= radius_km:
                neighbors.append((d, other_city, o_lat, o_lon))
        if len(neighbors) > len(best_neighbors):
            best_city, best_neighbors = city, neighbors

    best_neighbors.sort(key=lambda t: (t[0], t[1]))
    group = [(best_city, locations[best_city][0], locations[best_city][1])]
    for d, city, lat, lon in best_neighbors[: group_size - 1]:
        group.append((city, lat, lon))
    return group


def extract_hourly_series(cities: List[str], max_hours: int) -> Dict[str, pd.DataFrame]:
    """Targeted second pass: collects up to max_hours consecutive rows per
    selected city (in file order, which is chronological within each
    city's own contiguous block -- verified by the S1/S2 audits), reading
    only the columns needed. Stops each city independently once it has
    enough rows; stops the whole scan once every city has enough or the
    file is exhausted."""
    remaining = {c: max_hours for c in cities}
    collected: Dict[str, List[dict]] = {c: [] for c in cities}
    cities_set = set(cities)

    for chunk in pd.read_csv(
        RAW_CSV_PATH,
        usecols=["city", "datetime", "temperature_C", "humidity_pct", "pressure_hPa"],
        chunksize=500_000,
    ):
        sub = chunk[chunk["city"].isin(cities_set)]
        if len(sub) == 0:
            if all(v <= 0 for v in remaining.values()):
                break
            continue
        for city, group in sub.groupby("city"):
            need = remaining.get(city, 0)
            if need <= 0:
                continue
            take = group.iloc[:need]
            collected[city].extend(take.to_dict("records"))
            remaining[city] -= len(take)
        if all(v <= 0 for v in remaining.values()):
            break

    return {
        c: pd.DataFrame(rows).assign(datetime=lambda d: pd.to_datetime(d["datetime"])).sort_values("datetime")
        for c, rows in collected.items()
    }


def run_validation() -> Dict:
    t0 = time.time()
    group = select_nearby_city_group(GROUP_SEARCH_RADIUS_KM, TARGET_GROUP_SIZE)
    group_seconds = time.time() - t0
    city_names = [c for c, _, _ in group]
    coords = {c: (lat, lon) for c, lat, lon in group}

    t1 = time.time()
    series = extract_hourly_series(city_names, MAX_HOURS_PER_CITY)
    extract_seconds = time.time() - t1

    usable_cities = [c for c in city_names if len(series[c]) >= 2]
    common_length = min(len(series[c]) for c in usable_cities) if usable_cities else 0

    def run_sequence() -> Dict:
        det = AnomalyDetector()
        tracker = SpatialEventTracker(max_observation_gap_minutes=HOURLY_GAP_MINUTES_OVERRIDE)
        flags_seen = set()
        max_event_duration_minutes = 0.0
        event_ids_ever_created = set()
        hours_processed = 0
        errors = 0

        for i in range(common_length):
            readings = []
            ts = None
            for c in usable_cities:
                row = series[c].iloc[i]
                lat, lon = coords[c]
                if not is_valid_coordinate(lat, lon):
                    continue
                temp = None if pd.isna(row["temperature_C"]) else float(row["temperature_C"])
                rh = None if pd.isna(row["humidity_pct"]) else float(row["humidity_pct"])
                press = None if pd.isna(row["pressure_hPa"]) else float(row["pressure_hPa"])
                readings.append(AWSReading(station_id=c, lat=lat, lon=lon,
                                            temperature_c=temp, pressure_hpa=press, humidity_pct=rh))
                ts = row["datetime"].to_pydatetime().replace(tzinfo=timezone.utc)
            if not readings or ts is None:
                continue
            try:
                det.update_spatial_pool(readings)
                for r in readings:
                    det.evaluate_reading(r)
                result = det.update_spatial_event_tracking(timestamp=ts)
            except Exception:
                errors += 1
                continue
            hours_processed += 1
            for ev in result["active_events"]:
                flags_seen.update(ev["evolution_flags"])
                max_event_duration_minutes = max(max_event_duration_minutes, ev["evidence"]["duration_minutes"])
                event_ids_ever_created.add(ev["event_id"])
            for ev in result["newly_detected_events"]:
                event_ids_ever_created.add(ev["event_id"])

        return {
            "hours_processed": hours_processed, "errors": errors,
            "flags_seen": sorted(flags_seen),
            "max_event_duration_minutes": round(max_event_duration_minutes, 1),
            "distinct_events_created": len(event_ids_ever_created),
        }

    t2 = time.time()
    run1 = run_sequence()
    run_seconds = time.time() - t2
    run2 = run_sequence()
    determinism_ok = run1 == run2

    report = {
        "provenance_disclaimer": (
            "Historical Indian weather data of UNCERTAIN provenance. NOT confirmed AWS "
            "telemetry. NOT confirmed IMD AWS telemetry. NO ground-truth event-evolution "
            "labels exist -- this script does NOT and CANNOT measure event-tracking accuracy."
        ),
        "cadence_disclaimer": (
            f"This dataset is HOURLY. The tracker's default gap policy "
            f"(CONFIG.lstm_temporal.max_gap_minutes, ~10-min AWS cadence) is NOT usable "
            f"unmodified against hourly data -- this script explicitly overrides it to "
            f"{HOURLY_GAP_MINUTES_OVERRIDE} minutes, reusing schema.py's own existing "
            f"90-minute NWP-hourly-cadence freshness window (classify_freshness's default), "
            f"not a new invented number. This override applies to THIS script only."
        ),
        "method_disclaimer": (
            "Uses GENUINE temporal ordering: real consecutive hourly rows per selected "
            "city, in their own real datetime order -- NOT one arbitrary row per city "
            "(unlike the S2/S3/S4 validation scripts, which explicitly do not need "
            "temporal ordering). No resampling, interpolation, or reordering."
        ),
        "source_file": str(RAW_CSV_PATH),
        "source_file_untouched": True,
        "group_selection_seconds": round(group_seconds, 2),
        "extract_seconds": round(extract_seconds, 2),
        "run_seconds_per_pass": round(run_seconds, 2),
        "selected_city_group": city_names,
        "usable_cities": usable_cities,
        "common_sequence_length_hours": common_length,
        "run_result": run1,
        "determinism_verified_across_two_full_reruns": determinism_ok,
        "note_if_group_too_small": (
            None if len(usable_cities) >= 2 else
            "Fewer than 2 usable cities with sufficient hourly history were found in the "
            "selected group -- event-evolution validation could not exercise multi-station "
            "clustering meaningfully with this city selection. See usable_cities above."
        ),
    }
    return report


def main():
    report = run_validation()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
