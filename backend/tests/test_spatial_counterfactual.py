"""
S6 — Counterfactual Verification: focused regression tests.

Covers engine/spatial_counterfactual.py directly (per-channel decision
rule, using hand-built S3 ChannelAttributionEvidence objects for precise,
predictable control -- the same testing strategy already used for S3/S4/
S5) plus real end-to-end integration through
engine.layer4_spatial.SpatialNeighborLayer.evaluate() with carefully
constructed neighbor geometry (tight "quiet" clusters vs genuine
minority-opposition groups -- the same geometric lessons already learned
building the S3/S4 test suites).

Existing S1-S5 regression suites are unaffected and re-run alongside this
file (see the S6 final report for combined results).
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
from engine.spatial_attribution import ChannelAttributionEvidence
from engine.spatial_counterfactual import (
    evaluate_channel_counterfactual,
    evaluate_counterfactual_verification,
    SUPPORTED,
    CONTRADICTED,
    INSUFFICIENT_EVIDENCE,
)


def _reading(sid, lat, lon, t=25.0, p=1013.0, h=55.0):
    return AWSReading(station_id=sid, lat=lat, lon=lon, temperature_c=t, pressure_hpa=p, humidity_pct=h)


def _evidence(
    applicable=True, usable_neighbors=4, support_count=0, disagree_count=0,
    weighted_support=0.0, weighted_contradiction=0.0, support_ratio=None, disagree_ratio=None,
):
    n = usable_neighbors
    return ChannelAttributionEvidence(
        channel="temperature_c", applicable=applicable, target_value=45.0, target_robust_z=8.0,
        target_direction=1, usable_neighbors=n, spatial_coverage=min(1.0, n / 8),
        neighbor_support_count=support_count, neighbor_disagreement_count=disagree_count,
        neighbor_neutral_count=max(0, n - support_count - disagree_count),
        neighbor_support_ratio=support_ratio if support_ratio is not None else (support_count / n if n else 0.0),
        neighbor_disagreement_ratio=disagree_ratio if disagree_ratio is not None else (disagree_count / n if n else 0.0),
        distance_weighted_support=weighted_support,
        distance_weighted_contradiction=weighted_contradiction,
        magnitude_consistency=None,
        regional_event_evidence_strength=0.0, isolated_sensor_evidence_strength=0.0,
    )


class TestChannelCounterfactualUnit(unittest.TestCase):
    """Direct unit tests against evaluate_channel_counterfactual, using
    hand-built ChannelAttributionEvidence for exact, predictable control."""

    def test_not_applicable_is_insufficient_evidence(self):
        ev = _evidence(applicable=False)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(r.evidence_strength)

    def test_below_min_neighbors_is_insufficient_evidence(self):
        ev = _evidence(usable_neighbors=1)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(r.evidence_strength)

    # Case E — no valid neighbors at all
    def test_zero_valid_neighbors_is_insufficient_evidence(self):
        ev = _evidence(usable_neighbors=0, support_count=0, disagree_count=0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(r.evidence_strength)

    # Exactly the minimum valid neighbors, both supporting
    def test_exactly_minimum_valid_neighbors_supporting(self):
        ev = _evidence(usable_neighbors=2, support_count=2, weighted_support=1.0, weighted_contradiction=0.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, SUPPORTED)
        self.assertEqual(r.evidence_strength, 1.0)

    # Single valid neighbor (below min_neighbors_required=2)
    def test_single_valid_neighbor_is_insufficient(self):
        ev = _evidence(usable_neighbors=1, support_count=1, weighted_support=1.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)

    # Case A/C — neighbors quiet (neither support nor contradiction clears the bar)
    def test_neighbors_quiet_is_contradicted(self):
        ev = _evidence(usable_neighbors=4, support_count=0, disagree_count=0,
                        weighted_support=0.0, weighted_contradiction=0.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, CONTRADICTED)
        self.assertIsNotNone(r.evidence_strength)
        self.assertIn("none appeared", r.explanation)

    def test_neighbors_quiet_but_some_disagreement_present_uses_specific_explanation(self):
        ev = _evidence(usable_neighbors=4, support_count=0, disagree_count=2,
                        weighted_support=0.0, weighted_contradiction=0.05)  # nonzero count, weight below bar
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, CONTRADICTED)
        self.assertIn("opposing-direction reading", r.explanation)

    # Case B/D — clear support, no contradiction
    def test_clear_support_no_contradiction_is_supported(self):
        ev = _evidence(usable_neighbors=4, support_count=3, weighted_support=0.9, weighted_contradiction=0.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, SUPPORTED)
        self.assertEqual(r.evidence_strength, 0.9)

    # Case H — clear contradiction, no support
    def test_clear_contradiction_no_support_is_contradicted(self):
        ev = _evidence(usable_neighbors=4, disagree_count=3, weighted_support=0.0, weighted_contradiction=0.9)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, CONTRADICTED)
        self.assertEqual(r.evidence_strength, 0.9)

    # Case F — both clear the bar, comparable magnitude -> insufficient
    def test_mixed_comparable_evidence_is_insufficient(self):
        ev = _evidence(usable_neighbors=4, support_count=1, disagree_count=1,
                        weighted_support=0.4, weighted_contradiction=0.35)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertIsNone(r.evidence_strength)

    # Case F variant — both clear the bar, but support clearly (>=3x) dominates
    def test_mixed_but_support_clearly_dominates_is_supported(self):
        ev = _evidence(usable_neighbors=5, support_count=3, disagree_count=1,
                        weighted_support=0.6, weighted_contradiction=0.19)  # 0.6 >= 0.19*3=0.57
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, SUPPORTED)

    def test_mixed_but_contradiction_clearly_dominates_is_contradicted(self):
        ev = _evidence(usable_neighbors=5, support_count=1, disagree_count=3,
                        weighted_support=0.19, weighted_contradiction=0.6)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, CONTRADICTED)

    def test_zero_denominator_safe(self):
        # usable_neighbors=0 must not raise a ZeroDivisionError anywhere.
        ev = _evidence(usable_neighbors=0, support_count=0, disagree_count=0, support_ratio=0.0, disagree_ratio=0.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertTrue(math.isfinite(r.support_ratio))
        self.assertTrue(math.isfinite(r.contradiction_ratio))

    def test_s3_context_present_but_not_authoritative(self):
        ev = _evidence(usable_neighbors=4, support_count=3, weighted_support=0.9, weighted_contradiction=0.0)
        r = evaluate_channel_counterfactual("temperature_c", ev, min_neighbors_required=2, spatial_k_neighbors=8)
        d = r.to_dict()
        # s3_classification is None here since evaluate_channel_counterfactual doesn't set it directly
        # (evaluate_counterfactual_verification fills it in) -- confirms it's a separate, additive field.
        self.assertIn("s3_context", d)
        self.assertEqual(d["status"], SUPPORTED)  # status unaffected by s3_context being absent/present


class TestOverallAggregation(unittest.TestCase):
    def test_no_applicable_channels_overall_insufficient(self):
        result = evaluate_counterfactual_verification(
            {"temperature_c": _evidence(applicable=False)},
            min_neighbors_required=2, spatial_k_neighbors=8,
        )
        self.assertEqual(result["overall_status"], INSUFFICIENT_EVIDENCE)

    def test_all_supported_overall_supported(self):
        evidence = {
            "temperature_c": _evidence(usable_neighbors=4, support_count=3, weighted_support=0.9),
            "pressure_hpa": _evidence(usable_neighbors=4, support_count=3, weighted_support=0.8),
        }
        result = evaluate_counterfactual_verification(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result["overall_status"], SUPPORTED)

    def test_disagreeing_channels_overall_insufficient(self):
        evidence = {
            "temperature_c": _evidence(usable_neighbors=4, support_count=3, weighted_support=0.9),
            "pressure_hpa": _evidence(usable_neighbors=4, disagree_count=3, weighted_contradiction=0.9),
        }
        result = evaluate_counterfactual_verification(evidence, min_neighbors_required=2, spatial_k_neighbors=8)
        self.assertEqual(result["overall_status"], INSUFFICIENT_EVIDENCE)
        self.assertIn("disagree", result["summary"].lower())

    def test_s3_context_propagated_to_every_channel(self):
        evidence = {"temperature_c": _evidence(usable_neighbors=4, support_count=3, weighted_support=0.9)}
        result = evaluate_counterfactual_verification(
            evidence, min_neighbors_required=2, spatial_k_neighbors=8,
            s3_classification="REGIONAL_EVENT", s3_confidence=0.77,
        )
        ctx = result["channels"]["temperature"]["s3_context"]
        self.assertEqual(ctx["classification"], "REGIONAL_EVENT")
        self.assertEqual(ctx["confidence"], 0.77)


class TestLayer4Integration(unittest.TestCase):
    """End-to-end tests through the real SpatialNeighborLayer.evaluate(),
    using carefully constructed geometry (see module docstring)."""

    def setUp(self):
        self.layer = SpatialNeighborLayer(CONFIG.spatial)

    # Case A — isolated high-temperature anomaly, neighbors tightly quiet
    def test_case_a_isolated_high_anomaly_contradicted(self):
        target = _reading("TARGET", 20.0, 77.0, t=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, t=32.2), _reading("N2", 19.75, 77.35, t=32.3),
            _reading("N3", 20.4, 76.7, t=32.7), _reading("N4", 19.65, 76.8, t=32.8),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["status"], CONTRADICTED)

    # Case B — genuine regional high-temperature event
    def test_case_b_regional_event_supported(self):
        target = _reading("TARGET", 20.0, 77.0, t=44.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, t=42.0), _reading("N2", 19.9, 77.2, t=43.0), _reading("N3", 20.2, 76.9, t=41.5),
            _reading("N4", 20.5, 77.5, t=31.0), _reading("N5", 19.5, 76.5, t=32.0), _reading("N6", 20.6, 76.4, t=30.5),
            _reading("N7", 19.4, 77.6, t=31.5), _reading("N8", 20.7, 77.7, t=32.5),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["status"], SUPPORTED)
        self.assertGreater(cv["evidence_strength"], 0.5)

    # Case C — isolated low-temperature anomaly
    def test_case_c_isolated_low_anomaly_contradicted(self):
        target = _reading("TARGET", 20.0, 77.0, t=5.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, t=32.2), _reading("N2", 19.75, 77.35, t=32.3),
            _reading("N3", 20.4, 76.7, t=32.7), _reading("N4", 19.65, 76.8, t=32.8),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["status"], CONTRADICTED)

    # Case D — regional low-temperature event
    def test_case_d_regional_low_event_supported(self):
        target = _reading("TARGET", 20.0, 77.0, t=8.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, t=10.0), _reading("N2", 19.9, 77.2, t=9.0), _reading("N3", 20.2, 76.9, t=10.5),
            _reading("N4", 20.5, 77.5, t=31.0), _reading("N5", 19.5, 76.5, t=32.0), _reading("N6", 20.6, 76.4, t=30.5),
            _reading("N7", 19.4, 77.6, t=31.5), _reading("N8", 20.7, 77.7, t=32.5),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["status"], SUPPORTED)

    # Case E — insufficient neighbors (only 1, below min_neighbors_required)
    def test_case_e_insufficient_neighbors(self):
        target = _reading("TARGET", 20.0, 77.0, t=45.0)
        neighbors = [_reading("SOLO", 20.05, 77.05, t=25.0)]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        self.assertEqual(detail["status"], "INSUFFICIENT_NEIGHBORS")
        self.assertEqual(detail["counterfactual_verification"]["overall_status"], INSUFFICIENT_EVIDENCE)

    # Case H — opposite-direction neighborhood, with distance favoring the opposing group (also covers Case I)
    def test_case_h_and_i_opposite_direction_and_distance_weighting(self):
        target = _reading("TARGET", 20.0, 77.0, t=45.0)
        neighbors = [
            _reading("FAR1", 21.0, 78.0, t=32.0), _reading("FAR2", 21.2, 78.2, t=32.2), _reading("FAR3", 20.8, 78.5, t=32.5),
            _reading("CLOSE1", 20.05, 77.05, t=15.0), _reading("CLOSE2", 19.95, 76.95, t=14.5),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["status"], CONTRADICTED)
        self.assertGreater(cv["contradicting_neighbor_count"], 0)
        self.assertGreater(cv["evidence_strength"], 0.9)  # close opposing neighbors dominate the IDW weight

    # Case G — missing channel data must not be treated as contradiction
    def test_case_g_missing_channel_not_treated_as_contradiction(self):
        target = AWSReading(station_id="TARGET", lat=20.0, lon=77.0, temperature_c=45.0,
                             pressure_hpa=1013.0, humidity_pct=55.0)
        neighbors = [
            AWSReading(station_id="N1", lat=20.3, lon=77.2, temperature_c=32.2, pressure_hpa=1013.0, humidity_pct=None),
            AWSReading(station_id="N2", lat=19.75, lon=77.35, temperature_c=32.3, pressure_hpa=1013.0, humidity_pct=None),
            AWSReading(station_id="N3", lat=20.4, lon=76.7, temperature_c=32.7, pressure_hpa=1013.0, humidity_pct=None),
            AWSReading(station_id="N4", lat=19.65, lon=76.8, temperature_c=32.8, pressure_hpa=1013.0, humidity_pct=None),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        humidity_cv = detail["counterfactual_verification"]["channels"].get("humidity")
        # humidity is not applicable at all (target itself has no flagged deviation there without
        # neighbor comparison) -- confirm no CONTRADICTED verdict is fabricated from missing data.
        if humidity_cv is not None:
            self.assertNotEqual(humidity_cv["status"], CONTRADICTED)

    # Multiple channels
    def test_multiple_channels_reported_independently(self):
        target = AWSReading(station_id="TARGET", lat=20.0, lon=77.0,
                             temperature_c=42.0, pressure_hpa=1005.0, humidity_pct=30.0)
        neighbors = [
            AWSReading(station_id="N1", lat=20.1, lon=77.1, temperature_c=41.0, pressure_hpa=1005.5, humidity_pct=31.0),
            AWSReading(station_id="N2", lat=19.9, lon=77.2, temperature_c=40.5, pressure_hpa=1004.5, humidity_pct=29.0),
            AWSReading(station_id="N3", lat=20.2, lon=76.9, temperature_c=25.0, pressure_hpa=1013.0, humidity_pct=55.0),
            AWSReading(station_id="N4", lat=19.8, lon=76.8, temperature_c=26.0, pressure_hpa=1012.5, humidity_pct=54.0),
            AWSReading(station_id="N5", lat=20.3, lon=77.3, temperature_c=24.5, pressure_hpa=1013.5, humidity_pct=56.0),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        channels = detail["counterfactual_verification"]["channels"]
        self.assertIn("temperature", channels)
        self.assertIn("pressure", channels)
        self.assertIn("humidity", channels)

    # Determinism (Case J)
    def test_determinism_under_reversed_neighbor_order(self):
        target = _reading("TARGET", 20.0, 77.0, t=44.0)
        neighbors = [
            _reading("N1", 20.1, 77.1, t=42.0), _reading("N2", 19.9, 77.2, t=43.0), _reading("N3", 20.2, 76.9, t=41.5),
            _reading("N4", 20.5, 77.5, t=31.0), _reading("N5", 19.5, 76.5, t=32.0), _reading("N6", 20.6, 76.4, t=30.5),
            _reading("N7", 19.4, 77.6, t=31.5), _reading("N8", 20.7, 77.7, t=32.5),
        ]
        r1 = self.layer.evaluate(target, list(neighbors))
        r2 = self.layer.evaluate(target, list(reversed(neighbors)))
        self.assertEqual(r1[3]["counterfactual_verification"], r2[3]["counterfactual_verification"])

    # Backward compatibility
    def test_backward_compatible_output_unaffected_by_s6(self):
        target = _reading("TARGET", 20.0, 77.0, t=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, t=31.0), _reading("N2", 19.75, 77.35, t=32.0),
            _reading("N3", 20.4, 76.7, t=33.0), _reading("N4", 19.65, 76.8, t=34.0),
        ]
        score, consensus, reason, detail = self.layer.evaluate(target, neighbors)
        for field in ("total_neighbors_in_radius", "distance_range_km", "channel_results",
                      "status", "confidence_cap_reason", "regional_attribution"):
            self.assertIn(field, detail)
        t_res = detail["channel_results"]["temperature_c"]
        for field in ("target_value", "consensus_value", "deviation", "z_score",
                      "usable_neighbors", "method", "score", "flagged", "attribution_evidence"):
            self.assertIn(field, t_res)
        self.assertIn("counterfactual_verification", detail)  # new, additive
        self.assertIsInstance(score, float)
        self.assertIn("temperature_c", consensus)

    def test_invalid_coordinate_neighbor_excluded_upstream_no_crash(self):
        target = _reading("TARGET", 20.0, 77.0, t=45.0)
        neighbors = [
            _reading("N1", 20.3, 77.2, t=32.2), _reading("N2", 19.75, 77.35, t=32.3),
            _reading("BAD", 999.0, 77.0, t=32.5),  # invalid latitude -- excluded by S1, not S6's concern
            _reading("N4", 19.65, 76.8, t=32.8),
        ]
        _, _, _, detail = self.layer.evaluate(target, neighbors)
        self.assertIn("counterfactual_verification", detail)
        cv = detail["counterfactual_verification"]["channels"]["temperature"]
        self.assertEqual(cv["valid_neighbor_count"], 3)  # BAD excluded upstream


if __name__ == "__main__":
    unittest.main()
