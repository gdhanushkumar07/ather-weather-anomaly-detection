"""
Unit tests for Stage 3 (temporal_anomalies/*) — anomaly injection and LSTM
residual evaluation. These tests do NOT touch layer2_temporal.py, fusion,
root cause, the API, or the production anomaly engine.

Fast synthetic-fixture tests cover the injection functions directly
(no need to run the full 7,500-case experiment); a few tests exercise the
real Stage 1 dataset / Stage 2 model read-only, matching the "must remain
unchanged" requirements (spec section 21, items 11/12/14/15).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import pandas as pd

from temporal_anomalies.config import AnomalyInjectionConfig
from temporal_anomalies.utils import scenario_rng
from temporal_anomalies import scenarios as sc


def _make_station_df(n: int = 300, station_id: str = "TEST-STATION") -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=10 * i) for i in range(n)]
    rng = np.random.default_rng(0)
    temp = 20.0 + 3.0 * np.sin(np.linspace(0, 6 * np.pi, n)) + rng.normal(0, 0.05, n)
    press = 1013.0 + rng.normal(0, 0.05, n)
    rh = 60.0 + 5.0 * np.cos(np.linspace(0, 6 * np.pi, n)) + rng.normal(0, 0.1, n)
    return pd.DataFrame({
        "station_id": station_id,
        "timestamp": timestamps,
        "temperature_c": temp,
        "pressure_hpa": press,
        "relative_humidity_pct": rh,
        "split": "test",
        "is_anomaly": False,
        "anomaly_type": "none",
        "missing_channel": None,
    })


class TestAnomalyScenarios(unittest.TestCase):

    def setUp(self):
        self.cfg = AnomalyInjectionConfig()
        self.station_df = _make_station_df()
        self.rng = scenario_rng(42, "TEST-STATION", "unit-test", 0)

    def test_01_temperature_spike_changes_only_intended_timestep_and_channel(self):
        df = self.station_df.copy()
        original = df.copy()
        start = 150
        result_df, meta = sc.inject_temperature_step(df, start, self.cfg, self.rng, direction="spike")

        changed_mask = pd.Series(
            ~np.isclose(result_df["temperature_c"], original["temperature_c"]),
            index=result_df.index,
        )
        self.assertEqual(list(changed_mask[changed_mask].index), [start])
        # pressure/humidity must be completely untouched
        pd.testing.assert_series_equal(result_df["pressure_hpa"], original["pressure_hpa"])
        pd.testing.assert_series_equal(result_df["relative_humidity_pct"], original["relative_humidity_pct"])
        self.assertEqual(meta["duration_steps"], 1)
        self.assertEqual(meta["affected_channel"], "temperature_c")

    def test_02_temperature_drop_has_requested_negative_magnitude(self):
        df = self.station_df.copy()
        start = 150
        _, meta = sc.inject_temperature_step(df, start, self.cfg, self.rng, direction="drop")
        lo, hi = self.cfg.drop_magnitude_c
        self.assertLess(meta["magnitude"], 0)
        self.assertGreaterEqual(meta["magnitude"], lo)
        self.assertLessEqual(meta["magnitude"], hi)

    def test_03_frozen_temperature_repeats_selected_value(self):
        df = self.station_df.copy()
        start = 150
        expected_value = df.loc[start - 1, "temperature_c"]
        result_df, meta = sc.inject_frozen_channel(df, start, self.cfg, self.rng, channel="temperature_c")
        end = start + meta["duration_steps"] - 1
        frozen_slice = result_df.loc[start:end, "temperature_c"]
        self.assertTrue((frozen_slice == expected_value).all())
        self.assertTrue((result_df.loc[start:end, "is_anomaly"]).all())

    def test_04_frozen_humidity_repeats_selected_value(self):
        df = self.station_df.copy()
        start = 150
        expected_value = df.loc[start - 1, "relative_humidity_pct"]
        result_df, meta = sc.inject_frozen_channel(df, start, self.cfg, self.rng, channel="relative_humidity_pct")
        end = start + meta["duration_steps"] - 1
        frozen_slice = result_df.loc[start:end, "relative_humidity_pct"]
        self.assertTrue((frozen_slice == expected_value).all())

    def test_05_drift_is_monotonic_in_intended_direction(self):
        df = self.station_df.copy()
        start = 150
        result_df, meta = sc.inject_temperature_drift(df, start, self.cfg, self.rng)
        end = start + meta["duration_steps"] - 1
        drifted = result_df.loc[start:end, "temperature_c"].to_numpy()
        original = self.station_df.loc[start:end, "temperature_c"].to_numpy()
        added_component = drifted - original
        # The INJECTED drift component itself (isolated from the underlying
        # station signal's own natural wiggle) must be monotonically
        # increasing, matching the positive drift_rate_c_per_step config.
        self.assertTrue(np.all(np.diff(added_component) > 0))
        self.assertGreater(meta["magnitude"], 0)

    def test_06_pressure_offset_within_configured_range(self):
        df = self.station_df.copy()
        start = 150
        _, meta = sc.inject_pressure_offset(df, start, self.cfg, self.rng)
        lo, hi = self.cfg.pressure_offset_hpa
        self.assertGreaterEqual(abs(meta["magnitude"]), lo)
        self.assertLessEqual(abs(meta["magnitude"]), hi)

    def test_07_humidity_offset_respects_0_100_bounds(self):
        df = self.station_df.copy()
        start = 150
        result_df, meta = sc.inject_humidity_offset(df, start, self.cfg, self.rng)
        end = start + meta["duration_steps"] - 1
        self.assertTrue((result_df.loc[start:end, "relative_humidity_pct"] >= 0.0).all())
        self.assertTrue((result_df.loc[start:end, "relative_humidity_pct"] <= 100.0).all())

    def test_08_noise_burst_has_intended_duration(self):
        df = self.station_df.copy()
        start = 150
        _, meta = sc.inject_noise_burst(df, start, self.cfg, self.rng, channel="temperature_c")
        lo, hi = self.cfg.noise_burst_duration_steps
        self.assertGreaterEqual(meta["duration_steps"], lo)
        self.assertLessEqual(meta["duration_steps"], hi)

    def test_09_missing_values_are_nan_not_zero(self):
        df = self.station_df.copy()
        start = 150
        result_df, meta = sc.inject_missing_observation(df, start, self.cfg, self.rng, channel="pressure_hpa")
        end = start + meta["duration_steps"] - 1
        missing_slice = result_df.loc[start:end, "pressure_hpa"]
        self.assertTrue(missing_slice.isna().all())
        self.assertFalse((missing_slice == 0).any())  # NaN != 0, but explicit per spec intent
        self.assertEqual(meta["missing_channel"], "pressure_hpa")

    def test_10_stale_packet_repeats_all_three_channels(self):
        df = self.station_df.copy()
        start = 150
        expected = df.loc[start - 1, ["temperature_c", "pressure_hpa", "relative_humidity_pct"]]
        result_df, meta = sc.inject_stale_packet(df, start, self.cfg, self.rng)
        end = start + meta["duration_steps"] - 1
        for ch in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
            self.assertTrue((result_df.loc[start:end, ch] == expected[ch]).all())

    def test_11_no_anomaly_begins_before_timestep_144(self):
        from temporal_anomalies.injector import _pick_start_index
        rng = scenario_rng(42, "TEST-STATION", "temperature_spike", 0)
        for _ in range(200):
            start = _pick_start_index(rng, self.cfg, station_len=1008, max_duration=1)
            self.assertGreaterEqual(start, self.cfg.min_history_before_anomaly)

    def test_13_same_seed_produces_deterministic_injections(self):
        df_a = self.station_df.copy()
        df_b = self.station_df.copy()
        rng_a = scenario_rng(42, "TEST-STATION", "temperature_spike", 0)
        rng_b = scenario_rng(42, "TEST-STATION", "temperature_spike", 0)
        _, meta_a = sc.inject_temperature_step(df_a, 150, self.cfg, rng_a, direction="spike")
        _, meta_b = sc.inject_temperature_step(df_b, 150, self.cfg, rng_b, direction="spike")
        self.assertEqual(meta_a["magnitude"], meta_b["magnitude"])

    def test_16_residual_calculations_finite_for_valid_input(self):
        """Uses the real trained Stage 2 model on a clean (no-anomaly)
        window — residuals must be finite floats, never NaN/inf, whenever
        the input actually contains no missing values."""
        from temporal_lstm.dataset import add_time_features
        from temporal_anomalies.evaluate import load_stage2_artifacts
        from temporal_anomalies.config import AnomalyInjectionConfig as Cfg
        from temporal_anomalies.windowing import build_dense_predictions

        cfg = Cfg()
        model, scaler, lstm_cfg, device = load_stage2_artifacts(cfg.stage2_model_dir)
        df = _make_station_df(n=200)
        df = add_time_features(df)
        result = build_dense_predictions(
            df, lstm_cfg["sequence_length"], lstm_cfg["feature_columns"],
            lstm_cfg["target_columns"], lstm_cfg["scale_columns"], scaler, model, device,
        )
        available = result[result["residual_available"]]
        self.assertGreater(len(available), 0)
        for ch in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
            self.assertTrue(np.isfinite(available[f"residual_{ch}"]).all())
            self.assertTrue(np.isfinite(available[f"abs_residual_{ch}"]).all())


class TestStage1DatasetUnchanged(unittest.TestCase):
    """Spec section 21, items 12/14: Stage 3 must never touch Stage 1's
    dataset or its station-level split."""

    def test_12_original_normal_dataset_unchanged(self):
        from temporal_anomalies.config import AnomalyInjectionConfig as Cfg
        cfg = Cfg()
        path = cfg.stage1_dataset_dir / cfg.stage1_dataset_filename
        mtime_before = os.path.getmtime(path)
        # Merely importing/using the Stage 3 package must not touch this file.
        import temporal_anomalies.evaluate  # noqa: F401
        mtime_after = os.path.getmtime(path)
        self.assertEqual(mtime_before, mtime_after)

    def test_14_station_split_unchanged(self):
        from temporal_anomalies.config import AnomalyInjectionConfig as Cfg
        cfg = Cfg()
        df = pd.read_csv(cfg.stage1_dataset_dir / cfg.stage1_dataset_filename)
        counts = df.groupby("split")["station_id"].nunique().to_dict()
        self.assertEqual(counts.get("train"), 350)
        self.assertEqual(counts.get("val"), 75)
        self.assertEqual(counts.get("test"), 75)


class TestStage2ModelUnchanged(unittest.TestCase):
    """Spec section 21, item 15: Stage 3 must never retrain or mutate the
    Stage 2 model weights."""

    def test_15_model_weights_unchanged_after_stage3_pass(self):
        from temporal_anomalies.evaluate import load_stage2_artifacts, _model_weight_fingerprint
        from temporal_anomalies.config import AnomalyInjectionConfig as Cfg
        from temporal_lstm.dataset import add_time_features
        from temporal_anomalies.windowing import build_dense_predictions

        cfg = Cfg()
        model, scaler, lstm_cfg, device = load_stage2_artifacts(cfg.stage2_model_dir)
        fingerprint_before = _model_weight_fingerprint(model)

        df = add_time_features(_make_station_df(n=200))
        build_dense_predictions(
            df, lstm_cfg["sequence_length"], lstm_cfg["feature_columns"],
            lstm_cfg["target_columns"], lstm_cfg["scale_columns"], scaler, model, device,
        )

        fingerprint_after = _model_weight_fingerprint(model)
        self.assertEqual(fingerprint_before, fingerprint_after)


if __name__ == "__main__":
    unittest.main()
