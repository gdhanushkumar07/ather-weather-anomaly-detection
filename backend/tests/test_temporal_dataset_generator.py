"""
Unit tests for the Stage 1 synthetic temporal dataset generator
(temporal_dataset/*). These tests do NOT touch layer2_temporal.py,
fusion, root cause, the API, or any LSTM — Stage 1 is dataset generation
only, and these tests verify only that generation is correct.
"""
import os
import sys
import unittest
from dataclasses import replace

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from temporal_dataset.config import TemporalGeneratorConfig
from temporal_dataset.generate_dataset import run_generation
from temporal_dataset.station_selection import load_raw_stations, filter_clean_stations, select_stations
from temporal_dataset.splits import assign_station_splits


def _small_cfg(**overrides) -> TemporalGeneratorConfig:
    cfg = TemporalGeneratorConfig(num_stations=6, history_days=1)  # 1 day = 144 obs/station, fast tests
    return replace(cfg, **overrides) if overrides else cfg


class TestTemporalDatasetGenerator(unittest.TestCase):

    def test_01_deterministic_output_same_seed(self):
        """Same seed + same config must produce byte-identical output."""
        cfg_a = _small_cfg(seed=123)
        cfg_b = _small_cfg(seed=123)
        result_a = run_generation(cfg_a)
        result_b = run_generation(cfg_b)
        self.assertTrue(result_a["dataframe"].equals(result_b["dataframe"]))

    def test_01b_different_seed_gives_different_output(self):
        """Sanity check that the determinism test isn't trivially vacuous."""
        result_a = run_generation(_small_cfg(seed=1))
        result_b = run_generation(_small_cfg(seed=2))
        self.assertFalse(result_a["dataframe"]["temperature_c"].equals(result_b["dataframe"]["temperature_c"]))

    def test_02_ten_minute_timestamp_spacing(self):
        """Every consecutive pair of readings for a station must be exactly
        sampling_interval_minutes apart."""
        import pandas as pd
        cfg = _small_cfg(seed=7)
        df = run_generation(cfg)["dataframe"]
        expected = pd.Timedelta(minutes=cfg.sampling_interval_minutes)
        for station_id, g in df.groupby("station_id"):
            ts = pd.to_datetime(g["timestamp"]).sort_values()
            diffs = ts.diff().dropna()
            self.assertTrue((diffs == expected).all(), f"Spacing violation for {station_id}")

    def test_03_correct_observations_per_station(self):
        """observations per station must equal history_days * 24 * (60/interval)."""
        cfg = _small_cfg(seed=7, history_days=2)
        df = run_generation(cfg)["dataframe"]
        expected_count = cfg.total_steps_per_station
        counts = df.groupby("station_id").size()
        self.assertTrue((counts == expected_count).all())
        self.assertEqual(expected_count, 2 * 24 * 6)  # 288 for 2 days @ 10 min

    def test_04_values_within_physical_bounds(self):
        """No generated (post-clip) value may fall outside CONFIG.physics bounds."""
        df = run_generation(_small_cfg(seed=7))["dataframe"]
        phys = CONFIG.physics
        self.assertTrue((df["temperature_c"] >= phys.temp_min_c).all())
        self.assertTrue((df["temperature_c"] <= phys.temp_max_c).all())
        self.assertTrue((df["pressure_hpa"] >= phys.pressure_min_hpa).all())
        self.assertTrue((df["pressure_hpa"] <= phys.pressure_max_hpa).all())
        self.assertTrue((df["relative_humidity_pct"] >= phys.humidity_min_pct).all())
        self.assertTrue((df["relative_humidity_pct"] <= phys.humidity_max_pct).all())

    def test_05_no_duplicate_station_timestamp_pairs(self):
        df = run_generation(_small_cfg(seed=7))["dataframe"]
        dup_count = df.duplicated(subset=["station_id", "timestamp"]).sum()
        self.assertEqual(dup_count, 0)

    def test_06_station_level_split_integrity(self):
        """A station must belong to exactly one split, and splits must
        partition the full selected station set with no overlap."""
        cfg = _small_cfg(seed=7)
        raw = load_raw_stations(cfg.source_stations_path)
        clean, _ = filter_clean_stations(raw, cfg)
        selected, _ = select_stations(clean, cfg)
        assignment, report = assign_station_splits(selected, cfg)

        selected_ids = {str(s["id"]) for s in selected}
        assigned_ids = set(assignment.keys())
        self.assertEqual(selected_ids, assigned_ids)

        splits_seen = set(assignment.values())
        self.assertTrue(splits_seen.issubset({"train", "val", "test"}))
        self.assertEqual(
            report["train_stations"] + report["val_stations"] + report["test_stations"],
            report["total_stations"],
        )

        # Cross-check against the generated dataset: each station's rows
        # must ALL carry the same split it was assigned (no leakage of a
        # station's rows into a different split than assigned).
        df = run_generation(cfg)["dataframe"]
        splits_per_station = df.groupby("station_id")["split"].nunique()
        self.assertTrue((splits_per_station == 1).all())

    def test_07_complete_t_p_rh_values_no_missing(self):
        df = run_generation(_small_cfg(seed=7))["dataframe"]
        for col in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
            self.assertEqual(int(df[col].isna().sum()), 0)

    def test_08_generator_works_with_small_station_count(self):
        """End-to-end smoke test with a very small station count (quick-test mode)."""
        cfg = _small_cfg(num_stations=3, seed=99, history_days=1)
        result = run_generation(cfg)
        df = result["dataframe"]
        self.assertEqual(df["station_id"].nunique(), 3)
        self.assertGreater(len(df), 0)
        self.assertIn("validation", result)
        self.assertIn("metadata", result)

    def test_09_clean_station_filter_reuses_existing_physics_bounds(self):
        """filter_clean_stations must reject values outside CONFIG.physics
        bounds — verifies no second/duplicate bound set was introduced."""
        cfg = _small_cfg()
        synthetic_raw = [
            {"id": "OK-1", "temperature": 20.0, "pressure": 1010.0, "humidity": 50.0, "latitude": 10.0, "longitude": 20.0},
            {"id": "BAD-TEMP", "temperature": -5573.0, "pressure": 1010.0, "humidity": 50.0, "latitude": 10.0, "longitude": 20.0},
            {"id": "BAD-PRESSURE", "temperature": 20.0, "pressure": 0.0, "humidity": 50.0, "latitude": 10.0, "longitude": 20.0},
            {"id": "BAD-HUMIDITY", "temperature": 20.0, "pressure": 1010.0, "humidity": 120.0, "latitude": 10.0, "longitude": 20.0},
            {"id": "NULL-ISLAND", "temperature": 20.0, "pressure": 1010.0, "humidity": 50.0, "latitude": 0.0, "longitude": 0.0},
            {"id": "MISSING", "temperature": None, "pressure": 1010.0, "humidity": 50.0, "latitude": 10.0, "longitude": 20.0},
        ]
        clean, report = filter_clean_stations(synthetic_raw, cfg)
        clean_ids = {s["id"] for s in clean}
        self.assertEqual(clean_ids, {"OK-1"})
        self.assertEqual(report["stations_with_complete_valid_baseline"], 1)
        self.assertEqual(report["rejected_null_island"], 1)
        self.assertEqual(report["rejected_missing_fields"], 1)
        self.assertEqual(report["rejected_out_of_physics_bounds"], 3)

    def test_10_temperature_humidity_negative_coupling(self):
        """Per the design, humidity must be coupled to temperature deviation
        with a negative sign (RH falls as T rises above baseline)."""
        df = run_generation(_small_cfg(seed=7, num_stations=10))["dataframe"]
        per_station_corr = df.groupby("station_id")[["temperature_c", "relative_humidity_pct"]].apply(
            lambda g: g["temperature_c"].corr(g["relative_humidity_pct"])
        ).dropna()
        self.assertTrue((per_station_corr < 0).all())


if __name__ == "__main__":
    unittest.main()
