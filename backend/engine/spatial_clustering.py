"""
S4 — Spatial Clustering & Event Fingerprinting.

Answers: "Do multiple anomalous stations form a coherent spatial cluster,
and what are the characteristics of that cluster?" -- one level above S3,
which only answers "does THIS station's own neighborhood support ITS
deviation?"

================================================================
ALGORITHM CHOICE: DBSCAN (not HDBSCAN) -- see the S4 final report for the
full technical evaluation. Summary of the reasoning kept here for anyone
reading this module in isolation:

  - The clustering problem: group a SMALL set of already-flagged
    anomalous stations (not the whole network) by geographic proximity,
    to distinguish a coherent multi-station event from scattered
    unrelated anomalies.
  - India-wide station spacing (measured in S1's real-dataset audit,
    spatial_audit/results/spatial_neighborhood_audit.json) is
    order-of-magnitude consistent in populated regions (~72-105km median
    nearest-neighbor distance), not the kind of wildly multi-scale,
    nested-density data HDBSCAN was specifically built to handle. A
    single, well-justified eps is adequate.
  - HDBSCAN's main advantages (automatic density-threshold selection,
    variable-density cluster recovery) address a problem ATHER does not
    currently have; its costs (a less explainable "why did the hierarchy
    choose this cut" story, an extra tunable, more moving parts) are real
    for an evidence-explainability system built for SIH judging.
  - DBSCAN's determinism story is simple: given the same distance matrix,
    core/border/noise assignment is a fixed-point property of the
    algorithm itself, not a random or hierarchy-dependent process (see
    _canonicalize_clusters below for the one real edge case -- border-
    point tie-breaking under input order -- and how it is neutralized).
  - scikit-learn (a project dependency already) ships `sklearn.cluster.
    DBSCAN`; no new dependency is introduced.

DISTANCE METRIC: haversine great-circle distance -- not raw lat/lon
Euclidean distance (which distorts real distance by longitude, worse away
from the equator; India spans ~8-35N, a real ~20% distortion at the
northern extreme). DBSCAN is run with `algorithm='ball_tree',
metric='haversine'` directly on radian-converted coordinates (an
OPTIMIZATION pass over the original precomputed-full-matrix design -- see
"PERFORMANCE OPTIMIZATION" below). sklearn's 'haversine' metric expects
(lat, lon) in RADIANS and returns the ANGULAR distance in radians; eps is
converted the same way (eps_km / EARTH_RADIUS_KM). EARTH_RADIUS_KM=6371.0
below is the EXACT same constant engine.spatial_neighbors.
haversine_distance_km() uses -- empirically verified byte-for-byte
identical distances between the two implementations across equatorial,
mid-latitude, and high-latitude Indian point pairs (0.000000m difference)
before this was trusted. haversine_distance_km() itself is still used for
the (small, per-cluster) fingerprint spatial_extent_km computation below,
which this optimization does not touch.

PERFORMANCE OPTIMIZATION (kept, verified equivalent to the original
design): the original implementation built a full O(N^2) precomputed
haversine distance matrix and passed it to
`DBSCAN(metric='precomputed')`. Benchmarking (see the S4 optimization
report) showed this matrix construction was the dominant cost by a wide
margin (e.g. ~425ms of ~438ms total at 500 candidates) and its O(N^2)
memory (191MB at 5,000 candidates) scales badly. Replacing it with
`DBSCAN(algorithm='ball_tree', metric='haversine')` -- which builds a
spatial index instead of a full pairwise matrix -- measured 100-500x
faster and ~100-300x less peak memory at realistic-to-generous candidate
counts, with VERIFIED IDENTICAL cluster membership/noise assignment across
random, boundary-exact, chained, multi-latitude, and multi-cluster test
scenarios (see test_spatial_clustering.py's
TestOldVsOptimizedEquivalence). eps/min_samples semantics, candidate
pre-sorting (still required for the same border-point-ambiguity reason),
cluster canonicalization, and the event fingerprint schema are completely
UNCHANGED by this optimization -- only the internal neighbor-search
mechanism differs.

PARAMETERS -- eps and min_samples, both DERIVED from existing config, not
new independent numbers:
  - min_samples = CONFIG.spatial.min_neighbors_required (currently 2):
    the SAME "minimum evidence floor" S1-S3 already use to decide whether
    there is enough spatial evidence to draw ANY conclusion; reused
    verbatim, not a new threshold.
  - eps_km = CONFIG.spatial.neighbor_distance_km_max / EPS_DIVISOR
    (currently 250/2 = 125km). Deliberately NOT the full 250km neighbor
    radius: that radius is the outer bound for "close enough to be a
    useful baseline-comparison neighbor," intentionally generous so S1
    finds enough neighbors for statistics. A genuinely COHERENT local
    weather event should be visibly tighter than that outer bound --
    using the full 250km risks chain-merging two independent, unrelated
    anomaly groups that each happen to sit within 250km of some shared
    "bridging" station. Halving it gives a radius comfortably above the
    empirically observed typical nearest-neighbor spacing (so genuinely
    adjacent anomalous stations still chain together) while staying
    meaningfully tighter than the full comparison radius.

ARCHITECTURE: this module is a REGIONAL BATCH operation, not something run
inside each station's individual evaluate() call. See
app/anomaly/detector.py::AnomalyDetector.compute_spatial_events() for the
integration boundary and the full rationale (repeated per-station
clustering over the same small candidate set would be wasteful and is not
how the problem is naturally shaped).

This module explicitly does NOT implement event evolution, event tracking
across timestamps, growth/movement/weakening, persistence, or
counterfactual verification (S5/S6) -- it identifies the spatial cluster
for the CURRENT observation set only.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.cluster import DBSCAN

from config import CONFIG
from engine.spatial_neighbors import haversine_distance_km
from engine.spatial_attribution import CHANNEL_ORDER, CHANNEL_LABELS

NOISE_LABEL = -1  # sklearn DBSCAN's own convention for an unclustered point

# Divisor applied to the existing neighbor_distance_km_max to derive the
# clustering eps -- see module docstring for the justification. Centralized
# and documented rather than a free-floating literal.
EPS_DIVISOR = 2.0

# Earth radius used to convert between km and radians for the haversine
# metric. MUST match engine.spatial_neighbors.haversine_distance_km()'s own
# internal radius (6371.0) exactly, or eps_km would silently mean a
# different real-world distance depending on which code path computed it.
# Verified byte-for-byte identical output between the two before this was
# relied on (see module docstring).
EARTH_RADIUS_KM = 6371.0


def default_eps_km() -> float:
    """Derived, not invented: half of the existing S1 neighbor-comparison radius."""
    return CONFIG.spatial.neighbor_distance_km_max / EPS_DIVISOR


def default_min_samples() -> int:
    """Reused verbatim from the existing S1-S3 minimum-evidence floor."""
    return CONFIG.spatial.min_neighbors_required


@dataclass(frozen=True)
class ClusterCandidate:
    """
    One anomalous station's evidence, ready for spatial clustering. Built
    from ALREADY-COMPUTED S1-S3 output (engine/layer4_spatial.py's
    `detail` dict) -- nothing here re-derives anomaly evidence, re-selects
    neighbors, or recomputes statistics.

    A station only becomes a ClusterCandidate when it has at least one
    applicable channel (i.e. S3's regional_attribution shows a real
    deviation was found) -- normal/quiet stations never reach this stage.
    See build_cluster_candidate() below for how one is constructed from a
    station's cached evaluate() output.
    """
    station_id: str
    latitude: float
    longitude: float
    timestamp: Optional[str]
    affected_channels: Tuple[str, ...]
    attribution_classification: str  # "REGIONAL_EVENT" | "ISOLATED_SENSOR_ANOMALY" | "UNCERTAIN"
    attribution_confidence: float
    dominant_direction: int          # -1 / 0 / +1: direction of this station's single strongest channel
    magnitude_summary: float         # |robust_z| of that strongest channel


def build_cluster_candidate(
    station_id: str,
    latitude: float,
    longitude: float,
    regional_attribution: Dict[str, Any],
    timestamp: Optional[str] = None,
) -> Optional["ClusterCandidate"]:
    """
    Builds a ClusterCandidate from a station's ALREADY-COMPUTED
    detail["regional_attribution"] (S3's output). Returns None when the
    station has no applicable channel -- i.e. it showed no meaningful
    deviation and must NOT become a clustering candidate (task requirement:
    normal stations never become event members).
    """
    applicable = regional_attribution.get("applicable_channels") or []
    if not applicable:
        return None

    channel_evidence = regional_attribution.get("channel_evidence", {})
    affected = tuple(ch for ch in CHANNEL_ORDER if ch in applicable)

    # "Dominant" channel = the one with the largest |robust_z| among the
    # applicable channels -- this station's single strongest signal.
    strongest_ch = None
    strongest_abs_z = -1.0
    strongest_direction = 0
    for ch in affected:
        z = channel_evidence.get(ch, {}).get("target_robust_z")
        if z is None:
            continue
        if abs(z) > strongest_abs_z:
            strongest_abs_z = abs(z)
            strongest_direction = 1 if z > 0 else (-1 if z < 0 else 0)
            strongest_ch = ch

    if strongest_ch is None:
        return None

    return ClusterCandidate(
        station_id=station_id, latitude=latitude, longitude=longitude, timestamp=timestamp,
        affected_channels=affected,
        attribution_classification=regional_attribution.get("classification", "UNCERTAIN"),
        attribution_confidence=float(regional_attribution.get("confidence", 0.0)),
        dominant_direction=strongest_direction,
        magnitude_summary=strongest_abs_z,
    )


@dataclass(frozen=True)
class EventFingerprint:
    """
    A compact, deterministic description of what one detected spatial
    cluster looks like -- NOT a claim that a genuine meteorological event
    has been confirmed. See the S4 final report for the exact language
    discipline this is held to ("candidate regional event", "coherent
    anomaly cluster", never "confirmed weather event").
    """
    cluster_id: str
    member_count: int
    member_station_ids: Tuple[str, ...]
    centroid_lat: float
    centroid_lon: float
    spatial_extent_km: float
    affected_channels: Tuple[str, ...]
    dominant_direction: int
    direction_agreement_ratio: float
    magnitude_summary: Dict[str, float]
    regional_attribution_support: Dict[str, int]
    coherence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "member_count": self.member_count,
            "member_station_ids": list(self.member_station_ids),
            "centroid": {"lat": round(self.centroid_lat, 4), "lon": round(self.centroid_lon, 4)},
            "spatial_extent_km": round(self.spatial_extent_km, 1),
            "affected_channels": [CHANNEL_LABELS.get(c, c) for c in self.affected_channels],
            "dominant_direction": self.dominant_direction,
            "direction_agreement_ratio": round(self.direction_agreement_ratio, 3),
            "magnitude_summary": {k: round(v, 3) for k, v in self.magnitude_summary.items()},
            "regional_attribution_support": self.regional_attribution_support,
            "coherence": round(self.coherence, 3),
            "coherence_note": (
                "Evidence-strength score in [0,1] combining direction agreement and S3 "
                "REGIONAL_EVENT support among members -- NOT a calibrated probability, and "
                "NOT a confirmation that a genuine meteorological event occurred. This is "
                "spatial evidence / a candidate regional event, to be combined with further "
                "evidence (S5 evolution, S6 counterfactual verification, Evidence Fusion)."
            ),
        }


@dataclass(frozen=True)
class SpatialEventsResult:
    clusters: Tuple[EventFingerprint, ...]
    cluster_count: int
    largest_cluster_size: int
    unclustered_candidate_ids: Tuple[str, ...]
    candidates_considered: int
    eps_km: float
    min_samples: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clusters": [c.to_dict() for c in self.clusters],
            "cluster_count": self.cluster_count,
            "largest_cluster_size": self.largest_cluster_size,
            "unclustered_candidate_ids": list(self.unclustered_candidate_ids),
            "candidates_considered": self.candidates_considered,
            "parameters": {"eps_km": self.eps_km, "min_samples": self.min_samples, "metric": "haversine_balltree"},
            "method": (
                "DBSCAN with a BallTree haversine neighbor search (verified equivalent to a "
                "precomputed haversine distance matrix, S1's haversine_distance_km, across "
                "random/boundary/chained/multi-latitude test scenarios), run ONCE over the "
                "small set of already-anomalous candidates (a regional batch operation, not "
                "run inside per-station evaluate()). Cluster IDs are canonicalized by sorted "
                "centroid position, independent of sklearn's internal label order or input "
                "ordering."
            ),
        }


def _canonicalize_clusters(
    candidates: List[ClusterCandidate],
    raw_labels: np.ndarray,
) -> Dict[int, List[ClusterCandidate]]:
    """
    sklearn assigns integer cluster labels (0, 1, 2, ...) in the order it
    first encounters each cluster's core point while scanning the input --
    an artifact of processing order, not a meaningful identity. This groups
    members by that raw label, then the caller re-sorts by a stable,
    documented key (centroid position) to assign the final, canonical
    cluster_id -- so the SAME membership always produces the SAME
    cluster_id regardless of input order or sklearn's internal numbering.
    """
    groups: Dict[int, List[ClusterCandidate]] = {}
    for cand, label in zip(candidates, raw_labels):
        if label == NOISE_LABEL:
            continue
        groups.setdefault(int(label), []).append(cand)
    return groups


def cluster_anomalous_stations(
    candidates: Sequence[ClusterCandidate],
    *,
    eps_km: Optional[float] = None,
    min_samples: Optional[int] = None,
) -> SpatialEventsResult:
    """
    Runs ONE DBSCAN pass over `candidates` (already-anomalous stations
    only -- see build_cluster_candidate()), using a BallTree haversine
    neighbor search (see module docstring's "PERFORMANCE OPTIMIZATION"
    section). Deterministic regardless of input order: candidates are
    sorted by station_id BEFORE DBSCAN runs (this also neutralizes
    DBSCAN's one real nondeterminism edge case -- a border point within
    eps of core points from two different clusters can be assigned to
    either, depending on scan order; fixing the scan order to a stable
    key removes that ambiguity), and resulting clusters are re-labeled by
    sorted centroid position, not sklearn's raw (order-dependent) integer
    labels.
    """
    eps = eps_km if eps_km is not None else default_eps_km()
    min_s = min_samples if min_samples is not None else default_min_samples()

    ordered = sorted(candidates, key=lambda c: c.station_id)
    n = len(ordered)

    if n == 0:
        return SpatialEventsResult(
            clusters=(), cluster_count=0, largest_cluster_size=0,
            unclustered_candidate_ids=(), candidates_considered=0,
            eps_km=eps, min_samples=min_s,
        )
    if n < min_s:
        # Cannot possibly form a cluster -- every candidate is its own
        # isolated anomaly by construction (task's single-station case).
        return SpatialEventsResult(
            clusters=(), cluster_count=0, largest_cluster_size=0,
            unclustered_candidate_ids=tuple(c.station_id for c in ordered),
            candidates_considered=n, eps_km=eps, min_samples=min_s,
        )

    # Optimization: a BallTree-backed haversine neighbor search instead of a
    # full O(N^2) precomputed distance matrix (see module docstring's
    # "PERFORMANCE OPTIMIZATION" section for the verified-equivalent
    # rationale). `ordered` is already sorted by station_id above, which is
    # what makes this deterministic (see cluster_anomalous_stations'
    # docstring on the border-point tie-breaking edge case).
    coords_rad = np.radians(np.array([[c.latitude, c.longitude] for c in ordered], dtype=float))
    eps_rad = eps / EARTH_RADIUS_KM
    labels = DBSCAN(eps=eps_rad, min_samples=min_s, algorithm="ball_tree", metric="haversine").fit_predict(coords_rad)
    raw_groups = _canonicalize_clusters(ordered, labels)

    # Build fingerprints, then sort by (centroid_lat, centroid_lon,
    # min station_id) -- a fully documented, stable, deterministic key --
    # and assign final sequential cluster_ids in that order.
    unsorted_fingerprints: List[EventFingerprint] = []
    for members in raw_groups.values():
        member_ids = tuple(sorted(c.station_id for c in members))
        centroid_lat = float(np.mean([c.latitude for c in members]))
        centroid_lon = float(np.mean([c.longitude for c in members]))

        # Exact max pairwise distance within this ONE cluster -- O(M^2) in
        # the cluster's own member count M (not N, the full candidate
        # count). Deliberately left as the exact computation, not
        # approximated: M is realistically small (ATHER's station density
        # bounds how many stations can plausibly co-anomalous-cluster at
        # once), and an approximation would change spatial_extent_km's
        # value for the common case too, not just large-cluster edge
        # cases -- see the S4 optimization report for the considered
        # alternative and why it was not adopted.
        max_extent = 0.0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                d = haversine_distance_km(members[i].latitude, members[i].longitude,
                                           members[j].latitude, members[j].longitude)
                max_extent = max(max_extent, d)

        affected = tuple(sorted({ch for m in members for ch in m.affected_channels},
                                 key=CHANNEL_ORDER.index))

        directions = [m.dominant_direction for m in members]
        pos = sum(1 for d in directions if d > 0)
        neg = sum(1 for d in directions if d < 0)
        if pos >= neg:
            cluster_direction = 1 if pos > 0 else 0
            agreeing = pos
        else:
            cluster_direction = -1
            agreeing = neg
        direction_agreement_ratio = agreeing / len(members)

        magnitudes = sorted(m.magnitude_summary for m in members)
        magnitude_summary = {
            "min": magnitudes[0], "median": magnitudes[len(magnitudes) // 2], "max": magnitudes[-1],
        }

        support_counts = {"REGIONAL_EVENT": 0, "ISOLATED_SENSOR_ANOMALY": 0, "UNCERTAIN": 0}
        for m in members:
            support_counts[m.attribution_classification] = support_counts.get(m.attribution_classification, 0) + 1
        regional_support_ratio = support_counts.get("REGIONAL_EVENT", 0) / len(members)

        # Coherence: direction agreement AND S3-level regional support both
        # present -- a cluster where members disagree on direction, or
        # where S3 itself mostly called individual members isolated
        # faults rather than regional events, is NOT strong coherent
        # evidence just because DBSCAN found them geographically close.
        coherence = direction_agreement_ratio * regional_support_ratio

        unsorted_fingerprints.append(EventFingerprint(
            cluster_id="",  # assigned after sorting, below
            member_count=len(members),
            member_station_ids=member_ids,
            centroid_lat=centroid_lat, centroid_lon=centroid_lon,
            spatial_extent_km=max_extent,
            affected_channels=affected,
            dominant_direction=cluster_direction,
            direction_agreement_ratio=direction_agreement_ratio,
            magnitude_summary=magnitude_summary,
            regional_attribution_support=support_counts,
            coherence=coherence,
        ))

    unsorted_fingerprints.sort(key=lambda f: (round(f.centroid_lat, 6), round(f.centroid_lon, 6), f.member_station_ids[0]))
    fingerprints = tuple(
        EventFingerprint(
            cluster_id=f"CLUSTER_{i:03d}", member_count=f.member_count, member_station_ids=f.member_station_ids,
            centroid_lat=f.centroid_lat, centroid_lon=f.centroid_lon, spatial_extent_km=f.spatial_extent_km,
            affected_channels=f.affected_channels, dominant_direction=f.dominant_direction,
            direction_agreement_ratio=f.direction_agreement_ratio, magnitude_summary=f.magnitude_summary,
            regional_attribution_support=f.regional_attribution_support, coherence=f.coherence,
        )
        for i, f in enumerate(unsorted_fingerprints)
    )

    clustered_ids = {sid for f in fingerprints for sid in f.member_station_ids}
    unclustered = tuple(c.station_id for c in ordered if c.station_id not in clustered_ids)

    return SpatialEventsResult(
        clusters=fingerprints,
        cluster_count=len(fingerprints),
        largest_cluster_size=max((f.member_count for f in fingerprints), default=0),
        unclustered_candidate_ids=unclustered,
        candidates_considered=n,
        eps_km=eps, min_samples=min_s,
    )
