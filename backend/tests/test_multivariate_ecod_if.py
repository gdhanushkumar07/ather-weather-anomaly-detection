"""
Focused tests for the Multivariate layer (ECOD + Isolation Forest).

They pin the guarantees that matter for the evidence-honesty contract:

  * ECOD and Isolation Forest are REAL and actually execute -- proven with
    spies on the real fitted models, not by trusting a flag
  * the API reports `method_executed` / `detectors.*.executed` truthfully
  * the pressure-convention mismatch (dataset = SURFACE, runtime = MSL) is
    resolved by normalisation, so normal runtime stations are not outliers
  * an UNKNOWN pressure convention is never silently treated as MSL
  * insufficient / unavailable evidence is never reported as PASS
  * the canonical layer card never says "0 available" for valid channels
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np

from app.anomaly.detector import AnomalyDetector
from engine import multivariate_features as mf
from engine.layer3_multivariate import (DEFAULT_ARTIFACT_DIR, MultivariateArtifactError,
                                        MultivariateConsistencyLayer, load_artifacts,
                                        resolve_pressure_convention)
from multivariate_training.common import ecod_single_row_scores
from schema import AWSReading, ObservationSource

NWP = ObservationSource.NWP_MODEL_REFERENCE
INSITU = ObservationSource.AWS_IN_SITU
TEST = ObservationSource.SYNTHETIC_TEST

PUNE = (18.4923, 73.8619)
TOKYO = (35.7, 139.7)

# One shared layer / detector: loading the artifacts takes ~1 s.
LAYER = MultivariateConsistencyLayer()
DETECTOR = AnomalyDetector()


def rd(t=29.0, p=1010.6, rh=57.0, *, latlon=PUNE, source=NWP, conv="MSL", station="MV", elev=None, **kw):
    return AWSReading(station_id=station, temperature_c=t, pressure_hpa=p, humidity_pct=rh,
                      lat=latlon[0], lon=latlon[1], source=source, pressure_convention=conv,
                      elevation_m=elev, **kw)


def card_of(alert):
    return alert.canonical_result["layers"]["multivariate"]


# ════════════════════════ A. model artifact loading ════════════════════════
class TestArtifactLoading(unittest.TestCase):
    def test_artifacts_load_from_the_real_artifact_directory(self):
        a = load_artifacts(DEFAULT_ARTIFACT_DIR)
        self.assertEqual(a.model_version, a.card["model_version"])
        self.assertTrue(hasattr(a.ecod, "decision_function"))
        self.assertTrue(hasattr(a.iforest, "score_samples"))
        self.assertGreater(len(a.baselines.cities), 100)

    def test_model_card_records_full_provenance(self):
        card = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "model_card.json")))
        for key in ("source_dataset", "dataset_row_count", "sample_count", "train_period", "calibration_period",
                    "test_period", "feature_names", "pressure_source_convention", "runtime_pressure_convention",
                    "pressure_normalization_method", "climatological_elevation_proxy_method", "baseline_scope",
                    "random_seed", "ecod", "isolation_forest", "libraries", "calibration"):
            self.assertIn(key, card, key)
        self.assertEqual(card["pressure_source_convention"], "SURFACE")
        self.assertEqual(card["runtime_pressure_convention"], "MSL")
        self.assertIn("pyod", card["ecod"]["library"])
        self.assertIn("scikit-learn", card["isolation_forest"]["library"])

    def test_models_were_trained_on_the_indian_dataset_never_the_temporal_synthetic_one(self):
        card = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "model_card.json")))
        self.assertIn("Indian_Weather_Dataset", card["source_dataset"])
        self.assertNotIn("synthetic_temporal", card["source_dataset"])
        self.assertGreater(card["dataset_row_count"], 40_000_000)

    def test_chronological_split_has_no_overlap(self):
        card = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "model_card.json")))
        tr, ca, te = card["train_period"], card["calibration_period"], card["test_period"]
        self.assertEqual(tr["end_exclusive"], ca["start"])
        self.assertEqual(ca["end_exclusive"], te["start"])

    def test_missing_artifacts_fail_clearly_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(MultivariateArtifactError) as cm:
                MultivariateConsistencyLayer(artifact_dir=d, strict=True)
            self.assertIn("missing", str(cm.exception))

    def test_missing_artifacts_never_switch_to_another_algorithm(self):
        with tempfile.TemporaryDirectory() as d:
            layer = MultivariateConsistencyLayer(artifact_dir=d, strict=False)
            self.assertIsNone(layer.artifacts)
            with self.assertRaises(MultivariateArtifactError):
                layer.evaluate(rd())          # a 3-channel MSL reading REQUIRES the models

    def test_layer_with_missing_artifacts_is_reported_unavailable_by_the_detector(self):
        with tempfile.TemporaryDirectory() as d:
            det = AnomalyDetector()
            det.layer3 = MultivariateConsistencyLayer(artifact_dir=d, strict=False)
            card = card_of(det.evaluate_reading(rd(station="NOART")))
        self.assertEqual(card["status"], "UNAVAILABLE")
        self.assertNotEqual(card["status"], "PASS")
        self.assertNotIn("ECOD", card["reason"])


# ═══════════════ B. valid 3-channel inference / E, F, G. really executes ═══════════════
class TestThreeChannelInference(unittest.TestCase):
    def test_valid_three_channel_reading_runs_both_detectors(self):
        s, _r, d = LAYER.evaluate(rd())
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(d["method_executed"], "ECOD+IsolationForest")
        self.assertEqual(d["valid_channels"], ["T", "P", "RH"])
        self.assertEqual(d["n_valid"], 3)
        for name in ("ecod", "isolation_forest"):
            det = d["detectors"][name]
            self.assertTrue(det["executed"], name)
            for key in ("raw_score", "evidence_score", "threshold"):
                self.assertIsNotNone(det[key], f"{name}.{key}")
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 1.0)

    def test_ecod_really_executes_spy_on_the_real_model(self):
        real = LAYER.artifacts.ecod.decision_function
        with mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=real) as spy:
            _s, _r, d = LAYER.evaluate(rd())
        self.assertEqual(spy.call_count, 1)
        self.assertTrue(d["detectors"]["ecod"]["executed"])
        # the score the layer reports is the score the real model produced
        x = np.array(list(d["features"].values())).reshape(1, -1)
        # the reported features are rounded to 4 dp for display, hence the tolerance
        self.assertAlmostEqual(d["detectors"]["ecod"]["raw_score"], float(real(x)[0]), delta=0.02)

    def test_isolation_forest_really_executes_spy_on_the_real_model(self):
        real = LAYER.artifacts.iforest.score_samples
        with mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=real) as spy:
            _s, _r, d = LAYER.evaluate(rd())
        self.assertEqual(spy.call_count, 1)
        x = np.array(list(d["features"].values())).reshape(1, -1)
        self.assertAlmostEqual(d["detectors"]["isolation_forest"]["raw_score"], float(-real(x)[0]), delta=0.01)

    def test_method_executed_matches_reality_when_models_do_not_run(self):
        cases = {
            "two channels": rd(p=None),
            "one channel": rd(p=None, rh=None),
            "unknown pressure convention": rd(source=INSITU, conv=None),
        }
        for label, reading in cases.items():
            e_spy = mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=LAYER.artifacts.ecod.decision_function)
            i_spy = mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=LAYER.artifacts.iforest.score_samples)
            with e_spy as es, i_spy as isp:
                _s, _r, d = LAYER.evaluate(reading)
            self.assertEqual(es.call_count, 0, label)
            self.assertEqual(isp.call_count, 0, label)
            self.assertFalse(d["detectors"]["ecod"]["executed"], label)
            self.assertFalse(d["detectors"]["isolation_forest"]["executed"], label)
            self.assertNotEqual(d["method_executed"], "ECOD+IsolationForest", label)

    def test_scores_are_not_exposed_for_detectors_that_did_not_run(self):
        _s, _r, d = LAYER.evaluate(rd(p=None))
        for name in ("ecod", "isolation_forest"):
            self.assertIsNone(d["detectors"][name]["raw_score"])
            self.assertIsNone(d["detectors"][name]["evidence_score"])
            self.assertIn("skip_reason", d["detectors"][name])


# ════════════════════════ C, D. two channels and insufficient data ════════════════════════
class TestChannelGating(unittest.TestCase):
    def test_two_valid_channels_are_insufficient_and_models_do_not_run(self):
        """ECOD/IF need all three channels and nothing is imputed: 2 valid channels
        is INSUFFICIENT_DATA with score 0 -- never PASS, never an ECOD claim."""
        for reading in (rd(p=None), rd(rh=None), rd(t=None)):
            s, _r, d = LAYER.evaluate(reading)
            self.assertEqual(d["status"], "INSUFFICIENT_DATA")
            self.assertEqual(s, 0.0)
            self.assertEqual(d["n_valid"], 2)
            self.assertIsNone(d["method_executed"])
            self.assertFalse(d["detectors"]["ecod"]["executed"])
            self.assertFalse(d["detectors"]["isolation_forest"]["executed"])
            self.assertIn("all 3 valid channels", d["note"])

    def test_two_channel_reading_is_reported_by_the_canonical_card_as_insufficient(self):
        c = card_of(DETECTOR.evaluate_reading(rd(p=None, station="TWOCH")))
        self.assertEqual(c["status"], "INSUFFICIENT_DATA")
        self.assertEqual(c["score"], 0.0)
        self.assertNotIn("(0 available)", c["reason"])

    def test_two_channels_can_still_trigger_the_pressure_independent_rule(self):
        s, reason, d = LAYER.evaluate(rd(t=36.0, p=None, rh=98.0))
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(d["method_executed"], "RULE_ONLY:CLAUSIUS_CLAPEYRON")
        self.assertFalse(d["detectors"]["ecod"]["executed"])
        self.assertEqual(s, 0.85)

    def test_two_channels_involving_pressure_with_unknown_convention_are_insufficient(self):
        _s, _r, d = LAYER.evaluate(rd(rh=None, source=INSITU, conv=None))     # T + P, convention UNKNOWN
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")

    def test_one_channel_is_insufficient(self):
        s, _r, d = LAYER.evaluate(rd(p=None, rh=None))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertEqual(s, 0.0)
        self.assertEqual(d["n_valid"], 1)

    def test_no_channels_is_insufficient(self):
        s, _r, d = LAYER.evaluate(rd(t=None, p=None, rh=None))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertEqual(d["n_valid"], 0)
        self.assertEqual(s, 0.0)

    def test_a_zero_substituted_pressure_is_not_a_valid_channel(self):
        _s, _r, d = LAYER.evaluate(rd(p=0.0))
        self.assertEqual(d["n_valid"], 2)
        self.assertFalse(d["detectors"]["ecod"]["executed"])


# ═════════════════ pressure convention: never guessed, never fabricated ═════════════════
class TestPressureConvention(unittest.TestCase):
    def test_the_nwp_source_alone_does_not_imply_msl(self):
        """Open-Meteo can fall back from pressure_msl to surface_pressure, so the
        source name says nothing about the convention: only a declared one counts."""
        self.assertEqual(resolve_pressure_convention(rd(source=NWP, conv=None)), ("UNKNOWN", "not_declared"))

    def test_a_declared_msl_is_accepted_for_any_source(self):
        self.assertEqual(resolve_pressure_convention(rd(source=NWP, conv="MSL")), ("MSL", "declared_on_reading"))

    def test_unknown_is_never_silently_treated_as_msl(self):
        for src in (INSITU, TEST, NWP, ObservationSource.UNKNOWN):
            conv, _b = resolve_pressure_convention(rd(source=src, conv=None))
            self.assertEqual(conv, "UNKNOWN", src)

    def test_declared_convention_wins(self):
        self.assertEqual(resolve_pressure_convention(rd(source=INSITU, conv="MSL"))[0], "MSL")
        self.assertEqual(resolve_pressure_convention(rd(source=NWP, conv="UNKNOWN"))[0], "UNKNOWN")

    def test_unknown_convention_skips_the_models_and_says_why(self):
        s, _r, d = LAYER.evaluate(rd(source=INSITU, conv=None))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertEqual(d["pressure_convention"], "UNKNOWN")
        self.assertEqual(s, 0.0)
        self.assertIn("UNKNOWN", d["skip_reason"])
        self.assertIn("not assumed to be MSL", d["skip_reason"])
        self.assertIn("Pressure convention unavailable", d["skip_reason"])

    def test_surface_pressure_without_authoritative_elevation_is_not_converted(self):
        _s, _r, d = LAYER.evaluate(rd(p=950.0, source=INSITU, conv="SURFACE", elev=None))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertNotIn("pressure_conversion", d)
        self.assertIn("no elevation is invented", d["skip_reason"])

    def test_surface_pressure_with_supplied_elevation_is_converted_and_runs(self):
        _s, _r, d = LAYER.evaluate(rd(p=948.0, source=INSITU, conv="SURFACE", elev=560.0))
        self.assertEqual(d["status"], "EVALUATED")
        self.assertTrue(d["pressure_conversion"]["applied"])
        self.assertEqual(d["pressure_conversion"]["elevation_m"], 560.0)
        self.assertGreater(d["pressure_msl_equivalent_hpa"], 1000.0)

    def test_the_layer_reports_both_conventions(self):
        _s, _r, d = LAYER.evaluate(rd())
        self.assertEqual(d["pressure_convention"], "MSL")
        self.assertEqual(d["pressure_source_convention"], "SURFACE")
        self.assertEqual(d["pressure_normalization_method"], mf.PRESSURE_NORMALIZATION_METHOD)


# ═════════════════ pressure normalisation itself ═════════════════
class TestPressureNormalization(unittest.TestCase):
    def test_conversion_at_the_proxy_returns_the_reference_pressure(self):
        for p_sfc, t in ((911.5, 22.0), (948.0, 24.0), (1008.0, 27.0), (677.0, 0.0)):
            h = mf.climatological_elevation_proxy(p_sfc, t)
            self.assertAlmostEqual(mf.surface_to_msl_equivalent(p_sfc, t, h), mf.P_REF_HPA, places=6)

    def test_zero_elevation_is_the_identity(self):
        self.assertAlmostEqual(mf.surface_to_msl_equivalent(1000.0, 25.0, 0.0), 1000.0, places=9)

    def test_higher_stations_get_larger_corrections(self):
        self.assertGreater(mf.surface_to_msl_equivalent(900.0, 20.0, 1000.0), mf.surface_to_msl_equivalent(900.0, 20.0, 500.0))

    def test_proxy_is_labelled_a_proxy_and_is_plausible(self):
        a = load_artifacts()
        blr = a.baselines.cities["Bengaluru"]
        self.assertAlmostEqual(blr.climatological_elevation_proxy, 920.0, delta=60.0)   # ~true elevation, sanity only
        doc = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "baselines.json")))
        self.assertIn("climatological_elevation_proxy", doc["conventions"]["climatological_elevation_proxy_method"])
        self.assertIn("NOT", mf.__doc__ + "")     # documented as not authoritative

    def test_reference_pressure_is_on_the_sea_level_scale_for_every_city(self):
        a = load_artifacts()
        meds = np.array([b.pressure_msl_equivalent_median for b in a.baselines.cities.values()])
        self.assertGreater(meds.min(), 1005.0)
        self.assertLess(meds.max(), 1020.0)
        raw = np.array([b.pressure_surface_median for b in a.baselines.cities.values()])
        self.assertGreater(raw.max() - raw.min(), 200.0)          # the mismatch that normalisation removes

    def test_normal_runtime_pressure_is_not_an_outlier_because_of_the_convention(self):
        """The core requirement: a normal station must not become extreme purely
        because the dataset was SURFACE pressure and the runtime is MSL."""
        a = load_artifacts()
        for latlon, p in ((PUNE, 1010.2), ((12.9716, 77.5946), 1010.5), ((17.385, 78.4867), 1008.0)):
            base, _d = a.baselines.resolve(*latlon)
            z = mf.feature_vector(29.0, p, 60.0, base)
            self.assertLess(abs(z[1]), 3.0, f"{base.name}: z_pressure {z[1]:+.2f}")
            # the un-normalised comparison would have been huge
            naive = (p - base.pressure_surface_median) / mf.robust_scale(base.pressure_surface_mad, "pressure_hpa")
            self.assertGreater(abs(naive), 3.0 * abs(z[1]) if base.name != "Mumbai" else 0.0)

    def test_scale_floor_prevents_division_by_zero(self):
        self.assertGreaterEqual(mf.robust_scale(0.0, "temperature_c"), mf.SCALE_FLOOR["temperature_c"])
        self.assertTrue(np.isfinite(mf.robust_z(5.0, 5.0, 0.0, "pressure_hpa")))

    def test_runtime_and_training_feature_vectors_are_the_same_function(self):
        a = load_artifacts()
        base = a.baselines.cities["Pune"]
        _s, _r, d = LAYER.evaluate(rd())
        expect = mf.feature_vector(29.0, 1010.6, 57.0, base)
        got = np.array(list(d["features"].values()))
        np.testing.assert_allclose(got, np.round(expect, 4), atol=1e-4)
        self.assertEqual(list(d["features"]), list(mf.FEATURE_NAMES))


# ═════════════════ I, J. city baseline vs global fallback ═════════════════
class TestBaselineScope(unittest.TestCase):
    def test_station_near_a_reference_city_uses_the_city_baseline(self):
        _s, _r, d = LAYER.evaluate(rd(latlon=PUNE))
        self.assertEqual(d["baseline_scope"], "CITY")
        self.assertEqual(d["baseline_city"], "Pune")
        self.assertLess(d["baseline_distance_km"], mf.MAX_CITY_MATCH_KM)

    def test_station_far_from_every_city_is_reported_as_global_fallback_and_not_assessed(self):
        _s, _r, d = LAYER.evaluate(rd(latlon=TOKYO))
        self.assertEqual(d["baseline_scope"], "GLOBAL_FALLBACK")
        self.assertIsNone(d["baseline_city"])
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")           # not assessed -- never PASS
        self.assertFalse(d["detectors"]["ecod"]["executed"])
        self.assertFalse(d["detectors"]["isolation_forest"]["executed"])

    def test_missing_coordinates_never_match_a_city(self):
        _s, _r, d = LAYER.evaluate(rd(latlon=(0.0, 0.0)))
        self.assertEqual(d["baseline_scope"], "GLOBAL_FALLBACK")

    def test_city_match_radius_is_enforced(self):
        a = load_artifacts()
        base, dist = a.baselines.resolve(PUNE[0] + 0.9, PUNE[1])     # ~100 km north of Pune
        # either another city is genuinely nearer, or it falls back -- never a distant wrong city
        if base.scope == "CITY":
            self.assertLessEqual(dist, mf.MAX_CITY_MATCH_KM)

    def test_city_and_global_baselines_give_different_features(self):
        a = load_artifacts()
        city = mf.feature_vector(38.0, 1010.0, 30.0, a.baselines.cities["Pune"])
        glob = mf.feature_vector(38.0, 1010.0, 30.0, a.baselines.global_baseline)
        self.assertFalse(np.allclose(city, glob))            # scopes are never silently mixed


# ═════════════════ H. thresholds are actually used ═════════════════
class TestCalibratedThresholds(unittest.TestCase):
    def test_evidence_is_half_at_the_operating_threshold(self):
        a = load_artifacts()
        for det in ("ecod", "isolation_forest"):
            an = a.anchors[det]
            self.assertAlmostEqual(float(mf.evidence_from_raw(an["threshold"], **an)), 0.5, places=6)
            self.assertEqual(float(mf.evidence_from_raw(an["center"] - 1.0, **an)), 0.0)
            self.assertEqual(float(mf.evidence_from_raw(an["extreme"] + 1.0, **an)), 1.0)

    def test_reported_evidence_is_the_calibrated_mapping_of_the_raw_score(self):
        a = load_artifacts()
        _s, _r, d = LAYER.evaluate(rd(p=1035.0))          # moderate/high evidence, exercises the mapping
        for det in ("ecod", "isolation_forest"):
            info = d["detectors"][det]
            want = float(mf.evidence_from_raw(info["raw_score"], **a.anchors[det]))
            self.assertAlmostEqual(info["evidence_score"], want, places=3)
            self.assertAlmostEqual(info["threshold"], a.anchors[det]["threshold"], places=3)

    def test_calibration_used_clean_data_only_and_is_not_a_probability(self):
        card = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "model_card.json")))
        self.assertIn("No injected anomaly", card["calibration"]["method"])
        self.assertFalse(card["combination"]["evidence_is_probability"])
        _s, _r, d = LAYER.evaluate(rd())
        self.assertFalse(d["evidence_is_probability"])

    def test_clean_false_positive_rate_on_the_untouched_test_period_is_documented_and_small(self):
        card = json.load(open(os.path.join(DEFAULT_ARTIFACT_DIR, "model_card.json")))
        fpr = card["clean_false_positive_rate"]["on_test_2021_2026"]["combined"][">=0.5"]
        self.assertLess(fpr, 0.02)

    def test_combined_score_is_the_documented_maximum(self):
        _s, _r, d = LAYER.evaluate(rd(p=1035.0))
        e, i = d["detectors"]["ecod"]["evidence_score"], d["detectors"]["isolation_forest"]["evidence_score"]
        self.assertAlmostEqual(d["combined_score"], max(e, i), places=3)
        self.assertIn(d["score_driver"], ("ecod", "isolation_forest"))


# ═════════════════ Stage 4: the models are only applied inside their trained scope ═════════════════
# The exact readings from the Stage 3 verification that scored as anomalous against the
# India-pooled fallback baseline although the weather was ordinary.
POINT_COOK = dict(t=11.5, p=1034.3, rh=61.0, latlon=(-37.9, 144.7))
BURRA = dict(t=9.8, p=1031.9, rh=90.0, latlon=(-33.7, 138.9))
WHITEHORSE = dict(t=-2.8, p=1012.3, rh=92.0, latlon=(60.5, -135.1))
NON_INDIAN = {"Point Cook": POINT_COOK, "Burra": BURRA, "Whitehorse": WHITEHORSE}


def _far(name):
    c = NON_INDIAN[name]
    return rd(t=c["t"], p=c["p"], rh=c["rh"], latlon=c["latlon"], station=f"FAR-{name}")


class TestGlobalFallbackScope(unittest.TestCase):
    def test_city_baseline_executes_ecod_and_isolation_forest(self):
        e = mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=LAYER.artifacts.ecod.decision_function)
        i = mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=LAYER.artifacts.iforest.score_samples)
        with e as es, i as isp:
            _s, _r, d = LAYER.evaluate(rd(latlon=PUNE))
        self.assertEqual((es.call_count, isp.call_count), (1, 1))
        self.assertEqual(d["baseline_scope"], "CITY")
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(d["method_executed"], "ECOD+IsolationForest")

    def test_global_fallback_blocks_inference_and_never_calls_the_models(self):
        e = mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=LAYER.artifacts.ecod.decision_function)
        i = mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=LAYER.artifacts.iforest.score_samples)
        for label, reading in (("Tokyo", rd(latlon=TOKYO)), ("no coordinates", rd(latlon=(0.0, 0.0))),
                               ("Point Cook", _far("Point Cook"))):
            with e as es, i as isp:
                s, _r, d = LAYER.evaluate(reading)
            self.assertEqual((es.call_count, isp.call_count), (0, 0), label)
            self.assertEqual(d["baseline_scope"], "GLOBAL_FALLBACK", label)
            self.assertEqual(d["status"], "INSUFFICIENT_DATA", label)
            self.assertEqual(s, 0.0, label)

    def test_the_stage3_false_positive_stations_are_not_assessed_by_the_india_trained_model(self):
        for name in NON_INDIAN:
            card = card_of(DETECTOR.evaluate_reading(_far(name)))
            self.assertEqual(card["status"], "INSUFFICIENT_DATA", name)
            self.assertNotIn(card["status"], ("PASS", "WARNING", "ANOMALY"), name)
            self.assertEqual(card["score"], 0.0, name)
            self.assertFalse(card["details"]["detectors"]["ecod"]["executed"], name)
            self.assertFalse(card["details"]["detectors"]["isolation_forest"]["executed"], name)
            self.assertIn("Multivariate not assessed", card["reason"], name)

    def test_why_the_gate_exists_the_indian_fallback_really_scored_ordinary_weather_as_unusual(self):
        """Documents the Stage 3 finding: scoring Point Cook against the pooled fallback
        baseline (the behaviour the gate now prevents) gave an anomalous ECOD evidence."""
        a = load_artifacts()
        z = mf.feature_vector(POINT_COOK["t"], POINT_COOK["p"], POINT_COOK["rh"], a.baselines.global_baseline)
        raw = float(ecod_single_row_scores(a.ecod, z[None, :])[0])
        self.assertGreaterEqual(float(mf.evidence_from_raw(raw, **a.anchors["ecod"])), 0.75)

    def test_unavailable_multivariate_is_excluded_from_fusion_not_treated_as_normal(self):
        det = AnomalyDetector()
        with mock.patch.object(det.fusion, "fuse", wraps=det.fusion.fuse) as spy:
            city = det.evaluate_reading(rd(latlon=PUNE, station="FUS-CITY"))
            city_kw = spy.call_args.kwargs
            far = det.evaluate_reading(_far("Point Cook"))
            far_kw = spy.call_args.kwargs
        self.assertTrue(city_kw["layer_availability"]["multivariate"]["available"])
        self.assertFalse(far_kw["layer_availability"]["multivariate"]["available"])
        self.assertFalse(far.canonical_result["evidence_availability"]["multivariate"]["available"])
        # the same three layers otherwise: one fewer layer is available and evidence is less sufficient
        cf, ff = city.layer_details["fusion"], far.layer_details["fusion"]
        self.assertEqual(ff["available_layer_count"], cf["available_layer_count"] - 1)
        self.assertLess(ff["evidence_sufficiency"], cf["evidence_sufficiency"])
        self.assertEqual(far.status, "NORMAL")

    def test_unknown_pressure_convention_is_still_blocked_first_with_its_own_reason(self):
        for reading in (rd(latlon=PUNE, conv=None, source=INSITU), rd(latlon=TOKYO, conv=None, source=INSITU)):
            _s, _r, d = LAYER.evaluate(reading)
            self.assertEqual(d["status"], "INSUFFICIENT_DATA")
            self.assertEqual(d["pressure_convention"], "UNKNOWN")
            self.assertIn("Pressure convention unavailable", d["skip_reason"])
            self.assertNotIn("Multivariate not assessed", d["skip_reason"])
            self.assertIsNone(d["baseline_scope"])                 # never reached baseline selection

    def test_channel_gating_is_unchanged_inside_and_outside_scope(self):
        for latlon in (PUNE, TOKYO):
            for reading, n in ((rd(latlon=latlon, p=None), 2), (rd(latlon=latlon, p=None, rh=None), 1)):
                _s, _r, d = LAYER.evaluate(reading)
                self.assertEqual(d["status"], "INSUFFICIENT_DATA")
                self.assertEqual(d["n_valid"], n)
                self.assertIn("valid channel", d["note"])

    def test_the_api_flags_are_truthful_for_a_fallback_station(self):
        d = card_of(DETECTOR.evaluate_reading(_far("Whitehorse")))["details"]
        self.assertEqual(d["baseline_scope"], "GLOBAL_FALLBACK")
        self.assertEqual(d["pressure_convention"], "MSL")            # the pressure is fine; the SCOPE is not
        for name in ("ecod", "isolation_forest"):
            det = d["detectors"][name]
            self.assertFalse(det["executed"])
            self.assertIsNone(det["raw_score"])
            self.assertIsNone(det["evidence_score"])
            self.assertIn("Multivariate not assessed", det["skip_reason"])
        for key in ("method_executed", "combined_score", "final_score", "score_driver", "features"):
            self.assertIsNone(d.get(key), key)

    def test_method_executed_is_null_whenever_no_detector_executes(self):
        cases = {"global fallback": rd(latlon=TOKYO), "unknown pressure": rd(source=INSITU, conv=None),
                 "two channels": rd(p=None), "one channel": rd(p=None, rh=None), "no channels": rd(t=None, p=None, rh=None)}
        for label, reading in cases.items():
            s, _r, d = LAYER.evaluate(reading)
            self.assertIsNone(d["method_executed"], label)
            self.assertFalse(d["detectors"]["ecod"]["executed"], label)
            self.assertFalse(d["detectors"]["isolation_forest"]["executed"], label)
            self.assertEqual(s, 0.0, label)

    def test_a_supported_city_result_is_unchanged_by_the_scope_gate(self):
        """Golden values captured BEFORE the gate existed (Pune, MSL)."""
        for t, p, rh, want in ((29.0, 1010.6, 57.0, 0.0), (29.0, 1040.0, 57.0, 0.6964), (44.0, 985.0, 100.0, 1.0)):
            s, _r, d = LAYER.evaluate(rd(t=t, p=p, rh=rh, latlon=PUNE))
            self.assertAlmostEqual(s, want, places=4)
            self.assertEqual(d["baseline_scope"], "CITY")

    def test_the_pressure_independent_rule_is_unaffected_and_still_labelled_as_a_rule(self):
        """The Clausius-Clapeyron rule is not the trained model. Where it fires it is reported as
        RULE_ONLY (no detector ran) with the fallback scope visible."""
        s, _r, d = LAYER.evaluate(rd(t=36.0, p=1010.0, rh=98.0, latlon=TOKYO))
        self.assertEqual(d["method_executed"], "RULE_ONLY:CLAUSIUS_CLAPEYRON")
        self.assertEqual(d["baseline_scope"], "GLOBAL_FALLBACK")
        self.assertIsNone(d["combined_score"])
        self.assertEqual(d["score_driver"], "rule:clausius_clapeyron")
        self.assertFalse(d["detectors"]["ecod"]["executed"])


# ═════════════════ detector evidence is never confused with rule evidence ═════════════════
class TestDetectorVersusRuleEvidence(unittest.TestCase):
    """The layer combines ECOD/Isolation Forest evidence with one deterministic
    rule (Clausius-Clapeyron). The API must let a consumer tell them apart."""

    def test_rule_only_result_has_no_detector_combination(self):
        """No model ran, so `combined_score` (the ECOD/IF combination) must be None;
        the rule evidence lives in the rule block / final_score / score_driver."""
        for reading in (rd(t=36.0, p=1012.0, rh=98.0, source=INSITU, conv=None),       # UNKNOWN convention
                        rd(t=36.0, p=None, rh=98.0)):                                   # only 2 channels
            s, _r, d = LAYER.evaluate(reading)
            self.assertEqual(d["method_executed"], "RULE_ONLY:CLAUSIUS_CLAPEYRON")
            self.assertFalse(d["detectors"]["ecod"]["executed"])
            self.assertFalse(d["detectors"]["isolation_forest"]["executed"])
            self.assertIsNone(d["combined_score"], "rule evidence must not be reported as a detector combination")
            self.assertEqual(d["final_score"], 0.85)
            self.assertEqual(d["rules"]["clausius_clapeyron"]["score"], 0.85)
            self.assertEqual(d["score_driver"], "rule:clausius_clapeyron")
            self.assertEqual(s, 0.85)

    def test_rule_can_drive_the_score_while_both_detectors_report_zero(self):
        """Test Lab MULTIVARIATE_INCONSISTENCY: ECOD and IF ran and each gave 0.0 evidence;
        the 0.85 is the deterministic rule. The API must say so."""
        from app.simulation.service import run_simulation
        d = run_simulation("MULTIVARIATE_INCONSISTENCY")["diagnostics"]["multivariate"]
        det = d["details"]
        self.assertEqual(det["detectors"]["ecod"]["evidence_score"], 0.0)
        self.assertEqual(det["detectors"]["isolation_forest"]["evidence_score"], 0.0)
        self.assertEqual(det["combined_score"], 0.0)                 # detector evidence only
        self.assertEqual(det["rules"]["clausius_clapeyron"]["score"], 0.85)
        self.assertEqual(det["final_score"], 0.85)                   # what the layer reports
        self.assertEqual(d["score"], 0.85)
        self.assertEqual(det["score_driver"], "rule:clausius_clapeyron")
        self.assertTrue(det["detectors"]["ecod"]["executed"] and det["detectors"]["isolation_forest"]["executed"])

    def test_final_score_is_the_maximum_of_detector_and_rule_evidence(self):
        for reading in (rd(), rd(p=1035.0), rd(t=44.0, p=985.0, rh=100.0), rd(t=36.0, p=1010.0, rh=98.0)):
            s, _r, d = LAYER.evaluate(reading)
            rule = d["rules"]["clausius_clapeyron"]["score"] if d["rules"]["clausius_clapeyron"]["triggered"] else 0.0
            self.assertAlmostEqual(d["final_score"], max(d["combined_score"], rule), places=3)
            self.assertAlmostEqual(s, d["final_score"], places=3)

    def test_no_driver_is_named_when_nothing_produced_the_score(self):
        s, _r, d = LAYER.evaluate(rd())                                        # everything 0.0
        self.assertEqual(s, 0.0)
        self.assertEqual(d["combined_score"], 0.0)
        self.assertIsNone(d["score_driver"])

    def test_driver_names_the_detector_that_actually_produced_the_evidence(self):
        _s, _r, d = LAYER.evaluate(rd(p=1045.0))
        e, i = d["detectors"]["ecod"]["evidence_score"], d["detectors"]["isolation_forest"]["evidence_score"]
        self.assertGreater(d["final_score"], 0.0)
        self.assertEqual(d["score_driver"], "ecod" if e > i else "isolation_forest" if i > e else "ecod+isolation_forest")

    def test_when_no_detector_ran_and_no_rule_fired_nothing_is_reported_as_evidence(self):
        for reading in (rd(source=INSITU, conv=None), rd(p=None), rd(p=None, rh=None)):
            s, _r, d = LAYER.evaluate(reading)
            self.assertEqual(d["status"], "INSUFFICIENT_DATA")
            self.assertEqual(s, 0.0)
            self.assertIsNone(d["combined_score"])
            self.assertIsNone(d["final_score"])
            self.assertIsNone(d["score_driver"])


# ═════════════════ K. deterministic inference ═════════════════
class TestDeterminism(unittest.TestCase):
    def test_identical_readings_give_identical_results(self):
        r = rd(t=33.0, p=1004.0, rh=70.0)
        a = LAYER.evaluate(r)
        b = LAYER.evaluate(r)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[2]["detectors"], b[2]["detectors"])
        self.assertEqual(a[2]["features"], b[2]["features"])

    def test_two_independent_layers_agree(self):
        other = MultivariateConsistencyLayer()
        r = rd(t=33.0, p=1004.0, rh=70.0)
        self.assertEqual(LAYER.evaluate(r)[0], other.evaluate(r)[0])

    def test_single_row_ecod_closed_form_equals_the_library(self):
        """The calibration fast path must be exactly PyOD's own single-row result."""
        a = load_artifacts()
        rng = np.random.default_rng(0)
        X = rng.normal(0, 1.5, size=(12, 3))
        fast = ecod_single_row_scores(a.ecod, X)
        real = np.array([a.ecod.decision_function(X[i:i + 1])[0] for i in range(len(X))])
        np.testing.assert_allclose(fast, real, atol=1e-8)


# ═════════════════ L, M. anomaly vs normal scenarios (through the full detector) ═════════════════
class TestScenarios(unittest.TestCase):
    def test_normal_observation_is_not_flagged(self):
        a = DETECTOR.evaluate_reading(rd(station="NORM1"))
        c = card_of(a)
        self.assertEqual(c["status"], "PASS")
        self.assertLess(c["score"], 0.5)

    def test_large_pressure_offset_is_flagged_by_the_joint_detectors(self):
        a = DETECTOR.evaluate_reading(rd(p=1045.0, station="ANOM1"))
        c = card_of(a)
        self.assertGreaterEqual(c["score"], 0.5)
        self.assertIn(c["status"], ("WARNING", "ANOMALY"))
        self.assertEqual(c["details"]["method_executed"], "ECOD+IsolationForest")

    def test_extreme_joint_state_is_an_anomaly(self):
        # hot + very low pressure + saturated: outside the reference envelope on several axes at once
        a = DETECTOR.evaluate_reading(rd(t=44.0, p=985.0, rh=100.0, station="ANOM2"))
        c = card_of(a)
        self.assertEqual(c["status"], "ANOMALY")
        self.assertGreaterEqual(c["score"], 0.75)
        d = c["details"]["detectors"]
        self.assertTrue(d["ecod"]["executed"] and d["isolation_forest"]["executed"])

    def test_clausius_clapeyron_rule_is_reported_separately_from_the_models(self):
        _s, reason, d = LAYER.evaluate(rd(t=36.0, p=1010.0, rh=98.0, source=INSITU, conv=None))    # convention UNKNOWN
        self.assertEqual(d["method_executed"], "RULE_ONLY:CLAUSIUS_CLAPEYRON")
        self.assertFalse(d["detectors"]["ecod"]["executed"])
        self.assertTrue(d["rules"]["clausius_clapeyron"]["triggered"])
        self.assertIn("saturation", reason)

    def test_multivariate_evidence_is_not_a_replacement_for_physics(self):
        # a physically impossible humidity is a PHYSICS veto; the layers report independently
        a = DETECTOR.evaluate_reading(rd(rh=135.0, station="PHYS1"))
        self.assertTrue(a.veto_fired)


# ═════════════════ N, O, P. canonical API consistency ═════════════════
class TestCanonicalApi(unittest.TestCase):
    def test_card_details_expose_what_actually_happened(self):
        d = card_of(DETECTOR.evaluate_reading(rd(station="API1")))["details"]
        for key in ("method_executed", "baseline_scope", "pressure_convention", "pressure_normalization_method",
                    "valid_channels", "n_valid", "valid_channel_count", "detectors", "combined_score",
                    "features", "model_version"):
            self.assertIn(key, d, key)
        self.assertEqual(d["n_valid"], d["valid_channel_count"])

    def test_never_reports_zero_available_for_valid_channels(self):
        for reading in (rd(station="Z1"), rd(source=INSITU, conv=None, station="Z2"), rd(p=None, station="Z3")):
            c = card_of(DETECTOR.evaluate_reading(reading))
            self.assertNotIn("(0 available)", c["reason"])
            self.assertEqual(c["details"]["n_valid"], c["details"]["valid_channel_count"])
            self.assertGreaterEqual(c["details"]["n_valid"], 2)

    def test_unknown_convention_reason_is_not_the_channel_count_message(self):
        c = card_of(DETECTOR.evaluate_reading(rd(source=INSITU, conv=None, station="UNK1")))
        self.assertEqual(c["status"], "INSUFFICIENT_DATA")
        self.assertNotIn("requires ≥2 valid channels", c["reason"])
        self.assertIn("UNKNOWN", c["reason"])

    def test_card_status_and_score_are_always_consistent(self):
        readings = [rd(station="S1"), rd(p=1045.0, station="S2"), rd(t=44.0, p=985.0, rh=100.0, station="S3"),
                    rd(source=INSITU, conv=None, station="S4"), rd(p=None, rh=None, station="S5"), rd(p=None, station="S6")]
        for r in readings:
            c = card_of(DETECTOR.evaluate_reading(r))
            self.assertGreaterEqual(c["score"], 0.0)
            self.assertLessEqual(c["score"], 1.0)
            if c["status"] == "INSUFFICIENT_DATA":
                self.assertEqual(c["score"], 0.0, "INSUFFICIENT_DATA must never carry a score")
            elif c["status"] == "ANOMALY":
                self.assertGreaterEqual(c["score"], 0.75)
            elif c["status"] == "WARNING":
                self.assertGreaterEqual(c["score"], 0.5)
                self.assertLess(c["score"], 0.75)
            elif c["status"] == "PASS":
                self.assertLess(c["score"], 0.5)

    def test_insufficient_data_is_never_reported_as_pass(self):
        for r in (rd(source=INSITU, conv=None, station="I1"), rd(p=None, rh=None, station="I2"), rd(t=None, p=None, rh=None, station="I3")):
            self.assertNotEqual(card_of(DETECTOR.evaluate_reading(r))["status"], "PASS")

    def test_evidence_availability_reflects_whether_the_models_ran(self):
        ran = DETECTOR.evaluate_reading(rd(station="AV1")).canonical_result["evidence_availability"]["multivariate"]
        skipped = DETECTOR.evaluate_reading(rd(source=INSITU, conv=None, station="AV2")).canonical_result["evidence_availability"]["multivariate"]
        self.assertTrue(ran["available"])
        self.assertFalse(skipped["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
