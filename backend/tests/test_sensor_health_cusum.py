"""
Sensor Health Intelligence / CUSUM — validation (Phase 3 of backend validation).

The Sensor Health layer answers ONE question: "is this sensor showing a
persistent change in its behavior relative to its own recent past?" It reports
that as sensor-health EVIDENCE that can support a maintenance investigation.
It is NOT failure prediction, NOT an acute-anomaly detector, and (see the
expected-failure tests) it cannot separate natural weather variability from
drift because its reference is the sensor's own history.

All sequences are deterministic, controlled SYNTHETIC inputs. These tests prove
the layer's decision rules and its wiring into the production detector; they do
NOT prove real-world drift-detection accuracy.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np

from config import CONFIG
from schema import AWSReading
from engine.layer5_drift import SensorDriftHealthLayer, ChannelDriftState
from app.anomaly.detector import AnomalyDetector

T0 = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
CFG = CONFIG.drift
MIN_N = CFG.min_samples_for_drift            # 12
RESET_GAP = CFG.reset_gap_minutes            # 360


def ts(i):
    return T0 + timedelta(minutes=10 * i)


_J = object()   # "use the realistic default jitter"


def R(station, i, t=30.0, p=_J, h=_J, when=None, src="AWS_IN_SITU"):
    """Reading at ts(i). Pressure/humidity default to small realistic jitter (like the
    Test Lab scenarios) - perfectly constant p/h would legitimately be flagged as a
    FROZEN sensor by the Temporal layer and confuse production-path assertions."""
    if p is _J:
        p = 1012.0 + 0.05 * ((i % 5) - 2)
    if h is _J:
        h = 55.0 + 0.1 * ((i % 3) - 1)
    when = ts(i) if when is None else when
    return AWSReading(
        station_id=station, timestamp=when, observation_timestamp=when,
        temperature_c=t, pressure_hpa=p, humidity_pct=h, lat=17.0, lon=78.0, source=src,
    )


def stable(i):
    return 30.0 + 0.1 * (i % 3)          # 30.0, 30.1, 30.2, 30.0, ...


def feed(layer, values, station="S", start=0, **kw):
    """Feed temperature values one per 10 min; returns list of (score, health, dtf, reason, detail)."""
    return [layer.evaluate(R(station, start + k, t=v, **kw)) for k, v in enumerate(values)]


def temp(detail):
    return detail["channel_drift"]["temperature_c"]


NORMAL_TIERS = {"INSUFFICIENT_DATA", "NORMAL", "SUSPICIOUS"}


# ───────────────────────────── behaviors A–E ─────────────────────────────
class TestNormalSensor(unittest.TestCase):
    def test_01_normal_stable_sequence_has_no_drift_no_reason_no_projection(self):
        out = feed(SensorDriftHealthLayer(), [stable(i) for i in range(90)])
        for score, health, dtf, reason, d in out:
            self.assertEqual(score, 0.0)
            self.assertIsNone(dtf)
            self.assertIsNone(reason)
            self.assertEqual(health, 100.0)
        self.assertEqual(temp(out[-1][4])["drift_tier"], "NORMAL")


class TestPersistentDrift(unittest.TestCase):
    def ramp(self, sign, n=80, start=20, step=0.2):
        vals = [stable(i) + (sign * step * (i - start) if i >= start else 0.0) for i in range(n)]
        return feed(SensorDriftHealthLayer(), vals)

    def test_02_persistent_positive_drift_accumulates_gradually_then_indicates_drift(self):
        out = self.ramp(+1)
        scores = [o[0] for o in out]
        self.assertLess(scores[24], 0.05)                      # not instantly
        self.assertLess(scores[30], scores[36])                # gradual accumulation ...
        self.assertLess(scores[36], scores[45])
        d = out[-1][4]
        self.assertIn(temp(d)["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))
        self.assertGreaterEqual(out[-1][0], 0.75)
        self.assertGreater(temp(d)["estimated_bias"], 0)       # upward
        self.assertIn("CUSUM drift", out[-1][3])
        self.assertIn("own recent baseline", out[-1][3])
        self.assertLess(out[-1][1], 90.0)                      # health index reflects it

    def test_03_persistent_negative_drift_is_detected_symmetrically(self):
        out = self.ramp(-1)
        d = out[-1][4]
        self.assertIn(temp(d)["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))
        self.assertGreaterEqual(out[-1][0], 0.75)
        self.assertLess(temp(d)["estimated_bias"], 0)          # downward
        self.assertAlmostEqual(out[-1][0], self.ramp(+1)[-1][0], places=6)   # mirror image


class TestSingleSpike(unittest.TestCase):
    def spike(self, magnitude, at=30, n=90):
        vals = [stable(i) + (magnitude if i == at else 0.0) for i in range(n)]
        return feed(SensorDriftHealthLayer(), vals)

    def assert_not_persistent_degradation(self, out):
        self.assertLess(max(o[0] for o in out), 0.15)          # bounded influence of ONE value
        for score, health, dtf, reason, d in out:
            self.assertIn(temp(d)["drift_tier"], NORMAL_TIERS)
            self.assertIsNone(dtf)
            self.assertIsNone(reason)                          # no "CUSUM drift" claim from one point
        self.assertGreaterEqual(min(o[1] for o in out), 95.0)  # health barely moves

    def test_04_single_positive_spike_is_not_persistent_sensor_degradation(self):
        self.assert_not_persistent_degradation(self.spike(+15.0))

    def test_05_single_negative_spike_is_not_persistent_sensor_degradation(self):
        self.assert_not_persistent_degradation(self.spike(-15.0))

    def test_05b_an_enormous_single_value_adds_no_more_than_the_clip_allows(self):
        st = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=1)
        st.update(30.0)
        st.update(30.0 + 1e6)
        self.assertAlmostEqual(st.s_pos, (CFG.cusum_residual_clip_factor - 1.0) * 1.0 * CFG.cusum_leak, places=9)

    def test_05c_a_short_burst_needs_persistence_to_reach_a_drift_tier(self):
        """Persistence, not magnitude: 3 consecutive outliers stay below LIKELY_DRIFT,
        while a sustained run of them does reach it."""
        def run(k):
            vals = [stable(i) + (15.0 if 30 <= i < 30 + k else 0.0) for i in range(60)]
            return max(temp(o[4])["drift_tier"] in ("LIKELY_DRIFT", "HIGH_RISK") for o in feed(SensorDriftHealthLayer(), vals))
        self.assertFalse(run(3))
        self.assertTrue(run(15))


class TestFrozenSensor(unittest.TestCase):
    def test_06_frozen_values_are_NOT_a_sensor_health_signal_by_design(self):
        """A constant series has zero residual: CUSUM is silent. Frozen-sensor
        detection is Temporal's job (frozen-window rule) - see the production-path test."""
        out = feed(SensorDriftHealthLayer(), [30.0] * 90)
        self.assertEqual(max(o[0] for o in out), 0.0)
        self.assertEqual(temp(out[-1][4])["drift_tier"], "NORMAL")


class TestMissingObservations(unittest.TestCase):
    def test_07_missing_values_never_become_valid_samples(self):
        layer = SensorDriftHealthLayer()
        seq = [30.0, 30.1, None, None, 30.4, 30.2, None, 30.1, 30.3, None, None, None, 30.2, 30.0] * 3
        for i, v in enumerate(seq):
            layer.evaluate(R("S", i, t=v))
        st = layer.trackers["S"].channel_states["temperature_c"]
        self.assertEqual(st.sample_count, sum(v is not None for v in seq))

        # identical state to a layer that only ever saw the valid samples (same timestamps)
        ref = SensorDriftHealthLayer()
        for i, v in enumerate(seq):
            if v is not None:
                ref.evaluate(R("S", i, t=v))
        rs = ref.trackers["S"].channel_states["temperature_c"]
        self.assertEqual((st.sample_count, round(st.s_pos, 9), round(st.s_neg, 9), round(st.ema_mean, 9)),
                         (rs.sample_count, round(rs.s_pos, 9), round(rs.s_neg, 9), round(rs.ema_mean, 9)))

    def test_07b_a_reading_with_every_channel_missing_is_not_a_sample(self):
        layer = SensorDriftHealthLayer()
        layer.evaluate(R("S", 0, t=30.0))
        score, health, dtf, reason, d = layer.evaluate(R("S", 1, t=None, p=None, h=None))
        self.assertEqual(layer.trackers["S"].total_readings, 1)
        self.assertEqual(d["samples_tracked"], 0)              # nothing valid in this reading
        self.assertEqual(d["channel_drift"], {})
        self.assertEqual(score, 0.0)


# ───────────────────── ordering, duplicates, resets ─────────────────────
class TestObservationOrdering(unittest.TestCase):
    def test_08_duplicate_timestamp_does_not_advance_the_state(self):
        layer = SensorDriftHealthLayer()
        feed(layer, [stable(i) for i in range(20)])
        st = layer.trackers["S"].channel_states["temperature_c"]
        before = (st.sample_count, st.s_pos, st.s_neg, st.ema_mean, layer.trackers["S"].total_readings)
        for _ in range(5):                                     # same instant re-delivered, even with a different value
            _, _, _, _, d = layer.evaluate(R("S", 19, t=99.0))
            self.assertEqual(d["observation_status"], "DUPLICATE")
        self.assertEqual(before, (st.sample_count, st.s_pos, st.s_neg, st.ema_mean, layer.trackers["S"].total_readings))

    def test_08b_a_duplicated_observation_can_never_create_drift_evidence(self):
        layer = SensorDriftHealthLayer()
        for _ in range(200):
            out = layer.evaluate(R("S", 0, t=30.0))
        self.assertEqual(temp(out[4])["samples_tracked"], 1)
        self.assertEqual(temp(out[4])["drift_tier"], "INSUFFICIENT_DATA")

    def test_09_out_of_order_reading_is_ignored_and_state_continues_correctly(self):
        layer = SensorDriftHealthLayer()
        feed(layer, [stable(i) for i in range(20)])
        st = layer.trackers["S"].channel_states["temperature_c"]
        before = (st.sample_count, st.s_pos, st.s_neg, st.ema_mean)
        _, _, _, _, d = layer.evaluate(R("S", 5, t=55.0))       # 'old' reading arriving late
        self.assertEqual(d["observation_status"], "OUT_OF_ORDER")
        self.assertEqual(before, (st.sample_count, st.s_pos, st.s_neg, st.ema_mean))
        _, _, _, _, d = layer.evaluate(R("S", 20, t=stable(20)))  # the stream resumes in order
        self.assertEqual(d["observation_status"], "ACCEPTED")
        self.assertEqual(st.sample_count, 21)

    def test_11_observation_time_is_used_not_the_processing_clock(self):
        """Processed 1 s apart but OBSERVED 10 min apart: nothing is a duplicate or
        out-of-order, and the observed cadence (not the processing cadence) is what the layer sees."""
        layer = SensorDriftHealthLayer()
        proc0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            r = AWSReading(station_id="S", timestamp=proc0 + timedelta(seconds=i), observation_timestamp=ts(i),
                           temperature_c=stable(i), pressure_hpa=1012.0, humidity_pct=55.0, lat=17, lon=78)
            _, _, _, _, d = layer.evaluate(r)
            self.assertEqual(d["observation_status"], "ACCEPTED")
        st = layer.trackers["S"].channel_states["temperature_c"]
        self.assertAlmostEqual(st.mean_interval_minutes, 10.0, places=6)

    def test_11b_out_of_order_by_observation_time_even_if_processing_clock_advances(self):
        layer = SensorDriftHealthLayer()
        proc0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
        mk = lambda i, obs: AWSReading(station_id="S", timestamp=proc0 + timedelta(seconds=i), observation_timestamp=obs,
                                       temperature_c=30.0, pressure_hpa=1012.0, humidity_pct=55.0, lat=17, lon=78)
        layer.evaluate(mk(0, ts(10)))
        _, _, _, _, d = layer.evaluate(mk(1, ts(3)))            # observed EARLIER, processed later
        self.assertEqual(d["observation_status"], "OUT_OF_ORDER")

    def test_11c_naive_observation_time_is_treated_as_utc_and_never_raises(self):
        layer = SensorDriftHealthLayer()
        naive = datetime(2026, 6, 1, 0, 0)
        for i in range(4):
            obs = (naive if i % 2 == 0 else T0) + timedelta(minutes=10 * i)   # naive and aware mixed
            _, _, _, _, d = layer.evaluate(AWSReading(station_id="S", timestamp=T0 + timedelta(minutes=10 * i),
                                                       observation_timestamp=obs, temperature_c=30.0,
                                                       pressure_hpa=1012.0, humidity_pct=55.0, lat=17, lon=78))
            self.assertEqual(d["observation_status"], "ACCEPTED")


class TestResetBehavior(unittest.TestCase):
    def drifted_layer(self):
        layer = SensorDriftHealthLayer()
        feed(layer, [stable(i) + (0.2 * (i - 20) if i >= 20 else 0.0) for i in range(60)])
        return layer

    def test_13a_gap_longer_than_the_limit_reinitializes_the_stale_baseline(self):
        layer = self.drifted_layer()
        self.assertEqual(layer.trackers["S"].channel_states["temperature_c"].drift_tier, "HIGH_RISK")
        later = ts(59) + timedelta(minutes=RESET_GAP + 1)
        score, health, dtf, reason, d = layer.evaluate(R("S", 0, t=stable(0), when=later))
        self.assertIn("station", d["channel_resets"])
        self.assertEqual(temp(d)["samples_tracked"], 1)
        self.assertEqual(temp(d)["drift_tier"], "INSUFFICIENT_DATA")
        self.assertEqual(score, 0.0)
        self.assertEqual(health, 100.0)
        self.assertEqual(layer.trackers["S"].total_readings, 1)

    def test_13b_a_gap_exactly_at_the_limit_does_not_reset(self):
        layer = self.drifted_layer()
        at_limit = ts(59) + timedelta(minutes=RESET_GAP)
        _, _, _, _, d = layer.evaluate(R("S", 0, t=50.0, when=at_limit))
        self.assertEqual(d["channel_resets"], [])
        self.assertEqual(temp(d)["samples_tracked"], 61)

    def test_13c_only_the_channel_that_was_absent_too_long_is_reset(self):
        layer = SensorDriftHealthLayer()
        for i in range(30):
            layer.evaluate(R("S", i, t=stable(i), p=1012.0 + 0.01 * (i % 3)))
        # pressure disappears for > reset gap while temperature keeps reporting every 10 min
        for i in range(30, 30 + int(RESET_GAP / 10) + 5):
            layer.evaluate(R("S", i, t=stable(i), p=None))
        _, _, _, _, d = layer.evaluate(R("S", 30 + int(RESET_GAP / 10) + 5, t=stable(0), p=1012.0))
        self.assertEqual(d["channel_resets"], ["pressure_hpa"])
        self.assertEqual(d["channel_drift"]["pressure_hpa"]["samples_tracked"], 1)
        self.assertGreater(d["channel_drift"]["temperature_c"]["samples_tracked"], 30)   # temperature untouched

    def test_13d_channel_reset_returns_to_a_pristine_state(self):
        st = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=1)
        for k in range(30):
            st.update(30.0 + 0.5 * k, ts(k))
        self.assertGreater(st.s_pos, 0)
        st.reset()
        self.assertEqual((st.ema_mean, st.s_pos, st.s_neg, st.sample_count, st.recent_residuals, st.last_ts, st.score),
                         (None, 0.0, 0.0, 0, [], None, 0.0))


# ───────────────────── isolation, warm-up, thresholds ─────────────────────
class TestIsolation(unittest.TestCase):
    def test_10_multiple_stations_have_independent_state_even_when_interleaved(self):
        layer = SensorDriftHealthLayer()
        for i in range(70):
            layer.evaluate(R("A", i, t=stable(i) + (0.2 * (i - 20) if i >= 20 else 0.0)))   # drifting
            layer.evaluate(R("B", i, t=stable(i)))                                            # healthy
        a, b = layer.trackers["A"], layer.trackers["B"]
        self.assertIsNot(a, b)
        self.assertIsNot(a.channel_states["temperature_c"], b.channel_states["temperature_c"])
        self.assertEqual(a.channel_states["temperature_c"].drift_tier, "HIGH_RISK")
        self.assertEqual(b.channel_states["temperature_c"].drift_tier, "NORMAL")
        self.assertEqual(b.channel_states["temperature_c"].score, 0.0)
        self.assertEqual(b.total_readings, 70)

    def test_10b_identical_stations_evolve_identically_regardless_of_interleaving(self):
        solo, mixed = SensorDriftHealthLayer(), SensorDriftHealthLayer()
        seq = [stable(i) + (0.15 * (i - 10) if i >= 10 else 0.0) for i in range(50)]
        feed(solo, seq, station="X")
        for k, v in enumerate(seq):
            mixed.evaluate(R("NOISE", k, t=99.0 - k))            # a very different station in between
            mixed.evaluate(R("X", k, t=v))
        s, m = solo.trackers["X"].channel_states["temperature_c"], mixed.trackers["X"].channel_states["temperature_c"]
        self.assertEqual((s.sample_count, round(s.s_pos, 9), round(s.ema_mean, 9)),
                         (m.sample_count, round(m.s_pos, 9), round(m.ema_mean, 9)))

    def test_10c_separate_layer_instances_share_nothing(self):
        l1, l2 = SensorDriftHealthLayer(), SensorDriftHealthLayer()
        feed(l1, [stable(i) + 0.3 * i for i in range(50)])
        self.assertNotIn("S", l2.trackers)

    def test_12_channels_are_independent(self):
        # temperature drifts; pressure and humidity are steady
        layer = SensorDriftHealthLayer()
        for i in range(70):
            _, _, _, _, d = layer.evaluate(R("S", i, t=stable(i) + (0.2 * (i - 20) if i >= 20 else 0.0)))
        self.assertIn(temp(d)["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))
        self.assertEqual(d["channel_drift"]["pressure_hpa"]["drift_tier"], "NORMAL")
        self.assertEqual(d["channel_drift"]["humidity_pct"]["drift_tier"], "NORMAL")
        self.assertEqual(d["channel_drift"]["pressure_hpa"]["cusum_score"], 0.0)
        # and the reverse: only pressure drifts
        layer = SensorDriftHealthLayer()
        for i in range(70):
            _, _, _, _, d = layer.evaluate(R("S", i, t=stable(i), p=1012.0 + (0.3 * (i - 20) if i >= 20 else 0.0)))
        self.assertIn(d["channel_drift"]["pressure_hpa"]["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))
        self.assertEqual(temp(d)["drift_tier"], "NORMAL")

    def test_12b_a_missing_channel_does_not_disturb_the_others(self):
        layer = SensorDriftHealthLayer()
        for i in range(40):
            _, _, _, _, d = layer.evaluate(R("S", i, t=stable(i), h=None if i % 2 else 55.0))
        states = layer.trackers["S"].channel_states
        self.assertEqual(states["temperature_c"].sample_count, 40)
        self.assertEqual(states["pressure_hpa"].sample_count, 40)
        self.assertEqual(states["humidity_pct"].sample_count, 20)        # only the 20 valid humidity readings


class TestWarmUpAndThresholds(unittest.TestCase):
    def test_12_warm_up_no_drift_score_or_tier_before_the_minimum_samples(self):
        out = feed(SensorDriftHealthLayer(), [30.0 + 0.6 * i for i in range(20)])   # extreme ramp from the start
        for k in range(MIN_N - 1):                                                    # 1..11 samples
            self.assertEqual(out[k][0], 0.0, f"sample {k + 1}")
            self.assertEqual(temp(out[k][4])["drift_tier"], "INSUFFICIENT_DATA")
            self.assertEqual(out[k][4]["status"], "INSUFFICIENT_DATA")
        self.assertGreater(out[MIN_N - 1][0], 0.0)                                    # the 12th sample is the first conclusion
        self.assertNotEqual(temp(out[MIN_N - 1][4])["drift_tier"], "INSUFFICIENT_DATA")
        self.assertEqual(out[MIN_N - 1][4]["status"], "EVALUATED")

    def test_14a_tier_boundaries_are_inclusive_lower_bounds(self):
        h = 10.0
        st = ChannelDriftState(slack=1.0, threshold=h, min_samples=1)
        st.sample_count = 50
        for s, tier in [(0.0, "NORMAL"), (2.999, "NORMAL"), (3.0, "SUSPICIOUS"), (5.999, "SUSPICIOUS"),
                        (6.0, "POSSIBLE_DRIFT"), (9.999, "POSSIBLE_DRIFT"), (10.0, "LIKELY_DRIFT"),
                        (14.999, "LIKELY_DRIFT"), (15.0, "HIGH_RISK"), (400.0, "HIGH_RISK")]:
            st.s_pos, st.s_neg = s, 0.0
            self.assertEqual(st.drift_tier, tier, f"S={s}")
            st.s_pos, st.s_neg = 0.0, s                                           # symmetric for the lower accumulator
            self.assertEqual(st.drift_tier, tier, f"S-={s}")

    def test_14b_slack_boundary_a_residual_equal_to_the_slack_accumulates_nothing(self):
        st = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=1)
        st.update(30.0)
        st.update(31.0)                      # residual == slack exactly
        self.assertEqual(st.s_pos, 0.0)
        st2 = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=1)
        st2.update(30.0)
        st2.update(31.1)                     # 0.1 above the slack
        self.assertAlmostEqual(st2.s_pos, 0.1 * CFG.cusum_leak, places=9)

    def test_14c_warm_up_boundary_uses_the_configured_minimum(self):
        st = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=MIN_N)
        for k in range(MIN_N - 1):
            st.update(30.0 + 2.0 * k)
        self.assertEqual(st.score, 0.0)
        self.assertEqual(st.drift_tier, "INSUFFICIENT_DATA")
        st.update(30.0 + 2.0 * (MIN_N - 1))
        self.assertGreater(st.score, 0.0)

    def test_14d_score_is_the_accumulator_over_twice_the_threshold_clipped_to_one(self):
        st = ChannelDriftState(slack=1.0, threshold=10.0, min_samples=1)
        st.sample_count = 5
        st.s_pos = 10.0
        st.update(st.ema_mean if st.ema_mean is not None else 30.0)   # zero residual: only the leak applies
        self.assertAlmostEqual(st.score, min(1.0, (max(0.0, 10.0 - 1.0) * CFG.cusum_leak) / 20.0), places=9)

    def test_configuration_is_explicit_and_documented_in_config(self):
        for name in ("ema_beta", "cusum_leak", "cusum_residual_clip_factor", "min_samples_for_drift",
                     "reset_gap_minutes", "health_error_rate_min_samples",
                     "plausible_cadence_min_minutes", "plausible_cadence_max_minutes"):
            self.assertTrue(hasattr(CFG, name), name)


# ───────────────────── honesty: no failure prediction ─────────────────────
class TestNoFailurePredictionClaims(unittest.TestCase):
    def test_projection_only_with_sustained_evidence_and_it_is_labeled_indicative(self):
        out = feed(SensorDriftHealthLayer(), [stable(i) + (0.05 * (i - 20) if i >= 20 else 0.0) for i in range(90)])
        seen = False
        for score, health, dtf, reason, d in out:
            if dtf is not None:
                seen = True
                self.assertIn(temp(d)["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))   # never from a lone/soft signal
                self.assertIn("not a failure prediction", reason)
                self.assertIn("indicative only", reason)
        # (whether a projection appears at all depends on the rate; the invariant is the gating + wording)
        self.assertTrue(all("Projected" not in (o[3] or "") for o in out))
        _ = seen

    def test_no_projection_when_the_sampling_cadence_is_unknown_or_implausible(self):
        """A burst processed 1 s apart (observation time unknown) has no meaningful
        per-day rate, so no tolerance projection may be produced even under drift."""
        layer = SensorDriftHealthLayer()
        t0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
        for i in range(60):
            r = AWSReading(station_id="S", timestamp=t0 + timedelta(seconds=i), temperature_c=30.0 + 0.4 * i,
                           pressure_hpa=1012.0, humidity_pct=55.0, lat=17, lon=78)
            _, _, dtf, reason, d = layer.evaluate(r)
            self.assertIsNone(dtf)
            self.assertIsNone(temp(d).get("days_to_failure"))
            self.assertIsNone(temp(d)["drift_rate_per_day"])

    def test_layer_states_its_own_limits_in_every_response(self):
        _, _, _, _, d = SensorDriftHealthLayer().evaluate(R("S", 0))
        self.assertEqual(d["reference"], "OWN_RECENT_BASELINE")
        self.assertIn("cannot separate natural weather variability", d["note"])
        self.assertIn("not a failure prediction", d["note"])

    def test_health_index_is_not_dominated_by_one_flagged_reading_among_the_first_few(self):
        layer = SensorDriftHealthLayer()
        for i in range(4):
            _, health, _, _, _ = layer.evaluate(R("S", i, t=stable(i)), recent_is_anomaly=(i == 3))
        self.assertGreaterEqual(health, 89.0)      # previously 36.0 (a 100% "error rate" over 4 samples)

    def test_nwp_model_reference_is_not_a_sensor_no_state_no_evidence(self):
        layer = SensorDriftHealthLayer()
        for i in range(60):
            score, health, dtf, reason, d = layer.evaluate(R("NWP1", i, t=25.0 + 0.5 * i, src="NWP_MODEL_REFERENCE"))
        self.assertEqual((score, health, dtf, reason), (0.0, 100.0, None, None))
        self.assertEqual(d["status"], "NOT_APPLICABLE_NON_PHYSICAL_SOURCE")
        self.assertNotIn("NWP1", layer.trackers)


# ───────────────────── known limitations (recorded, not hidden) ─────────────────────
class TestKnownLimitations(unittest.TestCase):
    """These assert what a drift detector SHOULD do and are marked expectedFailure
    because the current single-sensor, self-referenced CUSUM cannot. If a future
    change makes one pass, unittest reports an 'unexpected success' so the
    limitation entry is removed deliberately."""

    @unittest.expectedFailure
    def test_KNOWN_LIMITATION_natural_diurnal_swing_is_not_separated_from_drift(self):
        out = feed(SensorDriftHealthLayer(), [25.0 + 5.0 * np.sin(2 * np.pi * i / 144) for i in range(288)])
        tiers = {temp(o[4])["drift_tier"] for o in out}
        self.assertFalse(tiers & {"LIKELY_DRIFT", "HIGH_RISK"}, "a healthy sensor on a normal daily cycle must not read as drifting")

    @unittest.expectedFailure
    def test_KNOWN_LIMITATION_slow_persistent_drift_is_below_the_detection_floor(self):
        out = feed(SensorDriftHealthLayer(), [stable(i) + (0.02 * (i - 20) if i >= 20 else 0.0) for i in range(90)])
        self.assertIn(temp(out[-1][4])["drift_tier"], ("POSSIBLE_DRIFT", "LIKELY_DRIFT", "HIGH_RISK"))

    @unittest.expectedFailure
    def test_KNOWN_LIMITATION_a_persistent_offset_is_forgotten_as_the_baseline_adapts(self):
        out = feed(SensorDriftHealthLayer(), [stable(i) + (3.0 if i >= 20 else 0.0) for i in range(90)])
        self.assertIn(temp(out[-1][4])["drift_tier"], ("POSSIBLE_DRIFT", "LIKELY_DRIFT", "HIGH_RISK"))


# ─────────────────────── production path: real AnomalyDetector ───────────────────────
class TestProductionPath(unittest.TestCase):
    """Observation -> Data Quality Gate -> Sensor Health layer -> CUSUM state ->
    evidence -> detector response -> fusion input, through the real detector."""

    def spied(self):
        det = AnomalyDetector()
        calls = []
        real = det.fusion.fuse

        def spy(**kw):
            calls.append(kw)
            return real(**kw)

        det.fusion.fuse = spy
        return det, calls

    def test_drift_evidence_flows_from_observation_to_fusion_input_and_response(self):
        det, calls = self.spied()
        alert = None
        for i in range(45):
            alert = det.evaluate_reading(R("PROD-DRIFT", i, t=stable(i) + (0.2 * (i - 20) if i >= 20 else 0.0)))

        d5 = alert.layer_details["drift"]
        # CUSUM state was built by the production detector, per channel
        self.assertGreaterEqual(d5["channel_drift"]["temperature_c"]["samples_tracked"], 45)
        self.assertIn(d5["channel_drift"]["temperature_c"]["drift_tier"], ("LIKELY_DRIFT", "HIGH_RISK"))
        self.assertEqual(d5["reference"], "OWN_RECENT_BASELINE")
        # evidence in the response
        self.assertEqual(alert.layer_scores["drift"], round(d5["max_drift_score"], 3))
        self.assertGreater(alert.layer_scores["drift"], 0.5)
        self.assertLess(alert.sensor_health_index, 90.0)
        card = alert.canonical_result["layers"]["sensor_health"]
        self.assertIn(card["status"], ("WARNING", "ANOMALY"))
        self.assertEqual(card["score"], alert.layer_scores["drift"])
        self.assertIn("CUSUM drift", card["reason"])
        # ... and it is exactly what fusion RECEIVED
        fused = calls[-1]
        self.assertEqual(fused["layer_scores"]["drift"], alert.layer_scores["drift"])
        self.assertEqual(fused["layer_coverage"]["drift"], 1.0)      # was ALWAYS 0.0 (missing top-level samples_tracked)

    def test_coverage_reaching_fusion_grows_with_the_real_sample_count(self):
        det, calls = self.spied()
        for i in range(30):
            det.evaluate_reading(R("PROD-COV", i, t=stable(i)))
        cov = [c["layer_coverage"]["drift"] for c in calls]
        self.assertAlmostEqual(cov[0], 1 / 20.0)
        self.assertAlmostEqual(cov[9], 10 / 20.0)
        self.assertEqual(cov[19], 1.0)
        self.assertEqual(cov[29], 1.0)

    def test_single_spike_through_the_detector_is_left_to_acute_layers_not_sensor_health(self):
        det = AnomalyDetector()
        for i in range(40):
            det.evaluate_reading(R("PROD-SPIKE", i, t=stable(i)))
        alert = det.evaluate_reading(R("PROD-SPIKE", 40, t=stable(40) + 15.0))
        self.assertLess(alert.layer_scores["drift"], 0.15)                 # not persistent degradation
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.70)      # the acute layer owns the spike
        self.assertNotEqual(alert.root_cause.value, "CALIBRATION_DRIFT")
        self.assertGreaterEqual(alert.sensor_health_index, 60.0)

    def test_frozen_sensor_is_caught_by_temporal_not_by_sensor_health(self):
        det = AnomalyDetector()
        for i in range(24):
            alert = det.evaluate_reading(R("PROD-FROZEN", i, t=30.0, p=1012.0, h=55.0))   # everything constant
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.90)
        self.assertTrue(any("Frozen" in r for r in alert.reasons))
        self.assertEqual(alert.layer_scores["drift"], 0.0)

    def test_stations_are_isolated_inside_the_real_detector(self):
        det = AnomalyDetector()
        for i in range(45):
            a = det.evaluate_reading(R("STN-A", i, t=stable(i) + (0.2 * (i - 20) if i >= 20 else 0.0)))
            b = det.evaluate_reading(R("STN-B", i, t=stable(i)))
        self.assertGreater(a.layer_scores["drift"], 0.5)
        self.assertEqual(b.layer_scores["drift"], 0.0)
        self.assertEqual(b.layer_details["drift"]["channel_drift"]["temperature_c"]["samples_tracked"], 45)
        self.assertEqual(b.layer_details["drift"]["channel_drift"]["temperature_c"]["drift_tier"], "NORMAL")

    def test_missing_value_through_the_data_quality_gate_is_not_a_sample(self):
        det = AnomalyDetector()
        for i in range(20):
            alert = det.evaluate_reading(R("PROD-MISS", i, t=None if i % 4 == 3 else stable(i)))
        st = det.layer5.trackers["PROD-MISS"].channel_states["temperature_c"]
        self.assertEqual(st.sample_count, 15)                            # 20 readings, 5 with temperature missing
        self.assertEqual(det.layer5.trackers["PROD-MISS"].channel_states["pressure_hpa"].sample_count, 20)

    def test_nwp_reference_never_contributes_drift_evidence_to_fusion(self):
        det, calls = self.spied()
        for i in range(45):
            alert = det.evaluate_reading(R("PROD-NWP", i, t=25.0 + 0.5 * i if i < 40 else 45.0, src="NWP_MODEL_REFERENCE"))
        self.assertEqual(alert.layer_scores["drift"], 0.0)
        self.assertEqual(alert.canonical_result["layers"]["sensor_health"]["status"], "NOT_APPLICABLE")
        self.assertEqual(calls[-1]["layer_scores"]["drift"], 0.0)

    def test_station_dict_runtime_path_with_observation_times_and_a_duplicate(self):
        """The same station-dict -> AWSReading conversion the live ingest path uses."""
        det = AnomalyDetector()
        base = {"id": "PROD-DICT", "name": "dict station", "latitude": 17.0, "longitude": 78.0,
                "pressure": 1012.0, "humidity": 55, "dataSource": "AWS_IN_SITU"}
        for i in range(25):
            det.evaluate_station({**base, "temperature": stable(i), "observationTimestamp": ts(i).isoformat()})
        alert = det.get_station_alert("PROD-DICT")
        self.assertEqual(alert.layer_details["drift"]["channel_drift"]["temperature_c"]["samples_tracked"], 25)
        det.evaluate_station({**base, "temperature": 99.0, "observationTimestamp": ts(24).isoformat()})   # re-delivered instant
        alert = det.get_station_alert("PROD-DICT")
        self.assertEqual(alert.layer_details["drift"]["observation_status"], "DUPLICATE")
        self.assertEqual(alert.layer_details["drift"]["channel_drift"]["temperature_c"]["samples_tracked"], 25)

    def test_layer_failure_degrades_gracefully_and_is_reported_not_hidden(self):
        det = AnomalyDetector()
        with mock.patch.object(det.layer5, "evaluate", side_effect=RuntimeError("boom")):
            alert = det.evaluate_reading(R("PROD-FAIL", 0))
        self.assertEqual(alert.layer_scores["drift"], 0.0)
        self.assertEqual(alert.canonical_result["layers"]["sensor_health"]["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
