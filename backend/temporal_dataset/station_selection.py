"""
Station loading, cleaning, and deterministic selection for the Stage 1
synthetic temporal dataset generator.

Cleaning reuses the EXISTING ATHER physical plausibility bounds
(config.CONFIG.physics) rather than inventing a second set of limits —
this is the same bound set layer1_physics.py uses for its VETO check.
"""
import json
from typing import Any, Dict, List, Tuple

import numpy as np

from config import CONFIG
from .config import TemporalGeneratorConfig


def load_raw_stations(path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_null_island(lat: Any, lon: Any) -> bool:
    """
    Exact (0.0, 0.0) is used ELSEWHERE in this codebase (schema.py) as the
    default/missing-value sentinel for latitude/longitude — not a real
    coordinate. We follow that same existing convention here rather than
    inventing a new one: a station reporting exactly (0.0, 0.0) is treated
    as missing-location data, consistent with how schema.py already treats
    zero-substituted sentinel values for other channels.
    """
    try:
        return float(lat) == 0.0 and float(lon) == 0.0
    except (TypeError, ValueError):
        return False


def filter_clean_stations(
    raw_stations: List[Dict[str, Any]],
    cfg: TemporalGeneratorConfig,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns (clean_stations, rejection_report).

    A station is "clean" for this generator when it has non-null
    temperature/pressure/humidity baselines that all fall within the
    EXISTING physics bounds (CONFIG.physics) — the same bounds
    layer1_physics.py already enforces. This single check also correctly
    excludes the known corrupt sentinel values present in data/stations.json
    (e.g. -5573 C temperature, 0/20/24 hPa pressure, 120% humidity) because
    they all fall outside those same bounds.
    """
    phys = CONFIG.physics

    total = len(raw_stations)
    rejected_missing = 0
    rejected_out_of_bounds = 0
    rejected_null_island = 0
    clean: List[Dict[str, Any]] = []

    for s in raw_stations:
        temp = s.get("temperature")
        press = s.get("pressure")
        rh = s.get("humidity")
        lat = s.get("latitude")
        lon = s.get("longitude")

        if temp is None or press is None or rh is None or lat is None or lon is None:
            rejected_missing += 1
            continue

        try:
            temp_f, press_f, rh_f = float(temp), float(press), float(rh)
        except (TypeError, ValueError):
            rejected_missing += 1
            continue

        if cfg.exclude_null_island and _is_null_island(lat, lon):
            rejected_null_island += 1
            continue

        in_bounds = (
            phys.temp_min_c <= temp_f <= phys.temp_max_c
            and phys.pressure_min_hpa <= press_f <= phys.pressure_max_hpa
            and phys.humidity_min_pct <= rh_f <= phys.humidity_max_pct
        )
        if not in_bounds:
            rejected_out_of_bounds += 1
            continue

        clean.append({
            **s,
            "temperature": temp_f,
            "pressure": press_f,
            "humidity": rh_f,
            "latitude": float(lat),
            "longitude": float(lon),
        })

    report = {
        "total_source_stations": total,
        "rejected_missing_fields": rejected_missing,
        "rejected_out_of_physics_bounds": rejected_out_of_bounds,
        "rejected_null_island": rejected_null_island,
        "stations_with_complete_valid_baseline": len(clean),
        "physics_bounds_used": {
            "temp_min_c": phys.temp_min_c, "temp_max_c": phys.temp_max_c,
            "pressure_min_hpa": phys.pressure_min_hpa, "pressure_max_hpa": phys.pressure_max_hpa,
            "humidity_min_pct": phys.humidity_min_pct, "humidity_max_pct": phys.humidity_max_pct,
        },
    }
    return clean, report


def select_stations(
    clean_stations: List[Dict[str, Any]],
    cfg: TemporalGeneratorConfig,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Deterministically selects up to cfg.num_stations from the clean pool.

    Determinism is achieved by sorting station ids first (JSON key order is
    not a reliable determinism source) and then drawing a seeded permutation
    — the same seed + same clean pool always yields the same selection,
    independent of dict/JSON ordering.
    """
    ordered = sorted(clean_stations, key=lambda s: str(s.get("id")))
    n_available = len(ordered)
    n_select = min(cfg.num_stations, n_available)

    rng = np.random.default_rng(cfg.seed)
    perm = rng.permutation(n_available)
    chosen_idx = sorted(perm[:n_select].tolist())  # sort for stable output order
    selected = [ordered[i] for i in chosen_idx]

    report = {
        "clean_stations_available": n_available,
        "requested_num_stations": cfg.num_stations,
        "stations_selected": len(selected),
    }
    return selected, report
