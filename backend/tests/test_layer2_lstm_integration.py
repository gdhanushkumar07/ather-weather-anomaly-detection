"""
Stage 4 tests: LSTM temporal-prediction evidence integrated into the
PRODUCTION TemporalPatternLayer (engine/layer2_temporal.py).

These tests use the REAL trained Stage 2/3 artifacts (read-only) — no
mocking of the model — since the whole point of Stage 4 is verifying the
real integration behaves correctly, degrades gracefully, and never
overrides the pre-existing rule-based checks.
"""
import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np

from config import CONFIG, LSTMTemporalConfig
from schema import AWSReading
from engine.layer2_temporal import TemporalPatternLayer, StationTemporalBuffer
from engine.lstm_temporal import LSTMTemporalEvidence
from app.anomaly.detector import AnomalyDetector

STATION_ID = "STAGE4-TEST-STATION"
START = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _reading(step: int, temp, press, rh, station_id: str = STATION_ID) -> AWSReading:
    ts = START + timedelta(minutes=10 * step)
    return AWSReading(
        station_id=station_id, timestamp=ts,
        temperature_c=temp, pressure_hpa=press, humidity_pct=rh,
        lat=17.0, lon=78.0,
    )


def _normal_series(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    temp = 25.0 + 3.0 * np.sin(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.05, n)
    press = 1012.0 + rng.normal(0, 0.05, n)
    rh = 55.0 + 5.0 * np.cos(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.1, n)
    return temp, press, rh


def _feed_normal_history(layer: TemporalPatternLayer, n: int, station_id: str = STATION_ID, seed: int = 0):
    """Feeds n normal readings and returns the last evaluate() result."""
    temp, press, rh = _normal_series(n, seed=seed)
    result = None
    for i in range(n):
        r = _reading(i, float(temp[i]), float(press[i]), float(rh[i]), station_id=station_id)
        result = layer.evaluate(r)
    return result


class TestLSTMArtifactLoading(unittest.TestCase):
    """Items 2-4: model/scaler/calibration load successfully."""

    def test_02_lstm_model_loads_successfully(self):
        evidence = LSTMTemporalEvidence(CONFIG.lstm_temporal)
        self.assertTrue(evidence.available, f"LSTM should load; load_error={evidence.load_error}")

    def test_03_lstm_scaler_loads_successfully(self):
        evidence = LSTMTemporalEvidence(CONFIG.lstm_temporal)
        self.assertIsNotNone(evidence.predictor.scaler)

    def test_04_calibration_statistics_load_successfully(self):
        evidence = LSTMTemporalEvidence(CONFIG.lstm_temporal)
        for ch in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
            self.assertIn("p99", evidence.calibration[ch])
            self.assertGreater(evidence.calibration[ch]["p99"], 0)


class TestModelLoadedOnce(unittest.TestCase):
    """Item 5: model is loaded once per layer instance, not per reading."""

    def test_05_model_instance_stable_across_multiple_evaluations(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        predictor_id_before = id(layer.lstm.predictor)
        _feed_normal_history(layer, 10)
        predictor_id_after = id(layer.lstm.predictor)
        self.assertEqual(predictor_id_before, predictor_id_after)


class TestWarmupBehavior(unittest.TestCase):
    """Items 6-7, and spec section 19 (warm-up)."""

    def test_06_fewer_than_144_readings_does_not_run_lstm(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        result = _feed_normal_history(layer, 100)
        _, _, _, detail = result
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")

    def test_07_144_valid_readings_enables_lstm(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        result = _feed_normal_history(layer, 145)  # 144 build history, 145th can be predicted
        _, _, _, detail = result
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_19b_warmup_does_not_mark_station_anomalous(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        result = _feed_normal_history(layer, 100)
        score, _, reason, _ = result
        self.assertLess(score, 0.5)


class TestLSTMPredictionAndResiduals(unittest.TestCase):
    """Items 8-12: prediction output, residual math, signed residual, bounded score."""

    def setUp(self):
        self.layer = TemporalPatternLayer(CONFIG.temporal)
        _feed_normal_history(self.layer, 144, seed=1)

    def test_08_three_channel_prediction_output(self):
        r = _reading(144, 25.0, 1012.0, 55.0)
        _, _, _, detail = self.layer.evaluate(r)
        lstm = detail["lstm"]
        self.assertTrue(lstm["lstm_available"])
        for key in ["lstm_predicted_temperature_c", "lstm_predicted_pressure_hpa", "lstm_predicted_humidity_pct"]:
            self.assertIsInstance(lstm[key], float)

    def test_09_residual_equals_actual_minus_predicted(self):
        r = _reading(144, 40.0, 1012.0, 55.0)  # deliberately far from expected
        _, _, _, detail = self.layer.evaluate(r)
        lstm = detail["lstm"]
        expected_residual = 40.0 - lstm["lstm_predicted_temperature_c"]
        self.assertAlmostEqual(lstm["temperature_residual"], expected_residual, places=4)

    def test_10_signed_residual_preserved(self):
        r = _reading(144, 5.0, 1012.0, 55.0)  # far BELOW expected -> negative residual
        _, _, _, detail = self.layer.evaluate(r)
        self.assertLess(detail["lstm"]["temperature_residual"], 0)

    def test_11_absolute_residual_correct(self):
        r = _reading(144, 5.0, 1012.0, 55.0)
        _, _, _, detail = self.layer.evaluate(r)
        lstm = detail["lstm"]
        self.assertAlmostEqual(lstm["temperature_abs_residual"], abs(lstm["temperature_residual"]), places=6)

    def test_12_score_bounded_0_1_even_for_extreme_residual(self):
        r = _reading(144, 45.0, 1012.0, 55.0)  # ~15-20C jump, many multiples of P99
        overall_score, scores, _, detail = self.layer.evaluate(r)
        self.assertLessEqual(overall_score, 1.0)
        self.assertGreaterEqual(overall_score, 0.0)
        for v in scores.values():
            self.assertLessEqual(v, 1.0)
        # The RAW (unclipped) score in detail is allowed to exceed 1.0 —
        # that's the explainability value, not the combined channel score.
        self.assertGreaterEqual(detail["lstm"]["temperature_lstm_raw_score"], 1.0)


class TestRuleBasedChecksUnaffected(unittest.TestCase):
    """Items 13-16: existing rule-based checks still fire and are not
    weakened by the LSTM merge."""

    def test_13_frozen_temperature_still_detected(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        temp, press, rh = _normal_series(30, seed=2)
        for i in range(30):
            layer.evaluate(_reading(i, float(temp[i]), float(press[i]), float(rh[i])))
        frozen_val = 25.0
        result = None
        for i in range(30, 30 + 14):
            result = layer.evaluate(_reading(i, frozen_val, 1012.0, 55.0))
        _, scores, reason, detail = result
        self.assertGreaterEqual(scores["temperature_c"], 0.9)
        self.assertIn("Frozen", reason)

    def test_14_rate_of_change_spike_still_detected(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        temp, press, rh = _normal_series(10, seed=3)
        for i in range(10):
            layer.evaluate(_reading(i, float(temp[i]), float(press[i]), float(rh[i])))
        _, scores, reason, _ = layer.evaluate(_reading(10, float(temp[-1]) + 20.0, float(press[-1]), float(rh[-1])))
        self.assertGreater(scores["temperature_c"], 0.5)
        self.assertIn("Abrupt", reason)

    def test_15_rolling_zscore_still_detected(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        rng = np.random.default_rng(4)
        for i in range(30):
            v = 25.0 + rng.normal(0, 0.1)
            layer.evaluate(_reading(i, v, 1012.0, 55.0))
        # A value inside the step-rate bound but far outside the tight rolling MAD.
        _, scores, reason, detail = layer.evaluate(_reading(30, 27.5, 1012.0, 55.0))
        self.assertTrue(any("statistical outlier" in r for r in [reason or ""]) or "zscore_temperature_c" in detail)

    def test_16_lstm_adds_without_removing_rule_evidence(self):
        """A strong rule-based signal (frozen sensor) must not be reduced
        by a weak/absent LSTM contribution."""
        layer_rules_only = TemporalPatternLayer(CONFIG.temporal, lstm_config=LSTMTemporalConfig(enabled=False))
        layer_with_lstm = TemporalPatternLayer(CONFIG.temporal)

        temp, press, rh = _normal_series(160, seed=5)
        for layer in (layer_rules_only, layer_with_lstm):
            for i in range(160):
                layer.evaluate(_reading(i, float(temp[i]), float(press[i]), float(rh[i])))

        frozen_val = float(temp[159])
        score_rules_only = score_with_lstm = None
        for i in range(160, 160 + 14):
            score_rules_only, _, _, _ = layer_rules_only.evaluate(_reading(i, frozen_val, 1012.0, 55.0))
            score_with_lstm, _, _, _ = layer_with_lstm.evaluate(_reading(i, frozen_val, 1012.0, 55.0))

        self.assertGreaterEqual(score_with_lstm, score_rules_only - 1e-9)


class TestMissingDataHandling(unittest.TestCase):
    """Items 17-18: missing current/historical data never fabricates a residual."""

    def test_17_missing_current_observation_no_fake_residual(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        _feed_normal_history(layer, 144, seed=6)
        r = _reading(144, None, 1012.0, 55.0)  # temperature missing on the CURRENT reading
        _, _, _, detail = layer.evaluate(r)
        lstm = detail["lstm"]
        self.assertFalse(lstm["lstm_available"])
        self.assertEqual(lstm["lstm_skip_reason"], "current_observation_incomplete")
        self.assertIsNone(lstm["lstm_predicted_temperature_c"])

    def test_18_missing_historical_values_skip_lstm_safely(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        temp, press, rh = _normal_series(200, seed=7)
        for i in range(200):
            # Knock out humidity every 5th reading -> history_complete never
            # accumulates 144 JOINT-valid entries.
            rh_val = None if i % 5 == 0 else float(rh[i])
            layer.evaluate(_reading(i, float(temp[i]), float(press[i]), rh_val))
        buf = layer.buffers[STATION_ID]
        self.assertLess(len(buf.history_complete), 144)
        _, _, _, detail = layer.evaluate(_reading(200, float(temp[-1]), float(press[-1]), float(rh[-1])))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")


class TestRecentPeak(unittest.TestCase):
    """Item 19: recent residual peak logic."""

    def test_19_recent_peak_persists_after_instantaneous_residual_decays(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        _feed_normal_history(layer, 144, seed=8)

        # Onset: one strong spike-like deviation.
        _, _, _, detail_onset = layer.evaluate(_reading(144, 45.0, 1012.0, 55.0))
        self.assertTrue(detail_onset["lstm"]["lstm_available"])
        peak_at_onset = detail_onset["lstm"]["recent_lstm_peak"]
        self.assertGreater(peak_at_onset, 0.5)

        # Immediately after, feed a perfectly ordinary reading — the
        # INSTANTANEOUS residual should be much smaller, but recent_lstm_peak
        # should still reflect the onset spike (rolling max over the window).
        _, _, _, detail_after = layer.evaluate(_reading(145, 25.0, 1012.0, 55.0))
        self.assertGreaterEqual(detail_after["lstm"]["recent_lstm_peak"], peak_at_onset - 1e-9)


class TestGracefulDegradation(unittest.TestCase):
    """Item 20: model-load failure does not crash the layer."""

    def test_20_missing_model_dir_disables_lstm_without_crashing(self):
        bad_cfg = LSTMTemporalConfig(model_dir="models/does_not_exist_stage4_test")
        layer = TemporalPatternLayer(CONFIG.temporal, lstm_config=bad_cfg)
        self.assertFalse(layer.lstm.available)
        # evaluate() must still work normally (rule-based only), no exception.
        result = _feed_normal_history(layer, 10)
        score, scores, reason, detail = result
        self.assertIsInstance(score, float)
        self.assertFalse(detail["lstm"]["lstm_available"])


class TestDeterminism(unittest.TestCase):
    """Item 21: repeated inference is deterministic in eval mode."""

    def test_21_repeated_evaluation_same_input_is_deterministic(self):
        evidence = LSTMTemporalEvidence(CONFIG.lstm_temporal)
        history = [(START + timedelta(minutes=10 * i), 25.0 + 0.01 * i, 1012.0, 55.0) for i in range(144)]
        result_a = evidence.evaluate(history, 26.0, 1012.0, 55.0)
        result_b = evidence.evaluate(history, 26.0, 1012.0, 55.0)
        self.assertEqual(result_a.predicted_temperature_c, result_b.predicted_temperature_c)
        self.assertEqual(result_a.temperature_residual, result_b.temperature_residual)
        self.assertEqual(result_a.lstm_residual_score, result_b.lstm_residual_score)


class TestExistingCallersCompatible(unittest.TestCase):
    """Items 22-23: fusion/detector/API-facing contract unchanged."""

    def test_22_full_detector_still_runs_end_to_end(self):
        detector = AnomalyDetector()
        reading_dict = {
            "id": "STAGE4-DETECTOR-TEST", "name": "Stage4 Test",
            "latitude": 17.0, "longitude": 78.0,
            "temperature": 25.0, "pressure": 1012.0, "humidity": 55.0,
        }
        status, legacy = detector.evaluate_station(reading_dict)
        alert = detector.get_station_alert("STAGE4-DETECTOR-TEST")
        self.assertIn("temporal", alert.layer_scores)
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.0)
        self.assertLessEqual(alert.layer_scores["temporal"], 1.0)

    def test_23_evaluate_return_signature_unchanged(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        result = layer.evaluate(_reading(0, 25.0, 1012.0, 55.0))
        self.assertEqual(len(result), 4)
        score, scores, reason, detail = result
        self.assertIsInstance(score, float)
        self.assertIsInstance(scores, dict)
        self.assertTrue(reason is None or isinstance(reason, str))
        self.assertIsInstance(detail, dict)


class TestStage4IntegrationScenarios(unittest.TestCase):
    """Spec section 24: controlled synthetic scenarios A-E."""

    def test_A_normal_sequence_small_residual(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        result = _feed_normal_history(layer, 145, seed=10)
        _, scores, _, detail = result
        self.assertTrue(detail["lstm"]["lstm_available"])
        self.assertLess(detail["lstm"]["lstm_residual_score"], 1.0)
        self.assertLess(scores["temperature_c"], 0.5)

    def test_B_temperature_spike_large_residual(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        _feed_normal_history(layer, 144, seed=11)
        overall_score, scores, reason, detail = layer.evaluate(_reading(144, 42.0, 1012.0, 55.0))
        self.assertGreater(scores["temperature_c"], 0.7)
        self.assertTrue(detail["lstm"]["lstm_available"])
        self.assertGreater(detail["lstm"]["temperature_abs_residual"], 5.0)

    def test_C_frozen_temperature_rule_persists_after_lstm_adapts(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        temp, press, rh = _normal_series(144, seed=12)
        for i in range(144):
            layer.evaluate(_reading(i, float(temp[i]), float(press[i]), float(rh[i])))
        frozen_val = float(temp[-1])
        onset_score = end_score = None
        onset_reason = end_reason = None
        for i, step in enumerate(range(144, 144 + 14)):
            score, scores, reason, detail = layer.evaluate(_reading(step, frozen_val, float(press[-1]), float(rh[-1])))
            if i == 0:
                onset_score, onset_reason = score, reason
            if i == 13:
                end_score, end_reason = score, reason
        # The RULE-BASED frozen check must still fire at the END of the
        # window (Stage 3 showed the LSTM's OWN residual fades by then).
        self.assertGreaterEqual(end_score, 0.9)
        self.assertIn("Frozen", end_reason)

    def test_D_stale_packet_rule_available(self):
        """All three channels repeating together — the existing frozen/
        rate-of-change rules remain the primary evidence source, exactly
        as Stage 3 recommended (LSTM alone is weak here)."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        temp, press, rh = _normal_series(144, seed=13)
        for i in range(144):
            layer.evaluate(_reading(i, float(temp[i]), float(press[i]), float(rh[i])))
        stale_t, stale_p, stale_rh = float(temp[-1]), float(press[-1]), float(rh[-1])
        result = None
        for step in range(144, 144 + 14):  # >= frozen_window_size (12) so the existing rule can fire
            result = layer.evaluate(_reading(step, stale_t, stale_p, stale_rh))
        score, scores, reason, detail = result
        # All 3 channels frozen simultaneously -> existing frozen-sensor
        # rule(s) fire on at least one channel.
        self.assertGreaterEqual(max(scores.values()), 0.9)

    def test_E_missing_observation_no_fake_lstm_residual(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        _feed_normal_history(layer, 144, seed=14)
        _, _, _, detail = layer.evaluate(_reading(144, None, None, None))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertIsNone(detail["lstm"]["temperature_residual"])


if __name__ == "__main__":
    unittest.main()
