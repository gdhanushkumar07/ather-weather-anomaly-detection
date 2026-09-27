"""
Evidence Fusion + final attribution — validation (Phase 4 of backend validation).

ATHER is NOT a five-model voting system. Fusion weighs evidence STRENGTH,
AVAILABILITY, CORROBORATION and specific CONTRADICTIONS, keeps the Spatial
attribution / counterfactual as context (never as a second score), treats Sensor
Health (CUSUM) as persistent-degradation evidence rather than an acute anomaly,
and reports a HEURISTIC confidence (not a calibrated probability).

Three levels are tested:
  1. fuse() on hand-set evidence  - exact, deterministic rules.
  2. the classifier on hand-set evidence - final attribution.
  3. the REAL AnomalyDetector on controlled observations - scenarios A-F and the
     evidence-gated trusted value, i.e. the actual production path.

All observations are SYNTHETIC controlled inputs for engineering verification;
nothing here proves real-world accuracy.
"""
import collections
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np

from config import CONFIG
from schema import AWSReading, FaultType, DiagnosisConfidence
from fusion.conformal_fusion import ConformalEvidenceFusion
from root_cause.classifier import RootCauseClassifier
from app.anomaly.detector import AnomalyDetector

LAYERS = ("physics", "temporal", "multivariate", "spatial", "drift")
FULL_COV = {l: 1.0 for l in LAYERS}


def scores(**kw):
    base = {l: 0.0 for l in LAYERS}
    base.update(kw)
    return base


def avail(**unavailable):
    """All layers available except those passed as name=<reason>."""
    return {l: {"available": l not in unavailable, "reason": unavailable.get(l)} for l in LAYERS}


def fuse(sc, availability=None, coverage=None, ctx=None, n_nb=5, n_hist=50, veto=False, f=None):
    f = f or ConformalEvidenceFusion(CONFIG.fusion)
    return f.fuse(sc, veto, coverage if coverage is not None else FULL_COV, n_nb, n_hist,
                  layer_availability=availability, spatial_context=ctx)


# ═══════════════════ 1. fuse(): evidence availability ═══════════════════
class TestEvidenceAvailability(unittest.TestCase):
    def test_unavailable_evidence_is_not_zero_evidence(self):
        only_physics = fuse(scores(physics=0.70), avail(temporal="x", multivariate="x", spatial="x", drift="x"))[5]
        all_quiet = fuse(scores(physics=0.70), avail())[5]
        # renormalized over the layers that could actually assess the observation ...
        self.assertAlmostEqual(only_physics["ensemble_score"], 0.70, places=4)
        # ... instead of being diluted by four layers that had nothing to say
        self.assertAlmostEqual(all_quiet["ensemble_score"], 0.35 * 0.70 / 0.95, places=3)
        self.assertGreater(only_physics["ensemble_score"], all_quiet["ensemble_score"])
        self.assertEqual(only_physics["available_layer_count"], 1)

    def test_a_lone_available_layer_is_not_an_ensemble(self):
        ia, st, sev, conf, p, d = fuse(scores(physics=0.60), avail(temporal="x", multivariate="x", spatial="x"))
        self.assertFalse(d["ensemble_hit"])
        self.assertFalse(ia)

    def test_an_unavailable_layer_cannot_trigger_an_acute_anomaly(self):
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.95), avail(temporal="insufficient history"))
        self.assertFalse(d["acute_triggers"]["temporal"])
        self.assertFalse(ia)
        self.assertEqual(st, "NORMAL")
        self.assertEqual(d["evidence_availability"]["temporal"], {"available": False, "reason": "insufficient history"})

    def test_evidence_sufficiency_is_availability_weighted(self):
        cov = {"physics": 1.0, "temporal": 1.0, "multivariate": 1.0, "spatial": 1.0, "drift": 1.0}
        self.assertEqual(fuse(scores(), avail(), cov)[5]["evidence_sufficiency"], 1.0)
        startup = fuse(scores(), avail(temporal="x", spatial="x", drift="x"), cov)[5]["evidence_sufficiency"]
        self.assertAlmostEqual(startup, (0.35 + 0.20) / 0.95, places=3)          # only physics + multivariate could assess
        blind = fuse(scores(), avail(physics="x", temporal="x", multivariate="x", spatial="x", drift="x"), cov)[5]["evidence_sufficiency"]
        self.assertEqual(blind, 0.0)
        partial_cov = fuse(scores(), avail(), {**cov, "physics": 0.5})[5]["evidence_sufficiency"]
        self.assertAlmostEqual(partial_cov, 1.0 - 0.35 * 0.5 / 0.95, places=3)   # channel coverage counts, weighted

    def test_normal_confidence_scales_with_how_much_evidence_there_was(self):
        c_all = fuse(scores(), avail())[3]
        c_startup = fuse(scores(), avail(temporal="x", spatial="x", drift="x"))[3]
        c_blind = fuse(scores(), avail(physics="x", temporal="x", multivariate="x", spatial="x", drift="x"))[3]
        self.assertAlmostEqual(c_all, 0.90, places=2)
        self.assertLess(c_startup, c_all - 0.20)         # was 0.75 vs 0.90: mostly-blind "normal" looked confident
        self.assertLess(c_blind, 0.30)
        self.assertGreater(c_all, c_startup)
        self.assertGreater(c_startup, c_blind)

    def test_no_available_evidence_means_no_severity_and_low_confidence(self):
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.9, spatial=0.9),
                                       avail(physics="x", temporal="x", multivariate="x", spatial="x", drift="x"))
        self.assertEqual((ia, st, sev), (False, "NORMAL", 0.0))
        self.assertLessEqual(conf, 0.30)

    def test_callers_that_pass_no_availability_get_all_layers_available(self):
        f = ConformalEvidenceFusion(CONFIG.fusion)
        legacy = f.fuse(scores(physics=0.7), False, FULL_COV, 5, 50)
        explicit = fuse(scores(physics=0.7), avail())
        self.assertEqual(legacy[:4], explicit[:4])


# ═══════════════════ 1b. fuse(): Sensor Health is not acute evidence ═══════════════════
class TestSensorHealthIsNotAnAcuteTrigger(unittest.TestCase):
    def test_strong_drift_alone_is_never_an_anomaly(self):
        # OLD behaviour: drift >= 0.75 was an acute trigger -> ANOMALY, is_anomaly=True
        ia, st, sev, conf, p, d = fuse(scores(drift=0.90), avail(spatial="no neighbors"))
        self.assertFalse(ia)
        self.assertNotEqual(st, "ANOMALY")
        self.assertFalse(d["acute_triggers"]["drift"])

    def test_uncorroborated_drift_is_a_low_certainty_maintenance_warning(self):
        ia, st, sev, conf, p, d = fuse(scores(drift=0.90), avail(spatial="no neighbors"))
        self.assertEqual(st, "WARNING")
        self.assertEqual(d["persistent_degradation"]["state"], "UNCORROBORATED")
        self.assertGreaterEqual(sev, 0.45)
        self.assertLess(sev, 0.60)              # WARNING band, below the anomaly band
        self.assertLessEqual(conf, 0.50)

    def test_drift_corroborated_by_neighbor_disagreement_is_stronger_but_still_not_acute(self):
        ia, st, sev, conf, p, d = fuse(scores(drift=0.90, spatial=0.60), avail())
        self.assertEqual(d["persistent_degradation"]["state"], "CORROBORATED_BY_SPATIAL")
        self.assertEqual(st, "WARNING")
        self.assertFalse(ia)
        self.assertLessEqual(conf, 0.70)
        unc = fuse(scores(drift=0.90), avail(spatial="x"))[3]
        self.assertGreater(conf, unc)

    def test_drift_shared_by_agreeing_neighbors_is_regionally_explained_and_raises_nothing(self):
        """Scenario E in isolation: CUSUM high, neighbors agree with the sensor."""
        ia, st, sev, conf, p, d = fuse(scores(drift=0.95, spatial=0.05), avail())
        self.assertEqual(d["persistent_degradation"]["state"], "REGIONALLY_EXPLAINED")
        self.assertEqual((ia, st), (False, "NORMAL"))
        self.assertLess(sev, 0.35)
        self.assertIn("shared regional weather change", d["persistent_degradation"]["note"])

    def test_drift_never_becomes_the_severity_peak(self):
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.80, drift=0.99), avail(spatial="x"))
        self.assertEqual(d["severity_basis"]["peak_layer"], "temporal")
        self.assertEqual(d["severity_basis"]["peak"], 0.8)
        self.assertTrue(d["acute_triggers"]["temporal"])
        self.assertFalse(d["acute_triggers"]["drift"])

    def test_unavailable_drift_evidence_is_ignored(self):
        ia, st, sev, conf, p, d = fuse(scores(drift=0.99), avail(drift="insufficient samples"))
        self.assertIsNone(d["persistent_degradation"])
        self.assertEqual(st, "NORMAL")

    def test_moderate_drift_is_recorded_but_does_not_change_the_status(self):
        ia, st, sev, conf, p, d = fuse(scores(drift=0.60), avail())
        self.assertIsNone(d["persistent_degradation"])
        self.assertEqual(st, "NORMAL")


# ═══════════════════ 1c. fuse(): attribution/counterfactual are context, contradictions are kept ═══════════════════
class TestSpatialContextAndContradictions(unittest.TestCase):
    def test_counterfactual_and_attribution_are_context_not_a_second_score(self):
        base = None
        for ra, cf in [("UNCERTAIN", "INSUFFICIENT_EVIDENCE"), ("REGIONAL_EVENT", "SUPPORTED"),
                       ("ISOLATED_SENSOR_ANOMALY", "CONTRADICTED")]:
            out = fuse(scores(temporal=0.55, spatial=0.30), avail(), ctx={"attribution": ra, "counterfactual": cf})
            numbers = out[:4]
            base = base or numbers
            self.assertEqual(numbers, base, "same layer scores must give the same numbers regardless of attribution/counterfactual")
            self.assertEqual(out[5]["evidence_context"]["regional_attribution"], ra)
            self.assertEqual(out[5]["evidence_context"]["counterfactual"], cf)

    def test_a_layer_agreeing_with_neighbors_while_another_flags_is_a_recorded_conflict(self):
        """Scenario F at fuse level: Temporal strongly anomalous, Spatial says the target agrees with its neighbors."""
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.95, spatial=0.02), avail())
        ctx = d["evidence_context"]
        self.assertEqual(ctx["spatial_view"], "AGREES_WITH_NEIGHBORS")
        self.assertEqual(len(ctx["conflicts"]), 1)
        self.assertEqual(ctx["conflicts"][0]["between"], ["temporal", "spatial"])
        self.assertEqual(d["agreement_factor"], 0.75)               # not pretended to be full agreement
        self.assertTrue(any("agrees with neighbors" in w for w in ctx["genuine_weather_indicators"]))
        no_conflict = fuse(scores(temporal=0.95, spatial=0.95), avail())[3]
        self.assertLess(conf, no_conflict)

    def test_quiet_physics_and_multivariate_are_not_a_contradiction_of_a_spike(self):
        """A spike inside physical limits legitimately leaves Physics / Multivariate quiet."""
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.95), avail(spatial="no neighbors"))
        self.assertEqual(d["evidence_context"]["conflicts"], [])
        self.assertEqual(d["agreement_factor"], 1.0)

    def test_spatial_score_and_regional_support_disagreeing_is_recorded(self):
        out = fuse(scores(spatial=0.90), avail(), ctx={"attribution": "REGIONAL_EVENT", "counterfactual": "SUPPORTED"})
        d = out[5]
        self.assertTrue(any(c["between"] == ["spatial_score", "spatial_counterfactual"] for c in d["evidence_context"]["conflicts"]))
        contra = fuse(scores(spatial=0.90), avail(), ctx={"attribution": "ISOLATED_SENSOR_ANOMALY", "counterfactual": "CONTRADICTED"})
        self.assertEqual(contra[5]["evidence_context"]["conflicts"], [])
        self.assertLess(out[3], contra[3])
        self.assertIn("counterfactual: neighbors do not support the reading (CONTRADICTED)",
                      contra[5]["evidence_context"]["sensor_fault_indicators"])

    def test_spatial_view_distinguishes_unavailable_from_agrees(self):
        self.assertEqual(fuse(scores(), avail(spatial="x"))[5]["evidence_context"]["spatial_view"], "UNAVAILABLE")
        self.assertEqual(fuse(scores(spatial=0.0), avail())[5]["evidence_context"]["spatial_view"], "AGREES_WITH_NEIGHBORS")
        self.assertEqual(fuse(scores(spatial=0.60), avail())[5]["evidence_context"]["spatial_view"], "DISAGREES_WITH_NEIGHBORS")
        self.assertEqual(fuse(scores(spatial=0.35), avail())[5]["evidence_context"]["spatial_view"], "AMBIGUOUS")


# ═══════════════════ 1d. fuse(): confidence, severity, honesty ═══════════════════
class TestConfidenceSeverityAndHonesty(unittest.TestCase):
    def test_case_a_one_layer_fires_confidence_is_capped(self):
        ia, st, sev, conf, p, d = fuse(scores(temporal=0.80), avail(spatial="x"))
        self.assertTrue(ia)
        self.assertEqual(d["meaningful_layer_count"], 1)
        self.assertLessEqual(conf, 0.65)                       # one layer, however strong, is never highly confident

    def test_case_b_independent_layers_agreeing_allow_higher_confidence(self):
        single = fuse(scores(temporal=0.85), avail(spatial="x"))[3]
        agree = fuse(scores(physics=0.80, temporal=0.80, multivariate=0.85), avail(spatial="x"))
        self.assertEqual(agree[5]["meaningful_layer_count"], 3)
        self.assertGreater(agree[3], 0.65)
        self.assertGreater(agree[3], single)
        self.assertLessEqual(agree[3], 0.97)

    def test_case_d_mostly_unavailable_and_weak_stays_low(self):
        # only Physics could assess the observation, and it sees nothing wrong
        ia, st, sev, conf, p, d = fuse(scores(physics=0.10), avail(temporal="x", multivariate="x", spatial="x", drift="x"))
        self.assertLessEqual(conf, 0.55)
        self.assertLess(d["evidence_sufficiency"], 0.40)
        self.assertLess(conf, fuse(scores(physics=0.10), avail())[3] - 0.30)

    def test_severity_is_explainable_and_independent_of_confidence(self):
        a = fuse(scores(temporal=0.80, spatial=0.40), avail(), coverage=FULL_COV)
        b = fuse(scores(temporal=0.80, spatial=0.40), avail(), coverage={**FULL_COV, "temporal": 0.3, "spatial": 0.3})
        peak, ens = a[5]["severity_basis"]["peak"], a[5]["severity_basis"]["ensemble"]
        self.assertAlmostEqual(a[2], min(1.0, 0.6 * peak + 0.4 * ens), delta=1e-3)   # basis values are rounded to 3 dp
        self.assertEqual(a[2], b[2])            # severity does not depend on coverage/confidence ...
        self.assertNotEqual(a[3], b[3])         # ... confidence does

    def test_confidence_is_labeled_heuristic_and_no_p_value_is_claimed_when_uncalibrated(self):
        f = ConformalEvidenceFusion(CONFIG.fusion)
        d = fuse(scores(physics=0.6, temporal=0.6), avail(), f=f)[5]
        self.assertFalse(f.is_calibrated)
        self.assertFalse(d["calibrated"])
        self.assertIsNone(d["p_value"])
        self.assertIn("NOT a calibrated probability", d["confidence_basis"])

    def test_after_real_calibration_the_flag_and_p_value_are_reported(self):
        f = ConformalEvidenceFusion(CONFIG.fusion)
        f.calibrate([scores(physics=0.05 * i) for i in range(20)])
        d = fuse(scores(physics=0.6, temporal=0.6), avail(), f=f)[5]
        self.assertTrue(d["calibrated"])
        self.assertIsNotNone(d["p_value"])

    def test_physics_veto_keeps_its_contract_and_reports_availability(self):
        ia, st, sev, conf, p, d = fuse(scores(physics=1.0), avail(temporal="x"), veto=True)
        self.assertEqual((ia, st, sev, conf), (True, "ANOMALY", 1.0, 0.95))
        self.assertEqual(d["triggered_by"], "physics_veto")
        self.assertIn("evidence_availability", d)
        self.assertIn("Deterministic physics rule", d["confidence_basis"])


# ═══════════════════ 2. classifier: final attribution ═══════════════════
def details(ra=None, cf=None, n_neighbors=6, sufficiency=1.0, n_avail=4, persistent=None):
    return {
        "spatial": {"regional_attribution": {"classification": ra} if ra else {},
                    "counterfactual_verification": {"overall_status": cf} if cf else {},
                    "total_neighbors_in_radius": n_neighbors},
        "fusion": {"evidence_sufficiency": sufficiency, "available_layer_count": n_avail,
                   "persistent_degradation": {"state": persistent, "note": "n"} if persistent else None},
    }


def classify(sc, spatial_score, reasons, det, is_anomaly=True):
    return RootCauseClassifier().classify(is_anomaly=is_anomaly, layer_scores=sc, veto_fired=False, channel_scores={},
                                          spatial_score=spatial_score, reasons=reasons, layer_details=det)


class TestFinalAttribution(unittest.TestCase):
    def test_normal_confidence_tier_reflects_evidence_sufficiency(self):
        tier = lambda s: classify(scores(), 0.0, [], details(sufficiency=s), is_anomaly=False).confidence
        self.assertEqual(tier(1.0), DiagnosisConfidence.HIGH)
        self.assertEqual(tier(0.6), DiagnosisConfidence.MEDIUM)
        self.assertEqual(tier(0.35), DiagnosisConfidence.LOW)
        self.assertEqual(tier(0.10), DiagnosisConfidence.INSUFFICIENT_DATA)
        legacy = RootCauseClassifier().classify(False, scores(), False, {}, 0.0, [], {})
        self.assertEqual(legacy.confidence, DiagnosisConfidence.HIGH)          # callers with no fusion context unchanged

    def test_low_evidence_normal_says_so(self):
        r = classify(scores(), 0.0, [], details(sufficiency=0.579, n_avail=2), is_anomaly=False)
        self.assertEqual(r.fault_type, FaultType.NORMAL)
        self.assertIn("2 of 4 evidence layers", r.primary_signal)

    def test_persistent_degradation_is_calibration_drift_with_honest_certainty(self):
        unc = classify(scores(drift=0.9), 0.0, ["x CUSUM drift"], details(persistent="UNCORROBORATED"), is_anomaly=False)
        cor = classify(scores(drift=0.9, spatial=0.6), 0.6, ["x CUSUM drift"], details(persistent="CORROBORATED_BY_SPATIAL"), is_anomaly=False)
        self.assertEqual((unc.fault_type, unc.confidence), (FaultType.CALIBRATION_DRIFT, DiagnosisConfidence.LOW))
        self.assertEqual((cor.fault_type, cor.confidence), (FaultType.CALIBRATION_DRIFT, DiagnosisConfidence.MEDIUM))
        self.assertIn("not an acute anomaly", unc.operator_action)
        self.assertIn("weather variation", " ".join(unc.alternatives))

    def test_regionally_explained_drift_is_not_diagnosed_as_a_sensor_fault(self):
        r = classify(scores(drift=0.95, spatial=0.05), 0.05, [], details(persistent="REGIONALLY_EXPLAINED"), is_anomaly=False)
        self.assertEqual(r.fault_type, FaultType.NORMAL)
        r2 = classify(scores(temporal=0.5, drift=0.95), 0.05, ["Abrupt change: CUSUM drift (HIGH_RISK)"],
                      details(persistent="REGIONALLY_EXPLAINED"))
        self.assertNotEqual(r2.fault_type, FaultType.CALIBRATION_DRIFT)

    def test_regional_support_recognises_a_weather_like_reading_even_when_the_idw_score_is_ambiguous(self):
        r = classify(scores(temporal=0.8, spatial=0.5), 0.5, ["Abrupt change"], details("REGIONAL_EVENT", "SUPPORTED"))
        self.assertEqual(r.fault_type, FaultType.POSSIBLE_WEATHER_CHANGE)       # contested -> LOW, not a sensor spike
        self.assertEqual(r.confidence, DiagnosisConfidence.LOW)
        without = classify(scores(temporal=0.8, spatial=0.5), 0.5, ["Abrupt change"], details("UNCERTAIN", "INSUFFICIENT_EVIDENCE"))
        self.assertEqual(without.fault_type, FaultType.SENSOR_SPIKE)
        self.assertEqual(without.confidence, DiagnosisConfidence.MEDIUM)

    def test_strong_weather_call_needs_clean_support_and_is_downgraded_by_isolation_evidence(self):
        clean = classify(scores(temporal=0.8, spatial=0.05), 0.05, ["Abrupt change"], details("REGIONAL_EVENT", "SUPPORTED"))
        self.assertEqual((clean.fault_type, clean.confidence), (FaultType.GENUINE_EXTREME_WEATHER, DiagnosisConfidence.MEDIUM))
        conflicted = classify(scores(temporal=0.8, spatial=0.05), 0.05, ["Abrupt change"], details("ISOLATED_SENSOR_ANOMALY", "CONTRADICTED"))
        self.assertEqual((conflicted.fault_type, conflicted.confidence), (FaultType.POSSIBLE_WEATHER_CHANGE, DiagnosisConfidence.LOW))
        self.assertEqual(conflicted.spatial_corroboration["state"], "CONFLICTING")

    def test_spatial_outlier_fault_is_low_when_the_region_supports_the_reading(self):
        r = classify(scores(spatial=0.9), 0.9, [], details("REGIONAL_EVENT", "SUPPORTED"))
        self.assertEqual((r.fault_type, r.confidence), (FaultType.SINGLE_CHANNEL_FAULT, DiagnosisConfidence.LOW))
        r2 = classify(scores(spatial=0.9), 0.9, [], details("ISOLATED_SENSOR_ANOMALY", "CONTRADICTED"))
        self.assertEqual((r2.fault_type, r2.confidence), (FaultType.SINGLE_CHANNEL_FAULT, DiagnosisConfidence.MEDIUM))

    def test_a_lone_multivariate_signal_with_almost_no_other_evidence_is_insufficient_not_a_named_fault(self):
        r = classify(scores(multivariate=0.85), 0.0, ["Rare joint state"], details(n_avail=2, sufficiency=0.58))
        self.assertEqual((r.fault_type, r.confidence), (FaultType.INSUFFICIENT_EVIDENCE, DiagnosisConfidence.INSUFFICIENT_DATA))
        r2 = classify(scores(multivariate=0.85), 0.0, ["Rare joint state"], details(n_avail=4))
        self.assertEqual(r2.fault_type, FaultType.NOISE_BURST)                  # enough layers were available: unchanged

    def test_contradictory_evidence_is_never_forced_into_a_confident_arbitrary_cause(self):
        r = classify(scores(temporal=0.7, spatial=0.9), 0.9, ["Abrupt change"], details("REGIONAL_EVENT", "CONTRADICTED"))
        self.assertIn(r.confidence, (DiagnosisConfidence.LOW, DiagnosisConfidence.INSUFFICIENT_DATA))


# ═══════════════════ 3. production detector: controlled scenarios ═══════════════════
T0 = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
ts = lambda i: T0 + timedelta(minutes=10 * i)


def R(sid, i, t, p=None, h=30.0, lat=17.0, src="AWS_IN_SITU"):
    p = 1012.0 + 0.05 * ((i % 5) - 2) if p is None else p
    return AWSReading(station_id=sid, lat=lat, lon=78.0, temperature_c=t, pressure_hpa=p,
                      humidity_pct=h + 0.1 * ((i % 3) - 1), timestamp=ts(i), observation_timestamp=ts(i), source=src)


def nb(i, temps):
    return [R(f"N{k}", i, t, lat=17.0 + 0.02 * (k + 1)) for k, t in enumerate(temps)]


def cf_of(a):
    return (a.layer_details["spatial"].get("counterfactual_verification") or {}).get("overall_status")


def ra_of(a):
    return (a.layer_details["spatial"].get("regional_attribution") or {}).get("classification")


def fusion_of(a):
    return a.layer_details["fusion"]


SENSOR_SIDE = {FaultType.SENSOR_SPIKE, FaultType.SINGLE_CHANNEL_FAULT, FaultType.CALIBRATION_DRIFT,
               FaultType.FROZEN_SENSOR, FaultType.NOISE_BURST}


class TestControlledScenarios(unittest.TestCase):
    def isolated_spike(self, target=44.0):
        det = AnomalyDetector()
        for i in range(10):
            det.update_spatial_pool(nb(i, [30, 31, 32, 31, 30, 32]))
            det.evaluate_reading(R("A", i, 31.0))
        det.update_spatial_pool(nb(10, [30, 31, 32, 31, 30, 32]))
        return det, det.evaluate_reading(R("A", 10, target))

    def test_scenario_A_isolated_sensor_fault_supports_a_sensor_side_attribution(self):
        det, a = self.isolated_spike()
        self.assertEqual(a.status, "ANOMALY")
        self.assertEqual(ra_of(a), "ISOLATED_SENSOR_ANOMALY")
        self.assertEqual(cf_of(a), "CONTRADICTED")
        self.assertGreaterEqual(a.layer_scores["temporal"], 0.70)
        self.assertGreaterEqual(a.layer_scores["spatial"], 0.70)
        self.assertEqual(a.root_cause, FaultType.SENSOR_SPIKE)
        self.assertEqual(a.diagnosis_confidence, DiagnosisConfidence.MEDIUM)
        self.assertEqual(a.canonical_result["diagnosis"]["spatial_corroboration"]["state"], "CORROBORATED")
        ctx = fusion_of(a)["evidence_context"]
        self.assertIn("spatial attribution: ISOLATED_SENSOR_ANOMALY", ctx["sensor_fault_indicators"])
        self.assertEqual(ctx["genuine_weather_indicators"], [])
        self.assertGreater(a.confidence_score, 0.70)                    # two independent layers corroborate

    def test_scenario_A2_isolated_deviation_with_persistent_drift_is_sensor_side_and_drift_is_corroborated(self):
        det = AnomalyDetector()
        for i in range(45):
            det.update_spatial_pool(nb(i, [30, 31, 32, 31, 30, 32]))
            a = det.evaluate_reading(R("A2", i, 31.0 + (0.3 * (i - 10) if i >= 10 else 0.0)))
        self.assertEqual(fusion_of(a)["persistent_degradation"]["state"], "CORROBORATED_BY_SPATIAL")
        self.assertIn(a.root_cause, SENSOR_SIDE)
        self.assertEqual(ra_of(a), "ISOLATED_SENSOR_ANOMALY")

    def test_scenario_B_regional_weather_event_stays_a_genuine_weather_call(self):
        det = AnomalyDetector()
        for i in range(10):
            det.update_spatial_pool(nb(i, [31] * 8))
            det.evaluate_reading(R("B", i, 31.0))
        det.update_spatial_pool(nb(10, [41, 42, 43, 30, 30, 31, 30, 31]))           # a coherent nearby cluster shares the reading
        a = det.evaluate_reading(R("B", 10, 42.0))
        self.assertEqual(ra_of(a), "REGIONAL_EVENT")
        self.assertEqual(cf_of(a), "SUPPORTED")
        self.assertGreaterEqual(a.layer_scores["temporal"], 0.70)                   # Temporal calls it unusual ...
        self.assertEqual(a.layer_scores["physics"], 0.0)                            # ... Physics says plausible
        self.assertEqual(a.root_cause, FaultType.GENUINE_EXTREME_WEATHER)
        self.assertEqual(a.canonical_result["diagnosis"]["spatial_corroboration"]["state"], "CORROBORATED")
        self.assertIn("counterfactual: neighbors support the reading (SUPPORTED)",
                      fusion_of(a)["evidence_context"]["genuine_weather_indicators"])
        self.assertEqual(fusion_of(a)["evidence_context"]["sensor_fault_indicators"], [])
        self.assertEqual(a.corrected_values["temperature_c"], 42.0)                 # the reading is NOT replaced

    def test_scenario_C_insufficient_evidence_is_uncertain_not_confident(self):
        det = AnomalyDetector()
        normal = det.evaluate_reading(R("C1", 0, 30.0))                             # nothing to compare with, nothing wrong
        f = fusion_of(normal)
        for layer in ("temporal", "spatial", "drift"):
            self.assertFalse(f["evidence_availability"][layer]["available"], layer)
        self.assertIn("spatial analysis requires", f["evidence_availability"]["spatial"]["reason"].lower())
        self.assertEqual(normal.status, "NORMAL")
        self.assertLess(f["evidence_sufficiency"], 0.60)
        self.assertNotEqual(normal.diagnosis_confidence, DiagnosisConfidence.HIGH)   # was HIGH
        self.assertLess(normal.confidence_score, 0.65)                               # was 0.69-0.75
        self.assertIn("evidence layers could assess", normal.primary_signal)          # says WHY it is not high confidence

        lone = AnomalyDetector().evaluate_reading(R("C2", 0, 33.0, h=96.0))         # a striking joint state, everything else unavailable
        self.assertEqual(lone.layer_scores["multivariate"], 0.85)
        self.assertEqual(lone.root_cause, FaultType.INSUFFICIENT_EVIDENCE)
        self.assertEqual(lone.diagnosis_confidence, DiagnosisConfidence.INSUFFICIENT_DATA)
        self.assertEqual(lone.corrected_values["humidity_pct"], lone.raw_values["humidity_pct"])

    def test_scenario_D_single_spike_is_acute_evidence_not_persistent_degradation(self):
        det = AnomalyDetector()
        for i in range(30):
            det.evaluate_reading(R("D", i, 30.0 + 0.1 * (i % 3)))
        a = det.evaluate_reading(R("D", 30, 45.0))
        self.assertLess(a.layer_scores["drift"], 0.15)                              # CUSUM does not call one spike drift
        self.assertIsNone(fusion_of(a)["persistent_degradation"])
        self.assertGreaterEqual(a.layer_scores["temporal"], 0.70)                   # the acute layer owns it
        self.assertTrue(fusion_of(a)["acute_triggers"]["temporal"])
        self.assertFalse(fusion_of(a)["acute_triggers"]["drift"])
        self.assertNotEqual(a.root_cause, FaultType.CALIBRATION_DRIFT)
        self.assertEqual(a.root_cause, FaultType.SENSOR_SPIKE)
        self.assertEqual(a.diagnosis_confidence, DiagnosisConfidence.LOW)           # no spatial evidence either way

    @staticmethod
    def wave(i):
        return 25.0 + 5.0 * np.sin(2 * np.pi * i / 144)

    def test_scenario_E_normal_weather_variation_is_not_a_sensor_fault_when_neighbors_share_it(self):
        det = AnomalyDetector()
        rows = []
        for i in range(200):
            det.update_spatial_pool([R(f"N{k}", i, self.wave(i) + 0.1 * k, lat=17.0 + 0.02 * (k + 1)) for k in range(6)])
            a = det.evaluate_reading(R("E", i, self.wave(i)))
            rows.append(((fusion_of(a)["persistent_degradation"] or {}).get("state"), a.status, a.root_cause,
                         a.layer_scores["drift"], a.layer_scores["spatial"]))
        self.assertGreaterEqual(max(r[3] for r in rows), 0.75)                      # CUSUM IS high (Sensor Health's known limitation) ...
        explained = [r for r in rows if r[0] == "REGIONALLY_EXPLAINED"]
        self.assertGreaterEqual(len(explained), 100)                                # ... and Fusion recognises neighbors share the change
        self.assertTrue(all(r[1] == "NORMAL" for r in rows), collections.Counter(r[1] for r in rows))
        self.assertTrue(all(r[2] == FaultType.NORMAL for r in rows))
        self.assertEqual(max(r[4] for r in rows), 0.0)

    def test_scenario_E2_the_same_wave_with_no_neighbors_is_only_a_low_certainty_maintenance_warning(self):
        det = AnomalyDetector()
        rows = []
        for i in range(200):
            a = det.evaluate_reading(R("E2", i, self.wave(i)))
            rows.append((fusion_of(a)["persistent_degradation"], a.status, a.root_cause, a.diagnosis_confidence, a.confidence_score, a.is_anomaly))
        flagged = [r for r in rows if r[0]]
        self.assertGreaterEqual(len(flagged), 100)
        for pd, status, root, tier, conf, is_anom in flagged:
            self.assertEqual(pd["state"], "UNCORROBORATED")                          # cannot exclude weather: says so
            self.assertEqual(status, "WARNING")                                      # never ANOMALY from CUSUM alone
            self.assertFalse(is_anom)
            self.assertEqual((root, tier), (FaultType.CALIBRATION_DRIFT, DiagnosisConfidence.LOW))
            self.assertLessEqual(conf, 0.50)
            self.assertIn("weather variation", pd["note"])

    def test_scenario_F_contradictory_evidence_is_preserved_not_flattened(self):
        det = AnomalyDetector()
        for i in range(10):
            det.update_spatial_pool(nb(i, [31] * 6))
            det.evaluate_reading(R("F", i, 31.0))
        det.update_spatial_pool(nb(10, [41, 42, 43, 42, 41, 43]))                    # the whole neighborhood moves with it
        a = det.evaluate_reading(R("F", 10, 42.0))
        f = fusion_of(a)
        self.assertGreaterEqual(a.layer_scores["temporal"], 0.70)
        self.assertEqual(a.layer_scores["spatial"], 0.0)
        self.assertEqual(len(f["evidence_context"]["conflicts"]), 1)
        self.assertEqual(f["agreement_factor"], 0.75)                                 # "not all layers agree" is visible in the numbers
        self.assertIn(a.root_cause, (FaultType.GENUINE_EXTREME_WEATHER, FaultType.POSSIBLE_WEATHER_CHANGE))
        self.assertNotIn(a.root_cause, SENSOR_SIDE)
        self.assertLess(a.confidence_score, self.isolated_spike()[1].confidence_score)  # less sure than the corroborated fault

    def test_status_in_the_response_is_exactly_what_fusion_returned(self):
        det = AnomalyDetector()
        seen = []
        real = det.fusion.fuse

        def spy(**kw):
            out = real(**kw)
            seen.append((kw, out))
            return out

        det.fusion.fuse = spy
        for i in range(10):
            det.update_spatial_pool(nb(i, [30, 31, 32, 31, 30, 32]))
            det.evaluate_reading(R("P", i, 31.0))
        det.update_spatial_pool(nb(10, [30, 31, 32, 31, 30, 32]))
        a = det.evaluate_reading(R("P", 10, 44.0))
        kw, (ia, st, sev, conf, p, d) = seen[-1]
        self.assertEqual((a.is_anomaly, a.status, a.severity_score, a.confidence_score), (ia, st, sev, conf))
        self.assertIn("layer_availability", kw)
        self.assertEqual(kw["spatial_context"], {"attribution": "ISOLATED_SENSOR_ANOMALY", "counterfactual": "CONTRADICTED"})
        self.assertEqual(kw["layer_scores"], a.layer_scores)
        self.assertEqual(kw["layer_coverage"]["multivariate"], 1.0)                   # was ALWAYS 0.0 (wrong key)

    def test_a_layer_that_fails_is_reported_unavailable_and_the_rest_still_fuse(self):
        det = AnomalyDetector()
        with mock.patch.object(det.layer2, "evaluate", side_effect=RuntimeError("boom")):
            a = det.evaluate_reading(R("X", 0, 30.0))
        av = fusion_of(a)["evidence_availability"]
        self.assertFalse(av["temporal"]["available"])
        self.assertEqual(av["temporal"]["reason"], "layer failed")
        self.assertTrue(av["physics"]["available"])


# ═══════════════════ trusted / estimated value ═══════════════════
class TestEvidenceGatedTrustedValue(unittest.TestCase):
    def setUp(self):
        self.det = AnomalyDetector()
        for i in range(10):
            self.det.update_spatial_pool(nb(i, [30, 31, 32, 31, 30, 32]))
            self.det.evaluate_reading(R("T", i, 31.0))
        self.det.update_spatial_pool(nb(10, [30, 31, 32, 31, 30, 32]))

    def test_justified_estimate_replaces_only_the_affected_channel_and_the_raw_value_survives(self):
        reading = R("T", 10, 44.0)
        a = self.det.evaluate_reading(reading)
        est = a.canonical_result["estimation"]
        self.assertTrue(est["justified"] and est["applied"])
        self.assertEqual(est["applied_channels"], ["temperature_c"])
        self.assertAlmostEqual(a.corrected_values["temperature_c"], 30.4, delta=0.6)   # independent neighbor consensus
        self.assertEqual(a.corrected_values["pressure_hpa"], reading.pressure_hpa)      # healthy channels untouched
        self.assertEqual(a.corrected_values["humidity_pct"], reading.humidity_pct)
        # the RAW observation is preserved everywhere
        self.assertEqual(a.raw_values["temperature_c"], 44.0)
        self.assertEqual(a.canonical_result["observation"]["temperature"], 44.0)
        self.assertEqual(reading.temperature_c, 44.0)
        self.assertTrue(est["raw_value_preserved"])

    def test_no_estimate_for_a_reading_the_region_supports(self):
        det = AnomalyDetector()
        for i in range(10):
            det.update_spatial_pool(nb(i, [31] * 8))
            det.evaluate_reading(R("T", i, 31.0))
        det.update_spatial_pool(nb(10, [41, 42, 43, 30, 30, 31, 30, 31]))
        a = det.evaluate_reading(R("T", 10, 42.0))
        self.assertFalse(a.canonical_result["estimation"]["applied"])
        self.assertEqual(a.corrected_values["temperature_c"], 42.0)

    def test_no_estimate_when_neighbor_counterfactual_supports_even_if_a_sensor_call_was_made(self):
        real = self.det.layer4.evaluate

        def supported(*args, **kw):
            s, c, r, d = real(*args, **kw)
            d["counterfactual_verification"]["overall_status"] = "SUPPORTED"
            return s, c, r, d

        with mock.patch.object(self.det.layer4, "evaluate", side_effect=supported):
            a = self.det.evaluate_reading(R("T", 10, 44.0))
        est = a.canonical_result["estimation"]
        self.assertFalse(est["justified"])
        self.assertEqual(a.corrected_values["temperature_c"], 44.0)

    def test_no_estimate_for_a_low_confidence_or_insufficient_diagnosis(self):
        det = AnomalyDetector()
        for i in range(30):
            det.evaluate_reading(R("D", i, 30.0 + 0.1 * (i % 3)))
        a = det.evaluate_reading(R("D", 30, 45.0))                                  # SENSOR_SPIKE, LOW: no spatial evidence
        self.assertEqual(a.corrected_values["temperature_c"], 45.0)
        self.assertIn("too low", a.canonical_result["estimation"]["reason"])
        lone = AnomalyDetector().evaluate_reading(R("C2", 0, 33.0, h=96.0))
        self.assertFalse(lone.canonical_result["estimation"]["justified"])

    def test_no_estimate_for_persistent_drift(self):
        det = AnomalyDetector()
        for i in range(45):
            det.update_spatial_pool(nb(i, [30, 31, 32, 31, 30, 32]))
            a = det.evaluate_reading(R("D2", i, 31.0 + (0.3 * (i - 10) if i >= 10 else 0.0)))
        self.assertEqual(a.root_cause, FaultType.CALIBRATION_DRIFT)
        self.assertFalse(a.canonical_result["estimation"]["justified"])
        self.assertEqual(a.corrected_values["temperature_c"], a.raw_values["temperature_c"])

    def test_never_a_blanket_replacement_without_an_identified_channel(self):
        d = AnomalyDetector()
        diag = SimpleNamespace(fault_type=FaultType.SENSOR_SPIKE, confidence=DiagnosisConfidence.HIGH)
        v = d._estimation_decision(True, diag, [], {})
        self.assertFalse(v["justified"])
        self.assertIn("No specific affected channel", v["reason"])
        ok = d._estimation_decision(True, diag, ["temperature_c"], {})
        self.assertTrue(ok["justified"])
        self.assertEqual(ok["channel"], "temperature_c")

    def test_a_normal_observation_is_used_as_reported(self):
        a = AnomalyDetector().evaluate_reading(R("N", 0, 30.0))
        self.assertEqual(a.corrected_values["temperature_c"], 30.0)
        self.assertFalse(a.canonical_result["estimation"]["justified"])


# ═══════════════════ response contract ═══════════════════
class TestResponseContract(unittest.TestCase):
    def test_final_response_carries_the_fusion_evidence_and_is_honest_about_confidence(self):
        a = TestControlledScenarios().isolated_spike()[1]
        c = a.canonical_result
        f = fusion_of(a)
        for key in ("evidence_availability", "evidence_sufficiency", "persistent_degradation", "evidence_context",
                    "severity_basis", "acute_triggers", "calibrated", "confidence_basis", "available_layer_count"):
            self.assertIn(key, f, key)
        self.assertEqual(set(f["evidence_availability"]), set(LAYERS))
        self.assertIn("evidence_availability", c)
        self.assertEqual(set(c["evidence_availability"]), set(LAYERS))
        self.assertIn("estimation", c)
        self.assertIn("NOT a calibrated probability", c["overall"]["confidence_basis"])
        self.assertFalse(f["calibrated"])
        self.assertIsNone(f["p_value"])
        self.assertEqual(c["overall"]["evidence_sufficiency"], f["evidence_sufficiency"])
        self.assertEqual(c["overall"]["confidence"], round(a.confidence_score, 3))


if __name__ == "__main__":
    unittest.main()
