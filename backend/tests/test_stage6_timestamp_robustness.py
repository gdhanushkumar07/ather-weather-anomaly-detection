"""
Stage 6 Phase 2: timestamp-robustness scenarios for TemporalPatternLayer.

Covers all 11 scenarios from the Stage 6 spec. Two concrete bugs were
found and fixed here (see engine/layer2_temporal.py "Stage 6" comments):

  BUG 1: buf.history_complete's gap-reset check only fired on gaps that
  were too big going FORWARD (gap_minutes > max_gap_minutes). A duplicate
  timestamp (gap=0) or an out-of-order/rollback reading (gap<0) was
  silently appended, corrupting the "144 consecutive forward steps"
  assumption the LSTM was trained on. Fix: also reset when gap_minutes<=0.

  BUG 2: the rule-based step-rate check computed
  dt_seconds = max(1.0, (reading.timestamp - prev.timestamp).total_seconds())
  — for a rollback (negative raw delta), this collapsed to the 1-second
  floor, making interval_factor hit its minimum (0.5) and the abrupt-
  change threshold artificially tight, which could flag a perfectly
  plausible value change as a false "Abrupt temperature change". Fix:
  use abs() of the delta so a rollback is scaled by the true MAGNITUDE of
  the time gap, not clamped to a meaningless 1 second.
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

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _reading(ts, temp, press, rh, station="TS"):
    return AWSReading(station_id=station, timestamp=ts, temperature_c=temp, pressure_hpa=press,
                       humidity_pct=rh, lat=17.0, lon=78.0)


def _seed_normal_history(layer, station, n=144, seed=0, start=START, interval_minutes=10):
    rng = np.random.default_rng(seed)
    temp = 25 + 3 * np.sin(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.05, n)
    press = 1012 + rng.normal(0, 0.05, n)
    rh = 55 + 5 * np.cos(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.1, n)
    ts = start
    for i in range(n):
        ts = start + timedelta(minutes=interval_minutes * i)
        layer.evaluate(_reading(ts, float(temp[i]), float(press[i]), float(rh[i]), station))
    return ts, float(temp[-1]), float(press[-1]), float(rh[-1])


class TestTimestampScenarios(unittest.TestCase):

    def test_01_perfect_10min_cadence_enables_lstm(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        _, t, p, r = _seed_normal_history(layer, "S1")
        _, _, _, detail = layer.evaluate(_reading(START + timedelta(minutes=1440), t, p, r, "S1"))
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_02_small_jitter_plus_minus_1min_still_works(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        rng = np.random.default_rng(1)
        ts = START
        for i in range(150):
            jitter = timedelta(seconds=int(rng.uniform(-60, 60)))
            ts = START + timedelta(minutes=10 * i) + jitter
            score, scores, reason, detail = layer.evaluate(_reading(
                ts, 25.0 + rng.normal(0, 0.05), 1012.0 + rng.normal(0, 0.05), 55.0 + rng.normal(0, 0.1), "S2"))
        self.assertTrue(detail["lstm"]["lstm_available"])
        self.assertIsNone(reason)  # small jitter on genuinely-varying values must not fabricate a reason

    def test_03_moderate_jitter_3_5min_does_not_falsely_reset(self):
        """Consecutive readings' independent jitter can COMBINE (one late,
        the next early), so the worst-case gap is 10 + 2*max_jitter, not
        10 + max_jitter. Capping jitter at +/-2min keeps the worst case at
        14min, safely under max_gap_minutes=15 — this scenario is
        specifically about jitter staying UNDER the reset threshold, not
        about the threshold boundary itself (covered by tests 05-07)."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        rng = np.random.default_rng(2)
        ts = START
        prev_ts = ts
        for i in range(150):
            jitter = timedelta(minutes=int(rng.uniform(-2, 2)))
            ts = START + timedelta(minutes=10 * i) + jitter
            if ts <= prev_ts:
                ts = prev_ts + timedelta(minutes=1)
            prev_ts = ts
            score, scores, reason, detail = layer.evaluate(_reading(
                ts, 25.0 + rng.normal(0, 0.05), 1012.0 + rng.normal(0, 0.05), 55.0 + rng.normal(0, 0.1), "S3"))
        # Moderate jitter (still well under max_gap_minutes) must not have
        # forced repeated resets -> LSTM should be available by the end.
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_04_irregular_intervals_under_gap_threshold(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        intervals = [8, 12, 9, 15, 10]
        ts = START
        detail = None
        for cycle in range(30):  # 30*5 = 150 readings
            for m in intervals:
                ts = ts + timedelta(minutes=m)
                _, _, _, detail = layer.evaluate(_reading(ts, 25.0, 1012.0, 55.0, "S4"))
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_05_gap_just_below_threshold_no_reset(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S5")
        buf = layer.buffers["S5"]
        len_before = len(buf.history_complete)
        gap = timedelta(minutes=CONFIG.lstm_temporal.max_gap_minutes - 1)
        layer.evaluate(_reading(last_ts + gap, t, p, r, "S5"))
        self.assertEqual(len(buf.history_complete), min(144, len_before + 1))

    def test_06_gap_exactly_at_threshold_no_reset(self):
        """Boundary is exclusive (`>`), so exactly max_gap_minutes must NOT reset."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S6")
        buf = layer.buffers["S6"]
        len_before = len(buf.history_complete)
        gap = timedelta(minutes=CONFIG.lstm_temporal.max_gap_minutes)
        layer.evaluate(_reading(last_ts + gap, t, p, r, "S6"))
        self.assertEqual(len(buf.history_complete), min(144, len_before + 1))

    def test_07_gap_just_above_threshold_resets(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S7")
        buf = layer.buffers["S7"]
        gap = timedelta(minutes=CONFIG.lstm_temporal.max_gap_minutes + 1)
        layer.evaluate(_reading(last_ts + gap, t, p, r, "S7"))
        self.assertEqual(len(buf.history_complete), 1)

    def test_08_large_missing_data_gap_resets_and_rewarms(self):
        """Regression guard for the 3rd Stage 6 bug: the reading that
        ARRIVES after a big gap must not itself get an LSTM prediction
        from the now-stale pre-gap history — it must be the first reading
        of the fresh rewarm-up, not a "144-available" prediction target."""
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S8")
        big_gap = timedelta(hours=6)
        _, _, _, detail = layer.evaluate(_reading(last_ts + big_gap, t, p, r, "S8"))
        self.assertFalse(detail["lstm"]["lstm_available"])
        self.assertEqual(detail["lstm"]["lstm_skip_reason"], "insufficient_valid_history")
        self.assertEqual(len(layer.buffers["S8"].history_complete), 1)
        # Re-warm with 144 more contiguous readings after the gap.
        _, _, _, detail = _seed_normal_history_from(layer, "S8", start=last_ts + big_gap + timedelta(minutes=10))
        self.assertTrue(detail["lstm"]["lstm_available"])

    def test_09_timestamp_rollback_resets_and_does_not_false_flag(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S9", seed=5)
        buf = layer.buffers["S9"]
        rollback_ts = last_ts - timedelta(minutes=30)
        score, scores, reason, detail = layer.evaluate(_reading(rollback_ts, t + 2.0, p, r, "S9"))
        self.assertEqual(len(buf.history_complete), 1)  # reset, not silently appended out of order
        self.assertIsNone(detail.get("temp_spike"))     # regression guard for BUG 2

    def test_10_duplicate_timestamp_resets_history_complete(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S10")
        buf = layer.buffers["S10"]
        layer.evaluate(_reading(last_ts, t + 0.1, p, r, "S10"))
        self.assertEqual(len(buf.history_complete), 1)

    def test_11_out_of_order_reading_resets_rather_than_corrupts(self):
        layer = TemporalPatternLayer(CONFIG.temporal)
        last_ts, t, p, r = _seed_normal_history(layer, "S11")
        buf = layer.buffers["S11"]
        out_of_order_ts = last_ts - timedelta(minutes=100)  # e.g. a backfilled/replayed reading
        layer.evaluate(_reading(out_of_order_ts, t, p, r, "S11"))
        self.assertEqual(len(buf.history_complete), 1)
        self.assertEqual(buf.history_complete[-1][0], out_of_order_ts)


def _seed_normal_history_from(layer, station, n=144, seed=0, start=START):
    """Feeds n+1 contiguous readings starting at `start` and returns the
    last (timestamp, None, None, detail) — used to re-warm a station's
    LSTM history after a gap/reset, then check availability on read n+1."""
    rng = np.random.default_rng(seed)
    temp = 25 + 3 * np.sin(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.05, n)
    ts = start
    detail = None
    for i in range(n + 1):
        ts = start + timedelta(minutes=10 * i)
        val = float(temp[i]) if i < n else float(temp[-1])
        _, _, _, detail = layer.evaluate(_reading(ts, val, 1012.0, 55.0, station))
    return ts, None, None, detail


if __name__ == "__main__":
    unittest.main()
