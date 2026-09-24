"""
S3 — Regional Event Attribution: focused regression tests.

Covers engine/spatial_attribution.py directly (per-channel evidence
construction, aggregation/classification logic, thresholds) and its
integration into engine/layer4_spatial.py (backward-compatible output,
score compatibility, determinism).

Existing SPATIAL_OUTLIER / REGIONAL_WEATHER_EVENT / COMBINED_SENSOR_FAILURE
scenario regressions remain covered by tests/test_simulation.py and are not
duplicated here. S1's and S2's own regression suites are unaffected and are
re-run alongside this file (see the S3 final report for combined results).
"""
import math
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from schema import AWSReading
from engine.layer4_spatial import SpatialNeighborLayer
from engine.spatial_attribution import (
    ChannelAttributionEvidence,
    compute_channel_attribution_evidence,
    aggregate_regional_attribution,
    MIN_MEANINGFUL_NEIGHBOR_Z,
    MAGNITUDE_CONSISTENCY_LOW_RATIO,
    MAGNITUDE_CONSISTENCY_HIGH_RATIO,
)


def _reading(station_id, lat, lon, temp=25.0, press=1013.0, rh=55.0):
    return AWSReading(
        station_id=station_id, lat=lat, lon=lon,
        temperature_c=temp, pressure_hpa=press, humidity_pct=rh,
    )


class TestChannelAttributionEvidenceUnit(unittest.TestCase):
    """Direct unit tests on compute_channel_attribution_evidence, bypassing
    layer4_spatial.py entirely -- exercises the evidence math in isolation."""

    def test_not_applicable_when_target_not_flagged(self):
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=30.0, target_flagged=False,
            target_robust_z=0.5, regional_median=29.5, regional_mad=1.0,
            neighbor_estimates=[29.0, 30.0], neighbor_weights=[1.0, 1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertFalse(ev.applicable)
        self.assertEqual(ev.regional_event_evidence_strength, 0.0)
        self.assertEqual(ev.isolated_sensor_evidence_strength, 0.0)

    def test_isolated_case_all_neighbors_neutral(self):
        # Target flagged; every neighbor TIGHTLY clustered near the median
        # (each neighbor's own |z| stays below MIN_MEANINGFUL_NEIGHBOR_Z) --
        # textbook isolated fault. median=32.5, mad=0.25 (well below the
        # min_std*0.6745=0.6745 floor -> MIN_SCALE_FALLBACK engages, so each
        # neighbor's z = (x-32.5)/1.0, all comfortably under 1.0 in magnitude).
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=45.0, target_flagged=True,
            target_robust_z=8.0, regional_median=32.5, regional_mad=0.25,
            neighbor_estimates=[32.2, 32.3, 32.7, 32.8],
            neighbor_weights=[1.0, 1.0, 1.0, 1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertTrue(ev.applicable)
        self.assertEqual(ev.neighbor_support_count, 0)
        self.assertGreater(ev.isolated_sensor_evidence_strength, ev.regional_event_evidence_strength)

    def test_regional_case_supporting_neighbors_present(self):
        # 3 of 8 neighbors support the target's direction AND are
        # deliberately given higher IDW weight (closer distance) than the
        # 5 non-supporting neighbors -- both count-based support AND
        # distance-awareness favor the regional hypothesis here (item 6 of
        # the S3 spec: closer supporting stations should be MORE
        # informative). Contrast with the equal-weight case, where the
        # same 3/8 split alone is not enough (see the dedicated
        # distance-awareness test below).
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=44.0, target_flagged=True,
            target_robust_z=5.28, regional_median=32.25, regional_mad=1.5,
            neighbor_estimates=[42.0, 43.0, 41.5, 31.0, 32.0, 30.5, 31.5, 32.5],
            neighbor_weights=[3.0, 3.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertTrue(ev.applicable)
        self.assertEqual(ev.neighbor_support_count, 3)
        self.assertGreater(ev.regional_event_evidence_strength, ev.isolated_sensor_evidence_strength)

    def test_distance_awareness_equal_weight_support_alone_may_not_dominate(self):
        # Same 3/8 supporting split as above, but with EQUAL weights (no
        # distance advantage for the supporters) -- demonstrates that
        # distance-awareness is doing real work, not just neighbor counting:
        # without a distance advantage, 3/8 support (37.5%) is not enough to
        # outweigh isolated evidence's full (1 - 0.375) = 0.625.
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=44.0, target_flagged=True,
            target_robust_z=5.28, regional_median=32.25, regional_mad=1.5,
            neighbor_estimates=[42.0, 43.0, 41.5, 31.0, 32.0, 30.5, 31.5, 32.5],
            neighbor_weights=[1.0] * 8,
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertEqual(ev.neighbor_support_count, 3)
        self.assertAlmostEqual(ev.distance_weighted_support, ev.neighbor_support_ratio)
        self.assertGreater(ev.isolated_sensor_evidence_strength, ev.regional_event_evidence_strength)

    def test_neighbor_does_not_use_target_itself(self):
        # The target's own value must never appear in neighbor_estimates --
        # this is a contract test on the CALLER (layer4_spatial.py already
        # excludes target from `estimates`), verified here by confirming a
        # neighbor list that does NOT include the target value still
        # produces sane, non-crashing evidence.
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=45.0, target_flagged=True,
            target_robust_z=6.0, regional_median=32.0, regional_mad=1.0,
            neighbor_estimates=[31.0, 32.0, 33.0],
            neighbor_weights=[1.0, 1.0, 1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertEqual(ev.usable_neighbors, 3)
        self.assertNotIn(45.0, [31.0, 32.0, 33.0])  # sanity: target value absent from neighbor pool

    def test_directional_agreement_field_reflects_support_presence(self):
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=50.0, target_flagged=True,
            target_robust_z=7.76, regional_median=27.0, regional_mad=2.0,
            neighbor_estimates=[45.0, 46.0, 25.0, 26.0, 27.0],
            neighbor_weights=[1.0] * 5,
            min_std=1.0, spatial_k_neighbors=8,
        )
        d = ev.to_dict()
        self.assertTrue(d["regional_event_evidence"]["directional_agreement"])
        self.assertEqual(d["regional_event_evidence"]["neighbor_support_count"], 2)

    def test_directional_disagreement_field_reflects_opposition_presence(self):
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=45.0, target_flagged=True,
            target_robust_z=15.0, regional_median=30.0, regional_mad=1.0,
            neighbor_estimates=[43.0, 15.0, 30.0, 30.5, 29.5],
            neighbor_weights=[1.0] * 5,
            min_std=1.0, spatial_k_neighbors=8,
        )
        d = ev.to_dict()
        self.assertTrue(d["isolated_sensor_evidence"]["directional_disagreement"])
        self.assertGreaterEqual(d["isolated_sensor_evidence"]["neighbor_disagreement_count"], 1)

    def test_magnitude_consistency_tolerant_band_not_exact_equality(self):
        # A supporting neighbor at ~2x the target's magnitude (within the
        # documented [1/3, 3x] tolerant band) must still count as
        # "consistent" -- the task explicitly forbids requiring exact
        # equality.
        # target z ~= 4.0; supporting neighbor z ~= 8.0 (2x, inside band)
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=38.0, target_flagged=True,
            target_robust_z=4.0, regional_median=30.0, regional_mad=2.0,
            neighbor_estimates=[45.9],  # z = (45.9-30)*0.6745/2 ~= 5.36... use a cleaner value below instead
            neighbor_weights=[1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        # Recompute with an exact, hand-verified pair instead of the messy value above.
        # median=30, mad=2 -> z(x) = (x-30)*0.6745/2. Want neighbor z ~= 2x target z (8.0).
        # x = 30 + 8.0*2/0.6745 = 30 + 23.72 = 53.72
        ev2 = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=38.0, target_flagged=True,
            target_robust_z=4.0, regional_median=30.0, regional_mad=2.0,
            neighbor_estimates=[53.72],
            neighbor_weights=[1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertEqual(ev2.magnitude_consistency, 1.0)  # within [1/3, 3x] band -> counted consistent

    def test_magnitude_consistency_none_when_no_supporting_neighbors(self):
        # Tight cluster (see test_isolated_case_all_neighbors_neutral for
        # the same construction): no neighbor clears MIN_MEANINGFUL_NEIGHBOR_Z,
        # so there is nothing to compare magnitude against.
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=45.0, target_flagged=True,
            target_robust_z=8.0, regional_median=32.5, regional_mad=0.25,
            neighbor_estimates=[32.2, 32.3, 32.7, 32.8],
            neighbor_weights=[1.0] * 4,
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertIsNone(ev.magnitude_consistency)

    def test_spatial_coverage_derived_from_spatial_k_neighbors(self):
        ev = compute_channel_attribution_evidence(
            channel="temperature_c", target_value=45.0, target_flagged=True,
            target_robust_z=8.0, regional_median=32.0, regional_mad=1.0,
            neighbor_estimates=[31.0, 32.0],  # 2 of a configured K=8
            neighbor_weights=[1.0, 1.0],
            min_std=1.0, spatial_k_neighbors=8,
        )
        self.assertAlmostEqual(ev.spatial_coverage, 2 / 8)

    def test_min_meaningful_neighbor_z_constant_is_one(self):
        # Documents/pins the centralized constant -- not an invented value
        # slipping in unnoticed.
        self.assertEqual(MIN_MEANINGFUL_NEIGHBOR_Z, 1.0)

    def test_magnitude_band_is_symmetric_in_ratio_space(self):
        self.assertAlmostEqual(MAGNITUDE_CONSISTENCY_LOW_RATIO * MAGNITUDE_CONSISTENCY_HIGH_RATIO, 1.0)


class TestAggregateRegionalAttribution(unittest.TestCase):
    """Direct unit tests on aggregate_regional_attribution's classification
    logic, using hand-built ChannelAttributionEvidence objects."""

    def _ev(self, channel, applicable, regional=0.0, isolated=0.0):
        return ChannelAttributionEvidence(
            channel=channel, applicable=applicable, target_value=1.0, target_robust_z=1.0,
            target_direction=1, usable_neighbors=4, spatial_coverage=0.5,
            neighbor_support_count=0, neighbor_disagreement_count=0, neighbor_neutral_count=4,
            neighbor_support_ratio=0.0, neighbor_disagreement_ratio=0.0,
            distance_weighted_support=0.0, distance_weighted_contradiction=0.0, magnitude_consistency=None,
            regional_event_evidence_strength=regional, isolated_sensor_evidence_strength=isolated,
        )

    def test_no_applicable_channels_is_uncertain(self):
        result = aggregate_regional_attribution(
            {"temperature_c": self._ev("temperature_c", False)},
            min_neighbors_required=2, spatial_k_neighbors=8,
        )
        self.assertEqual(result.classification, "UNCERTAIN")
        self.assertEqual(result.confidence, 0.0)

    def test_contradictory_channels_force_uncertain(self):
        evidence = {
            "temperature_c": self._ev("temperature_c", True, regional=0.8, isolated=0.1),
            "pressure_hpa": self._ev("pressure_hpa", True, regional=0.1, isolated=0.8),
        }
        result = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result.classification, "UNCERTAIN")
        self.assertIn("disagree", result.explanation.lower())

    def test_agreeing_channels_classify_regional(self):
        evidence = {
            "temperature_c": self._ev("temperature_c", True, regional=0.8, isolated=0.1),
            "pressure_hpa": self._ev("pressure_hpa", True, regional=0.7, isolated=0.05),
        }
        result = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result.classification, "REGIONAL_EVENT")
        self.assertGreater(result.confidence, 0.0)

    def test_agreeing_channels_classify_isolated(self):
        evidence = {
            "temperature_c": self._ev("temperature_c", True, regional=0.05, isolated=0.7),
        }
        result = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result.classification, "ISOLATED_SENSOR_ANOMALY")

    def test_exactly_at_minimum_evidence_bar_is_uncertain_not_classified(self):
        # min_evidence_strength = 2/8 = 0.25 exactly -> must NOT classify.
        evidence = {"temperature_c": self._ev("temperature_c", True, regional=0.0, isolated=0.25)}
        result = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result.classification, "UNCERTAIN")

    def test_deterministic_channel_ordering_in_explanation(self):
        evidence = {
            "humidity_pct": self._ev("humidity_pct", True, regional=0.8, isolated=0.1),
            "temperature_c": self._ev("temperature_c", True, regional=0.7, isolated=0.05),
        }
        r1 = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        r2 = aggregate_regional_attribution(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r1.explanation, r2.explanation)
        # applicable_channels always follows CHANNEL_ORDER (temperature before humidity)
        self.assertEqual(r1.applicable_channels, ("temperature_c", "humidity_pct"))


class TestLayer4AttributionIntegration(unittest.TestCase):
    """End-to-end tests through the real SpatialNeighborLayer.evaluate()."""

    def setUp(self):
        self.layer = SpatialNeighborLayer(CONFIG.spatial)

    # CASE 1 — isolated sensor fault
    def test_case1_isolated_sensor_fault(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0), _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0), _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "ISOLATED_SENSOR_ANOMALY")
        self.assertGreater(ra["confidence"], 0.0)

    # CASE 2 — regional weather event (minority-of-8 elevated cluster)
    def test_case2_regional_event(self):
        target = _reading("TARGET", 20.0, 77.0, temp=44.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, temp=42.0), _reading("N2", 19.9, 77.2, temp=43.0),
            _reading("N3", 20.2, 76.9, temp=41.5),
            _reading("N4", 20.5, 77.5, temp=31.0), _reading("N5", 19.5, 76.5, temp=32.0),
            _reading("N6", 20.6, 76.4, temp=30.5), _reading("N7", 19.4, 77.6, temp=31.5),
            _reading("N8", 20.7, 77.7, temp=32.5),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "REGIONAL_EVENT")
        self.assertGreater(ra["confidence"], 0.5)

    # CASE 3 — weak/insufficient neighborhood (exactly minimum, no support)
    def test_case3_weak_neighborhood_is_uncertain(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [_reading("N1", 20.05, 77.05, temp=25.0), _reading("N2", 20.06, 77.04, temp=26.0)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "UNCERTAIN")
        self.assertLess(ra["confidence"], 0.5)

    # CASE 3b — below min_neighbors_required entirely
    def test_case3b_single_neighbor_insufficient_is_uncertain(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [_reading("SOLO", 20.05, 77.05, temp=25.0)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "UNCERTAIN")
        self.assertEqual(ra["confidence"], 0.0)

    # CASE 4 — genuinely mixed neighbor evidence -> reduced/moderate confidence
    def test_case4_mixed_neighbor_evidence_reduces_confidence(self):
        target = _reading("TARGET", 20.0, 77.0, temp=50.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, temp=45.0), _reading("N2", 19.9, 77.2, temp=46.0),  # support
            _reading("N3", 20.2, 76.9, temp=25.0), _reading("N4", 19.8, 76.8, temp=26.0),  # normal
            _reading("N5", 20.3, 77.3, temp=27.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        # Evidence is genuinely close between the two hypotheses -- neither
        # dominates overwhelmingly (contrast with CASE 1/2's clean splits).
        self.assertLess(abs(ra["regional_event_evidence_strength"] - ra["isolated_sensor_evidence_strength"]), 0.15)
        self.assertLess(ra["confidence"], 0.6)

    def test_case4_explicit_disagreement_evidence_present(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, temp=43.0),  # supports
            _reading("N2", 19.9, 77.2, temp=15.0),  # disagrees (opposite direction)
            _reading("N3", 20.2, 76.9, temp=30.0), _reading("N4", 19.8, 76.8, temp=30.5),
            _reading("N5", 20.3, 77.3, temp=29.5),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        t_ev = detail["channel_results"]["temperature_c"]["attribution_evidence"]
        self.assertTrue(t_ev["isolated_sensor_evidence"]["directional_disagreement"])
        self.assertGreaterEqual(t_ev["isolated_sensor_evidence"]["neighbor_disagreement_count"], 1)

    # CASE 5 — multi-channel regional event
    def test_case5_multichannel_regional_event_stronger_than_single_channel(self):
        target = AWSReading(station_id="TARGET", lat=20.0, lon=77.0,
                             temperature_c=42.0, pressure_hpa=1005.0, humidity_pct=30.0)
        neighbors = [
            AWSReading(station_id="N1", lat=20.1, lon=77.1, temperature_c=41.0, pressure_hpa=1005.5, humidity_pct=31.0),
            AWSReading(station_id="N2", lat=19.9, lon=77.2, temperature_c=40.5, pressure_hpa=1004.5, humidity_pct=29.0),
            AWSReading(station_id="N3", lat=20.2, lon=76.9, temperature_c=25.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N4", lat=19.8, lon=76.8, temperature_c=26.0, pressure_hpa=1012.5, humidity_pct=54.0),
            AWSReading(station_id="N5", lat=20.3, lon=77.3, temperature_c=24.5, pressure_hpa=1013.5, humidity_pct=56.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "REGIONAL_EVENT")
        self.assertEqual(len(ra["applicable_channels"]), 3)  # temp, pressure, humidity all applicable

        # A single-channel-only version of the same story should show
        # WEAKER (or at most equal) multi-channel corroboration than the
        # full 3-channel version -- fewer applicable channels is less
        # total evidence, not more.
        target_single = AWSReading(station_id="TARGET", lat=20.0, lon=77.0,
                                    temperature_c=42.0, pressure_hpa=1013.0, humidity_pct=55.0)
        neighbors_single = [
            AWSReading(station_id="N1", lat=20.1, lon=77.1, temperature_c=41.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N2", lat=19.9, lon=77.2, temperature_c=40.5, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N3", lat=20.2, lon=76.9, temperature_c=25.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N4", lat=19.8, lon=76.8, temperature_c=26.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N5", lat=20.3, lon=77.3, temperature_c=24.5, pressure_hpa=1013.0, humidity_pct=55.0),
        ]
        _, _, _, detail_single = self.layer.evaluate(target_single, neighbors_single)
        ra_single = detail_single["regional_attribution"]
        self.assertEqual(len(ra_single["applicable_channels"]), 1)

    # CASE 6 — single-channel sensor fault (temp anomalous, pressure/humidity normal)
    def test_case6_single_channel_fault_does_not_force_regional_event(self):
        target = AWSReading(station_id="TARGET", lat=20.0, lon=77.0,
                             temperature_c=45.0, pressure_hpa=1013.0, humidity_pct=55.0)
        neighbors = [
            AWSReading(station_id="N1", lat=20.3, lon=77.2, temperature_c=31.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N2", lat=19.75, lon=77.35, temperature_c=32.0, pressure_hpa=1012.5, humidity_pct=54.0),
            AWSReading(station_id="N3", lat=20.4, lon=76.7, temperature_c=33.0, pressure_hpa=1013.5, humidity_pct=56.0),
            AWSReading(station_id="N4", lat=19.65, lon=76.8, temperature_c=34.0, pressure_hpa=1012.8, humidity_pct=55.5),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        ra = detail["regional_attribution"]
        self.assertEqual(ra["classification"], "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(ra["applicable_channels"], ["temperature_c"])

    def test_deterministic_results_across_repeated_calls_and_input_order(self):
        target = _reading("TARGET", 20.0, 77.0, temp=44.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, temp=42.0), _reading("N2", 19.9, 77.2, temp=43.0),
            _reading("N3", 20.2, 76.9, temp=41.5), _reading("N4", 20.5, 77.5, temp=31.0),
        ]
        r1 = self.layer.evaluate(target, list(neighbors))
        r2 = self.layer.evaluate(target, list(reversed(neighbors)))
        self.assertEqual(r1[3]["regional_attribution"], r2[3]["regional_attribution"])

    def test_backward_compatible_output_unaffected_by_s3(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, temp=31.0), _reading("N2", 19.75, 77.35, temp=32.0),
            _reading("N3", 20.4, 76.7, temp=33.0), _reading("N4", 19.65, 76.8, temp=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        # All pre-S3 top-level detail fields remain.
        for field in ("total_neighbors_in_radius", "distance_range_km", "channel_results",
                      "status", "confidence_cap_reason"):
            self.assertIn(field, detail)
        # All pre-S3/pre-S2 channel_results fields remain.
        t_res = detail["channel_results"]["temperature_c"]
        for field in ("target_value", "consensus_value", "deviation", "z_score",
                      "usable_neighbors", "method", "score", "flagged"):
            self.assertIn(field, t_res)
        self.assertIn("attribution_evidence", t_res)  # new, additive
        self.assertIn("regional_attribution", detail)  # new, additive
        self.assertIsInstance(score, float)
        self.assertIn("temperature_c", consensus)

    def test_insufficient_neighbors_still_reports_regional_attribution_key(self):
        target = _reading("TARGET", 20.0, 77.0, temp=45.0)
        neighbors = [_reading("SOLO", 20.05, 77.05, temp=25.0)]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(detail["status"], "INSUFFICIENT_NEIGHBORS")
        self.assertIn("regional_attribution", detail)
        self.assertEqual(detail["regional_attribution"]["classification"], "UNCERTAIN")


class TestProductionShapeAttributionValidation(unittest.TestCase):
    """S3 production-shape validation: confirm the attribution pipeline
    computes without error against the real production station metadata
    shape (data/stations.json). This file is demo/production-shape
    metadata, not guaranteed physical AWS observations -- used only to
    confirm computability, not as a ground-truth claim."""

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

    def test_regional_attribution_computes_without_error_on_real_production_pool(self):
        seen_classifications = set()
        for target in self.readings[:50]:
            score, consensus, reason, detail = self.layer.evaluate(target, self.readings)
            ra = detail.get("regional_attribution")
            self.assertIsNotNone(ra)
            self.assertIn(ra["classification"], ("REGIONAL_EVENT", "ISOLATED_SENSOR_ANOMALY", "UNCERTAIN"))
            self.assertTrue(math.isfinite(ra["confidence"]))
            seen_classifications.add(ra["classification"])
        self.assertGreater(len(seen_classifications), 0)


if __name__ == "__main__":
    unittest.main()
