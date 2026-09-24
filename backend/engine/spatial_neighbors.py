"""
S1 — Spatial Neighborhood Foundation.

Single, reusable, deterministic K-nearest-neighbor selection pipeline for
the Spatial Intelligence layer:

    candidate stations
        -> coordinate validation
        -> self-station exclusion
        -> geographic distance calculation (haversine)
        -> radius filtering
        -> distance sorting
        -> K-nearest selection
        -> final neighbor list

This module answers exactly one question, reliably:
"For this target station, which valid nearby stations should be considered
its spatial neighbors, in deterministic distance order?"

It intentionally does NOT decide what to do with those neighbors once
selected (IDW consensus, z-scoring, confidence capping, elevation lapse-rate
correction, etc. all remain in engine/layer4_spatial.py, unchanged). It also
does NOT implement any later Spatial stage (robust statistics, clustering,
event fingerprinting/evolution, counterfactual attribution) -- those are
explicitly deferred to S2+.

Both production entry points reuse this SAME function so there is a single
source of truth for "what counts as a valid, ranked neighbor":
  - app/anomaly/detector.py :: AnomalyDetector.get_neighbors_for_reading()
    (selects candidates out of the live station pool)
  - engine/layer4_spatial.py :: SpatialNeighborLayer.evaluate()
    (re-validates/re-ranks whatever neighbor list it is handed, since it can
    also be called directly with a raw, unsorted, unvalidated list -- e.g.
    from tests and the simulation Test Lab)
"""
import math
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from schema import AWSReading


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres.

    Uses the stdlib `math` module rather than numpy scalar functions: this is
    called once per candidate station during neighbor selection, where numpy's
    per-call overhead dominated the whole spatial evaluation (~84% of
    per-station cost). Numerically bit-identical to the previous numpy
    implementation (verified on 200k random/regional/degenerate point pairs)
    and ~6x faster."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return r * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def is_valid_coordinate(lat: Any, lon: Any) -> bool:
    """
    A coordinate is valid for neighbor selection when it is present, finite,
    and within the physically possible range: latitude in [-90, 90],
    longitude in [-180, 180]. This does NOT repair or invent coordinates --
    an invalid coordinate simply excludes that station from consideration.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return False
    return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0


@dataclass(frozen=True)
class NeighborCandidate:
    """
    Clean, reusable representation of one selected spatial neighbor.
    Carries the original AWSReading (so existing consumers -- IDW,
    per-channel DataQuality checks, elevation correction -- can keep
    reading whatever fields they need) plus a flat, convenient snapshot of
    the fields future Spatial stages (S2+) are expected to need most often.
    """
    station_id: str
    latitude: float
    longitude: float
    distance_km: float
    temperature_c: Optional[float]
    pressure_hpa: Optional[float]
    humidity_pct: Optional[float]
    elevation_m: Optional[float]
    reading: AWSReading


@dataclass
class NeighborSelectionResult:
    """
    The final ranked neighbor list plus enough bookkeeping to make
    exclusions understandable in debugging/test output, without changing
    any existing public API surface (this result is an internal type; it is
    not returned by SpatialNeighborLayer.evaluate() or AnomalyDetector's
    public methods).
    """
    neighbors: List[NeighborCandidate]
    target_coordinate_valid: bool
    candidates_considered: int
    excluded_self: int = 0
    excluded_invalid_coordinate: int = 0
    excluded_out_of_radius: int = 0
    within_radius_count: int = 0  # candidates that passed validation + radius filter, BEFORE the K cap


def select_k_nearest_neighbors(
    target: AWSReading,
    candidates: Iterable[AWSReading],
    *,
    radius_km: float,
    k: int,
) -> NeighborSelectionResult:
    """
    Deterministic K-nearest-neighbor selection.

    Pipeline: coordinate validation -> self-exclusion -> haversine distance
    -> radius filtering -> sort by (distance_km, station_id) -> take the
    nearest K.

    The (distance_km, station_id) secondary sort key makes ordering fully
    deterministic even for exact or near-exact distance ties, independent of
    the input iteration order (e.g. a dict's .values()).

    If `target`'s own coordinate is invalid, no neighbors can be computed
    (there is no distance to measure from) and an empty result is returned
    with target_coordinate_valid=False.
    """
    target_valid = is_valid_coordinate(target.lat, target.lon)

    excluded_self = 0
    excluded_invalid = 0
    excluded_radius = 0
    considered = 0
    scored: List[NeighborCandidate] = []

    if target_valid:
        for c in candidates:
            considered += 1
            if c.station_id == target.station_id:
                excluded_self += 1
                continue
            if not is_valid_coordinate(c.lat, c.lon):
                excluded_invalid += 1
                continue
            dist = haversine_distance_km(target.lat, target.lon, c.lat, c.lon)
            if dist > radius_km:
                excluded_radius += 1
                continue
            scored.append(NeighborCandidate(
                station_id=c.station_id,
                latitude=c.lat,
                longitude=c.lon,
                distance_km=round(dist, 3),
                temperature_c=c.temperature_c,
                pressure_hpa=c.pressure_hpa,
                humidity_pct=c.humidity_pct,
                elevation_m=c.elevation_m,
                reading=c,
            ))

    scored.sort(key=lambda nc: (nc.distance_km, nc.station_id))
    within_radius_count = len(scored)
    k_eff = k if (k is not None and k >= 0) else len(scored)
    selected = scored[:k_eff]

    return NeighborSelectionResult(
        neighbors=selected,
        target_coordinate_valid=target_valid,
        candidates_considered=considered,
        excluded_self=excluded_self,
        excluded_invalid_coordinate=excluded_invalid,
        excluded_out_of_radius=excluded_radius,
        within_radius_count=within_radius_count,
    )
