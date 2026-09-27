"""
S2 — Robust Spatial Statistics: focused regression tests.

Covers engine/spatial_statistics.py directly (median, MAD, robust z-score,
zero-MAD fallback, IDW helper, NaN handling) and its integration into
engine/layer4_spatial.py (backward-compatible output, score compatibility,
DataQuality filtering, minimum-neighbor behavior, determinism).

Existing SPATIAL_OUTLIER / REGIONAL_WEATHER_EVENT / COMBINED_SENSOR_FAILURE
scenario regressions remain covered by tests/test_simulation.py and are not
duplicated here -- this file adds NEW coverage for the S2 robust-statistics
layer itself. S1's own regression suite
(tests/test_spatial_neighbor_foundation.py) is unaffected and re-run
alongside this file (see the S2 final report for combined results).
"""
import math
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
from engine.spatial_statistics import (
    MAD_CONSISTENCY_CONSTANT,
    compute_median,
    compute_mad,
    compute_robust_z,
    compute_idw_statistics,
    compute_robust_spatial_evidence,
)
from engine.layer4_spatial import SpatialNeighborLayer


def _reading(station_id, lat, lon, temp=25.0, press=1013.0, rh=55.0, elev=0.0):
    return AWSReading(
        station_id=station_id, lat=lat, lon=lon,
        temperature_c=temp, pressure_hpa=press, humidity_pct=rh,
        elevation_m=elev,
    )


class TestMedianAndMAD(unittest.TestCase):
    """1 & 2: median and MAD calculation."""

    def test_median_odd_count(self):
        self.assertEqual(compute_median([3.0, 1.0, 2.0]), 2.0)

    def test_median_even_count(self):
        # Average of the two middle sorted values.
        self.assertEqual(compute_median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_mad_known_value(self):
        # values = [1,1,2,2,4] -> median=2, abs deviations=[1,1,0,0,2] -> median of those = 1
        values = [1.0, 1.0, 2.0, 2.0, 4.0]
        median = compute_median(values)
        self.assertEqual(median, 2.0)
        self.assertEqual(compute_mad(values, center=median), 1.0)

    def test_mad_reuses_precomputed_center(self):
        values = [10.0, 12.0, 14.0]
        median = compute_median(values)
        self.assertEqual(compute_mad(values), compute_mad(values, center=median))

    def test_median_and_mad_require_nonempty(self):
        with self.assertRaises(ValueError):
            compute_median([])
        with self.assertRaises(ValueError):
            compute_mad([])


class TestRobustZScore(unittest.TestCase):
    """3, 4: robust z-score formula and the zero-MAD safety fallback."""

    def test_robust_z_matches_textbook_formula_when_mad_is_large_enough(self):
        # MAD well above the floor -> exact 0.6745*(x-median)/MAD, no fallback.
        median, mad, min_scale = 30.0, 2.0, 1.0
        z, method = compute_robust_z(34.0, median, mad, min_scale=min_scale)
        expected = MAD_CONSISTENCY_CONSTANT * (34.0 - median) / mad
        self.assertAlmostEqual(z, expected, places=9)
        self.assertEqual(method, "MAD")

    def test_robust_z_is_signed(self):
        z_above, _ = compute_robust_z(35.0, 30.0, 2.0, min_scale=1.0)
        z_below, _ = compute_robust_z(25.0, 30.0, 2.0, min_scale=1.0)
        self.assertGreater(z_above, 0)
        self.assertLess(z_below, 0)

    def test_zero_mad_does_not_divide_by_zero(self):
        # All neighbors report the identical value -> MAD == 0 exactly.
        z, method = compute_robust_z(35.0, 30.0, 0.0, min_scale=1.0)
        self.assertTrue(math.isfinite(z))
        self.assertEqual(method, "MIN_SCALE_FALLBACK")

    def test_zero_mad_fallback_matches_deviation_over_min_scale(self):
        # Algebraic identity documented in spatial_statistics.py: when MAD
        # is below the floor, robust_z reduces exactly to
        # (value - median) / min_scale.
        z, method = compute_robust_z(33.0, 30.0, 0.0, min_scale=1.0)
        self.assertEqual(method, "MIN_SCALE_FALLBACK")
        self.assertAlmostEqual(z, (33.0 - 30.0) / 1.0, places=9)

    def test_tiny_nonzero_mad_still_uses_fallback_floor(self):
        # MAD > 0 but far below the floor -- must still use the floor, not
        # the raw (near-zero) MAD, to avoid an exploding z-score.
        z, method = compute_robust_z(31.0, 30.0, 1e-6, min_scale=1.0)
        self.assertEqual(method, "MIN_SCALE_FALLBACK")
        self.assertTrue(math.isfinite(z))
        self.assertLess(abs(z), 10.0)  # not an exploded value

    def test_nan_mad_input_propagates_predictably_not_silently(self):
        # NaN/non-finite input is not repaired -- it propagates to the
        # output rather than being silently treated as zero or a valid
        # number, so a caller can detect it rather than trust a bad score.
        z, method = compute_robust_z(31.0, float("nan"), 1.0, min_scale=1.0)
        self.assertTrue(math.isnan(z))


class TestIDWStatisticsHelper(unittest.TestCase):
    """6: the existing IDW baseline, factored into a standalone helper."""

    def test_idw_mean_matches_manual_weighted_average(self):
        estimates = [10.0, 20.0, 30.0]
        weights = [1.0, 1.0, 2.0]  # third estimate weighted twice as heavily
        result = compute_idw_statistics(estimates, weights, target_value=25.0, min_std=1.0)
        expected_mean = (10.0 * 1.0 + 20.0 * 1.0 + 30.0 * 2.0) / (1.0 + 1.0 + 2.0)
        self.assertAlmostEqual(result["idw_mean"], expected_mean, places=9)

    def test_idw_std_respects_min_std_floor(self):
        # All estimates identical -> raw std=0 -> floor must apply.
        result = compute_idw_statistics([20.0, 20.0, 20.0], [1.0, 1.0, 1.0], target_value=20.0, min_std=1.0)
        self.assertEqual(result["idw_std"], 1.0)

    def test_idw_statistics_requires_nonempty(self):
        with self.assertRaises(ValueError):
            compute_idw_statistics([], [], target_value=1.0, min_std=1.0)


class TestSingleExtremeNeighborRobustness(unittest.TestCase):
    """5: the task's own worked example -- one extreme neighbor among a
    tight cluster must have limited influence on the median baseline,
    without hardcoding a specific expected score."""

    def test_extreme_neighbor_barely_moves_median_but_pulls_the_mean(self):
        target = 30.0
        neighbor_values = [30.1, 30.2, 29.9, 30.0, 30.3, 50.0]  # one extreme (50.0) among a tight cluster
        equal_weights = [1.0] * len(neighbor_values)

        evidence = compute_robust_spatial_evidence(neighbor_values, equal_weights, target, min_std=1.0)

        tight_cluster_low, tight_cluster_high = 29.9, 30.3
        # The median-based baseline must stay INSIDE the tight cluster's
        # own range -- the extreme neighbor does not drag it out.
        self.assertGreaterEqual(evidence["regional_median"], tight_cluster_low)
        self.assertLessEqual(evidence["regional_median"], tight_cluster_high)

        # The IDW/mean-based baseline, by contrast, is measurably pulled
        # toward the extreme neighbor, landing OUTSIDE the tight cluster's
        # range -- this is the concrete failure mode S2 targets.
        self.assertGreater(evidence["idw_mean"], tight_cluster_high)

        # The robust baseline is therefore closer to the tight cluster's
        # center (and to the target) than the IDW baseline is, without
        # asserting any specific hardcoded numeric threshold.
        median_error = abs(evidence["regional_median"] - target)
        idw_error = abs(evidence["idw_mean"] - target)
        self.assertLess(median_error, idw_error)

    def test_all_neighbors_identical_mad_zero_fallback_engages(self):
        neighbor_values = [30.0, 30.0, 30.0, 30.0]
        evidence = compute_robust_spatial_evidence(neighbor_values, [1.0] * 4, target_value=30.0, min_std=1.0)
        self.assertEqual(evidence["regional_mad"], 0.0)
        self.assertEqual(evidence["robust_z_method"], "MIN_SCALE_FALLBACK")
        self.assertTrue(math.isfinite(evidence["robust_z"]))


class TestLayer4RobustIntegration(unittest.TestCase):
    """Backward compatibility, score compatibility, DataQuality filtering,
    minimum-neighbor behavior, and determinism through the real
    SpatialNeighborLayer.evaluate() entry point."""

    def setUp(self):
        self.layer = SpatialNeighborLayer(CONFIG.spatial)

    def test_backward_compatible_output_fields_unchanged(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0),
            _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0),
            _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        t_res = detail["channel_results"]["temperature_c"]
        # Every pre-S2 field must still be present with its original name.
        for field in ("target_value", "consensus_value", "deviation", "z_score",
                      "usable_neighbors", "method", "score", "flagged"):
            self.assertIn(field, t_res)
        # New S2 fields are ADDITIONAL, not replacements.
        for field in ("idw_mean", "idw_std", "idw_z", "regional_median",
                      "regional_mad", "robust_z", "robust_z_method"):
            self.assertIn(field, t_res)
        # idw_mean must equal consensus_value (same underlying quantity,
        # exposed under both the legacy and the new canonical name).
        self.assertAlmostEqual(t_res["idw_mean"], t_res["consensus_value"], places=1)

    def test_anomaly_score_unchanged_by_s2(self):
        # SPATIAL_OUTLIER-shaped case: score must still come from the IDW
        # z-score vs spatial_z_threshold comparison, exactly as before S2.
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0),
            _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0),
            _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        t_res = detail["channel_results"]["temperature_c"]
        # score must be derivable from idw_z (NOT robust_z) exactly as the
        # pre-S2 formula: min(1, (z - threshold)/3 + 0.5), capped by the
        # existing neighbor-count confidence cap (4 neighbors -> 0.75).
        z = t_res["idw_z"]
        threshold = CONFIG.spatial.spatial_z_threshold
        n_count = len(neighbors)
        confidence_cap = 1.0 if n_count >= 5 else (0.75 if n_count >= 3 else 0.5)
        expected_raw = min(1.0, (z - threshold) / 3.0 + 0.5) if z > threshold else 0.0
        expected_raw = min(expected_raw, confidence_cap)
        self.assertAlmostEqual(round(expected_raw, 3), t_res["score"], places=2)

    def test_exactly_minimum_neighbor_count_produces_robust_fields(self):
        target = _reading("TARGET", 20.0, 77.0, temp=30.0)
        neighbors = [
            _reading("N1", 20.05, 77.05, temp=25.0),
            _reading("N2", 20.06, 77.04, temp=26.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        t_res = detail["channel_results"]["temperature_c"]
        self.assertEqual(t_res["usable_neighbors"], CONFIG.spatial.min_neighbors_required)
        self.assertIn("regional_median", t_res)
        self.assertIn("robust_z", t_res)

    def test_fewer_than_minimum_neighbors_reports_insufficient_no_robust_fields(self):
        target = _reading("TARGET", 20.0, 77.0, temp=30.0)
        neighbors = [_reading("SOLO", 20.05, 77.05, temp=25.0)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(detail["status"], "INSUFFICIENT_NEIGHBORS")
        # channel_results is empty at the top level (evaluate() returns
        # before any channel is evaluated) -- confirms no robust stats are
        # fabricated when there isn't enough spatial evidence.
        self.assertEqual(detail["channel_results"], {})

    def test_data_quality_filtering_excludes_invalid_channel_from_robust_stats(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0, press=1013.0, rh=50.0)
        neighbors = [
            _reading("N1", 20.05, 77.05, temp=25.0, press=1013.0, rh=None),
            _reading("N2", 20.06, 77.04, temp=24.0, press=1012.0, rh=None),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        temp_result = detail["channel_results"]["temperature_c"]
        self.assertEqual(temp_result["usable_neighbors"], 2)
        self.assertIn("regional_median", temp_result)
        humidity_result = detail["channel_results"]["humidity_pct"]
        self.assertEqual(humidity_result["status"], "INSUFFICIENT_VALID_NEIGHBORS")
        self.assertNotIn("regional_median", humidity_result)

    def test_deterministic_results_across_repeated_calls(self):
        target = _reading("TARGET", 20.0, 77.0, temp=33.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, temp=30.0),
            _reading("N2", 19.9, 77.2, temp=31.0),
            _reading("N3", 20.2, 76.9, temp=45.0),  # one extreme neighbor
        ]
        r1 = self.layer.evaluate(target, list(neighbors))
        r2 = self.layer.evaluate(target, list(reversed(neighbors)))
        t1 = r1[3]["channel_results"]["temperature_c"]
        t2 = r2[3]["channel_results"]["temperature_c"]
        self.assertEqual(t1["regional_median"], t2["regional_median"])
        self.assertEqual(t1["regional_mad"], t2["regional_mad"])
        self.assertEqual(t1["robust_z"], t2["robust_z"])
        self.assertEqual(t1["idw_mean"], t2["idw_mean"])

    def test_consensus_dict_and_overall_score_unaffected(self):
        # The 2nd/1st return values (used by self-healing imputation and
        # fusion respectively) must be untouched by S2.
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0),
            _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0),
            _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertIn("temperature_c", consensus)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestProductionShapeRobustValidation(unittest.TestCase):
    """S2 item G: validate the robust-statistics pipeline against the real
    production station metadata shape (data/stations.json). This file is
    demo/production-shape metadata, not guaranteed physical AWS
    observations, and its elevation field is effectively always 0 -- it is
    used here only to confirm the pipeline computes without error on the
    real production data shape, not as a ground-truth claim."""

    @classmethod
    def setUpClass(cls):
        import json
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
        cls.layer = SpatialNeighborLayer(CONFIG.spatial)

    def test_robust_statistics_compute_without_error_on_real_production_pool(self):
        computed = 0
        for target in self.readings[:50]:  # bounded sample; full pool exercised in the audit script
            score, consensus, reason, detail = self.layer.evaluate(target, self.readings)
            if detail["status"] == "EVALUATED":
                t_res = detail["channel_results"].get("temperature_c", {})
                if "regional_median" in t_res:
                    computed += 1
                    self.assertTrue(math.isfinite(t_res["regional_median"]))
                    self.assertTrue(math.isfinite(t_res["robust_z"]))
        self.assertGreater(computed, 0)


if __name__ == "__main__":
    unittest.main()
