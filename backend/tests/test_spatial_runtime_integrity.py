"""
Spatial Intelligence — runtime integrity (Phase 2 of backend validation).

Verifies that the Spatial layer only treats neighbors as evidence when they are
SIMULTANEOUS (observation time within tolerance), SAME-SOURCE, and correctly
handled for elevation, and that the resulting evidence really travels through
the PRODUCTION detector into fusion's inputs and the canonical response.

All readings are SYNTHETIC controlled inputs for engineering verification.
These tests prove the plumbing and the decision rules behave as designed; they
do NOT prove real-world detection accuracy or AWS validation.
"""
import math
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from schema import AWSReading, station_dict_to_reading
from engine.layer4_spatial import SpatialNeighborLayer
from engine.spatial_neighbors import select_k_nearest_neighbors, observation_time
from app.anomaly.detector import AnomalyDetector

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
TOL = CONFIG.spatial.neighbor_time_tolerance_minutes  # 30
AWS = "AWS_IN_SITU"
NWP = "NWP_MODEL_REFERENCE"
_UNSET = object()


def R(sid, dlat, t=30.0, obs=_UNSET, src=AWS, elev=None, p=1010.0, h=50.0, dlon=0.0):
    """Reading ~2 km per 0.02 deg-lat step north of (17N, 78E)."""
    return AWSReading(
        station_id=sid, lat=17.0 + dlat, lon=78.0 + dlon,
        temperature_c=t, pressure_hpa=p, humidity_pct=h,
        observation_timestamp=T0 if obs is _UNSET else obs,
        source=src, elevation_m=elev,
    )


def ring(temps, **kw):
    return [R(f"N{i}", 0.02 * (i + 1), t, **kw) for i, t in enumerate(temps)]


def evaluate(target, neighbors):
    return SpatialNeighborLayer().evaluate(target, neighbors)


def ra(detail):
    return detail["regional_attribution"]["classification"]


def cf(detail):
    return detail["counterfactual_verification"]["overall_status"]


# ─────────────────────────────────────────────────────────────────────────
class TestScenarioA_IsolatedSensorFault(unittest.TestCase):
    def test_strong_disagreement_isolated_and_contradicted_with_visible_evidence(self):
        score, consensus, reason, d = evaluate(R("T", 0, 55.0), ring([30, 31, 32, 31, 30, 32]))
        self.assertEqual(d["status"], "EVALUATED")
        self.assertGreaterEqual(score, 0.90)
        self.assertEqual(ra(d), "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(cf(d), "CONTRADICTED")
        # neighbor evidence is visible, not just a verdict
        t = d["channel_results"]["temperature_c"]
        self.assertEqual(t["usable_neighbors"], 6)
        self.assertEqual(t["target_value"], 55.0)
        self.assertAlmostEqual(t["consensus_value"], 31.0, delta=1.0)
        self.assertGreater(t["robust_z"], CONFIG.spatial.spatial_z_threshold)
        self.assertEqual(d["neighbor_selection"]["eligible_within_radius"], 6)
        self.assertIn("disagrees", reason)


class TestScenarioB_RegionalAgreement(unittest.TestCase):
    def test_b1_all_neighbors_agree_is_spatial_agreement_not_a_fault_and_not_contradicted(self):
        """Target 42 with EVERY neighbor 41-43. By the layer's documented design
        (spatial_attribution.py docstring) a single snapshot has no baseline to
        call a fully-agreeing region an 'event': the target is simply consistent
        with its neighbors -> score 0, nothing to attribute, counterfactual has
        nothing to verify (INSUFFICIENT_EVIDENCE) - and crucially NOT
        ISOLATED / NOT CONTRADICTED."""
        score, _, _, d = evaluate(R("T", 0, 42.0), ring([41, 42, 43, 42, 41, 43]))
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(score, 0.0)
        self.assertNotEqual(ra(d), "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(ra(d), "UNCERTAIN")
        self.assertEqual(d["regional_attribution"]["applicable_channels"], [])
        self.assertNotEqual(cf(d), "CONTRADICTED")
        self.assertEqual(d["channel_results"]["temperature_c"]["usable_neighbors"], 6)

    def test_b2_regional_cluster_topology_is_regional_event_and_supported(self):
        """The topology REGIONAL_EVENT is designed for: the target's deviation
        from the wider baseline is shared by a coherent cluster of nearby stations."""
        near_cluster = [R("C0", 0.02, 41.0), R("C1", 0.04, 42.0), R("C2", 0.06, 43.0)]
        wider = [R(f"W{i}", 0.30 + 0.05 * i, t) for i, t in enumerate([30, 30, 31, 30, 31])]
        score, _, _, d = evaluate(R("T", 0, 42.0), near_cluster + wider)
        self.assertEqual(ra(d), "REGIONAL_EVENT")
        self.assertEqual(cf(d), "SUPPORTED")
        self.assertGreater(d["regional_attribution"]["confidence"], 0.5)


class TestScenarioC_InsufficientEvidence(unittest.TestCase):
    def assert_uncertain_no_invented_confidence(self, d, score):
        self.assertEqual(score, 0.0)
        self.assertEqual(d["status"], "INSUFFICIENT_NEIGHBORS")
        self.assertEqual(ra(d), "UNCERTAIN")
        self.assertEqual(d["regional_attribution"]["confidence"], 0.0)
        self.assertEqual(cf(d), "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(d["counterfactual_verification"].get("evidence_strength"))

    def test_no_neighbors(self):
        score, _, _, d = evaluate(R("T", 0, 55.0), [])
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertEqual(d["total_neighbors_in_radius"], 0)

    def test_only_one_neighbor(self):
        score, _, _, d = evaluate(R("T", 0, 55.0), ring([31]))
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertEqual(d["total_neighbors_in_radius"], 1)

    def test_neighbors_too_old_are_not_used_and_the_reason_is_reported(self):
        stale = ring([30, 31, 32, 31, 30, 32], obs=T0 - timedelta(hours=5))
        score, _, _, d = evaluate(R("T", 0, 55.0), stale)
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertEqual(d["neighbor_selection"]["excluded"]["time_misaligned"], 6)
        self.assertEqual(d["neighbor_selection"]["geo_within_radius"], 6)
        self.assertIn("observed more than", d["note"])

    def test_incompatible_source_neighbors_are_not_used(self):
        nwp = ring([30, 31, 32, 31, 30, 32], src=NWP)
        score, _, _, d = evaluate(R("T", 0, 55.0, src=AWS), nwp)
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertEqual(d["neighbor_selection"]["excluded"]["source_mismatch"], 6)
        self.assertIn("different data source", d["note"])

    def test_neighbors_without_observation_time_are_not_used(self):
        undated = ring([30, 31, 32, 31, 30, 32], obs=None)
        score, _, _, d = evaluate(R("T", 0, 55.0), undated)
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertEqual(d["neighbor_selection"]["excluded"]["time_unverified"], 6)

    def test_target_without_observation_time_cannot_use_any_neighbor(self):
        score, _, _, d = evaluate(R("T", 0, 55.0, obs=None), ring([30, 31, 32, 31, 30, 32]))
        self.assert_uncertain_no_invented_confidence(d, score)
        self.assertFalse(d["neighbor_selection"]["target_observation_time_known"])

    def test_mixed_eligibility_only_eligible_neighbors_count(self):
        ns = ring([30, 31, 32], obs=T0) + [
            R("OLD", 0.10, 60.0, obs=T0 - timedelta(hours=3)),
            R("NWP", 0.12, 60.0, src=NWP),
            R("UND", 0.14, 60.0, obs=None),
        ]
        score, _, _, d = evaluate(R("T", 0, 31.0), ns)
        self.assertEqual(d["neighbor_selection"]["eligible_within_radius"], 3)
        self.assertEqual(d["channel_results"]["temperature_c"]["usable_neighbors"], 3)
        self.assertEqual(score, 0.0)   # the three 60 C impostors were never consulted


# ─────────────────────────────────────────────────────────────────────────
class TestNeighborSelectionRules(unittest.TestCase):
    def sel(self, target, cands, **kw):
        kw.setdefault("radius_km", CONFIG.spatial.neighbor_distance_km_max)
        kw.setdefault("k", CONFIG.spatial.spatial_k_neighbors)
        kw.setdefault("max_time_diff_minutes", TOL)
        kw.setdefault("require_same_source", True)
        return select_k_nearest_neighbors(target, cands, **kw)

    def test_target_is_excluded_from_its_own_neighbors(self):
        target = R("T", 0)
        r = self.sel(target, [target] + ring([30, 31, 32]))
        self.assertEqual(r.excluded_self, 1)
        self.assertNotIn("T", [n.station_id for n in r.neighbors])

    def test_maximum_radius(self):
        near, far = R("NEAR", 2.16), R("FAR", 2.34)   # ~240 km and ~260 km north
        r = self.sel(R("T", 0), [near, far])
        self.assertEqual([n.station_id for n in r.neighbors], ["NEAR"])
        self.assertEqual(r.excluded_out_of_radius, 1)

    def test_maximum_k_caps_selection_but_reports_true_pool_size(self):
        cands = [R(f"N{i:02d}", 0.01 * (i + 1)) for i in range(12)]
        r = self.sel(R("T", 0), cands)
        self.assertEqual(len(r.neighbors), CONFIG.spatial.spatial_k_neighbors)
        self.assertEqual(r.within_radius_count, 12)
        self.assertEqual([n.station_id for n in r.neighbors], [f"N{i:02d}" for i in range(8)])  # nearest first

    def test_timestamp_tolerance_boundary_is_inclusive_and_symmetric(self):
        edge = int(TOL * 60)
        cands = [
            R("IN_PAST", 0.02, obs=T0 - timedelta(seconds=edge)),
            R("IN_FUTURE", 0.04, obs=T0 + timedelta(seconds=edge)),
            R("OUT_PAST", 0.06, obs=T0 - timedelta(seconds=edge + 1)),
            R("OUT_FUTURE", 0.08, obs=T0 + timedelta(seconds=edge + 1)),
        ]
        r = self.sel(R("T", 0), cands)
        self.assertEqual({n.station_id for n in r.neighbors}, {"IN_PAST", "IN_FUTURE"})
        self.assertEqual(r.excluded_time_misaligned, 2)

    def test_filters_are_opt_in_and_pure_s1_behavior_is_unchanged(self):
        cands = [R("OLD", 0.02, obs=T0 - timedelta(days=9)), R("NWP", 0.04, src=NWP), R("UND", 0.06, obs=None)]
        r = select_k_nearest_neighbors(R("T", 0), cands, radius_km=250.0, k=8)
        self.assertEqual(len(r.neighbors), 3)

    def test_naive_observation_time_is_treated_as_utc(self):
        naive = T0.replace(tzinfo=None)
        r = self.sel(R("T", 0), [R("N", 0.02, obs=naive)])
        self.assertEqual(len(r.neighbors), 1)
        self.assertEqual(observation_time(R("N", 0.02, obs=naive)), T0)

    def test_duplicate_station_entries_collapse_to_the_latest_observation(self):
        older = R("DUP", 0.02, t=30.0, obs=T0 - timedelta(minutes=20))
        newer = R("DUP", 0.02, t=55.0, obs=T0 - timedelta(minutes=2))
        r = self.sel(R("T", 0), [older, newer, R("OTHER", 0.04)])
        self.assertEqual(len(r.neighbors), 2)
        self.assertEqual(r.excluded_duplicate_station, 1)
        dup = next(n for n in r.neighbors if n.station_id == "DUP")
        self.assertEqual(dup.temperature_c, 55.0)   # latest observation kept, counted once

    def test_a_duplicated_station_cannot_be_counted_as_multiple_neighbors_in_the_layer(self):
        ns = [R("SAME", 0.02, t=31.0)] * 5
        _, _, _, d = evaluate(R("T", 0, 55.0), ns)
        self.assertEqual(d["status"], "INSUFFICIENT_NEIGHBORS")   # 1 distinct station, not 5

    def test_input_order_does_not_change_the_result(self):
        cands = ring([30, 31, 32, 31, 30, 32])
        a = evaluate(R("T", 0, 55.0), cands)
        b = evaluate(R("T", 0, 55.0), list(reversed(cands)))
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[3]["channel_results"]["temperature_c"]["consensus_value"],
                         b[3]["channel_results"]["temperature_c"]["consensus_value"])


class TestPoolOrdering(unittest.TestCase):
    def test_out_of_order_older_observation_never_overwrites_a_newer_one(self):
        d = AnomalyDetector()
        newer, older, newest = R("S", 0.02, 31.0, obs=T0), R("S", 0.02, 99.0, obs=T0 - timedelta(hours=1)), R("S", 0.02, 32.0, obs=T0 + timedelta(minutes=10))
        d.update_spatial_pool([newer])
        d.update_spatial_pool([older])
        self.assertEqual(d._spatial_pool["S"].temperature_c, 31.0)     # older ignored
        d.update_spatial_pool([newest])
        self.assertEqual(d._spatial_pool["S"].temperature_c, 32.0)     # newer replaces

    def test_readings_with_unknown_time_cannot_be_ordered_and_replace_as_before(self):
        d = AnomalyDetector()
        d.update_spatial_pool([R("S", 0.02, 31.0, obs=T0)])
        d.update_spatial_pool([R("S", 0.02, 40.0, obs=None)])
        self.assertEqual(d._spatial_pool["S"].temperature_c, 40.0)


# ─────────────────────────────────────────────────────────────────────────
class TestSpatialMathEdgeCases(unittest.TestCase):
    def test_zero_mad_uses_the_documented_floor_and_stays_finite(self):
        same = ring([31.0] * 6)                      # identical neighbors -> MAD == 0
        score, _, _, d = evaluate(R("T", 0, 40.0), same)
        t = d["channel_results"]["temperature_c"]
        self.assertEqual(t["regional_mad"], 0.0)
        self.assertTrue(math.isfinite(t["robust_z"]))
        self.assertGreater(t["robust_z"], CONFIG.spatial.spatial_z_threshold)
        self.assertGreater(score, 0.5)
        self.assertEqual(ra(d), "ISOLATED_SENSOR_ANOMALY")

    def test_missing_neighbor_values_reduce_usable_neighbors_not_eligibility(self):
        ns = ring([30, 31, 32, 31, 30, 32])
        ns[0] = R("N0", 0.02, t=None)
        ns[1] = R("N1", 0.04, t=None)
        _, _, _, d = evaluate(R("T", 0, 55.0), ns)
        self.assertEqual(d["neighbor_selection"]["eligible_within_radius"], 6)       # all eligible
        self.assertEqual(d["channel_results"]["temperature_c"]["usable_neighbors"], 4)  # 2 lack temperature
        self.assertEqual(d["channel_results"]["pressure_hpa"]["usable_neighbors"], 6)   # other channels intact

    def test_channel_with_too_few_valid_neighbor_values_reports_insufficient_not_a_score(self):
        ns = [R(f"N{i}", 0.02 * (i + 1), t=None) for i in range(5)] + [R("N5", 0.12, t=31.0)]
        score, _, _, d = evaluate(R("T", 0, 55.0), ns)
        self.assertEqual(d["channel_results"]["temperature_c"]["status"], "INSUFFICIENT_VALID_NEIGHBORS")
        self.assertEqual(score, 0.0)


class TestElevationHandling(unittest.TestCase):
    def test_unknown_elevation_is_never_invented_in_the_data_quality_gate(self):
        base = {"id": "E1", "latitude": 17.0, "longitude": 78.0, "temperature": 30.0, "pressure": 1010.0, "humidity": 50}
        self.assertIsNone(station_dict_to_reading(base).elevation_m)
        self.assertEqual(station_dict_to_reading({**base, "elevation": 0}).elevation_m, 0.0)    # genuine 0 m kept
        self.assertEqual(station_dict_to_reading({**base, "elevation": 250}).elevation_m, 250.0)
        self.assertEqual(station_dict_to_reading({**base, "elevation_m": 640}).elevation_m, 640.0)

    def test_known_target_vs_unknown_neighbor_elevation_gets_no_phantom_lapse_correction(self):
        """Before: unknown neighbors were read as 0 m, so a 900 m target vs ~31 C
        neighbors was 'corrected' by -5.85 C and scored 1.0 against them."""
        score, _, _, d = evaluate(R("T", 0, 31.0, elev=900.0), ring([30, 31, 32, 31, 30, 32], elev=None))
        self.assertEqual(score, 0.0)
        self.assertEqual(d["elevation_adjustment"]["status"], "NOT_APPLIED_UNKNOWN_ELEVATION")
        self.assertTrue(d["elevation_adjustment"]["target_elevation_known"])
        self.assertEqual(d["elevation_adjustment"]["neighbors_with_known_elevation"], 0)

    def test_both_elevations_known_applies_the_lapse_rate(self):
        # 900 m target at 25.2 C / 902 hPa vs sea-level neighbors at ~31 C / 1010 hPa:
        # temperature 31 - 0.0065*900 = 25.15 and pressure 1010 - 0.12*900 = 902 -> agreement
        score, _, _, d = evaluate(R("T", 0, 25.2, elev=900.0, p=902.0), ring([30, 31, 32, 31, 30, 32], elev=0.0))
        self.assertEqual(score, 0.0)
        self.assertEqual(d["elevation_adjustment"]["status"], "APPLIED")

    def test_same_readings_without_elevation_are_a_real_disagreement(self):
        score, _, _, d = evaluate(R("T", 0, 25.2), ring([30, 31, 32, 31, 30, 32]))
        self.assertGreater(score, 0.5)
        self.assertEqual(d["elevation_adjustment"]["status"], "NOT_APPLIED_UNKNOWN_ELEVATION")

    def test_partial_neighbor_elevation_is_reported_as_partial(self):
        ns = ring([30, 31, 32, 31], elev=0.0) + ring([30, 31], elev=None)[:0]
        ns += [R("U1", 0.20, 31.0, elev=None), R("U2", 0.22, 31.0, elev=None)]
        _, _, _, d = evaluate(R("T", 0, 31.0, elev=10.0), ns)
        self.assertEqual(d["elevation_adjustment"]["status"], "PARTIAL")


# ─────────────────────────────────────────────────────────────────────────
class TestProductionPathObservationToFusion(unittest.TestCase):
    """The real AnomalyDetector (pool -> selection -> Spatial -> fusion ->
    diagnosis -> canonical response), not helper functions."""

    def det_with_pool(self, temps, **kw):
        det = AnomalyDetector()
        det.update_spatial_pool(ring(temps, **kw))
        calls = []
        original = det.fusion.fuse

        def spy(**kwargs):
            calls.append(kwargs)
            return original(**kwargs)

        det.fusion.fuse = spy
        return det, calls

    def test_isolated_fault_flows_observation_to_spatial_to_fusion_to_response(self):
        det, calls = self.det_with_pool([30, 31, 32, 31, 30, 32])
        # 42 C (not 55 C): 55 C exceeds the Physics hard bound and short-circuits
        # fusion with a veto (covered separately below); 42 C keeps fusion on its
        # normal weighted/acute-trigger path so Spatial's contribution is visible.
        alert = det.evaluate_reading(R("TARGET", 0, 42.0))          # neighbors come from the detector's OWN pool

        # 1. Spatial layer produced neighbor evidence + score
        d = alert.layer_details["spatial"]
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(d["neighbor_selection"]["eligible_within_radius"], 6)
        self.assertGreaterEqual(alert.layer_scores["spatial"], 0.90)
        # 2. attribution + counterfactual computed from that evidence
        self.assertEqual(ra(d), "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(cf(d), "CONTRADICTED")
        # 3. the same score / neighbor count / coverage are what fusion RECEIVED
        fused = calls[-1]
        self.assertEqual(fused["layer_scores"]["spatial"], alert.layer_scores["spatial"])
        self.assertEqual(fused["spatial_neighbor_count"], 6)
        self.assertEqual(fused["layer_coverage"]["spatial"], 1.0)
        self.assertTrue(alert.layer_details["fusion"]["acute_triggers"]["spatial"])
        # 4. present in the final detector response
        self.assertEqual(alert.spatial_neighbor_count, 6)
        card = alert.canonical_result["layers"]["spatial"]
        self.assertEqual(card["regional_attribution"]["classification"], "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(card["counterfactual_verification"]["overall_status"], "CONTRADICTED")
        self.assertEqual(alert.canonical_result["data_quality"]["nearby_stations"], 6)
        corr = alert.canonical_result["diagnosis"]["spatial_corroboration"]
        self.assertIsNotNone(corr)
        self.assertEqual(corr["state"], "CORROBORATED")
        # Spatial is EVIDENCE, not the decision: the diagnosis still comes from the classifier
        self.assertTrue(alert.is_anomaly)

    def test_physics_veto_does_not_erase_or_replace_the_spatial_evidence(self):
        """Scenario A literally (55 C) exceeds the Physics bound (50 C): fusion
        short-circuits on the veto. Spatial must still REPORT its own evidence
        for the response - it is one evidence source, not overridden or hidden."""
        det, calls = self.det_with_pool([30, 31, 32, 31, 30, 32])
        alert = det.evaluate_reading(R("TARGET", 0, 55.0))
        self.assertTrue(alert.veto_fired)
        self.assertEqual(alert.layer_details["fusion"]["triggered_by"], "physics_veto")
        d = alert.layer_details["spatial"]
        self.assertEqual(ra(d), "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(cf(d), "CONTRADICTED")
        self.assertGreaterEqual(alert.layer_scores["spatial"], 0.90)
        self.assertEqual(calls[-1]["spatial_neighbor_count"], 6)

    def test_stale_pool_neighbors_are_not_used_by_the_production_path(self):
        det, calls = self.det_with_pool([30, 31, 32, 31, 30, 32], obs=T0 - timedelta(hours=5))
        alert = det.evaluate_reading(R("TARGET", 0, 55.0))
        d = alert.layer_details["spatial"]
        self.assertEqual(d["status"], "INSUFFICIENT_NEIGHBORS")
        self.assertEqual(alert.layer_scores["spatial"], 0.0)
        self.assertEqual(d["neighbor_selection"]["excluded"]["time_misaligned"], 6)
        self.assertEqual(calls[-1]["spatial_neighbor_count"], 0)
        card = alert.canonical_result["layers"]["spatial"]
        self.assertEqual(card["status"], "INSUFFICIENT_DATA")
        self.assertIn("observed more than", card["reason"])         # says WHY, not a bare 'insufficient'
        self.assertEqual(card["regional_attribution"]["classification"], "UNCERTAIN")
        self.assertEqual(card["counterfactual_verification"]["overall_status"], "INSUFFICIENT_EVIDENCE")

    def test_cross_source_pool_neighbors_are_not_used_by_the_production_path(self):
        det, _ = self.det_with_pool([30, 31, 32, 31, 30, 32], src=NWP)
        alert = det.evaluate_reading(R("TARGET", 0, 55.0, src=AWS))
        self.assertEqual(alert.layer_scores["spatial"], 0.0)
        self.assertEqual(alert.layer_details["spatial"]["neighbor_selection"]["excluded"]["source_mismatch"], 6)

    def test_same_source_same_time_pool_still_works_for_nwp_targets(self):
        det, _ = self.det_with_pool([30, 31, 32, 31, 30, 32], src=NWP)
        alert = det.evaluate_reading(R("TARGET", 0, 55.0, src=NWP))
        self.assertEqual(alert.layer_details["spatial"]["status"], "EVALUATED")   # like-with-like is allowed

    def test_true_pool_size_is_reported_even_when_more_than_k_neighbors_exist(self):
        det = AnomalyDetector()
        det.update_spatial_pool([R(f"N{i:02d}", 0.01 * (i + 1), 31.0) for i in range(12)])
        alert = det.evaluate_reading(R("TARGET", 0, 31.0))
        self.assertEqual(alert.layer_details["spatial"]["total_neighbors_in_radius"], 12)
        self.assertEqual(alert.spatial_neighbor_count, 12)
        self.assertEqual(alert.layer_details["spatial"]["channel_results"]["temperature_c"]["usable_neighbors"], 8)

    def test_get_neighbors_for_reading_public_api_applies_the_same_rules(self):
        det, _ = self.det_with_pool([30, 31, 32])
        det.update_spatial_pool([R("OLD", 0.09, 60.0, obs=T0 - timedelta(hours=4)), R("NWPN", 0.10, 60.0, src=NWP)])
        got = [n.station_id for n in det.get_neighbors_for_reading(R("TARGET", 0, 31.0))]
        self.assertEqual(sorted(got), ["N0", "N1", "N2"])


class TestStartupEvaluationOrder(unittest.TestCase):
    """The WeatherUnion batch must be fully pooled BEFORE any of its stations is
    evaluated, so a station is never judged 'no regional context' merely
    because a later CSV row hasn't been processed yet."""

    def test_weatherunion_batch_is_pooled_before_any_station_is_evaluated(self):
        import app.anomaly.detector as detector_module
        import app.incidents as incidents_pkg

        fresh = AnomalyDetector()
        seen = {}                                     # station id -> spatial neighbors seen at its evaluation
        real_eval = fresh.evaluate_reading

        def recording_eval(reading, neighbors=None, station_data=None):
            alert = real_eval(reading, neighbors=neighbors, station_data=station_data)
            seen[reading.station_id] = alert.layer_details["spatial"]["total_neighbors_in_radius"]
            return alert

        fresh.evaluate_reading = recording_eval

        def fake_batch(coords, chunk_size=50):        # deterministic stub: no network, no cache file
            return [{"temperature": 30.0, "pressure": 1010.0, "humidity": 55, "windSpeed": 5.0,
                     "windDirection": "N", "condition": "Fair", "timestamp": "2026-06-01T12:00"} for _ in coords]

        fake_meteo = types.ModuleType("app.weather.open_meteo")
        fake_meteo.open_meteo_service = types.SimpleNamespace(
            get_batch_weather=fake_batch, get_current_weather=lambda la, lo: None)
        fake_incidents = types.SimpleNamespace(upsert_from_evaluation=lambda snap: None)

        with mock.patch.dict(sys.modules, {"app.weather.open_meteo": fake_meteo}), \
             mock.patch.object(detector_module, "detector", fresh), \
             mock.patch.object(incidents_pkg, "service", fake_incidents, create=True), \
             mock.patch.dict(sys.modules, {"app.incidents.service": fake_incidents}):
            sys.modules.pop("app.stations.service", None)
            import app.stations.service as svc

            wu = [s for s in svc.station_service._stations.values() if s.get("dataSource") == NWP]
            self.assertGreater(len(wu), 100)
            in_city = [s for s in wu if "Bengaluru" in s.get("town", "") and s["id"] in seen]
            self.assertGreater(len(in_city), 5)
            # Old behavior: each station was evaluated as soon as it was built, so
            # the FIRST Bengaluru row saw 0 same-source neighbors and later rows
            # saw progressively more. Pool-first means the FIRST row already sees
            # the whole batch, and the count no longer depends on CSV row order.
            first_row_count = seen[in_city[0]["id"]]
            last_row_count = seen[in_city[-1]["id"]]
            self.assertGreaterEqual(first_row_count, len(in_city) - 1)
            self.assertGreaterEqual(min(seen[s["id"]] for s in in_city), len(in_city) - 1)
            self.assertGreaterEqual(first_row_count, last_row_count - (max(seen[s["id"]] for s in in_city) - last_row_count))
            sys.modules.pop("app.stations.service", None)


if __name__ == "__main__":
    unittest.main()
