"""
S7 -- Production integration tests for Spatial Intelligence (S1-S6) through
the REAL AnomalyDetector pipeline (Physics/Temporal/Multivariate/Spatial/
Drift -> Fusion -> Root Cause -> Estimated value -> canonical API object).

Covers: end-to-end scenarios A-F, graceful degradation, regression tests for
the key-name integration bugs fixed in S7, the additive root-cause
corroboration (which must never change category/confidence), and the
no-double-counting guarantee.
"""
import os
import sys
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.anomaly.detector import AnomalyDetector
from root_cause.classifier import RootCauseClassifier
from datetime import datetime as _dt, timezone as _tz
from schema import AWSReading as _AWSReading, FaultType

# Phase 2 spatial contract: a neighbor is only usable evidence when it was
# OBSERVED within CONFIG.spatial.neighbor_time_tolerance_minutes of the target
# (same source, known observation time). These fixtures model stations that
# were observed simultaneously - the assumption the tests always made
# implicitly, now stated explicitly.
_FIXTURE_OBS_TIME = _dt(2026, 1, 1, 12, 0, tzinfo=_tz.utc)


def AWSReading(**kw):  # noqa: N802 - deliberately shadows the schema class name
    kw.setdefault("observation_timestamp", _FIXTURE_OBS_TIME)
    return _AWSReading(**kw)


def rd(sid, lat, lon, t=30.0, p=1013.0, h=30.0):
    # 30% RH keeps hot targets below the wet-bulb physics veto so the
    # scenarios isolate SPATIAL evidence.
    return AWSReading(station_id=sid, lat=lat, lon=lon, temperature_c=t, pressure_hpa=p, humidity_pct=h)


def quiet_neighbors():
    return [rd(f"N{i}", 20 + 0.1 * i, 77 + 0.1 * i, t=32.1 + 0.1 * i) for i in range(1, 5)]


def regional_neighbors():
    return [
        rd("R1", 20.1, 77.1, t=42.0), rd("R2", 19.9, 77.2, t=43.0), rd("R3", 20.2, 76.9, t=41.5),
        rd("B1", 20.5, 77.5, t=31.0), rd("B2", 19.5, 76.5, t=32.0), rd("B3", 20.6, 76.4, t=30.5),
        rd("B4", 19.4, 77.6, t=31.5), rd("B5", 20.7, 77.7, t=32.5),
    ]


def spatial_card(alert):
    return alert.canonical_result["layers"]["spatial"]


class TestEndToEndScenarios(unittest.TestCase):
    # TEST A
    def test_a_normal_station(self):
        a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=32.3), neighbors=quiet_neighbors())
        self.assertEqual(a.status, "NORMAL")
        self.assertEqual(a.root_cause, FaultType.NORMAL)
        self.assertEqual(a.corrected_values["temperature_c"], a.raw_values["temperature_c"])  # no fabricated value
        self.assertIsNone(a.canonical_result["diagnosis"]["spatial_corroboration"])
        self.assertEqual(spatial_card(a)["status"], "PASS")

    # TEST B
    def test_b_isolated_sensor_anomaly(self):
        a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=quiet_neighbors())
        card = spatial_card(a)
        self.assertEqual(card["regional_attribution"]["classification"], "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(card["counterfactual_verification"]["overall_status"], "CONTRADICTED")
        self.assertTrue(a.is_anomaly)
        self.assertIn(a.root_cause, (FaultType.SINGLE_CHANNEL_FAULT, FaultType.SENSOR_SPIKE))
        corr = a.canonical_result["diagnosis"]["spatial_corroboration"]
        self.assertEqual(corr["state"], "CORROBORATED")

    # TEST C
    def test_c_regional_event_not_treated_as_sensor_fault(self):
        a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=44.0), neighbors=regional_neighbors())
        card = spatial_card(a)
        self.assertEqual(card["regional_attribution"]["classification"], "REGIONAL_EVENT")
        self.assertEqual(card["counterfactual_verification"]["overall_status"], "SUPPORTED")
        self.assertNotIn(a.root_cause, (FaultType.SINGLE_CHANNEL_FAULT, FaultType.SENSOR_SPIKE))
        self.assertEqual(a.corrected_values["temperature_c"], 44.0)  # genuine reading not replaced

    # TEST D
    def test_d_insufficient_neighborhood_no_fabricated_contradiction(self):
        for nbrs in ([], quiet_neighbors()[:1]):
            a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=nbrs)
            card = spatial_card(a)
            self.assertEqual(card["status"], "INSUFFICIENT_DATA")
            self.assertEqual(card["counterfactual_verification"]["overall_status"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(card["regional_attribution"]["classification"], "UNCERTAIN")
            # no neighbor consensus exists -> no estimated replacement is fabricated
            self.assertEqual(a.corrected_values["temperature_c"], a.raw_values["temperature_c"])

    # TEST F
    def test_f_raw_observation_preserved(self):
        reading = rd("T", 20, 77, t=45.0)
        snapshot = reading.model_dump()
        a = AnomalyDetector().evaluate_reading(reading, neighbors=quiet_neighbors())
        self.assertEqual(reading.model_dump(), snapshot)            # input object untouched
        self.assertEqual(a.raw_values["temperature_c"], 45.0)       # raw preserved in output
        self.assertNotEqual(a.corrected_values["temperature_c"], a.raw_values["temperature_c"])
        self.assertLess(abs(a.corrected_values["temperature_c"] - 32.25), 1.0)


class TestGracefulDegradation(unittest.TestCase):
    LAYERS = (("layer1", "physics"), ("layer2", "temporal"), ("layer3", "multivariate"),
              ("layer4", "spatial"), ("layer5", "sensor_health"))

    # TEST E
    def test_e_any_single_layer_failure_does_not_crash(self):
        for attr, card in self.LAYERS:
            det = AnomalyDetector()
            with mock.patch.object(getattr(det, attr), "evaluate", side_effect=RuntimeError("boom")):
                a = det.evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=quiet_neighbors())
            layers = a.canonical_result["layers"]
            self.assertEqual(layers[card]["status"], "UNAVAILABLE", attr)
            others = [c for _, c in self.LAYERS if c != card]
            self.assertTrue(all(layers[c]["status"] != "UNAVAILABLE" for c in others), attr)
            self.assertEqual(set(a.layer_scores), {"physics", "temporal", "multivariate", "spatial", "drift"})

    def test_spatial_failure_exposes_missing_evidence_not_fault(self):
        det = AnomalyDetector()
        with mock.patch.object(det.layer4, "evaluate", side_effect=ValueError("x")):
            a = det.evaluate_reading(rd("T", 20, 77, t=32.3), neighbors=quiet_neighbors())
        card = spatial_card(a)
        self.assertEqual(card["status"], "UNAVAILABLE")
        self.assertIsNone(card["regional_attribution"])
        self.assertIsNone(card["counterfactual_verification"])
        self.assertEqual(a.layer_scores["spatial"], 0.0)
        self.assertFalse(a.is_anomaly)

    def test_malformed_coordinates_and_missing_channels(self):
        for lat in (float("nan"), 999.0):
            a = AnomalyDetector().evaluate_reading(rd("T", lat, 77, t=32.3), neighbors=quiet_neighbors())
            self.assertEqual(spatial_card(a)["status"], "INSUFFICIENT_DATA")
        a = AnomalyDetector().evaluate_reading(AWSReading(station_id="T", lat=20, lon=77), neighbors=quiet_neighbors())
        self.assertIn("layers", a.canonical_result)

    def test_lstm_unavailable_falls_back(self):
        from config import CONFIG, LSTMTemporalConfig
        from engine.layer2_temporal import TemporalPatternLayer
        det = AnomalyDetector()
        det.layer2 = TemporalPatternLayer(CONFIG.temporal, lstm_config=LSTMTemporalConfig(enabled=False))
        a = det.evaluate_reading(rd("T", 20, 77, t=32.3), neighbors=quiet_neighbors())
        self.assertEqual(a.status, "NORMAL")


class TestIntegrationBugFixes(unittest.TestCase):
    """Regression tests for the key-name bug (detector consumers read
    "neighbor_count"/"min_distance_km"/"deviations", which layer4_spatial.py
    never sets)."""

    def setUp(self):
        self.a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=quiet_neighbors())

    def test_neighbor_count_reaches_fusion_and_output(self):
        self.assertEqual(self.a.spatial_neighbor_count, 4)
        self.assertEqual(self.a.canonical_result["data_quality"]["nearby_stations"], 4)
        self.assertIsNotNone(self.a.spatial_neighbor_range_km)
        self.assertGreater(self.a.spatial_neighbor_range_km, 0)

    def test_canonical_spatial_card_reflects_real_evaluation(self):
        self.assertEqual(spatial_card(self.a)["status"], "ANOMALY")
        self.assertNotIn("Insufficient neighboring", spatial_card(self.a)["reason"])

    def test_weather_analysis_and_insights_use_real_spatial_evidence(self):
        wa = " ".join(self.a.canonical_result["weather_analysis"]["evidence"])
        self.assertIn("Regional temperature comparison", wa)
        whats = [i["what"] for i in self.a.canonical_result["insights"]]
        self.assertIn("Regional spatial peer comparison available.", whats)
        limits = self.a.canonical_result["data_quality"]["limitations"]
        self.assertFalse(any("Sparse regional coverage" in l for l in limits))

    def test_sparse_coverage_still_reported_when_truly_sparse(self):
        a = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=32.3), neighbors=quiet_neighbors()[:1])
        limits = a.canonical_result["data_quality"]["limitations"]
        self.assertTrue(any("Sparse regional coverage" in l for l in limits))
        self.assertEqual(a.spatial_neighbor_count, 1)


class TestRootCauseCorroboration(unittest.TestCase):
    def _details(self, ra, cv):
        return {"spatial": {"total_neighbors_in_radius": 5,
                             "regional_attribution": {"classification": ra},
                             "counterfactual_verification": {"overall_status": cv}}}

    def _classify(self, layer_details, layer_scores, spatial_score, reasons):
        return RootCauseClassifier().classify(
            is_anomaly=True, layer_scores=layer_scores, veto_fired=False, channel_scores={},
            spatial_score=spatial_score, reasons=reasons, layer_details=layer_details)

    def test_weather_like_corroborated_and_category_unchanged(self):
        scores = {"physics": 0.0, "temporal": 0.8, "multivariate": 0.0, "spatial": 0.1, "drift": 0.0}
        reasons = ["Abrupt change"]
        core = RootCauseClassifier()._classify_core(True, scores, False, {}, 0.1, reasons, self._details("REGIONAL_EVENT", "SUPPORTED"), 3)
        res = self._classify(self._details("REGIONAL_EVENT", "SUPPORTED"), scores, 0.1, reasons)
        self.assertEqual(res.fault_type, core.fault_type)
        self.assertEqual(res.confidence, core.confidence)
        self.assertEqual(res.fault_type, FaultType.GENUINE_EXTREME_WEATHER)
        self.assertEqual(res.spatial_corroboration["state"], "CORROBORATED")
        self.assertEqual(res.evidence[0], "Abrupt change")           # appended at END only
        self.assertEqual(len(res.evidence), 2)
        self.assertEqual(reasons, ["Abrupt change"])                  # shared list not mutated

    def test_weather_like_call_is_downgraded_not_kept_when_spatial_evidence_conflicts(self):
        """PHASE 4 (behavior change, was: 'decision untouched'): a strong GENUINE_EXTREME_WEATHER call is
        no longer kept at MEDIUM against ISOLATED_SENSOR_ANOMALY / CONTRADICTED evidence. It is downgraded
        to the contested POSSIBLE_WEATHER_CHANGE (LOW) and the conflict is still reported."""
        scores = {"physics": 0.0, "temporal": 0.8, "multivariate": 0.0, "spatial": 0.1, "drift": 0.0}
        res = self._classify(self._details("ISOLATED_SENSOR_ANOMALY", "CONTRADICTED"), scores, 0.1, ["Abrupt change"])
        self.assertEqual(res.fault_type, FaultType.POSSIBLE_WEATHER_CHANGE)
        self.assertEqual(res.confidence.value, "LOW")
        self.assertEqual(res.spatial_corroboration["state"], "CONFLICTING")

    def test_sensor_like_corroborated_by_isolation(self):
        scores = {"physics": 0.0, "temporal": 0.0, "multivariate": 0.0, "spatial": 0.9, "drift": 0.0}
        res = self._classify(self._details("ISOLATED_SENSOR_ANOMALY", "CONTRADICTED"), scores, 0.9, ["Temperature disagrees"])
        self.assertEqual(res.fault_type, FaultType.SINGLE_CHANNEL_FAULT)
        self.assertEqual(res.spatial_corroboration["state"], "CORROBORATED")

    def test_insufficient_evidence_is_not_converted_to_support_or_conflict(self):
        scores = {"physics": 0.0, "temporal": 0.0, "multivariate": 0.0, "spatial": 0.9, "drift": 0.0}
        res = self._classify(self._details("UNCERTAIN", "INSUFFICIENT_EVIDENCE"), scores, 0.9, ["Temperature disagrees"])
        self.assertEqual(res.spatial_corroboration["state"], "INSUFFICIENT")

    def test_no_spatial_evidence_leaves_result_untouched(self):
        scores = {"physics": 0.0, "temporal": 0.0, "multivariate": 0.0, "spatial": 0.9, "drift": 0.0}
        res = self._classify({}, scores, 0.9, ["Temperature disagrees"])
        self.assertIsNone(res.spatial_corroboration)
        self.assertEqual(res.evidence, ["Temperature disagrees"])


class TestNoDoubleCounting(unittest.TestCase):
    def test_rich_spatial_evidence_does_not_change_fusion_outcome(self):
        """Fusion consumes only the single primary spatial score (+ neighbor
        count). Stripping S3/S6 evidence from the layer detail must not change
        status, severity, confidence, or root cause."""
        rich = AnomalyDetector().evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=quiet_neighbors())

        det = AnomalyDetector()
        real_eval = det.layer4.evaluate

        def stripped(target, neighbors):
            score, consensus, reason, detail = real_eval(target, neighbors)
            detail = {k: v for k, v in detail.items() if k not in ("regional_attribution", "counterfactual_verification")}
            return score, consensus, reason, detail

        with mock.patch.object(det.layer4, "evaluate", side_effect=stripped):
            plain = det.evaluate_reading(rd("T", 20, 77, t=45.0), neighbors=quiet_neighbors())

        self.assertEqual((rich.status, rich.severity_score, rich.confidence_score, rich.root_cause, rich.diagnosis_confidence),
                         (plain.status, plain.severity_score, plain.confidence_score, plain.root_cause, plain.diagnosis_confidence))
        self.assertEqual(rich.layer_scores, plain.layer_scores)
        self.assertEqual(set(rich.layer_scores), {"physics", "temporal", "multivariate", "spatial", "drift"})


class TestOutputContract(unittest.TestCase):
    def test_canonical_object_exposes_required_fields(self):
        a = AnomalyDetector().evaluate_reading(rd("STN-1", 20, 77, t=45.0), neighbors=quiet_neighbors())
        c = a.canonical_result
        for key in ("station", "observation", "overall", "layers", "diagnosis", "weather_analysis", "insights", "data_quality"):
            self.assertIn(key, c)
        self.assertEqual(c["station"]["id"], "STN-1")
        self.assertEqual(c["observation"]["temperature"], 45.0)   # raw observation
        self.assertIn("timestamp", c["observation"])
        for key in ("primary", "confidence", "evidence", "alternatives", "operator_action", "spatial_corroboration"):
            self.assertIn(key, c["diagnosis"])
        for key in ("severity", "status", "confidence"):
            self.assertIn(key, c["overall"])
        self.assertEqual(a.raw_values["temperature_c"], 45.0)
        self.assertIn("temperature_c", a.corrected_values)         # estimated value kept separate from raw
        for layer in ("physics", "temporal", "multivariate", "spatial", "sensor_health"):
            self.assertIn(layer, c["layers"])
        for key in ("details", "regional_attribution", "counterfactual_verification"):
            self.assertIn(key, c["layers"]["spatial"])

    def test_regional_batch_apis_still_available(self):
        det = AnomalyDetector()
        pool = regional_neighbors() + [rd("T", 20, 77, t=44.0)]
        det.update_spatial_pool(pool)
        for r in pool:
            det.evaluate_reading(r)
        self.assertIn("clusters", det.compute_spatial_events())
        from datetime import datetime, timezone
        out = det.update_spatial_event_tracking(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("summary", out)


if __name__ == "__main__":
    unittest.main()
