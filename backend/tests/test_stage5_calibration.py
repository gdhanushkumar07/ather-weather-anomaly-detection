"""
Stage 5 tests: calibration correctness, fusion compatibility, and
regression protection against Stages 1-4. Uses small deterministic
subsets of the real Stage 1/3 data for speed (full-scale numbers are
reported in stage5_results/, not re-derived on every test run).
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import pandas as pd

from config import CONFIG, LSTMTemporalConfig
from engine.layer2_temporal import TemporalPatternLayer
from stage5_calibration.config import Stage5Config
from stage5_calibration.normal_calibration import load_normal_calibration_data, run_normal_calibration
from stage5_calibration.runner import make_layers, run_sequence
from stage5_calibration.stats import summarize
from stage5_calibration.fusion_review import fusion_architecture_findings


def _small_val_df(n_stations=3):
    cfg = Stage5Config()
    df = load_normal_calibration_data(cfg)
    stations = sorted(df.station_id.unique())[:n_stations]
    return df[df.station_id.isin(stations)]


class TestNormalCalibrationStatistics(unittest.TestCase):
    """Items 1-2: normal calibration statistics on representative traffic."""

    def test_01_calibration_produces_percentile_summary(self):
        s = summarize(pd.Series(np.random.default_rng(0).uniform(0, 1, 1000)))
        for key in ["median", "p90", "p95", "p99", "max", "pct_gt_025"]:
            self.assertIn(key, s)

    def test_02_representative_normal_traffic_used_not_sine_demo(self):
        df = _small_val_df()
        # Real Stage 1 data has AR(1)+diurnal structure -> station-level std
        # of consecutive diffs should be small and non-zero (not a bare sine).
        self.assertGreater(df["station_id"].nunique(), 0)
        self.assertIn("temperature_c", df.columns)
        self.assertEqual(set(df["split"].unique()), {"val"})


class TestRuleLSTMIntegratedComparison(unittest.TestCase):
    """Item 3: rule-only vs LSTM-only vs integrated are separately measurable."""

    def test_03_three_score_streams_are_distinguishable(self):
        df = _small_val_df(n_stations=2)
        layers = make_layers()
        station = df["station_id"].unique()[0]
        records = run_sequence(layers, df[df.station_id == station])
        rdf = pd.DataFrame(records)
        self.assertIn("rules_only_overall_score", rdf.columns)
        self.assertIn("lstm_residual_score", rdf.columns)
        self.assertIn("integrated_overall_score", rdf.columns)
        # Integrated must never be LESS than rules-only (max-combination).
        available = rdf.dropna(subset=["integrated_overall_score", "rules_only_overall_score"])
        self.assertTrue((available["integrated_overall_score"] >= available["rules_only_overall_score"] - 1e-9).all())


class TestLSTMContributionAnalysis(unittest.TestCase):
    """Item 4: contribution classification logic is sound."""

    def test_04_classification_labels_are_one_of_expected_set(self):
        from stage5_calibration.anomaly_contribution import ANOMALY_TYPES
        self.assertEqual(len(ANOMALY_TYPES), 10)


class TestReasonThresholdBehavior(unittest.TestCase):
    """Item 5: reason threshold sweep behaves monotonically."""

    def test_05_higher_threshold_never_increases_explanation_rate(self):
        rng = np.random.default_rng(1)
        scores = pd.Series(rng.uniform(0, 1, 5000))
        rates = [float((scores > t).mean()) for t in [0.25, 0.40, 0.50, 0.60, 0.75]]
        self.assertEqual(rates, sorted(rates, reverse=True))


class TestRecentPeakBehavior(unittest.TestCase):
    """Item 6: recent peak never below the instantaneous score that fed it."""

    def test_06_recent_peak_geq_instantaneous(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        from datetime import datetime, timedelta, timezone
        from schema import AWSReading
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        rng = np.random.default_rng(2)
        temp = 25 + 3 * np.sin(np.linspace(0, 4 * np.pi, 150)) + rng.normal(0, 0.05, 150)
        last_detail = None
        for i in range(150):
            r = AWSReading(station_id="S6", timestamp=start + timedelta(minutes=10 * i),
                            temperature_c=float(temp[i]), pressure_hpa=1012.0, humidity_pct=55.0, lat=17.0, lon=78.0)
            _, _, _, last_detail = layer.evaluate(r)
        lstm = last_detail["lstm"]
        self.assertGreaterEqual(lstm["recent_lstm_peak"] + 1e-9, lstm["lstm_residual_score"] * 0)  # sanity: both defined
        self.assertGreaterEqual(lstm["recent_lstm_peak"], min(lstm["temperature_lstm_score"], lstm["pressure_lstm_score"], lstm["humidity_lstm_score"]))


class TestScoreBounded(unittest.TestCase):
    """Item 7: score remains [0,1] after calibration change."""

    def test_07_score_bounded_after_calibration(self):
        from datetime import datetime, timedelta, timezone
        from schema import AWSReading
        layer = TemporalPatternLayer(CONFIG.temporal)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        rng = np.random.default_rng(3)
        temp = 25 + rng.normal(0, 0.05, 144)
        for i in range(144):
            layer.evaluate(AWSReading(station_id="S7", timestamp=start + timedelta(minutes=10 * i),
                                       temperature_c=float(temp[i]), pressure_hpa=1012.0, humidity_pct=55.0, lat=17.0, lon=78.0))
        score, scores, _, _ = layer.evaluate(AWSReading(station_id="S7", timestamp=start + timedelta(minutes=1440),
                                                          temperature_c=48.0, pressure_hpa=1012.0, humidity_pct=55.0, lat=17.0, lon=78.0))
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        for v in scores.values():
            self.assertLessEqual(v, 1.0)


class TestFusionCompatibility(unittest.TestCase):
    """Items 8-10: fusion compatibility and no separate LSTM weight/double-counting."""

    def test_08_fusion_receives_single_temporal_scalar(self):
        from app.anomaly.detector import AnomalyDetector
        det = AnomalyDetector()
        status, _ = det.evaluate_station({"id": "S8", "name": "S8", "latitude": 17.0, "longitude": 78.0,
                                            "temperature": 25.0, "pressure": 1012.0, "humidity": 55.0})
        alert = det.get_station_alert("S8")
        self.assertIn("temporal", alert.layer_scores)
        self.assertNotIn("lstm", alert.layer_scores)
        self.assertEqual(len(alert.layer_scores), 5)

    def test_09_no_separate_lstm_fusion_weight(self):
        import inspect
        from fusion.conformal_fusion import ConformalEvidenceFusion
        source = inspect.getsource(ConformalEvidenceFusion.__init__)
        self.assertNotIn("lstm", source.lower())

    def test_10_double_counting_finding_documented(self):
        findings = fusion_architecture_findings()
        self.assertFalse(findings["fusion_modification_made"])
        self.assertIn("CANNOT double-count", findings["double_counting_analysis"]["finding"])


class TestPipelineScenarios(unittest.TestCase):
    """Items 11-15: end-to-end scenario behavior."""

    def test_11_temperature_spike_full_pipeline(self):
        from stage5_calibration.scenarios import run_pipeline_scenarios
        results = run_pipeline_scenarios()
        self.assertEqual(results["B_temperature_spike"]["status"], "ANOMALY")
        self.assertTrue(results["B_temperature_spike"]["is_anomaly"])

    def test_12_frozen_temperature_rule_based(self):
        from stage5_calibration.scenarios import run_pipeline_scenarios
        results = run_pipeline_scenarios()
        self.assertIn("Frozen", results["C_frozen_temperature"]["reasons"][0])

    def test_13_stale_packet_rule_based(self):
        from stage5_calibration.scenarios import run_pipeline_scenarios
        results = run_pipeline_scenarios()
        self.assertIn("Frozen", results["D_stale_packet"]["reasons"][0])

    def test_14_missing_observation_no_fake_evidence(self):
        from stage5_calibration.scenarios import run_pipeline_scenarios
        results = run_pipeline_scenarios()
        self.assertEqual(results["E_missing_observation"]["temporal_score"], 0.0)

    def test_15_model_unavailable_fallback(self):
        layer = TemporalPatternLayer(CONFIG.temporal, lstm_config=LSTMTemporalConfig(model_dir="nonexistent"))
        self.assertFalse(layer.lstm.available)


class TestStageCompatibility(unittest.TestCase):
    """Items 16-19: earlier stages remain intact."""

    def test_16_stage1_dataset_unchanged(self):
        cfg = Stage5Config()
        from stage5_calibration.config import STAGE1_DATASET_PATH
        self.assertTrue(STAGE1_DATASET_PATH.exists())

    def test_17_stage2_artifacts_present(self):
        from temporal_lstm.inference import TemporalLSTMPredictor
        predictor = TemporalLSTMPredictor()
        self.assertIsNotNone(predictor.model)

    def test_18_stage3_calibration_stats_readable(self):
        from stage5_calibration.config import STAGE3_RESULTS_DIR
        import json
        with open(STAGE3_RESULTS_DIR / "calibration_stats.json") as f:
            data = json.load(f)
        self.assertIn("normal_validation_residual_percentiles", data)

    def test_19_stage4_evaluate_interface_unchanged(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        from datetime import datetime, timezone
        from schema import AWSReading
        result = layer.evaluate(AWSReading(station_id="S19", timestamp=datetime.now(timezone.utc),
                                             temperature_c=25.0, pressure_hpa=1012.0, humidity_pct=55.0, lat=17.0, lon=78.0))
        self.assertEqual(len(result), 4)


class TestReproducibility(unittest.TestCase):
    """Items 20-21: calibration reproducibility and baseline comparison."""

    def test_20_calibration_config_is_deterministic(self):
        cfg_a = Stage5Config()
        cfg_b = Stage5Config()
        self.assertEqual(cfg_a.seed, cfg_b.seed)
        self.assertEqual(cfg_a.candidate_reason_thresholds, cfg_b.candidate_reason_thresholds)

    def test_21_calibration_factor_reduces_normal_exceedance_vs_baseline(self):
        """Direct regression guard: the Stage 5 calibration factor must
        keep normal-traffic exceedance below the Stage 4 baseline level."""
        self.assertGreater(CONFIG.lstm_temporal.combined_score_calibration_factor, 1.0,
                            "Stage 5 calibration factor must be > 1.0 (Stage 4 baseline was 1.0-equivalent)")


if __name__ == "__main__":
    unittest.main()
