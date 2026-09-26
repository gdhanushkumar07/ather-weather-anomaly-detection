"""
Layer 3 (Multivariate Intelligence) test suite.

Covers feature engineering, ECOD, Isolation Forest, conformal calibration,
the ensemble decision, trust-gated online learning, the T-RH decoupling
case, and ATHER pipeline compatibility. Model verdicts are never hardcoded:
tests train on generated data and check the behaviour that follows.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import MultivariateThresholds
from schema import AWSReading
from multivariate import schema as S
from multivariate.decision import ANOMALY, NORMAL, SUSPICIOUS, decide
from multivariate.features import (DELTA_FEATURES, DYNAMIC, STATIC, Observation, add_features, dew_point_c,
                                   input_feature_names, observation_features)
from multivariate.models import ConformalCalibrator, DetectorPair, ECODDetector, IsolationForestDetector
from multivariate.online import OnlineMultivariateEngine
from multivariate.preprocessing import standardize
from multivariate.training import fit_pair
from engine.layer3_multivariate import MultivariateConsistencyLayer
from app.anomaly.detector import AnomalyDetector

T0 = datetime(2024, 5, 1, tzinfo=timezone.utc)


def _cfg(**kw) -> MultivariateThresholds:
    base = dict(reference_enabled=False, min_train_samples=300, retrain_interval=100, buffer_max_len=2000)
    base.update(kw)
    return MultivariateThresholds(**base)


def _station_series(n_hours: int, seed: int = 0, lon: float = 77.2):
    """A station whose RH follows T physically: roughly constant moisture
    (dew point ~14C + slow noise) and a diurnal temperature cycle, so RH is
    low in the hot afternoon and high at night."""
    rng = np.random.default_rng(seed)
    rows = []
    td_noise = 0.0
    for h in range(n_hours):
        ts = T0 + timedelta(hours=h)
        solar = (ts.hour + lon / 15.0) % 24
        t = 27.0 + 7.0 * np.cos(2 * np.pi * (solar - 15.0) / 24.0) + rng.normal(0, 0.6)
        td_noise = 0.97 * td_noise + rng.normal(0, 0.35)
        td = min(14.0 + td_noise, t - 0.5)
        rh = float(np.clip(100 * np.exp(17.625 * td / (243.04 + td) - 17.625 * t / (243.04 + t)), 1, 100))
        p = 1008.0 + 1.5 * np.cos(4 * np.pi * solar / 24.0) + rng.normal(0, 0.3)
        rows.append((ts, round(t, 1), round(p, 1), round(rh)))
    return rows


def _frame(rows, station="S", lon=77.2):
    return pd.DataFrame({S.STATION_ID: station, S.TIMESTAMP: [r[0] for r in rows],
                         S.TEMPERATURE: [r[1] for r in rows], S.PRESSURE: [r[2] for r in rows],
                         S.HUMIDITY: [r[3] for r in rows], S.LONGITUDE: lon})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TestFeatureEngineering(unittest.TestCase):

    def test_deltas_are_per_hour_rates(self):
        df = _frame([(T0, 20.0, 1010.0, 50.0), (T0 + timedelta(hours=2), 24.0, 1009.0, 40.0)])
        f = add_features(df, max_delta_gap_hours=3.0)
        self.assertTrue(np.isnan(f.loc[0, DELTA_FEATURES[0]]))
        self.assertAlmostEqual(f.loc[1, "d_temperature_c_per_h"], 2.0)
        self.assertAlmostEqual(f.loc[1, "d_pressure_hpa_per_h"], -0.5)
        self.assertAlmostEqual(f.loc[1, "d_humidity_pct_per_h"], -5.0)

    def test_deltas_never_cross_station_boundaries(self):
        a = _frame([(T0, 20.0, 1010.0, 50.0), (T0 + timedelta(hours=1), 21.0, 1010.0, 48.0)], "A")
        b = _frame([(T0 + timedelta(hours=2), 35.0, 1000.0, 20.0), (T0 + timedelta(hours=3), 34.0, 1000.0, 22.0)], "B")
        f = add_features(pd.concat([a, b], ignore_index=True), 3.0)
        first_b = f[f[S.STATION_ID] == "B"].iloc[0]
        self.assertTrue(np.isnan(first_b["d_temperature_c_per_h"]))

    def test_rows_are_sorted_by_time_before_deltas(self):
        rows = [(T0 + timedelta(hours=h), 20.0 + h, 1010.0, 50.0) for h in range(4)]
        shuffled = _frame([rows[2], rows[0], rows[3], rows[1]])
        f = add_features(shuffled, 3.0)
        self.assertTrue(f[S.TIMESTAMP].is_monotonic_increasing)
        np.testing.assert_allclose(f["d_temperature_c_per_h"].to_numpy()[1:], [1.0, 1.0, 1.0])

    def test_gap_longer_than_limit_gives_no_delta(self):
        df = _frame([(T0, 20.0, 1010.0, 50.0), (T0 + timedelta(hours=5), 24.0, 1009.0, 40.0)])
        f = add_features(df, max_delta_gap_hours=3.0)
        self.assertTrue(np.isnan(f.loc[1, "d_temperature_c_per_h"]))

    def test_missing_and_invalid_values_are_removed_and_counted(self):
        df = _frame([(T0, 20.0, 1010.0, 50.0), (T0 + timedelta(hours=1), np.nan, 1010.0, 50.0),
                     (T0 + timedelta(hours=2), 20.0, np.inf, 50.0), (T0 + timedelta(hours=3), 20.0, 1010.0, 140.0),
                     (T0, 20.0, 1010.0, 50.0)])
        out, rep = standardize(df)
        self.assertEqual(len(out), 1)
        self.assertEqual(rep["dropped_missing_or_nonfinite_channel"], 2)
        self.assertEqual(rep["dropped_outside_physical_bounds"], 1)
        self.assertEqual(rep["dropped_duplicate_station_timestamp"], 1)

    def test_dew_point_matches_metpy(self):
        try:
            from metpy.calc import dewpoint_from_relative_humidity
            from metpy.units import units
        except ImportError:
            self.skipTest("MetPy not installed")
        for t, rh in [(20.0, 50.0), (32.0, 88.0), (5.0, 95.0), (40.0, 10.0)]:
            ref = dewpoint_from_relative_humidity(t * units.degC, rh * units.percent).m_as("degC")
            self.assertAlmostEqual(float(dew_point_c(t, rh)), float(ref), delta=0.2)

    def test_online_features_equal_batch_features(self):
        rows = _station_series(10, seed=3)
        batch = add_features(_frame(rows), 3.0)
        prev = None
        for i, (ts, t, p, rh) in enumerate(rows):
            obs = Observation(ts, t, p, rh, 77.2)
            online = observation_features(obs, prev, 3.0)
            for name in input_feature_names(DYNAMIC if i else STATIC):
                self.assertAlmostEqual(online[name], batch.loc[i, name], places=9, msg=name)
            prev = obs


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TestECOD(unittest.TestCase):

    def test_trains_and_scores_with_sufficient_samples(self):
        rng = np.random.default_rng(0)
        det = ECODDetector()
        self.assertTrue(det.fit(rng.normal(size=(500, 4))))
        s = det.score(rng.normal(size=(20, 4)))
        self.assertEqual(s.shape, (20,))
        self.assertTrue(np.all(np.isfinite(s)))

    def test_insufficient_samples_do_not_train(self):
        self.assertFalse(ECODDetector().fit(np.ones((1, 3))))
        self.assertIsNone(fit_pair(add_features(_frame(_station_series(10)), 3.0),
                                   add_features(_frame(_station_series(5, seed=1)), 3.0), STATIC, _cfg()))

    def test_scores_equal_pyod_single_row_decision_function_including_ties(self):
        rng = np.random.default_rng(1)
        x = np.round(rng.normal(size=(800, 5)) * 3)          # heavy ties, like integer RH
        q = np.round(rng.normal(size=(60, 5)) * 6)
        det = ECODDetector()
        det.fit(x)
        self.assertFalse(det.use_pyod_per_row)
        ref = [det.model.decision_function(q[i:i + 1, det.active_cols])[0] for i in range(len(q))]
        np.testing.assert_allclose(det.score(q), ref, rtol=1e-9, atol=1e-9)

    def test_constant_feature_does_not_produce_nan(self):
        rng = np.random.default_rng(2)
        x = np.column_stack([rng.normal(size=300), np.full(300, 1012.0)])
        det = ECODDetector()
        self.assertTrue(det.fit(x))
        self.assertTrue(np.all(np.isfinite(det.score(x[:10]))))

    def test_outlier_scores_higher_than_inlier(self):
        rng = np.random.default_rng(3)
        det = ECODDetector()
        det.fit(rng.normal(size=(1000, 3)))
        s = det.score(np.array([[0.0, 0.0, 0.0], [5.0, -5.0, 5.0]]))
        self.assertGreater(s[1], s[0])


class TestIsolationForest(unittest.TestCase):

    def test_trains_and_returns_scores(self):
        rng = np.random.default_rng(0)
        det = IsolationForestDetector(100, "auto", 42)
        self.assertTrue(det.fit(rng.normal(size=(500, 4))))
        s = det.score(np.array([[0, 0, 0, 0], [6, 6, -6, 6]], dtype=float))
        self.assertGreater(s[1], s[0])

    def test_reproducible_with_fixed_random_state(self):
        rng = np.random.default_rng(1)
        x, q = rng.normal(size=(400, 3)), rng.normal(size=(30, 3))
        a, b = IsolationForestDetector(100, "auto", 7), IsolationForestDetector(100, "auto", 7)
        a.fit(x), b.fit(x)
        np.testing.assert_array_equal(a.score(q), b.score(q))


class TestConformalCalibration(unittest.TestCase):

    def test_p_values_bounded_and_monotone(self):
        c = ConformalCalibrator()
        c.fit(np.arange(99, dtype=float))
        p = c.p_values(np.array([-1.0, 50.0, 1000.0]))
        self.assertAlmostEqual(p[0], 1.0)
        self.assertAlmostEqual(p[2], 1.0 / 100.0)
        self.assertTrue(p[0] > p[1] > p[2])

    def test_false_alarm_rate_on_exchangeable_normal_data_is_near_alpha(self):
        rng = np.random.default_rng(5)
        data = rng.normal(size=(9000, 4))
        pair = DetectorPair(["a", "b", "c", "d"], _cfg())
        pair.fit(data[:3000], data[3000:5000])
        self.assertEqual(pair.feature_names, ["a", "b", "c", "d"])
        sc = pair.score(data[5000:])
        for name in ("ecod_p", "isolation_forest_p"):
            fpr = float(np.mean(sc[name] <= 0.05))
            self.assertLess(abs(fpr - 0.05), 0.015, name)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TestEnsembleDecision(unittest.TestCase):

    def test_both_normal_is_normal(self):
        d = decide(0.4, 0.3, 0.01)
        self.assertEqual(d.status, NORMAL)
        self.assertFalse(d.layer3_anomaly)
        self.assertLess(d.layer_score, 0.5)

    def test_both_flag_is_high_confidence_anomaly(self):
        d = decide(0.001, 0.004, 0.01)
        self.assertEqual((d.status, d.confidence), (ANOMALY, "HIGH"))
        self.assertTrue(d.layer3_anomaly)
        self.assertGreaterEqual(d.layer_score, 0.80)

    def test_one_flag_is_low_confidence_suspicious(self):
        for e, i in ((0.001, 0.5), (0.5, 0.001)):
            d = decide(e, i, 0.01)
            self.assertEqual((d.status, d.confidence), (SUSPICIOUS, "LOW"))
            self.assertFalse(d.layer3_anomaly)
            self.assertTrue(0.60 <= d.layer_score < 0.75)

    def test_single_available_model_cannot_reach_high_confidence(self):
        d = decide(0.0001, None, 0.01)
        self.assertEqual(d.status, SUSPICIOUS)
        self.assertIsNone(d.isolation_forest_anomaly)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TestOnlineLearning(unittest.TestCase):

    def _warm_engine(self, n=400, **kw):
        eng = OnlineMultivariateEngine(_cfg(**kw))
        rows = _station_series(n, seed=11)
        for ts, t, p, rh in rows:
            eng.evaluate("S", Observation(ts, t, p, rh, 77.2), lat=28.6, lon=77.2)
        return eng, rows

    def test_station_trains_own_model_after_min_samples(self):
        eng, rows = self._warm_engine(n=330, min_train_samples=300)
        ts = rows[-1][0] + timedelta(hours=1)
        res = eng.score("S", Observation(ts, 25.0, 1008.0, 50.0, 77.2), lat=28.6, lon=77.2)
        self.assertEqual(res["model_source"], "station_history")
        self.assertEqual(res["status_ml"], "EVALUATED")

    def test_no_model_without_history_or_reference(self):
        eng = OnlineMultivariateEngine(_cfg())
        res = eng.score("NEW", Observation(T0, 25.0, 1008.0, 50.0, 77.2))
        self.assertEqual(res["status_ml"], "NO_MODEL")

    def test_flagged_and_upstream_suspect_observations_are_not_learned(self):
        eng, rows = self._warm_engine(n=330, min_train_samples=300)
        st = eng.state("S")
        n0 = len(st.trusted)
        ts = rows[-1][0]
        eng.evaluate("S", Observation(ts + timedelta(hours=1), 26.0, 1008.0, 40.0, 77.2), upstream_suspect=True)
        self.assertEqual(len(st.trusted), n0)
        res = eng.score("S", Observation(ts + timedelta(hours=2), 26.0, 1008.0, 40.0, 77.2))
        eng.commit("S", Observation(ts + timedelta(hours=2), 26.0, 1008.0, 40.0, 77.2), res, trusted=False)
        self.assertEqual(len(st.trusted), n0)
        self.assertFalse(res["trusted_for_update"])

    def test_repeated_observation_is_not_appended_twice(self):
        eng = OnlineMultivariateEngine(_cfg())
        obs = Observation(T0, 25.0, 1008.0, 50.0, 77.2)
        eng.evaluate("S", obs)
        res = eng.evaluate("S", obs)
        self.assertTrue(res["duplicate_observation"])
        self.assertEqual(len(eng.state("S").trusted), 1)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Phase-3 scenarios on a synthetic REGIONAL REFERENCE (two climates, 3 years
# hourly). Physically structured: RH follows from T and a slowly varying dew
# point; P has a semi-diurnal tide, a seasonal cycle and weak synoptic
# coupling to T. Every test value is derived from that climate's own data.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from scipy.signal import lfilter
from multivariate.reference import ReferenceLibrary
from multivariate.features import relative_humidity_from_dew_point

SITES = {
    # name: lat, lon, T mean, T seasonal amp, T diurnal amp, Td mean, Td seasonal amp, P mean
    "DRY_INLAND": (26.9, 75.8, 26.0, 7.0, 7.0, 8.0, 8.0, 1006.0),
    "HUMID_COAST": (13.1, 80.3, 28.5, 2.0, 3.5, 23.0, 2.0, 1008.0),
}
REF_START, REF_YEARS, EVAL_YEAR = "2021-01-01", 3, 2024


def _ar1(n, rho, sd, rng):
    return lfilter([1.0], [1.0, -rho], rng.normal(0.0, sd, n))


def synthetic_site(name, start, hours, seed):
    lat, lon, t_m, t_s, t_d, td_m, td_s, p_m = SITES[name]
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    doy, solar = ts.dayofyear.to_numpy(), (ts.hour.to_numpy() + lon / 15.0) % 24
    season = np.cos(2 * np.pi * (doy - 135) / 365.0)
    t_syn = _ar1(hours, 0.98, 0.35, rng)
    t = t_m + t_s * season + t_d * np.cos(2 * np.pi * (solar - 15) / 24) + t_syn + rng.normal(0, 0.3, hours)
    td = td_m + td_s * np.cos(2 * np.pi * (doy - 200) / 365.0) + _ar1(hours, 0.985, 0.3, rng)
    td = np.minimum(td, t - 0.3)
    rh = np.round(np.clip(relative_humidity_from_dew_point(t, td), 1, 100))
    p = (p_m - 4.0 * season + 1.2 * np.cos(4 * np.pi * (solar - 10) / 24) - 0.25 * t_syn
         + _ar1(hours, 0.99, 0.25, rng))
    return pd.DataFrame({S.STATION_ID: name, S.TIMESTAMP: ts, S.TEMPERATURE: np.round(t, 1),
                         S.PRESSURE: np.round(p, 1), S.HUMIDITY: rh, S.LATITUDE: lat, S.LONGITUDE: lon})


class _RegionalScenario(unittest.TestCase):
    MONTH = 5

    @classmethod
    def setUpClass(cls):
        cls.cfg = MultivariateThresholds()
        cls.ref_frame = pd.concat([synthetic_site(n, REF_START, 24 * 365 * REF_YEARS, seed=i)
                                   for i, n in enumerate(SITES)], ignore_index=True)
        cls.ref = ReferenceLibrary.from_frame(cls.cfg, cls.ref_frame)
        cls._n = 0

    def layer(self):
        return MultivariateConsistencyLayer(config=self.cfg, reference=self.ref)

    def when(self, site, solar_hour, day=15, month=None):
        """UTC timestamp at the given local solar hour at `site` in EVAL_YEAR."""
        lon = SITES[site][1]
        base = pd.Timestamp(year=EVAL_YEAR, month=month or self.MONTH, day=day, tz="UTC")
        return (base + pd.Timedelta(hours=round((solar_hour - lon / 15.0) % 24))).to_pydatetime()

    def climate(self, site, solar_hour, width=1.0):
        """Reference rows of `site` in the evaluation month at solar_hour +- width."""
        f = self.ref_frame[self.ref_frame[S.STATION_ID] == site]
        lon = SITES[site][1]
        sol = (f[S.TIMESTAMP].dt.hour + lon / 15.0) % 24
        d = np.abs(((sol - solar_hour) + 12) % 24 - 12)
        return f[(f[S.TIMESTAMP].dt.month == self.MONTH) & (d <= width)]

    def evaluate(self, layer, site, t, p, rh, when, station_id=None, near=True):
        lat, lon = SITES[site][:2]
        type(self)._n += 1
        r = AWSReading(station_id=station_id or f"{site}_T{self._n}", lat=lat + (0.2 if near else 0), lon=lon,
                       temperature_c=float(t), pressure_hpa=float(p), humidity_pct=float(rh),
                       observation_timestamp=when)
        return layer.evaluate(r)

    @staticmethod
    def min_p(d):
        return min(d["ecod"]["p_value"], d["isolation_forest"]["p_value"])


class TestPhase3Scenarios(_RegionalScenario):

    def _matched(self, site="DRY_INLAND", hour=15):
        c = self.climate(site, hour)
        return c[S.TEMPERATURE].median(), c[S.PRESSURE].median(), c[S.HUMIDITY].median()

    # 1 â”€â”€ normal joint state
    def test_1_normal_multivariate_state_is_normal(self):
        t, p, rh = self._matched()
        _, _, d = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, self.when("DRY_INLAND", 15))
        self.assertEqual(d["model_source"], "regional_reference")
        self.assertEqual(d["decision"]["status"], NORMAL)

    def test_1b_held_out_normal_year_false_alarm_rate_is_low(self):
        held = synthetic_site("DRY_INLAND", f"{EVAL_YEAR}-05-01", 24 * 20, seed=99)
        layer = self.layer()
        statuses = [self.evaluate(layer, "DRY_INLAND", r.temperature_c, r.pressure_hpa, r.humidity_pct,
                                  r.timestamp.to_pydatetime(), station_id="HELD_OUT")[2]["decision"]["status"]
                    for r in held.itertuples()]
        self.assertLessEqual(np.mean([s == ANOMALY for s in statuses]), 0.03)

    # 2 â”€â”€ T-RH inconsistency
    def test_2_t_rh_inconsistency_increases_evidence_substantially(self):
        t, p, rh = self._matched()
        night_rh = self.climate("DRY_INLAND", 3)[S.HUMIDITY].median()
        self.assertGreaterEqual(night_rh - rh, 15)                     # a real decoupling
        c = self.climate("DRY_INLAND", 15)                             # both values individually plausible
        self.assertTrue(c[S.HUMIDITY].min() <= rh and night_rh <= self.ref_frame.loc[
            self.ref_frame[S.STATION_ID] == "DRY_INLAND", S.HUMIDITY].quantile(0.99))
        when = self.when("DRY_INLAND", 15)
        _, _, ok = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, when)
        score, reason, bad = self.evaluate(self.layer(), "DRY_INLAND", t, p, night_rh, when)
        self.assertNotEqual(bad["decision"]["status"], NORMAL)
        self.assertGreaterEqual(bad["relationships"]["t_rh"]["residual_z"], 3.0)
        self.assertLessEqual(self.min_p(bad) * 10, self.min_p(ok))
        self.assertGreater(score, 0.6)
        self.assertIn("temperature-humidity", reason)

    # 3 â”€â”€ pressure relationship / context
    def test_3_pressure_inconsistent_with_context_increases_evidence(self):
        t, p, rh = self._matched()
        season_p = self.ref_frame.loc[(self.ref_frame[S.STATION_ID] == "DRY_INLAND")
                                      & (self.ref_frame[S.TIMESTAMP].dt.month == self.MONTH), S.PRESSURE]
        p_bad = season_p.quantile(0.995)                                  # individually plausible for May
        self.assertGreater(p_bad - p, 3.0)
        when = self.when("DRY_INLAND", 15)
        _, _, ok = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, when)
        _, _, bad = self.evaluate(self.layer(), "DRY_INLAND", t, p_bad, rh, when)
        self.assertTrue(bad["relationships"]["t_p"]["used_by_models"])
        self.assertGreaterEqual(bad["relationships"]["t_p"]["residual_z"], 2.5)
        self.assertLessEqual(self.min_p(bad) * 10, self.min_p(ok))
        self.assertGreater(bad["decision"]["layer_score"], ok["decision"]["layer_score"])

    # 4 â”€â”€ joint anomaly, nothing individually out of range
    def test_4_joint_anomaly_without_single_out_of_range_value_is_flagged(self):
        """Depends on the P|T residual being a model column (the default).
        Without it this state gets ECOD p=0.028 / Isolation Forest p=0.013 at
        alpha=0.01 and is NOT flagged — see config.use_pressure_temperature_residual."""
        c = self.climate("DRY_INLAND", 15)
        vals = {col: c[col].quantile(0.975) for col in (S.TEMPERATURE, S.HUMIDITY, S.PRESSURE)}
        for col, v in vals.items():                          # each value individually plausible
            self.assertTrue(c[col].quantile(0.01) <= v <= c[col].quantile(0.99))
        # ...but the combination never occurred in 3 years of this climate at this hour and season
        joint = (c[S.TEMPERATURE] >= vals[S.TEMPERATURE]) & (c[S.HUMIDITY] >= vals[S.HUMIDITY]) \
            & (c[S.PRESSURE] >= vals[S.PRESSURE])
        self.assertEqual(int(joint.sum()), 0)
        _, _, d = self.evaluate(self.layer(), "DRY_INLAND", vals[S.TEMPERATURE], vals[S.PRESSURE],
                                vals[S.HUMIDITY], self.when("DRY_INLAND", 15))
        self.assertIn(d["decision"]["status"], (SUSPICIOUS, ANOMALY))

    # 5 â”€â”€ normal diurnal extreme
    def test_5_extreme_but_normal_for_the_hour_is_not_flagged(self):
        c = self.climate("DRY_INLAND", 15)
        hot = c[c[S.TEMPERATURE] >= c[S.TEMPERATURE].quantile(0.97)]
        t, rh, p = hot[S.TEMPERATURE].median(), hot[S.HUMIDITY].median(), hot[S.PRESSURE].median()
        self.assertGreater(t, self.ref_frame.loc[self.ref_frame[S.STATION_ID] == "DRY_INLAND",
                                                 S.TEMPERATURE].quantile(0.95))   # extreme overall
        _, _, d15 = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, self.when("DRY_INLAND", 15))
        self.assertEqual(d15["decision"]["status"], NORMAL)
        # the same values at 03:00 are far outside that hour's normal -> strong evidence
        _, _, d03 = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, self.when("DRY_INLAND", 3))
        self.assertNotEqual(d03["decision"]["status"], NORMAL)

    # 6 â”€â”€ station awareness
    def test_6_same_reading_is_normal_at_one_station_and_anomalous_at_another(self):
        c = self.climate("HUMID_COAST", 15)
        t, p, rh = c[S.TEMPERATURE].median(), c[S.PRESSURE].median(), c[S.HUMIDITY].median()
        when = self.when("HUMID_COAST", 15)
        _, _, coast = self.evaluate(self.layer(), "HUMID_COAST", t, p, rh, when)
        _, _, dry = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, when)
        self.assertEqual((coast["reference_site"], dry["reference_site"]), ("HUMID_COAST", "DRY_INLAND"))
        self.assertEqual(coast["decision"]["status"], NORMAL)
        self.assertNotEqual(dry["decision"]["status"], NORMAL)

    # 7 â”€â”€ cold start
    def test_7_cold_start_uses_regional_reference_and_far_station_is_labelled_fallback(self):
        t, p, rh = self._matched()
        _, _, d = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, self.when("DRY_INLAND", 15))
        self.assertEqual(d["model_source"], "regional_reference")
        self.assertEqual(d["station_trusted_history"], 0)
        far = AWSReading(station_id="FAR_AWAY", lat=45.0, lon=10.0, temperature_c=t, pressure_hpa=p,
                         humidity_pct=rh, observation_timestamp=self.when("DRY_INLAND", 15))
        _, _, f = self.layer().evaluate(far)
        self.assertEqual((f["method"], f["status_ml"]), ("3D_static_prior_fallback", "INSUFFICIENT_TRAINING_DATA"))

    def test_7b_own_model_replaces_reference_only_after_takeover_threshold(self):
        import copy
        cfg = copy.deepcopy(self.cfg)
        cfg.min_train_samples, cfg.station_model_takeover_samples = 200, 450
        layer = MultivariateConsistencyLayer(config=cfg, reference=self.ref)
        hist = synthetic_site("DRY_INLAND", f"{EVAL_YEAR}-05-01", 520, seed=7)
        sources = []
        for r in hist.itertuples():
            _, _, d = self.evaluate(layer, "DRY_INLAND", r.temperature_c, r.pressure_hpa, r.humidity_pct,
                                    r.timestamp.to_pydatetime(), station_id="GROWING")
            sources.append((len(layer.states["GROWING"].trusted), d["model_source"]))
        n_at_switch = next(n for n, s in sources if s == "station_history")
        self.assertGreaterEqual(n_at_switch, 450)                       # not at min_train_samples (200)
        self.assertTrue(all(s == "regional_reference" for n, s in sources if n < 450))

    # 8 â”€â”€ online learning safety
    def test_8_anomalous_reading_does_not_enter_station_history(self):
        layer = self.layer()
        t, p, rh = self._matched()
        night_rh = self.climate("DRY_INLAND", 3)[S.HUMIDITY].median()
        when = self.when("DRY_INLAND", 15)
        _, _, ok = self.evaluate(layer, "DRY_INLAND", t, p, rh, when, station_id="SAFE")
        self.assertTrue(ok["trusted_for_update"])
        self.assertEqual(len(layer.states["SAFE"].trusted), 1)
        _, _, bad = self.evaluate(layer, "DRY_INLAND", t, p, night_rh, when + timedelta(hours=24), station_id="SAFE")
        self.assertNotEqual(bad["decision"]["status"], NORMAL)
        self.assertFalse(bad["trusted_for_update"])
        self.assertEqual(len(layer.states["SAFE"].trusted), 1)
        hum = [o.humidity_pct for o, _ in layer.states["SAFE"].trusted]
        self.assertNotIn(float(night_rh), hum)

    # 9 â”€â”€ timestamp correctness
    def test_9_season_and_hour_come_from_the_observation_time_never_now(self):
        t, p, rh = self._matched()
        jan = self.when("DRY_INLAND", 15, month=1)
        _, _, d = self.evaluate(self.layer(), "DRY_INLAND", t, p, rh, jan)
        self.assertEqual(d["reference_month"], 1)
        # unverified time: no seasonal/diurnal model, not learned (never "assume now")
        layer = self.layer()
        _, _, u = layer.evaluate(AWSReading(station_id="NO_TIME", lat=26.9, lon=75.8, temperature_c=t,
                                            pressure_hpa=p, humidity_pct=rh))
        self.assertEqual(u["status_ml"], "OBSERVATION_TIME_UNKNOWN")
        self.assertNotIn("NO_TIME", layer.states)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TestLayerContract(unittest.TestCase):

    def setUp(self):
        self.layer = MultivariateConsistencyLayer(config=_cfg())

    def test_zero_and_one_valid_channel_is_insufficient(self):
        for r in (AWSReading(station_id="S1"), AWSReading(station_id="S1", temperature_c=22.0)):
            score, _, d = self.layer.evaluate(r)
            self.assertEqual((score, d["status"]), (0.0, "INSUFFICIENT_DATA"))

    def test_nan_and_inf_channels_are_not_counted_valid(self):
        _, _, d = self.layer.evaluate(AWSReading(station_id="S1", temperature_c=float("nan"), pressure_hpa=1012.0, humidity_pct=55.0))
        self.assertEqual(d["valid_channel_count"], 2)
        _, _, d = self.layer.evaluate(AWSReading(station_id="S1", temperature_c=22.0, pressure_hpa=float("inf"), humidity_pct=55.0))
        self.assertEqual(d["valid_channel_count"], 2)

    def test_no_model_uses_labelled_static_fallback(self):
        _, _, d = self.layer.evaluate(AWSReading(station_id="FAR", temperature_c=25.0, pressure_hpa=1012.0,
                                                 humidity_pct=55.0, observation_timestamp=T0))
        self.assertEqual(d["method"], "3D_static_prior_fallback")
        self.assertEqual(d["status_ml"], "INSUFFICIENT_TRAINING_DATA")

    def test_unknown_observation_time_is_not_modelled_or_learned(self):
        layer = MultivariateConsistencyLayer(config=MultivariateThresholds())   # reference enabled
        _, _, d = layer.evaluate(AWSReading(station_id="SNAP", lat=17.38, lon=78.48, temperature_c=32.4,
                                            pressure_hpa=1008.0, humidity_pct=68.0))
        self.assertEqual(d["status_ml"], "OBSERVATION_TIME_UNKNOWN")
        self.assertFalse(d["trusted_for_update"])
        self.assertNotIn("SNAP", layer.states)

    def test_two_valid_channels_use_bivariate_rule(self):
        _, _, d = self.layer.evaluate(AWSReading(station_id="S2", temperature_c=25.0, pressure_hpa=1012.0))
        self.assertTrue(d["method"].startswith("2D_bivariate"))

    def test_clausius_clapeyron_rule_still_fires(self):
        score, reason, _ = self.layer.evaluate(AWSReading(station_id="CC", temperature_c=36.0, pressure_hpa=1005.0, humidity_pct=98.0))
        self.assertGreaterEqual(score, 0.85)
        self.assertIn("saturation", reason)


class TestRegionalReference(unittest.TestCase):
    """Runs only when the Open-Meteo reference data (or its cache) is present."""

    def setUp(self):
        from multivariate.reference import ReferenceLibrary
        self.cfg = MultivariateThresholds()
        self.ref = ReferenceLibrary(self.cfg)
        if self.ref.nearest_site(28.6, 77.2) is None:
            self.skipTest("reference data not available")

    def test_live_station_near_delhi_uses_delhi_reference(self):
        site, km = self.ref.nearest_site(28.5, 77.1)
        self.assertEqual(site, "Delhi")
        self.assertLess(km, self.cfg.reference_max_distance_km)
        self.assertIsNone(self.ref.nearest_site(51.5, -0.1))   # London: no Indian reference


class TestPipelineCompatibility(unittest.TestCase):

    def test_detector_output_shape_is_unchanged(self):
        det = AnomalyDetector()
        alert = det.evaluate_reading(AWSReading(station_id="API", temperature_c=25.0, pressure_hpa=1012.0, humidity_pct=55.0))
        self.assertIn("multivariate", alert.layer_scores)
        card = alert.canonical_result["layers"]["multivariate"]
        for key in ("name", "status", "score", "evidence_quality", "reason", "details"):
            self.assertIn(key, card)
        self.assertEqual(alert.layer_details["multivariate"]["valid_channel_count"], 3)
        self.assertNotIn("_features_raw", alert.layer_details["multivariate"])


if __name__ == "__main__":
    unittest.main()
