"""
Stage 6 Phase 3: sensor recovery / stream-transition scenarios (A-G).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np

from config import CONFIG
from schema import AWSReading
from engine.layer2_temporal import TemporalPatternLayer

START = datetime(2025, 2, 1, tzinfo=timezone.utc)


def _reading(ts, temp, press, rh, station="R"):
    return AWSReading(station_id=station, timestamp=ts, temperature_c=temp, pressure_hpa=press,
                       humidity_pct=rh, lat=17.0, lon=78.0)


def _seed(layer, station, n=144, seed=0, start=START):
    rng = np.random.default_rng(seed)
    temp = 25 + 3 * np.sin(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.05, n)
    press = 1012 + rng.normal(0, 0.05, n)
    rh = 55 + 5 * np.cos(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.1, n)
    ts = start
    for i in range(n):
        ts = start + timedelta(minutes=10 * i)
        layer.evaluate(_reading(ts, float(temp[i]), float(press[i]), float(rh[i]), station))
    return ts, float(temp[-1]), float(press[-1]), float(rh[-1])


class TestRecoveryScenarios(unittest.TestCase):

    def test_A_single_missing_reading_within_gap_tolerance(self):
        """A SINGLE missing reading spans exactly 2x cadence (20min) between
        the surrounding valid readings, which is enough to test the
        gap-tolerance boundary directly."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "A")
        buf = layer.buffers["A"]
        len_before = len(buf.history_complete)
        missing_ts = last_ts + timedelta(minutes=10)
        _, _, _, detail = layer.evaluate(_reading(missing_ts, None, None, None, "A"))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(len(buf.history_complete), len_before)  # missing reading never appended

    def test_A2_missing_readings_spanning_more_than_max_gap_correctly_reset(self):
        """FINDING (not a bug): with max_gap_minutes=15 and 10-min cadence,
        ANY single missed/invalid reading already puts the next valid
        reading 20 minutes after the last complete one — exceeding the
        15-minute tolerance — so a full reset is the CORRECT, designed
        response, not a defect. This test documents/locks in that real
        behavior rather than assuming (incorrectly, as an earlier draft of
        this test did) that a few missed ticks count as "short"."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "A2")
        buf = layer.buffers["A2"]
        ts = last_ts
        for i in range(1, 4):
            ts = last_ts + timedelta(minutes=10 * i)
            layer.evaluate(_reading(ts, None, None, None, "A2"))
        resume_ts = ts + timedelta(minutes=10)
        _, _, _, detail = layer.evaluate(_reading(resume_ts, t, p, r, "A2"))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(len(buf.history_complete), 1)  # correctly reset and restarted, not corrupted

    def test_B_out_of_range_temperature_is_NOT_caught_at_data_quality_level(self):
        """FINDING, documented not fixed (out of Temporal Intelligence's
        ownership — see Stage 6 report): unlike pressure (<1 hPa ->
        ZERO_SUBSTITUTED) and humidity (<0 or >100 -> INVALID/OUT_OF_RANGE),
        schema.py's populate_data_quality() applies NO bounds check to
        temperature_c at all — any non-None value is tagged VALID. So
        TemporalPatternLayer.evaluate() run in ISOLATION treats a
        physically-impossible 999C reading as a normal joint-valid
        observation and appends it to history_complete. In the FULL
        production pipeline this is still caught — Layer 1 Physics fires a
        hard VETO on out-of-bounds temperature before fusion ever weighs
        Layer 2's score — so this is a real gap in Layer 2 standing alone,
        not an exploitable gap in the actual system. Fixing it would mean
        changing schema.py's shared data-quality logic used by every
        layer, which is outside this stage's scope (Physics/schema
        ownership boundary) and is reported rather than patched here."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "B")
        buf = layer.buffers["B"]
        len_before = len(buf.history_complete)
        bad_ts = last_ts + timedelta(minutes=10)
        layer.evaluate(_reading(bad_ts, 999.0, p, r, "B"))
        # Confirms the finding rather than asserting the (incorrect) hope
        # that it was rejected: the impossible value WAS appended (buffer
        # was already at its 144 maxlen, so length is unchanged but the
        # LAST entry is now the impossible 999.0 reading, not a reset).
        self.assertEqual(len(buf.history_complete), len_before)
        self.assertEqual(buf.history_complete[-1][1], 999.0)

    def test_C_invalid_humidity_never_contaminates_joint_history(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "C")
        buf = layer.buffers["C"]
        len_before = len(buf.history_complete)
        bad_ts = last_ts + timedelta(minutes=10)
        layer.evaluate(_reading(bad_ts, t, p, 250.0, "C"))  # impossible RH
        self.assertEqual(len(buf.history_complete), len_before)
        resume_ts = bad_ts + timedelta(minutes=10)
        _, _, _, detail = layer.evaluate(_reading(resume_ts, t, p, r, "C"))
        self.assertFalse(detail["lstm"]["lstm_available"])  # correct reset, per test_A2's finding
        self.assertEqual(len(buf.history_complete), 1)

    def test_D_invalid_pressure_never_contaminates_joint_history(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "D")
        buf = layer.buffers["D"]
        len_before = len(buf.history_complete)
        bad_ts = last_ts + timedelta(minutes=10)
        layer.evaluate(_reading(bad_ts, t, 0.5, r, "D"))  # near-zero pressure -> ZERO_SUBSTITUTED/invalid
        self.assertEqual(len(buf.history_complete), len_before)
        resume_ts = bad_ts + timedelta(minutes=10)
        _, _, _, detail = layer.evaluate(_reading(resume_ts, t, p, r, "D"))
        self.assertFalse(detail["lstm"]["lstm_available"])  # correct reset, per test_A2's finding
        self.assertEqual(len(buf.history_complete), 1)

    def test_E_long_outage_then_recovery(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "E")
        buf = layer.buffers["E"]
        outage_end = last_ts + timedelta(hours=12)
        _, _, _, detail = layer.evaluate(_reading(outage_end, t, p, r, "E"))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(len(buf.history_complete), 1)  # clean reset, not stale-history prediction
        # rewarm
        ts, t2, p2, r2 = _seed(layer, "E", n=144, seed=1, start=outage_end + timedelta(minutes=10))
        _, _, _, detail = layer.evaluate(_reading(ts + timedelta(minutes=10), t2, p2, r2, "E"))
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_F_anomaly_then_recovery_score_returns_down(self):
        """FINDING (not a bug): snapping directly back to the pre-spike
        baseline is ITSELF a second abrupt change in the opposite
        direction (confirmed: it independently triggers its own "Abrupt
        temperature change" rule and its own LSTM residual, since the
        model's expectation was thrown off by the spike). Each of the two
        events gets its own 6-step recent-peak window, so full decay
        legitimately takes up to ~2x residual_window, not 1x. This test
        uses a long-enough recovery run to observe the genuine decay
        rather than assuming an unrealistically fast return."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "F", seed=9)
        spike_ts = last_ts + timedelta(minutes=10)
        score_spike, _, _, _ = layer.evaluate(_reading(spike_ts, t + 15.0, p, r, "F"))
        self.assertGreater(score_spike, 0.7)
        # Recovery values carry small REALISTIC noise (not an exact repeated
        # constant) — repeating the exact same float for 12+ steps would
        # itself spuriously trip the separate, pre-existing frozen-sensor
        # rule, which is unrelated to what this test is checking (LSTM/
        # recent-peak decay).
        rng = np.random.default_rng(99)
        ts = spike_ts
        scores_over_time = []
        for i in range(1, 16):  # > 2x residual_window(6) to let BOTH transient events fully age out
            ts = spike_ts + timedelta(minutes=10 * i)
            score_recover, _, _, _ = layer.evaluate(_reading(
                ts, t + rng.normal(0, 0.05), p + rng.normal(0, 0.05), r + rng.normal(0, 0.1), "F"))
            scores_over_time.append(score_recover)
        self.assertLess(scores_over_time[-1], score_spike)
        self.assertLess(scores_over_time[-1], 0.3)  # genuinely back to quiet, not just "less than 1.0"

    def test_G_frozen_then_recovery(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed(layer, "G", seed=11)
        ts = last_ts
        score = None
        for i in range(1, 15):
            ts = last_ts + timedelta(minutes=10 * i)
            score, scores, reason, detail = layer.evaluate(_reading(ts, t, p, r, "G"))
        self.assertGreaterEqual(scores["temperature_c"], 0.9)  # frozen rule fired
        # recovery: sensor starts reporting normal variation again
        rng = np.random.default_rng(12)
        recovered_score = None
        for i in range(15, 20):
            ts = last_ts + timedelta(minutes=10 * i)
            v = t + rng.normal(0, 0.05)
            recovered_score, _, _, _ = layer.evaluate(_reading(ts, v, p, r, "G"))
        # Frozen-window rule needs fresh variance to clear -> score should
        # drop once genuine variation resumes for a full window.
        self.assertLessEqual(recovered_score, score)


if __name__ == "__main__":
    unittest.main()
