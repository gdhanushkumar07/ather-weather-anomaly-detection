"""
S1 — Spatial Neighborhood Foundation: focused regression tests.

Covers engine/spatial_neighbors.py directly (unit-level: sorting, self-
exclusion, radius filtering, K-limit, coordinate validation, deterministic
tie handling) and its integration into engine/layer4_spatial.py (channel-
wise DataQuality behavior, IDW consensus, insufficient-neighbor handling).

Existing SPATIAL_OUTLIER / REGIONAL_WEATHER_EVENT / COMBINED_SENSOR_FAILURE
scenario regressions are already covered by tests/test_simulation.py
(test_spatial_outlier_uses_synthetic_neighbors,
test_regional_weather_event_is_not_forced_to_sensor_fault,
test_combined_failure_has_multiple_agreeing_layers) and are not duplicated
here — this file adds NEW coverage for the S1 neighbor-selection pipeline
itself.
"""
import json
import os
import sys
import unittest

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
from engine.spatial_neighbors import (
    select_k_nearest_neighbors,
    is_valid_coordinate,
    haversine_distance_km,
)
from engine.layer4_spatial import SpatialNeighborLayer


def _reading(station_id, lat, lon, temp=25.0, press=1013.0, rh=55.0, elev=0.0):
    return AWSReading(
        station_id=station_id, lat=lat, lon=lon,
        temperature_c=temp, pressure_hpa=press, humidity_pct=rh,
        elevation_m=elev,
    )


class TestKNearestNeighborSelection(unittest.TestCase):
    """Unit-level tests against engine.spatial_neighbors directly."""

    def test_neighbors_are_distance_sorted(self):
        target = _reading("TARGET", 20.0, 77.0)
        # Deliberately scrambled input order, at increasing true distance.
        candidates = [
            _reading("FAR", 20.9, 77.9),
            _reading("NEAR", 20.05, 77.05),
            _reading("MID", 20.3, 77.3),
        ]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        ids = [n.station_id for n in result.neighbors]
        self.assertEqual(ids, ["NEAR", "MID", "FAR"])
        dists = [n.distance_km for n in result.neighbors]
        self.assertEqual(dists, sorted(dists))

    def test_target_station_excluded_from_own_neighbors(self):
        target = _reading("STN-001", 20.0, 77.0)
        # Same station_id as target, but at a different (invalid trick)
        # location — must be excluded purely by identity, not distance.
        candidates = [
            _reading("STN-001", 20.001, 77.001),
            _reading("STN-002", 20.05, 77.05),
        ]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        ids = [n.station_id for n in result.neighbors]
        self.assertNotIn("STN-001", ids)
        self.assertEqual(ids, ["STN-002"])
        self.assertEqual(result.excluded_self, 1)

    def test_radius_filtering_excludes_farther_candidates(self):
        target = _reading("TARGET", 20.0, 77.0)
        candidates = [
            _reading("INSIDE", 20.5, 77.5),    # ~76km — within 250km
            _reading("OUTSIDE", 25.0, 82.0),   # ~740km — outside 250km
        ]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        ids = [n.station_id for n in result.neighbors]
        self.assertEqual(ids, ["INSIDE"])
        self.assertEqual(result.excluded_out_of_radius, 1)
        self.assertEqual(result.within_radius_count, 1)

    def test_k_limit_is_respected(self):
        target = _reading("TARGET", 20.0, 77.0)
        # 6 valid candidates within radius, K=3.
        candidates = [_reading(f"N{i}", 20.0 + i * 0.05, 77.0 + i * 0.05) for i in range(1, 7)]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=3)
        self.assertEqual(len(result.neighbors), 3)
        # within_radius_count reports the TRUE pool size, unaffected by K.
        self.assertEqual(result.within_radius_count, 6)
        # The 3 selected must be the 3 nearest (N1, N2, N3).
        self.assertEqual([n.station_id for n in result.neighbors], ["N1", "N2", "N3"])

    def test_invalid_candidate_coordinates_are_excluded(self):
        target = _reading("TARGET", 20.0, 77.0)
        candidates = [
            _reading("VALID", 20.05, 77.05),
            _reading("BAD_LAT", 999.0, 77.05),
            _reading("BAD_LON", 20.05, -999.0),
            _reading("NAN_LAT", float("nan"), 77.05),
        ]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        ids = [n.station_id for n in result.neighbors]
        self.assertEqual(ids, ["VALID"])
        self.assertEqual(result.excluded_invalid_coordinate, 3)

    def test_invalid_target_coordinate_yields_no_neighbors(self):
        target = _reading("TARGET", 200.0, 77.0)  # invalid latitude
        candidates = [_reading("N1", 20.05, 77.05)]
        result = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        self.assertFalse(result.target_coordinate_valid)
        self.assertEqual(result.neighbors, [])

    def test_is_valid_coordinate_bounds(self):
        self.assertTrue(is_valid_coordinate(0.0, 0.0))
        self.assertTrue(is_valid_coordinate(90.0, 180.0))
        self.assertTrue(is_valid_coordinate(-90.0, -180.0))
        self.assertFalse(is_valid_coordinate(90.1, 0.0))
        self.assertFalse(is_valid_coordinate(0.0, 180.1))
        self.assertFalse(is_valid_coordinate(float("nan"), 0.0))
        self.assertFalse(is_valid_coordinate(float("inf"), 0.0))
        self.assertFalse(is_valid_coordinate(None, 0.0))

    def test_deterministic_tie_handling(self):
        target = _reading("TARGET", 20.0, 77.0)
        # Two candidates at (numerically) identical distance from target —
        # mirrored offsets on either side.
        candidates = [
            _reading("ZEBRA", 20.1, 77.0),
            _reading("ALPHA", 19.9, 77.0),
        ]
        result_1 = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=8)
        result_2 = select_k_nearest_neighbors(target, list(reversed(candidates)), radius_km=250.0, k=8)
        ids_1 = [n.station_id for n in result_1.neighbors]
        ids_2 = [n.station_id for n in result_2.neighbors]
        # Same result regardless of input order — secondary sort key is station_id.
        self.assertEqual(ids_1, ids_2)
        self.assertEqual(ids_1, ["ALPHA", "ZEBRA"])

    def test_selection_is_repeatable(self):
        target = _reading("TARGET", 20.0, 77.0)
        candidates = [_reading(f"N{i}", 20.0 + i * 0.03, 77.0 - i * 0.02) for i in range(1, 10)]
        r1 = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=5)
        r2 = select_k_nearest_neighbors(target, candidates, radius_km=250.0, k=5)
        self.assertEqual(
            [n.station_id for n in r1.neighbors],
            [n.station_id for n in r2.neighbors],
        )

    def test_haversine_known_distance(self):
        # Delhi to Mumbai is approximately 1150-1160 km great-circle.
        d = haversine_distance_km(28.7041, 77.1025, 19.0760, 72.8777)
        self.assertGreater(d, 1100)
        self.assertLess(d, 1200)


class TestLayer4SpatialIntegration(unittest.TestCase):
    """Confirms the shared K-NN pipeline is correctly wired into
    SpatialNeighborLayer.evaluate() without disturbing IDW/scoring."""

    def setUp(self):
        self.layer = SpatialNeighborLayer(CONFIG.spatial)

    def test_insufficient_neighbor_behavior_preserved(self):
        target = _reading("TARGET", 20.0, 77.0, temp=30.0)
        neighbors = [_reading("SOLO", 20.05, 77.05, temp=25.0)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(score, 0.0)
        self.assertEqual(detail["status"], "INSUFFICIENT_NEIGHBORS")
        self.assertIsNone(reason)

    def test_channel_wise_invalid_value_still_allows_other_channels(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0, press=1013.0, rh=50.0)
        neighbors = [
            _reading("N1", 20.05, 77.05, temp=25.0, press=1013.0, rh=None),
            _reading("N2", 20.06, 77.04, temp=24.0, press=1012.0, rh=None),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        # Both neighbors have missing humidity but valid temperature/pressure
        # — humidity must not silently drag the whole station out; the
        # temperature channel is still evaluated using both neighbors.
        temp_result = detail["channel_results"]["temperature_c"]
        self.assertEqual(temp_result.get("usable_neighbors"), 2)
        self.assertGreater(temp_result["score"], 0.0)
        humidity_result = detail["channel_results"]["humidity_pct"]
        self.assertEqual(humidity_result["status"], "INSUFFICIENT_VALID_NEIGHBORS")

    def test_idw_consensus_still_functional(self):
        # Two neighbors at DIFFERENT distances so IDW weighting is
        # observable: the closer one should pull the consensus toward it.
        target = _reading("TARGET", 20.0, 77.0, temp=30.0)
        near = _reading("NEAR", 20.02, 77.0, temp=20.0)   # ~2.2km
        far = _reading("FAR", 20.5, 77.0, temp=40.0)      # ~55.6km
        score, consensus, reason, detail = self.layer.evaluate(target, [near, far])
        c = consensus["temperature_c"]
        self.assertIsNotNone(c)
        # IDW-weighted consensus must sit strictly between the two neighbor
        # values, pulled toward the much-closer NEAR station (not a plain
        # 30.0 midpoint of 20 and 40).
        self.assertGreater(c, 20.0)
        self.assertLess(c, 30.0)

    def test_k_cap_does_not_break_existing_small_neighbor_scenarios(self):
        # SPATIAL_OUTLIER-shaped case: 4 neighbors, well under default K=8.
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0),
            _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0),
            _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(detail["total_neighbors_in_radius"], 4)
        self.assertGreaterEqual(score, 0.5)

    def test_total_neighbors_in_radius_reflects_pool_before_k_cap(self):
        # More than the default K=8 valid neighbors within radius; confirm
        # total_neighbors_in_radius still reports the TRUE pool size while
        # the actual computation uses only the nearest K.
        target = _reading("TARGET", 20.0, 77.0, temp=25.0)
        neighbors = [_reading(f"N{i}", 20.0 + i * 0.02, 77.0, temp=25.0 + (i % 3)) for i in range(1, 13)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(detail["total_neighbors_in_radius"], 12)
        temp_result = detail["channel_results"]["temperature_c"]
        self.assertLessEqual(temp_result["usable_neighbors"], CONFIG.spatial.spatial_k_neighbors)


class TestProductionShapeValidation(unittest.TestCase):
    """S1 item 13: validate the new pipeline against the real production
    station metadata shape (data/stations.json), not just synthetic
    fixtures."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(BASE_DIR, "..", "data", "stations.json")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cls.readings = [
            AWSReading(
                station_id=s["id"], lat=s["latitude"], lon=s["longitude"],
                temperature_c=s.get("temperature"), pressure_hpa=s.get("pressure"),
                humidity_pct=s.get("humidity"),
            )
            for s in raw
        ]

    def test_station_records_load_and_coordinates_parse(self):
        self.assertGreater(len(self.readings), 1000)
        for r in self.readings[:20]:
            self.assertIsInstance(r.lat, float)
            self.assertIsInstance(r.lon, float)

    def test_self_exclusion_and_k_selection_work_on_real_pool(self):
        target = self.readings[0]
        result = select_k_nearest_neighbors(
            target, self.readings,
            radius_km=CONFIG.spatial.neighbor_distance_km_max,
            k=CONFIG.spatial.spatial_k_neighbors,
        )
        ids = [n.station_id for n in result.neighbors]
        self.assertNotIn(target.station_id, ids)
        self.assertLessEqual(len(result.neighbors), CONFIG.spatial.spatial_k_neighbors)
        # Deterministic distance order.
        dists = [n.distance_km for n in result.neighbors]
        self.assertEqual(dists, sorted(dists))

    def test_radius_filtering_works_on_real_pool(self):
        target = self.readings[0]
        result = select_k_nearest_neighbors(
            target, self.readings,
            radius_km=CONFIG.spatial.neighbor_distance_km_max,
            k=1000,
        )
        for n in result.neighbors:
            self.assertLessEqual(n.distance_km, CONFIG.spatial.neighbor_distance_km_max)


if __name__ == "__main__":
    unittest.main()
