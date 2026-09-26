"""
Unit tests for Stage 2 (temporal_lstm/*) — the standalone LSTM next-step
predictor. These tests do NOT touch layer2_temporal.py, fusion, root
cause, the API, or the production anomaly engine: Stage 2 is a standalone,
isolated pipeline (dataset -> windows -> LSTM -> evaluation -> inference).
"""
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import torch

from temporal_lstm.config import TemporalLSTMConfig
from temporal_lstm.dataset import (
    load_dataset, add_time_features, fit_scaler,
    build_split_windows, run_data_quality_checks, DataQualityError,
)
from temporal_lstm.model import TemporalLSTM
from temporal_lstm.utils import set_seed, get_device
from temporal_lstm.train import train


def _tiny_cfg(output_dir: str, **overrides) -> TemporalLSTMConfig:
    cfg = TemporalLSTMConfig(max_epochs=1, patience=1, batch_size=64)
    cfg.output_dir = __import__("pathlib").Path(output_dir)
    return replace(cfg, **overrides) if overrides else cfg


class TestTemporalLSTMDataset(unittest.TestCase):
    """Windowing/scaling correctness — does not require training a model."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = TemporalLSTMConfig()
        cls.df = load_dataset(cls.cfg)
        cls.qc_report = run_data_quality_checks(cls.df, cls.cfg)
        cls.df = add_time_features(cls.df)
        cls.scaler = fit_scaler(cls.df, cls.cfg)

    def test_sequence_length_is_144(self):
        X, y, _ = build_split_windows(self.df, "train", self.cfg, self.scaler)
        self.assertEqual(X.shape[1], 144)

    def test_input_feature_dimension_is_5(self):
        X, y, _ = build_split_windows(self.df, "train", self.cfg, self.scaler)
        self.assertEqual(X.shape[2], 5)
        self.assertEqual(self.cfg.feature_columns,
                          ["temperature_c", "pressure_hpa", "relative_humidity_pct", "hour_sin", "hour_cos"])

    def test_target_dimension_is_3(self):
        X, y, _ = build_split_windows(self.df, "train", self.cfg, self.scaler)
        self.assertEqual(y.shape[1], 3)

    def test_windows_do_not_cross_station_boundaries(self):
        """Each window is built from one station's own contiguous slice —
        verify by checking a station's window count matches the expected
        formula and that no cross-station mixing occurred (spot-check via
        per-station window count consistency, since all stations here have
        the same 1008-row length)."""
        X, y, station_ids = build_split_windows(self.df, "train", self.cfg, self.scaler)
        n_per_station = 1008
        expected_per_station = len(range(0, n_per_station - self.cfg.sequence_length, self.cfg.stride))
        self.assertEqual(len(X), expected_per_station * len(station_ids))

    def test_windows_do_not_cross_split_boundaries(self):
        train_ids = set(self.df[self.df.split == "train"].station_id.unique())
        val_ids = set(self.df[self.df.split == "val"].station_id.unique())
        test_ids = set(self.df[self.df.split == "test"].station_id.unique())
        self.assertEqual(train_ids & val_ids, set())
        self.assertEqual(train_ids & test_ids, set())
        self.assertEqual(val_ids & test_ids, set())

        _, _, train_station_ids = build_split_windows(self.df, "train", self.cfg, self.scaler)
        _, _, val_station_ids = build_split_windows(self.df, "val", self.cfg, self.scaler)
        self.assertEqual(set(train_station_ids) & set(val_station_ids), set())

    def test_scaler_fitted_only_on_training_data(self):
        """The scaler's fitted mean must match the TRAIN split's own mean,
        not the full dataset's mean (which would indicate a leak)."""
        train_rows = self.df.loc[self.df["split"] == "train", self.cfg.scale_columns]
        full_rows = self.df[self.cfg.scale_columns]

        train_mean = train_rows.mean().to_numpy()
        full_mean = full_rows.mean().to_numpy()

        np.testing.assert_allclose(self.scaler.mean_, train_mean, rtol=1e-8)
        # Sanity check that this test isn't vacuous: the train-only mean must
        # differ measurably from the full-dataset mean, otherwise fitting on
        # "train only" vs "everything" would be indistinguishable here.
        self.assertTrue(np.any(np.abs(train_mean - full_mean) > 1e-6))

    def test_data_quality_checks_pass_on_real_dataset(self):
        report = run_data_quality_checks(self.df, self.cfg)
        self.assertEqual(report["duplicate_rows"], 0)
        self.assertEqual(report["missing_values"], 0)
        self.assertEqual(report["station_split_overlap"], 0)

    def test_data_quality_check_rejects_missing_column(self):
        bad_df = self.df.drop(columns=["pressure_hpa"])
        with self.assertRaises(DataQualityError):
            run_data_quality_checks(bad_df, self.cfg)

    def test_data_quality_check_rejects_duplicate_rows(self):
        bad_df = pd_concat_dup(self.df)
        with self.assertRaises(DataQualityError):
            run_data_quality_checks(bad_df, self.cfg)


def pd_concat_dup(df):
    import pandas as pd
    dup_row = df.iloc[[0]]
    return pd.concat([df, dup_row], ignore_index=True)


class TestTemporalLSTMModel(unittest.TestCase):

    def test_model_output_shape(self):
        cfg = TemporalLSTMConfig()
        model = TemporalLSTM.from_config(cfg)
        x = torch.randn(8, cfg.sequence_length, cfg.input_size)
        out = model(x)
        self.assertEqual(tuple(out.shape), (8, cfg.output_size))


class TestTemporalLSTMTrainingSmoke(unittest.TestCase):
    """End-to-end smoke test: trains for 1 epoch on the REAL Stage 1
    dataset (small epoch count keeps this fast), then verifies the saved
    model can be reloaded and produces deterministic, finite inference."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="ather_lstm_test_")
        cfg = _tiny_cfg(cls.tmp_dir)
        set_seed(cfg.seed)
        cls.result = train(cfg)
        cls.cfg = cfg

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_saved_model_can_be_reloaded(self):
        model = TemporalLSTM.from_config(self.cfg)
        state_dict = torch.load(f"{self.tmp_dir}/{self.cfg.model_filename}", map_location="cpu")
        model.load_state_dict(state_dict)  # must not raise

    def test_inference_produces_finite_physical_values(self):
        from temporal_lstm.inference import TemporalLSTMPredictor
        from temporal_lstm.dataset import load_dataset

        predictor = TemporalLSTMPredictor(model_dir=self.tmp_dir)
        df = load_dataset(TemporalLSTMConfig())
        one_station = df[df.station_id == sorted(df.station_id.unique())[0]].sort_values("timestamp").head(144)
        pred = predictor.predict_next(one_station[["timestamp", "temperature_c", "pressure_hpa", "relative_humidity_pct"]])

        self.assertEqual(set(pred.keys()), {"temperature_c", "pressure_hpa", "relative_humidity_pct"})
        for v in pred.values():
            self.assertTrue(np.isfinite(v))

    def test_repeated_inference_is_deterministic_in_eval_mode(self):
        from temporal_lstm.inference import TemporalLSTMPredictor
        from temporal_lstm.dataset import load_dataset

        predictor = TemporalLSTMPredictor(model_dir=self.tmp_dir)
        df = load_dataset(TemporalLSTMConfig())
        one_station = df[df.station_id == sorted(df.station_id.unique())[0]].sort_values("timestamp").head(144)
        history = one_station[["timestamp", "temperature_c", "pressure_hpa", "relative_humidity_pct"]]

        pred_a = predictor.predict_next(history)
        pred_b = predictor.predict_next(history)
        self.assertEqual(pred_a, pred_b)

    def test_metrics_file_reports_physical_units_not_only_scaled_mse(self):
        metrics = self.result["metrics"]
        self.assertIn("test_metrics_physical_units", metrics)
        for ch in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
            self.assertIn("mae", metrics["test_metrics_physical_units"][ch])
            self.assertIn("rmse", metrics["test_metrics_physical_units"][ch])


if __name__ == "__main__":
    unittest.main()
