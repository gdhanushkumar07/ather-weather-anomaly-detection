"""
Temporal Intelligence — runtime pipeline verification (Phase 1 of backend
validation).

Feeds ONE station a controlled, deterministic stream of contiguous valid
observations through the PRODUCTION AnomalyDetector / TemporalPatternLayer and
verifies the intended flow:

    observation -> temporal history -> 144 valid contiguous observations
    -> LSTM prediction -> actual - predicted residual -> normalized residual
    -> temporal score -> Evidence Fusion

Nothing here preloads or fabricates history: every history point is a reading
the layer was actually handed, one at a time. The observations are SYNTHETIC
controlled inputs for engineering verification only. These tests prove the
runtime plumbing is wired and behaves as designed — they do NOT prove
real-world detection accuracy.
"""
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
from engine.layer2_temporal import TemporalPatternLayer
from app.anomaly.detector import AnomalyDetector

SEQ = CONFIG.lstm_temporal.sequence_length  # 144
START = datetime(2025, 6, 1, tzinfo=timezone.utc)
STATION = "TEMPORAL-RUNTIME-1"


def _normal_values(i: int, rng):
    """Smooth diurnal-like controlled input (10-minute cadence)."""
    t = 25.0 + 3.0 * np.sin(i / 12.0) + rng.normal(0, 0.05)
    p = 1012.0 + rng.normal(0, 0.05)
    h = 55.0 + 5.0 * np.cos(i / 12.0) + rng.normal(0, 0.1)
    return float(t), float(p), float(h)


def _reading(i, t, p, h, *, obs=None, ts=None, station=STATION) -> AWSReading:
    return AWSReading(
        station_id=station,
        timestamp=ts if ts is not None else START + timedelta(minutes=10 * i),
        observation_timestamp=obs,
        temperature_c=t, pressure_hpa=p, humidity_pct=h,
        lat=17.0, lon=78.0,
    )


def _warm_detector(n: int = SEQ + 6, seed: int = 0):
    """A fresh production detector fed n contiguous normal observations."""
    det = AnomalyDetector()
    rng = np.random.default_rng(seed)
    alert = None
    for i in range(n):
        alert = det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
    return det, rng, alert


class TestHistoryBuildsAndWarmUp(unittest.TestCase):
    """Verification items 1-2: history starts building; warm-up before 144."""

    def test_01_history_builds_one_observation_at_a_time(self):
        det = AnomalyDetector()
        rng = np.random.default_rng(0)
        for i in range(10):
            alert = det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
            d = alert.layer_details["temporal"]
            self.assertEqual(d["history_points"], i + 1)
            self.assertEqual(d["lstm_history_points"], i + 1)
            self.assertEqual(d["lstm_required_history_points"], SEQ)

    def test_02_lstm_not_active_before_144_and_reports_why(self):
        layer = TemporalPatternLayer()
        self.assertTrue(layer.lstm.available, "trained LSTM artifacts must load")
        rng = np.random.default_rng(0)
        for i in range(SEQ):  # readings 0..143 -> only 0..142 exist as PRIOR history
            _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng)))
            self.assertFalse(detail["lstm"]["lstm_available"], f"reading {i}")
            self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")

    def test_03_lstm_block_present_even_on_insufficient_data_early_return(self):
        """Previously the INSUFFICIENT_DATA early return dropped the whole
        'lstm' block, so the skip reason was invisible for the first 2 readings."""
        layer = TemporalPatternLayer()
        _, _, _, detail = layer.evaluate(_reading(0, 25.0, 1012.0, 55.0))
        self.assertEqual(detail["status"], "INSUFFICIENT_DATA")
        self.assertIn("lstm", detail)
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")
        self.assertEqual(detail["history_points"], 1)

    def test_04_rule_based_checks_still_work_during_warmup(self):
        layer = TemporalPatternLayer()
        rng = np.random.default_rng(0)
        for i in range(30):
            layer.evaluate(_reading(i, *_normal_values(i, rng)))
        t, p, h = _normal_values(30, rng)
        score, ch, reason, detail = layer.evaluate(_reading(30, t + 10.0, p, h))
        self.assertFalse(detail["lstm"]["lstm_available"])          # still warming up
        self.assertGreaterEqual(ch["temperature_c"], 0.70)          # rule-based step-rate fired
        self.assertIn("Abrupt temperature change", reason)
        self.assertIn("temp_spike", detail)


class TestLSTMActivation(unittest.TestCase):
    """Verification items 3-7: activation, prediction, residuals, scores."""

    @classmethod
    def setUpClass(cls):
        cls.det, cls.rng, cls.last = _warm_detector(n=SEQ + 6)

    def test_05_lstm_activates_on_first_reading_after_144_prior_points(self):
        layer = TemporalPatternLayer()
        rng = np.random.default_rng(0)
        avail = []
        for i in range(SEQ + 3):
            _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng)))
            avail.append(detail["lstm"]["lstm_available"])
        # 144 prior valid points are required, so the FIRST prediction is made
        # for reading index 144 (the 145th observation).
        self.assertEqual(avail.index(True), SEQ)
        self.assertTrue(all(avail[SEQ:]))
        self.assertFalse(any(avail[:SEQ]))

    def test_06_prediction_residuals_and_scores_are_generated(self):
        lstm = self.last.layer_details["temporal"]["lstm"]
        self.assertTrue(lstm["lstm_available"])
        self.assertIsNone(lstm["lstm_skip_reason"])
        for key in ("lstm_predicted_temperature_c", "lstm_predicted_pressure_hpa", "lstm_predicted_humidity_pct",
                    "temperature_residual", "pressure_residual", "humidity_residual",
                    "temperature_abs_residual", "pressure_abs_residual", "humidity_abs_residual",
                    "temperature_lstm_raw_score", "pressure_lstm_raw_score", "humidity_lstm_raw_score"):
            self.assertIsNotNone(lstm[key], key)
        # residual is actual - predicted
        raw = self.last.raw_values
        self.assertAlmostEqual(lstm["temperature_residual"], raw["temperature_c"] - lstm["lstm_predicted_temperature_c"], places=6)
        self.assertAlmostEqual(lstm["humidity_residual"], raw["humidity_pct"] - lstm["lstm_predicted_humidity_pct"], places=6)
        # per-channel scores are clipped normalized residuals in [0, 1]
        for ch in ("temperature", "pressure", "humidity"):
            self.assertGreaterEqual(lstm[f"{ch}_lstm_score"], 0.0)
            self.assertLessEqual(lstm[f"{ch}_lstm_score"], 1.0)
        self.assertAlmostEqual(
            lstm["lstm_residual_score"],
            max(lstm["temperature_lstm_score"], lstm["pressure_lstm_score"], lstm["humidity_lstm_score"]),
            places=4,
        )

    def test_07_overall_temporal_score_generated_and_baseline_is_not_acute(self):
        temporal_score = self.last.layer_scores["temporal"]
        self.assertGreaterEqual(temporal_score, 0.0)
        self.assertLess(temporal_score, 0.70, "clean controlled input must not trip the acute temporal trigger")


class TestOutputContractAndFusion(unittest.TestCase):
    """Verification items 8-9: history_points exposed; temporal reaches fusion."""

    def _spied_detector(self):
        det = AnomalyDetector()
        calls = []
        original = det.fusion.fuse

        def spy(**kwargs):
            calls.append(kwargs)
            return original(**kwargs)

        det.fusion.fuse = spy
        return det, calls

    def test_08_history_points_exposed_through_alert_and_data_quality(self):
        det = AnomalyDetector()
        rng = np.random.default_rng(0)
        alert = None
        for i in range(5):
            alert = det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
        self.assertEqual(alert.layer_details["temporal"]["history_points"], 5)
        self.assertEqual(alert.temporal_history_points, 5)
        dq = alert.canonical_result["data_quality"]
        self.assertEqual(dq["historical_points"], 5)
        self.assertFalse(any("Limited historical sequence" in s for s in dq["limitations"]))

    def test_09_history_count_and_coverage_reach_fusion(self):
        det, calls = self._spied_detector()
        rng = np.random.default_rng(0)
        for i in range(6):
            det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
        first, last = calls[0], calls[-1]
        # reading 0: 1 point -> below the 3-point coverage floor, scarcity applies
        self.assertEqual(first["temporal_history_count"], 1)
        self.assertEqual(first["layer_coverage"]["temporal"], 0.2)
        # reading 5: 6 points -> full temporal coverage, no scarcity
        self.assertEqual(last["temporal_history_count"], 6)
        self.assertEqual(last["layer_coverage"]["temporal"], 1.0)

    def test_10_injected_lstm_only_anomaly_responds_and_reaches_fusion(self):
        """A +12 %RH offset is below the rule step threshold (15 %) and inside the
        rolling-z tolerance, so ONLY the LSTM residual can flag it."""
        det, calls = self._spied_detector()
        rng = np.random.default_rng(0)
        for i in range(SEQ + 6):
            det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
        i = SEQ + 6
        t, p, h = _normal_values(i, rng)
        alert = det.evaluate_reading(_reading(i, t, p, h + 12.0))
        d = alert.layer_details["temporal"]

        self.assertTrue(d["lstm"]["lstm_available"])
        rule_keys = [k for k in d if k.startswith(("zscore", "temp_spike", "press_spike", "frozen"))]
        self.assertEqual(rule_keys, [], f"a rule fired, this is not an LSTM-only case: {rule_keys}")
        self.assertGreater(d["lstm"]["humidity_residual"], 8.0)
        self.assertGreaterEqual(d["lstm"]["humidity_lstm_score"], 0.90)
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.90)
        self.assertTrue(any("Temporal prediction residual" in r for r in alert.reasons))
        # reaches fusion, unchanged, and trips fusion's acute temporal trigger
        fused_scores = calls[-1]["layer_scores"]
        self.assertEqual(fused_scores["temporal"], alert.layer_scores["temporal"])
        self.assertTrue(alert.layer_details["fusion"]["acute_triggers"]["temporal"])
        self.assertTrue(alert.is_anomaly)

    def test_11_injected_temperature_spike_hits_rule_and_lstm(self):
        det = AnomalyDetector()
        rng = np.random.default_rng(0)
        for i in range(SEQ + 6):
            det.evaluate_reading(_reading(i, *_normal_values(i, rng)))
        i = SEQ + 6
        t, p, h = _normal_values(i, rng)
        alert = det.evaluate_reading(_reading(i, t + 10.0, p, h))
        d = alert.layer_details["temporal"]
        self.assertIn("temp_spike", d)                                   # rule-based
        self.assertGreaterEqual(d["lstm"]["temperature_lstm_score"], 0.70)  # LSTM residual
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.70)
        self.assertTrue(alert.layer_details["fusion"]["acute_triggers"]["temporal"])

    def test_12_lstm_disabled_still_exposes_contract_and_rule_evidence(self):
        layer = TemporalPatternLayer(CONFIG.temporal, LSTMTemporalConfig(enabled=False))
        rng = np.random.default_rng(0)
        for i in range(10):
            _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng)))
        self.assertEqual(detail["history_points"], 10)
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "disabled_by_config")


class TestTimestampHandling(unittest.TestCase):
    """Verification item 10: which clock spaces the history."""

    def _feed(self, layer, n, obs_fn=None, ts_fn=None, rng=None):
        rng = rng or np.random.default_rng(0)
        out = None
        for i in range(n):
            obs = obs_fn(i) if obs_fn else None
            ts = ts_fn(i) if ts_fn else None
            out = layer.evaluate(_reading(i, *_normal_values(i, rng), obs=obs, ts=ts))
        return out

    def test_13_observation_timestamp_preferred_over_processing_clock(self):
        """Readings PROCESSED 1 s apart but OBSERVED 10 min apart (a burst /
        backfill). Spacing must follow the observation clock."""
        layer = TemporalPatternLayer()
        proc0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
        _, _, _, detail = self._feed(
            layer, SEQ + 1,
            obs_fn=lambda i: START + timedelta(minutes=10 * i),
            ts_fn=lambda i: proc0 + timedelta(seconds=i),
        )
        self.assertTrue(detail["lstm"]["lstm_available"])
        hist = layer.buffers[STATION].history_complete
        self.assertEqual((hist[1][0] - hist[0][0]).total_seconds(), 600.0)
        self.assertEqual(hist[0][0], START + timedelta(minutes=10 * 1))  # observation clock, not proc0

    def test_14_large_observation_gap_resets_even_if_processing_clock_is_contiguous(self):
        layer = TemporalPatternLayer()
        proc0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self._feed(layer, 20, obs_fn=lambda i: START + timedelta(minutes=10 * i),
                   ts_fn=lambda i: proc0 + timedelta(seconds=i))
        self.assertEqual(len(layer.buffers[STATION].history_complete), 20)
        # next observation is 3 h later (processing clock still 1 s later)
        r = _reading(20, 25.0, 1012.0, 55.0, obs=START + timedelta(minutes=10 * 19 + 180),
                     ts=proc0 + timedelta(seconds=20))
        _, _, _, detail = layer.evaluate(r)
        self.assertEqual(detail["lstm_history_points"], 1)  # cleared, restarted from this reading

    def test_15_falls_back_to_processing_timestamp_when_no_observation_time(self):
        layer = TemporalPatternLayer()
        _, _, _, detail = self._feed(layer, SEQ + 1)  # obs=None, explicit 10-min timestamps
        self.assertTrue(detail["lstm"]["lstm_available"])
        hist = layer.buffers[STATION].history_complete
        self.assertEqual(hist[0][0], START + timedelta(minutes=10))

    def test_16_naive_observation_timestamp_is_utc_and_never_raises(self):
        """Open-Meteo style naive timestamps mixed with aware ones must not
        raise TypeError when subtracted."""
        layer = TemporalPatternLayer()
        naive0 = datetime(2025, 6, 1, 0, 0)  # tz-naive, interpreted as UTC
        rng = np.random.default_rng(0)
        for i in range(6):
            obs = naive0 + timedelta(minutes=10 * i) if i % 2 == 0 else START + timedelta(minutes=10 * i)
            _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng), obs=obs))
        self.assertEqual(detail["lstm_history_points"], 6)  # all contiguous: naive == same UTC instants
        for ts, *_ in layer.buffers[STATION].history_complete:
            self.assertIsNotNone(ts.tzinfo)


class TestGapAndOrdering(unittest.TestCase):
    """Verification items 11-12: existing robustness logic is preserved."""

    @classmethod
    def setUpClass(cls):
        cls.max_gap = CONFIG.lstm_temporal.max_gap_minutes

    def _warm_layer(self):
        layer = TemporalPatternLayer()
        rng = np.random.default_rng(0)
        for i in range(SEQ + 3):
            layer.evaluate(_reading(i, *_normal_values(i, rng)))
        return layer, rng

    def test_17_gap_larger_than_max_resets_history_and_lstm_deactivates(self):
        layer, rng = self._warm_layer()
        i = SEQ + 3
        gap_ts = START + timedelta(minutes=10 * (i - 1) + 30)   # +30 min since last
        _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng), ts=gap_ts))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")
        self.assertEqual(detail["lstm_history_points"], 1)
        # rule-based history is NOT wiped by the gap
        self.assertGreater(detail["history_points"], 3)

    def test_18_gap_exactly_at_limit_is_still_contiguous(self):
        layer, rng = self._warm_layer()
        i = SEQ + 3
        ok_ts = START + timedelta(minutes=10 * (i - 1) + self.max_gap)
        _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng), ts=ok_ts))
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_19_out_of_order_reading_resets_and_never_uses_misordered_history(self):
        layer, rng = self._warm_layer()
        i = SEQ + 3
        early_ts = START + timedelta(minutes=10 * (i - 1) - 20)  # earlier than the last stored point
        _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng), ts=early_ts))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm_history_points"], 1)

    def test_20_duplicate_timestamp_treated_as_non_advancing_and_resets(self):
        """Existing policy (gap <= 0 clears the LSTM history) — documented, unchanged."""
        layer, rng = self._warm_layer()
        i = SEQ + 3
        dup_ts = START + timedelta(minutes=10 * (i - 1))
        _, _, _, detail = layer.evaluate(_reading(i, *_normal_values(i, rng), ts=dup_ts))
        self.assertFalse(detail["lstm"]["lstm_available"])

    def test_21_history_rebuilds_after_gap(self):
        layer, rng = self._warm_layer()
        base = SEQ + 3
        t0 = START + timedelta(minutes=10 * (base - 1) + 60)
        counts = []
        for k in range(5):
            _, _, _, detail = layer.evaluate(_reading(base + k, *_normal_values(base + k, rng), ts=t0 + timedelta(minutes=10 * k)))
            counts.append(detail["lstm_history_points"])
        self.assertEqual(counts, [1, 2, 3, 4, 5])


class TestRuntimeConverterPath(unittest.TestCase):
    """The same station-dict -> AWSReading conversion the live ingest/startup
    path uses (schema.station_dict_to_reading), driven at machine speed with
    observation times 10 min apart."""

    def test_22_station_dict_path_builds_history_and_activates_lstm(self):
        det = AnomalyDetector()
        rng = np.random.default_rng(0)
        proc_times = []
        alert = None
        for i in range(SEQ + 2):
            t, p, h = _normal_values(i, rng)
            stn = {
                "id": "RUNTIME-DICT-1", "name": "Runtime dict station",
                "latitude": 17.0, "longitude": 78.0,
                "temperature": t, "pressure": p, "humidity": h,
                "dataSource": "AWS_IN_SITU",
                "observationTimestamp": (START + timedelta(minutes=10 * i)).isoformat(),
            }
            det.evaluate_station(stn)
            alert = det.get_station_alert("RUNTIME-DICT-1")
            proc_times.append(alert.timestamp)
        # sanity: the processing clock really was ~machine speed (seconds, not 24 h)
        self.assertLess((proc_times[-1] - proc_times[0]).total_seconds(), 600.0)
        d = alert.layer_details["temporal"]
        self.assertTrue(d["lstm"]["lstm_available"])
        self.assertGreater(alert.temporal_history_points, 3)
        self.assertEqual(d["lstm_history_points"], SEQ)  # buffer capped at the sequence length


if __name__ == "__main__":
    unittest.main()
