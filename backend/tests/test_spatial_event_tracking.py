"""
S5 — Event Evolution: focused regression tests.

Covers engine/spatial_event_tracking.py directly (event association,
identity, evolution flags, gap policy, ambiguity handling) using
hand-built S4-shaped snapshots for precise, predictable control over
cluster membership at each simulated timestep -- exactly the same
testing strategy already used for S3 (hand-built ChannelAttributionEvidence)
and S4 (hand-built ClusterCandidate). A small number of true end-to-end
integration tests exercise the real
AnomalyDetector.update_spatial_event_tracking() pipeline separately.

Existing S1-S4 regression suites are unaffected and re-run alongside this
file (see the S5 final report for combined results).
"""
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from datetime import datetime as _dt, timezone as _tz
from schema import AWSReading as _AWSReading

# Phase 2 spatial contract: a neighbor is only usable evidence when it was
# OBSERVED within CONFIG.spatial.neighbor_time_tolerance_minutes of the target
# (same source, known observation time). These fixtures model stations that
# were observed simultaneously - the assumption the tests always made
# implicitly, now stated explicitly.
_FIXTURE_OBS_TIME = _dt(2026, 1, 1, 12, 0, tzinfo=_tz.utc)


def AWSReading(**kw):  # noqa: N802 - deliberately shadows the schema class name
    kw.setdefault("observation_timestamp", _FIXTURE_OBS_TIME)
    return _AWSReading(**kw)
from app.anomaly.detector import AnomalyDetector
from engine.spatial_event_tracking import (
    SpatialEventTracker,
    DEFAULT_MAX_OBSERVATION_GAP_MINUTES,
    MIN_MEANINGFUL_MAGNITUDE_CHANGE,
    _movement_significance_km,
    _station_overlap_ratio,
)


def _cluster(cluster_id, member_ids, lat, lon, magnitude=4.0, extent_km=50.0,
             channels=("temperature",), coherence=0.9, regional=None):
    return {
        "cluster_id": cluster_id,
        "member_count": len(member_ids),
        "member_station_ids": list(member_ids),
        "centroid": {"lat": lat, "lon": lon},
        "spatial_extent_km": extent_km,
        "affected_channels": list(channels),
        "dominant_direction": 1,
        "direction_agreement_ratio": 1.0,
        "magnitude_summary": {"min": magnitude, "median": magnitude, "max": magnitude},
        "regional_attribution_support": regional or {"REGIONAL_EVENT": len(member_ids), "ISOLATED_SENSOR_ANOMALY": 0, "UNCERTAIN": 0},
        "coherence": coherence,
    }


def _s4_result(clusters):
    return {
        "clusters": clusters,
        "cluster_count": len(clusters),
        "largest_cluster_size": max((c["member_count"] for c in clusters), default=0),
        "unclustered_candidate_ids": [],
        "candidates_considered": sum(c["member_count"] for c in clusters),
        "parameters": {"eps_km": 125.0, "min_samples": 2, "metric": "haversine_balltree"},
        "method": "test fixture",
    }


T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class TestReusedConstants(unittest.TestCase):
    def test_gap_policy_reuses_lstm_temporal_config(self):
        self.assertEqual(DEFAULT_MAX_OBSERVATION_GAP_MINUTES, CONFIG.lstm_temporal.max_gap_minutes)

    def test_magnitude_change_bar_reuses_spatial_attribution_constant(self):
        from engine.spatial_attribution import MIN_MEANINGFUL_NEIGHBOR_Z
        self.assertEqual(MIN_MEANINGFUL_MAGNITUDE_CHANGE, MIN_MEANINGFUL_NEIGHBOR_Z)

    def test_movement_significance_reuses_s4_eps(self):
        from engine.spatial_clustering import default_eps_km
        self.assertEqual(_movement_significance_km(), default_eps_km())


class TestStationOverlapRatio(unittest.TestCase):
    def test_full_overlap(self):
        self.assertEqual(_station_overlap_ratio(["A", "B"], ["A", "B"]), 1.0)

    def test_no_overlap(self):
        self.assertEqual(_station_overlap_ratio(["A", "B"], ["C", "D"]), 0.0)

    def test_partial_overlap_jaccard(self):
        # {A,B,C,D} vs {B,C,D,E}: intersection=3, union=5
        self.assertAlmostEqual(_station_overlap_ratio(["A", "B", "C", "D"], ["B", "C", "D", "E"]), 3 / 5)

    def test_empty_inputs(self):
        self.assertEqual(_station_overlap_ratio([], []), 0.0)


class TestEventLifecycle(unittest.TestCase):
    def setUp(self):
        self.tracker = SpatialEventTracker()

    # TEST 1 — NEW EVENT
    def test_new_event(self):
        r1 = self.tracker.update(_s4_result([]), T0)
        self.assertEqual(r1["summary"]["new_count"], 0)
        self.assertEqual(r1["summary"]["active_count"], 0)

        r2 = self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D"], 20.0, 77.0)]),
                                  T0 + timedelta(minutes=10))
        self.assertEqual(r2["summary"]["new_count"], 1)
        self.assertEqual(r2["newly_detected_events"][0]["evolution_flags"], ["NEW"])
        self.assertEqual(r2["newly_detected_events"][0]["event_id"], "EVENT_0001")

    # TEST 2 — PERSISTING EVENT
    def test_persisting_event_same_event_id(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]),
                                  T0 + timedelta(minutes=10))
        self.assertEqual(r2["summary"]["updated_count"], 1)
        ev = r2["updated_events"][0]
        self.assertEqual(ev["event_id"], "EVENT_0001")
        self.assertEqual(ev["evolution_flags"], ["PERSISTING"])
        self.assertEqual(ev["evidence"]["member_count_change"], 0)

    # TEST 3 — GROWING EVENT
    def test_growing_event(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D", "E"], 20.0, 77.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertIn("GROWING", ev["evolution_flags"])
        self.assertEqual(ev["evidence"]["member_count_change"], 2)
        self.assertAlmostEqual(ev["evidence"]["member_count_change_ratio"], 2 / 3, places=3)

    # TEST 4 — SHRINKING EVENT
    def test_shrinking_event(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D", "E"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertIn("SHRINKING", ev["evolution_flags"])
        self.assertEqual(ev["evidence"]["member_count_change"], -2)

    # TEST 5 — MOVING EVENT
    def test_moving_event_with_overlapping_membership(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        # Shift centroid by ~200km (> 125km eps significance bar), keep partial overlap.
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["B", "C", "D"], 21.8, 77.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertIn("MOVING", ev["evolution_flags"])
        self.assertGreater(ev["evidence"]["centroid_distance_km"], _movement_significance_km())
        # Exact haversine check
        from engine.spatial_neighbors import haversine_distance_km
        expected = haversine_distance_km(20.0, 77.0, 21.8, 77.0)
        self.assertAlmostEqual(ev["evidence"]["centroid_distance_km"], round(expected, 2), places=1)

    def test_small_movement_not_flagged(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.05, 77.0)]),  # ~5.5km shift
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertNotIn("MOVING", ev["evolution_flags"])
        self.assertLess(ev["evidence"]["centroid_distance_km"], 10.0)

    # TEST 6 — INTENSIFYING
    def test_intensifying_event(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=3.5)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=6.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertIn("INTENSIFYING", ev["evolution_flags"])
        self.assertAlmostEqual(ev["evidence"]["magnitude_change"], 2.5)

    # TEST 7 — WEAKENING
    def test_weakening_event(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=7.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=4.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertIn("WEAKENING", ev["evolution_flags"])
        self.assertAlmostEqual(ev["evidence"]["magnitude_change"], -3.0)

    def test_negligible_magnitude_change_not_flagged(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=4.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=4.3)]),  # +0.3, below 1.0 bar
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertNotIn("INTENSIFYING", ev["evolution_flags"])
        self.assertNotIn("WEAKENING", ev["evolution_flags"])
        self.assertEqual(ev["evolution_flags"], ["PERSISTING"])

    # TEST 8 — TWO INDEPENDENT EVENTS
    def test_two_independent_events_continue_independently(self):
        self.tracker.update(_s4_result([
            _cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0),
            _cluster("CLUSTER_001", ["X", "Y", "Z"], 28.6, 77.2),
        ]), T0)
        r2 = self.tracker.update(_s4_result([
            _cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0),
            _cluster("CLUSTER_001", ["X", "Y", "Z"], 28.6, 77.2),
        ]), T0 + timedelta(minutes=10))
        ids = {e["event_id"] for e in r2["updated_events"]}
        self.assertEqual(ids, {"EVENT_0001", "EVENT_0002"})
        self.assertEqual(r2["summary"]["active_count"], 2)

    # TEST 9 — EVENT ENDS (disappears per gap policy)
    def test_event_disappears_after_gap_exceeded(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        gap = timedelta(minutes=DEFAULT_MAX_OBSERVATION_GAP_MINUTES + 1)
        r2 = self.tracker.update(_s4_result([]), T0 + gap)
        self.assertEqual(r2["summary"]["disappeared_count"], 1)
        self.assertEqual(r2["disappeared_events"][0]["event_id"], "EVENT_0001")
        self.assertEqual(r2["disappeared_events"][0]["status"], "DISAPPEARED")
        self.assertEqual(r2["summary"]["active_count"], 0)

    def test_event_not_disappeared_within_gap_even_if_unmatched_this_round(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        small_gap = timedelta(minutes=DEFAULT_MAX_OBSERVATION_GAP_MINUTES - 1)
        r2 = self.tracker.update(_s4_result([]), T0 + small_gap)
        self.assertEqual(r2["summary"]["disappeared_count"], 0)
        self.assertEqual(r2["summary"]["active_count"], 1)  # still active, just unmatched this round

    # TEST 10 — NEW UNRELATED EVENT (not a continuation of a distant prior event)
    def test_distant_unrelated_cluster_is_a_new_event_not_a_continuation(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["X", "Y", "Z"], 28.6, 77.2)]),  # zero overlap, far away
            T0 + timedelta(minutes=10),
        )
        self.assertEqual(r2["summary"]["new_count"], 1)
        self.assertEqual(r2["newly_detected_events"][0]["event_id"], "EVENT_0002")
        # The original event has no overlap candidate this round -> stays active, unmatched (within gap).
        self.assertEqual(r2["summary"]["active_count"], 2)

    # TEST 11 — PARTIAL STATION OVERLAP
    def test_partial_overlap_is_strong_continuity_evidence(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["B", "C", "D", "E"], 20.05, 77.0)]),
            T0 + timedelta(minutes=10),
        )
        self.assertEqual(r2["summary"]["updated_count"], 1)
        ev = r2["updated_events"][0]
        self.assertEqual(ev["event_id"], "EVENT_0001")
        self.assertAlmostEqual(ev["evidence"]["station_overlap_ratio"], 3 / 5)

    # TEST 12 — INPUT ORDER DETERMINISM
    def test_determinism_under_shuffled_member_order(self):
        t1 = SpatialEventTracker()
        t2 = SpatialEventTracker()
        c1a = _cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)
        c1b = _cluster("CLUSTER_000", ["C", "B", "A"], 20.0, 77.0)  # shuffled member order
        t1.update(_s4_result([c1a]), T0)
        t2.update(_s4_result([c1b]), T0)
        c2a = _cluster("CLUSTER_000", ["A", "B", "C", "D"], 20.0, 77.0)
        c2b = _cluster("CLUSTER_000", ["D", "C", "B", "A"], 20.0, 77.0)
        r1 = t1.update(_s4_result([c2a]), T0 + timedelta(minutes=10))
        r2 = t2.update(_s4_result([c2b]), T0 + timedelta(minutes=10))
        self.assertEqual(r1["updated_events"][0]["event_id"], r2["updated_events"][0]["event_id"])
        self.assertEqual(sorted(r1["updated_events"][0]["member_station_ids"]),
                          sorted(r2["updated_events"][0]["member_station_ids"]))
        self.assertEqual(r1["updated_events"][0]["evolution_flags"], r2["updated_events"][0]["evolution_flags"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tracker = SpatialEventTracker()

    def test_no_previous_no_current(self):
        r = self.tracker.update(_s4_result([]), T0)
        self.assertEqual(r["summary"], {"active_count": 0, "new_count": 0, "updated_count": 0,
                                         "disappeared_count": 0, "ambiguous_count": 0})

    def test_one_cluster_then_none(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(_s4_result([]), T0 + timedelta(minutes=1))
        self.assertEqual(r2["summary"]["active_count"], 1)  # unmatched but within gap

    def test_zero_overlap_never_treated_as_continuity(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["D", "E", "F"], 20.01, 77.01)]),  # essentially same location, no overlap
            T0 + timedelta(minutes=10),
        )
        # Must NOT be treated as a continuation despite near-identical centroid.
        self.assertEqual(r2["summary"]["new_count"], 1)
        self.assertNotIn("EVENT_0001", [e["event_id"] for e in r2["newly_detected_events"]])

    def test_identical_centroid_full_overlap_zero_evidence_change(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=4.0)]), T0)
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C"], 20.0, 77.0, magnitude=4.0)]),
            T0 + timedelta(minutes=10),
        )
        ev = r2["updated_events"][0]
        self.assertEqual(ev["evidence"]["centroid_distance_km"], 0.0)
        self.assertEqual(ev["evidence"]["magnitude_change"], 0.0)
        self.assertEqual(ev["evolution_flags"], ["PERSISTING"])

    def test_missing_timestamp_not_invented_uses_explicit_value_only(self):
        # The tracker never invents a timestamp -- it always uses exactly
        # what the caller supplies.
        r = self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0)]), T0)
        self.assertEqual(r["newly_detected_events"][0]["first_seen"], r["timestamp"])

    def test_missing_magnitude_evidence_reports_none_not_zero(self):
        # New event: no previous magnitude exists yet.
        r = self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0, magnitude=5.0)]), T0)
        ev = r["newly_detected_events"][0]
        self.assertIsNone(ev["evidence"]["magnitude_change"])  # None, not 0 -- "unknown" != "no change"
        self.assertIsNone(ev["evidence"]["member_count_change"])
        self.assertIsNone(ev["evidence"]["centroid_distance_km"])

    def test_multiple_clusters_multiple_events(self):
        r = self.tracker.update(_s4_result([
            _cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0),
            _cluster("CLUSTER_001", ["C", "D"], 25.0, 80.0),
            _cluster("CLUSTER_002", ["E", "F"], 10.0, 77.0),
        ]), T0)
        self.assertEqual(r["summary"]["new_count"], 3)
        self.assertEqual({e["event_id"] for e in r["newly_detected_events"]}, {"EVENT_0001", "EVENT_0002", "EVENT_0003"})

    def test_reset_clears_all_state(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0)]), T0)
        self.tracker.reset()
        r = self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0)]), T0)
        # Numbering restarts at EVENT_0001 after reset, not EVENT_0002.
        self.assertEqual(r["newly_detected_events"][0]["event_id"], "EVENT_0001")


class TestMergeSplitAmbiguity(unittest.TestCase):
    def setUp(self):
        self.tracker = SpatialEventTracker()

    def test_merge_two_previous_events_into_one_current_cluster(self):
        self.tracker.update(_s4_result([
            _cluster("CLUSTER_000", ["A", "B"], 20.0, 77.0),
            _cluster("CLUSTER_001", ["C", "D"], 20.5, 77.5),
        ]), T0)
        # A single current cluster now contains members from BOTH prior events.
        r2 = self.tracker.update(
            _s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D"], 20.25, 77.25)]),
            T0 + timedelta(minutes=10),
        )
        # Neither parent's id is silently inherited -- a NEW event id is assigned.
        new_ids = {e["event_id"] for e in r2["newly_detected_events"]}
        self.assertEqual(new_ids, {"EVENT_0003"})
        self.assertIn("MERGE", r2["newly_detected_events"][0]["notes"][0])
        # Both parents are marked ambiguous, not silently disappeared or silently continued.
        merge_flagged = [e for e in r2["active_events"] if e["evolution_flags"] == ["MERGE_AMBIGUOUS"]]
        self.assertEqual({e["event_id"] for e in merge_flagged}, {"EVENT_0001", "EVENT_0002"})
        self.assertGreaterEqual(r2["summary"]["ambiguous_count"], 1)

    def test_split_one_previous_event_into_two_current_clusters(self):
        self.tracker.update(_s4_result([_cluster("CLUSTER_000", ["A", "B", "C", "D"], 20.0, 77.0)]), T0)
        r2 = self.tracker.update(_s4_result([
            _cluster("CLUSTER_000", ["A", "B"], 19.9, 76.9),
            _cluster("CLUSTER_001", ["C", "D"], 20.1, 77.1),
        ]), T0 + timedelta(minutes=10))
        # Neither fragment inherits EVENT_0001 -- both become new events.
        new_ids = {e["event_id"] for e in r2["newly_detected_events"]}
        self.assertEqual(new_ids, {"EVENT_0002", "EVENT_0003"})
        # The original event is flagged ambiguous, not silently dropped.
        original = next(e for e in r2["active_events"] if e["event_id"] == "EVENT_0001")
        self.assertEqual(original["evolution_flags"], ["SPLIT_AMBIGUOUS"])
        self.assertIn("SPLIT", original["notes"][0])


class TestEndToEndIntegration(unittest.TestCase):
    """A small number of true end-to-end tests through the real
    AnomalyDetector.update_spatial_event_tracking() pipeline."""

    def _reading(self, sid, lat, lon, t=25.0, p=1013.0, h=55.0):
        return AWSReading(station_id=sid, lat=lat, lon=lon, temperature_c=t, pressure_hpa=p, humidity_pct=h)

    def test_new_then_persisting_through_real_pipeline(self):
        det = AnomalyDetector()
        # R group forms the anomaly cluster; B group sits nearby (within
        # the 250km S1 comparison radius, so R has a genuine local
        # baseline to be judged against) but is NOT itself elevated --
        # the same known-good pattern used throughout the S4 test suite.
        pool = [
            self._reading("R1", 20.1, 77.1, t=42.0), self._reading("R2", 19.9, 77.2, t=43.0),
            self._reading("R3", 20.2, 76.9, t=41.5), self._reading("R4", 20.0, 77.3, t=42.5),
            self._reading("B1", 20.5, 77.5, t=31.0), self._reading("B2", 19.5, 76.5, t=32.0),
            self._reading("B3", 20.6, 76.4, t=30.5), self._reading("B4", 19.4, 77.6, t=31.5),
            self._reading("B5", 20.7, 77.7, t=32.5),
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)

        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        r1 = det.update_spatial_event_tracking(timestamp=t1)
        self.assertEqual(r1["summary"]["new_count"], 1)

        t2 = t1 + timedelta(minutes=10)
        r2 = det.update_spatial_event_tracking(timestamp=t2)
        self.assertEqual(r2["summary"]["updated_count"], 1)
        self.assertEqual(r2["updated_events"][0]["evolution_flags"], ["PERSISTING"])

    def test_production_shape_sample_runs_without_error(self):
        import json
        path = os.path.join(BASE_DIR, "..", "data", "stations.json")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)[:150]
        det = AnomalyDetector()
        pool = [
            AWSReading(station_id=s["id"], lat=s["latitude"], lon=s["longitude"],
                       temperature_c=s.get("temperature"), pressure_hpa=s.get("pressure"),
                       humidity_pct=s.get("humidity"))
            for s in raw
        ]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        r1 = det.update_spatial_event_tracking(timestamp=t1)
        r2 = det.update_spatial_event_tracking(timestamp=t1 + timedelta(minutes=10))
        r3 = det.update_spatial_event_tracking(timestamp=t1 + timedelta(minutes=20))
        for result in (r1, r2, r3):
            for ev in result["active_events"]:
                if ev["centroid"]:
                    self.assertTrue(math.isfinite(ev["centroid"]["lat"]))
                    self.assertTrue(math.isfinite(ev["centroid"]["lon"]))


if __name__ == "__main__":
    unittest.main()
