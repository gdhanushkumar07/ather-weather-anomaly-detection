"""
S4 — Spatial Clustering & Event Fingerprinting: focused regression tests.

Covers engine/spatial_clustering.py directly (candidate construction,
DBSCAN wiring, canonicalization, fingerprint contents) and its integration
into app/anomaly/detector.py::AnomalyDetector.compute_spatial_events()
(the regional-batch API, backed by already-cached S1-S3 evaluate() output).

Existing S1/S2/S3 regression suites and the production simulation scenarios
are unaffected and re-run alongside this file (see the S4 final report for
combined results) -- this file adds NEW coverage for the S4 clustering
layer itself.
"""
import math
import os
import random
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
from sklearn.cluster import DBSCAN

from config import CONFIG
from schema import AWSReading
from app.anomaly.detector import AnomalyDetector
from engine.spatial_neighbors import haversine_distance_km
from engine.spatial_clustering import (
    ClusterCandidate,
    build_cluster_candidate,
    cluster_anomalous_stations,
    default_eps_km,
    default_min_samples,
    EPS_DIVISOR,
)


def _cand(sid, lat, lon, cls="REGIONAL_EVENT", conf=0.7, direction=1, magnitude=4.0, channels=("temperature_c",)):
    return ClusterCandidate(
        station_id=sid, latitude=lat, longitude=lon, timestamp=None,
        affected_channels=tuple(channels), attribution_classification=cls,
        attribution_confidence=conf, dominant_direction=direction, magnitude_summary=magnitude,
    )


class TestDerivedParameters(unittest.TestCase):
    def test_eps_derived_from_existing_neighbor_radius_not_equal_to_it(self):
        eps = default_eps_km()
        self.assertEqual(eps, CONFIG.spatial.neighbor_distance_km_max / EPS_DIVISOR)
        # Explicit: must NOT blindly equal the full 250km neighbor radius.
        self.assertLess(eps, CONFIG.spatial.neighbor_distance_km_max)

    def test_min_samples_reuses_existing_min_neighbors_required(self):
        self.assertEqual(default_min_samples(), CONFIG.spatial.min_neighbors_required)


class TestBuildClusterCandidate(unittest.TestCase):
    def test_no_applicable_channels_returns_none(self):
        ra = {"applicable_channels": [], "channel_evidence": {}, "classification": "UNCERTAIN", "confidence": 0.0}
        self.assertIsNone(build_cluster_candidate("STN", 20.0, 77.0, ra))

    def test_applicable_channel_produces_candidate_with_dominant_channel(self):
        ra = {
            "applicable_channels": ["temperature_c", "humidity_pct"],
            "channel_evidence": {
                "temperature_c": {"target_robust_z": 5.0},
                "humidity_pct": {"target_robust_z": -2.0},
            },
            "classification": "ISOLATED_SENSOR_ANOMALY", "confidence": 0.5,
        }
        cand = build_cluster_candidate("STN", 20.0, 77.0, ra)
        self.assertIsNotNone(cand)
        self.assertEqual(cand.affected_channels, ("temperature_c", "humidity_pct"))
        self.assertEqual(cand.dominant_direction, 1)  # temperature_c has the larger |z| (5.0 > 2.0)
        self.assertAlmostEqual(cand.magnitude_summary, 5.0)


class TestClusterAnomalousStationsUnit(unittest.TestCase):
    """Direct unit tests against cluster_anomalous_stations with hand-built
    candidates -- precise control over geometry for exact assertions."""

    # TEST 1 — single anomalous station
    def test_single_station_no_cluster(self):
        result = cluster_anomalous_stations([_cand("A", 20.0, 77.0)])
        self.assertEqual(result.cluster_count, 0)
        self.assertEqual(result.unclustered_candidate_ids, ("A",))

    # TEST 10 — empty input
    def test_empty_input_no_errors(self):
        result = cluster_anomalous_stations([])
        self.assertEqual(result.cluster_count, 0)
        self.assertEqual(result.candidates_considered, 0)
        self.assertEqual(result.clusters, ())

    # TEST 2 — two nearby anomalous stations, min_samples=2 -> clusters
    def test_two_nearby_stations_cluster_under_default_min_samples(self):
        candidates = [_cand("A", 20.0, 77.0), _cand("B", 20.1, 77.1)]  # ~15km apart
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.cluster_count, 1)
        self.assertEqual(result.clusters[0].member_station_ids, ("A", "B"))

    # TEST 3 — coherent regional cluster (same direction, similar magnitude)
    def test_coherent_cluster_same_direction_similar_magnitude(self):
        candidates = [
            _cand("A", 20.0, 77.0, direction=1, magnitude=4.0),
            _cand("B", 20.2, 77.1, direction=1, magnitude=4.2),
            _cand("C", 19.9, 76.9, direction=1, magnitude=3.8),
        ]
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.cluster_count, 1)
        fp = result.clusters[0]
        self.assertEqual(fp.member_count, 3)
        self.assertEqual(fp.dominant_direction, 1)
        self.assertEqual(fp.direction_agreement_ratio, 1.0)
        self.assertEqual(fp.regional_attribution_support["REGIONAL_EVENT"], 3)
        self.assertGreater(fp.coherence, 0.9)

    # TEST 4 — two separate, well-separated clusters
    def test_two_geographically_separate_clusters(self):
        candidates = [
            _cand("A1", 20.0, 77.0), _cand("A2", 20.1, 77.1),   # Maharashtra-ish
            _cand("D1", 28.6, 77.2), _cand("D2", 28.7, 77.3),   # Delhi-ish, >1000km away
        ]
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.cluster_count, 2)
        member_sets = {frozenset(c.member_station_ids) for c in result.clusters}
        self.assertIn(frozenset({"A1", "A2"}), member_sets)
        self.assertIn(frozenset({"D1", "D2"}), member_sets)

    # TEST 5 — scattered anomalies must not be incorrectly merged
    def test_scattered_anomalies_not_merged(self):
        candidates = [_cand("A", 8.5, 77.0), _cand("B", 20.0, 77.0), _cand("C", 30.0, 77.0)]  # each >1000km apart
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.cluster_count, 0)
        self.assertEqual(set(result.unclustered_candidate_ids), {"A", "B", "C"})

    # TEST 6 — noisy outlier next to a coherent cluster
    def test_noisy_outlier_does_not_join_coherent_cluster(self):
        candidates = [
            _cand("A", 20.0, 77.0), _cand("B", 20.1, 77.1), _cand("C", 19.9, 76.9),  # tight cluster
            _cand("X", 22.5, 79.5),  # ~350km away -- outside eps (125km default)
        ]
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.cluster_count, 1)
        self.assertEqual(set(result.clusters[0].member_station_ids), {"A", "B", "C"})
        self.assertIn("X", result.unclustered_candidate_ids)

    # TEST 7 — multi-channel fingerprint
    def test_multichannel_fingerprint_contains_all_channels(self):
        candidates = [
            _cand("A", 20.0, 77.0, channels=("temperature_c", "pressure_hpa", "humidity_pct")),
            _cand("B", 20.1, 77.1, channels=("temperature_c", "humidity_pct")),
        ]
        result = cluster_anomalous_stations(candidates)
        fp = result.clusters[0]
        self.assertEqual(fp.affected_channels, ("temperature_c", "pressure_hpa", "humidity_pct"))
        d = fp.to_dict()
        self.assertEqual(d["affected_channels"], ["temperature", "pressure", "humidity"])

    # TEST 8 — single-channel fingerprint
    def test_single_channel_fingerprint(self):
        candidates = [_cand("A", 20.0, 77.0, channels=("temperature_c",)),
                      _cand("B", 20.1, 77.1, channels=("temperature_c",))]
        result = cluster_anomalous_stations(candidates)
        self.assertEqual(result.clusters[0].affected_channels, ("temperature_c",))

    # TEST 9 — determinism under reversed input order
    def test_determinism_under_reversed_input_order(self):
        candidates = [
            _cand("A", 20.0, 77.0), _cand("B", 20.1, 77.1), _cand("C", 19.9, 76.9),
            _cand("D1", 28.6, 77.2), _cand("D2", 28.7, 77.3),
        ]
        r1 = cluster_anomalous_stations(list(candidates))
        r2 = cluster_anomalous_stations(list(reversed(candidates)))
        self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_below_min_samples_no_cluster(self):
        # 1 candidate total is below min_samples=2 -> cannot cluster at all.
        result = cluster_anomalous_stations([_cand("A", 20.0, 77.0)], min_samples=2)
        self.assertEqual(result.cluster_count, 0)

    def test_explicit_parameters_are_reported(self):
        result = cluster_anomalous_stations([_cand("A", 20.0, 77.0), _cand("B", 20.1, 77.1)],
                                             eps_km=50.0, min_samples=2)
        self.assertEqual(result.eps_km, 50.0)
        self.assertEqual(result.min_samples, 2)

    def test_centroid_and_extent_are_correct(self):
        candidates = [_cand("A", 20.0, 77.0), _cand("B", 20.2, 77.0)]  # ~22.2km apart, due north-south
        result = cluster_anomalous_stations(candidates)
        fp = result.clusters[0]
        self.assertAlmostEqual(fp.centroid_lat, 20.1, places=3)
        self.assertAlmostEqual(fp.centroid_lon, 77.0, places=3)
        self.assertGreater(fp.spatial_extent_km, 20.0)
        self.assertLess(fp.spatial_extent_km, 25.0)

    def test_cluster_id_format_and_sequential_assignment(self):
        candidates = [
            _cand("A", 20.0, 77.0), _cand("B", 20.1, 77.1),
            _cand("D1", 28.6, 77.2), _cand("D2", 28.7, 77.3),
        ]
        result = cluster_anomalous_stations(candidates)
        ids = sorted(c.cluster_id for c in result.clusters)
        self.assertEqual(ids, ["CLUSTER_000", "CLUSTER_001"])

    def test_contradictory_channel_evidence_lowers_coherence(self):
        # Mixed direction within the geographically-clustered group.
        candidates = [
            _cand("A", 20.0, 77.0, direction=1),
            _cand("B", 20.1, 77.1, direction=-1),
            _cand("C", 19.9, 76.9, direction=1),
        ]
        result = cluster_anomalous_stations(candidates)
        fp = result.clusters[0]
        self.assertLess(fp.direction_agreement_ratio, 1.0)
        self.assertLess(fp.coherence, 1.0)

    def test_isolated_classification_members_reduce_coherence(self):
        candidates = [
            _cand("A", 20.0, 77.0, cls="ISOLATED_SENSOR_ANOMALY"),
            _cand("B", 20.1, 77.1, cls="ISOLATED_SENSOR_ANOMALY"),
        ]
        result = cluster_anomalous_stations(candidates)
        fp = result.clusters[0]
        self.assertEqual(fp.regional_attribution_support["REGIONAL_EVENT"], 0)
        self.assertEqual(fp.coherence, 0.0)  # geographically close, but S3 itself called both isolated


class TestComputeSpatialEventsIntegration(unittest.TestCase):
    """End-to-end tests through the real AnomalyDetector.compute_spatial_events()."""

    def _reading(self, sid, lat, lon, t=25.0, p=1013.0, h=55.0):
        return AWSReading(station_id=sid, lat=lat, lon=lon, temperature_c=t, pressure_hpa=p, humidity_pct=h)

    def test_end_to_end_regional_cluster_and_isolated_fault_both_correct(self):
        det = AnomalyDetector()
        pool = [
            self._reading("R1", 20.1, 77.1, t=42.0), self._reading("R2", 19.9, 77.2, t=43.0),
            self._reading("R3", 20.2, 76.9, t=41.5), self._reading("R4", 20.0, 77.3, t=42.5),
            self._reading("B1", 20.5, 77.5, t=31.0), self._reading("B2", 19.5, 76.5, t=32.0),
            self._reading("B3", 20.6, 76.4, t=30.5), self._reading("B4", 19.4, 77.6, t=31.5),
            self._reading("B5", 20.7, 77.7, t=32.5),
            self._reading("ISO", 28.6, 77.2, t=48.0),
            self._reading("ISO_B1", 28.7, 77.3, t=30.0), self._reading("ISO_B2", 28.5, 77.1, t=31.0),
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)

        events = det.compute_spatial_events()
        self.assertEqual(events["cluster_count"], 1)
        self.assertEqual(set(events["clusters"][0]["member_station_ids"]), {"R1", "R2", "R3", "R4"})
        self.assertIn("ISO", events["unclustered_candidate_ids"])
        # Normal baseline stations must never appear as candidates at all.
        for sid in ("B1", "B2", "B3", "B4", "B5", "ISO_B1", "ISO_B2"):
            self.assertNotIn(sid, events["unclustered_candidate_ids"])
            for c in events["clusters"]:
                self.assertNotIn(sid, c["member_station_ids"])

    def test_no_anomalous_stations_yields_empty_result(self):
        det = AnomalyDetector()
        pool = [self._reading(f"N{i}", 20.0 + i * 0.1, 77.0, t=30.0 + i * 0.1) for i in range(5)]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)
        events = det.compute_spatial_events()
        self.assertEqual(events["cluster_count"], 0)
        self.assertEqual(events["candidates_considered"], 0)

    def test_station_ids_filter_restricts_candidates(self):
        det = AnomalyDetector()
        pool = [
            self._reading("R1", 20.1, 77.1, t=42.0), self._reading("R2", 19.9, 77.2, t=43.0),
            self._reading("R3", 20.2, 76.9, t=41.5), self._reading("R4", 20.0, 77.3, t=42.5),
            self._reading("B1", 20.5, 77.5, t=31.0), self._reading("B2", 19.5, 76.5, t=32.0),
            self._reading("B3", 20.6, 76.4, t=30.5), self._reading("B4", 19.4, 77.6, t=31.5),
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)
        events = det.compute_spatial_events(station_ids=["R1"])
        self.assertEqual(events["candidates_considered"], 1)
        self.assertEqual(events["cluster_count"], 0)  # only 1 candidate considered -> below min_samples

    def test_finite_deterministic_results(self):
        det = AnomalyDetector()
        pool = [
            self._reading("R1", 20.1, 77.1, t=42.0), self._reading("R2", 19.9, 77.2, t=43.0),
            self._reading("R3", 20.2, 76.9, t=41.5),
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)
        e1 = det.compute_spatial_events()
        e2 = det.compute_spatial_events()
        self.assertEqual(e1, e2)
        for c in e1["clusters"]:
            self.assertTrue(math.isfinite(c["coherence"]))
            self.assertTrue(math.isfinite(c["centroid"]["lat"]))
            self.assertTrue(math.isfinite(c["centroid"]["lon"]))


class TestProductionShapeClusteringValidation(unittest.TestCase):
    """S4 production-shape validation: confirm clustering computes without
    error against the real production station metadata shape
    (data/stations.json). Demo/production-shape metadata, not guaranteed
    AWS ground truth -- used only to confirm computability/determinism."""

    def test_clustering_runs_without_error_on_real_production_sample(self):
        import json
        path = os.path.join(BASE_DIR, "..", "data", "stations.json")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)[:120]  # bounded sample for test runtime

        det = AnomalyDetector()
        pool = [
            AWSReading(
                station_id=s["id"], lat=s["latitude"], lon=s["longitude"],
                temperature_c=s.get("temperature"), pressure_hpa=s.get("pressure"),
                humidity_pct=s.get("humidity"),
            )
            for s in raw
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)

        events = det.compute_spatial_events()
        events_repeat = det.compute_spatial_events()
        self.assertEqual(events, events_repeat)
        for c in events["clusters"]:
            self.assertTrue(math.isfinite(c["coherence"]))
            self.assertGreaterEqual(c["member_count"], default_min_samples())


def _old_reference_labels(points, eps_km, min_samples):
    """
    A self-contained reference implementation reproducing the ORIGINAL
    (pre-optimization) precomputed-matrix DBSCAN design EXACTLY, kept only
    here (never in production code) so the optimized production
    implementation can be regression-tested against it. Not imported from
    engine.spatial_clustering -- this is intentionally a separate,
    independent computation.
    """
    n = len(points)
    mat = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_distance_km(points[i][0], points[i][1], points[j][0], points[j][1])
            mat[i, j] = mat[j, i] = d
    return DBSCAN(eps=eps_km, min_samples=min_samples, metric="precomputed").fit_predict(mat)


def _label_partition(labels, ids):
    """Order/numbering-independent representation of a labeling: a set of
    member-id frozensets (one per cluster) plus the noise set."""
    groups = {}
    noise = set()
    for lbl, sid in zip(labels, ids):
        if lbl == -1:
            noise.add(sid)
        else:
            groups.setdefault(int(lbl), set()).add(sid)
    return frozenset(frozenset(g) for g in groups.values()), frozenset(noise)


class TestOldVsOptimizedEquivalence(unittest.TestCase):
    """
    Directly compares the OPTIMIZED production implementation
    (cluster_anomalous_stations, BallTree haversine) against the
    self-contained OLD reference (_old_reference_labels, precomputed
    haversine matrix) on deterministic datasets, including boundary-exact
    cases. Cluster membership and noise assignment must be identical
    (canonical cluster_id numbering aside, which both approaches already
    assign independently of algorithm label order).
    """

    def _assert_equivalent(self, points, eps_km=None, min_samples=None):
        eps = eps_km if eps_km is not None else default_eps_km()
        min_s = min_samples if min_samples is not None else default_min_samples()
        ids = [f"S{i:04d}" for i in range(len(points))]

        old_labels = _old_reference_labels(points, eps, min_s)
        old_groups, old_noise = _label_partition(old_labels, ids)

        candidates = [_cand(sid, lat, lon) for sid, (lat, lon) in zip(ids, points)]
        new_result = cluster_anomalous_stations(candidates, eps_km=eps, min_samples=min_s)
        new_groups = frozenset(frozenset(c.member_station_ids) for c in new_result.clusters)
        new_noise = frozenset(new_result.unclustered_candidate_ids)

        self.assertEqual(old_groups, new_groups, f"cluster membership differs for {points}")
        self.assertEqual(old_noise, new_noise, f"noise set differs for {points}")

    def test_random_scattered_points_various_sizes(self):
        for n in (10, 50, 100, 300):
            random.seed(1000 + n)
            points = [(random.uniform(8.0, 35.0), random.uniform(68.0, 97.0)) for _ in range(n)]
            self._assert_equivalent(points)

    def test_tight_single_cluster(self):
        self._assert_equivalent([(20.0 + i * 0.05, 77.0 + i * 0.05) for i in range(5)])

    def test_two_well_separated_clusters(self):
        self._assert_equivalent([(20.0, 77.0), (20.1, 77.1), (28.6, 77.2), (28.7, 77.3)])

    def test_boundary_pair_just_inside_eps(self):
        # ~124.98km apart -- just inside the default 125km eps.
        self._assert_equivalent([(20.0, 77.0), (21.124, 77.0)])

    def test_boundary_pair_just_outside_eps(self):
        # ~139.6km apart -- just outside the default 125km eps.
        self._assert_equivalent([(20.0, 77.0), (20.0, 78.336)])

    def test_chain_of_points(self):
        self._assert_equivalent([(20.0 + i * 0.9, 77.0) for i in range(6)])

    def test_mixed_indian_latitudes(self):
        # Near-equatorial (Nicobar-ish) and high-latitude (Kashmir-ish) pairs together.
        self._assert_equivalent([(0.5, 77.0), (0.6, 77.05), (34.0, 74.8), (34.05, 74.85)])

    def test_equivalence_with_non_default_parameters(self):
        points = [(20.0, 77.0), (20.3, 77.3), (20.6, 77.6), (25.0, 80.0)]
        self._assert_equivalent(points, eps_km=50.0, min_samples=2)
        self._assert_equivalent(points, eps_km=250.0, min_samples=2)


if __name__ == "__main__":
    unittest.main()
