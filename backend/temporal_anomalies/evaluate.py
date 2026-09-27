"""
Stage 3 main evaluation orchestrator.

Loads the FROZEN Stage 2 model + scaler (never retrained, never
overwritten) and:
  1. Runs a dense baseline pass over NORMAL VALIDATION stations only ->
     calibration statistics (spec section 11).
  2. Injects anomalies into held-out TEST stations (spec section 7) via
     injector.py, and runs a dense pass over each resulting local slice.
  3. Computes the initial_lstm_residual_score (spec section 12).
  4. Evaluates candidate thresholds (spec section 13) and per-anomaly-type
     metrics (spec section 14).
  5. Runs onset-delay, frozen-value, drift, and missing-data analyses
     (spec sections 15-18).

Does not modify engine/layer2_temporal.py, fusion/, or root_cause/, and
does not retrain or overwrite the Stage 2 model/scaler.
"""
import argparse
import dataclasses
import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import torch

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from temporal_lstm.model import TemporalLSTM
from temporal_lstm.dataset import add_time_features
from temporal_lstm.utils import get_device

from .config import ANOMALY_TYPES, AnomalyInjectionConfig
from .injector import generate_anomaly_dataset
from .calibrate import (
    add_temporal_score, candidate_threshold_value, compute_calibration_stats,
    evaluate_at_threshold,
)
from .windowing import build_dense_predictions
from . import visualize


def load_stage2_artifacts(model_dir: Path):
    with open(model_dir / "config.json") as f:
        saved_cfg = json.load(f)

    device = get_device()
    model = TemporalLSTM(
        input_size=len(saved_cfg["feature_columns"]),
        hidden_size=saved_cfg["hidden_size"],
        num_layers=saved_cfg["num_layers"],
        output_size=saved_cfg["output_size"],
    ).to(device)
    state_dict = torch.load(model_dir / "model.pt", map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    with open(model_dir / "scaler.pkl", "rb") as f:
        scaler = pickle.load(f)

    return model, scaler, saved_cfg, device


def _model_weight_fingerprint(model: TemporalLSTM) -> str:
    """A cheap checksum to verify (in tests) that Stage 3 never mutates the
    loaded Stage 2 weights."""
    import hashlib
    h = hashlib.sha256()
    for p in model.parameters():
        h.update(p.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def load_stage1_normal_dataset(cfg: AnomalyInjectionConfig) -> pd.DataFrame:
    path = cfg.stage1_dataset_dir / cfg.stage1_dataset_filename
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def run_baseline_pass(normal_df: pd.DataFrame, lstm_cfg: Dict[str, Any], model, scaler, device) -> pd.DataFrame:
    """Dense per-timestep predictions over every NORMAL VALIDATION station
    (spec section 11) — the ONLY source used for calibration statistics."""
    val_df = normal_df[normal_df["split"] == "val"]
    station_ids = sorted(val_df["station_id"].unique())

    all_results = []
    for station_id in station_ids:
        station_df = val_df[val_df["station_id"] == station_id].sort_values("timestamp").reset_index(drop=True)
        station_df = add_time_features(station_df)
        result = build_dense_predictions(
            station_df, lstm_cfg["sequence_length"], lstm_cfg["feature_columns"],
            lstm_cfg["target_columns"], lstm_cfg["scale_columns"], scaler, model, device,
        )
        result["station_id"] = station_id
        all_results.append(result)

    return pd.concat(all_results, ignore_index=True)


def run_anomaly_pass(injected_df: pd.DataFrame, lstm_cfg: Dict[str, Any], model, scaler, device) -> pd.DataFrame:
    """Dense per-timestep predictions over every Stage 3 injected local
    slice (spec section 10)."""
    all_results = []
    for anomaly_id, seq_df in injected_df.groupby("anomaly_id", sort=False):
        seq_df = seq_df.sort_values("timestamp").reset_index(drop=True)
        seq_df = add_time_features(seq_df)
        result = build_dense_predictions(
            seq_df, lstm_cfg["sequence_length"], lstm_cfg["feature_columns"],
            lstm_cfg["target_columns"], lstm_cfg["scale_columns"], scaler, model, device,
        )
        result["anomaly_id"] = anomaly_id
        result["station_id"] = seq_df["station_id"].iloc[0]
        result["scenario_anomaly_type"] = seq_df["anomaly_type"][seq_df["anomaly_type"] != "none"].iloc[0] \
            if (seq_df["anomaly_type"] != "none").any() else "none"
        all_results.append(result)

    return pd.concat(all_results, ignore_index=True)


def _primary_abs_residual(row: pd.Series, affected_channel: str) -> float:
    """Returns the abs_residual on the channel(s) this specific case
    actually affected (stale_packet affects all three -> take the max)."""
    channels = [c.strip() for c in str(affected_channel).split(",")]
    values = [row.get(f"abs_residual_{ch}") for ch in channels if f"abs_residual_{ch}" in row]
    values = [v for v in values if v is not None and not pd.isna(v)]
    return max(values) if values else np.nan


def compute_per_type_metrics(scored_df: pd.DataFrame, metadata_df: pd.DataFrame,
                               threshold_p95: float, threshold_p99: float) -> Dict[str, Any]:
    from .calibrate import confusion_metrics

    affected_channel_by_id = dict(zip(metadata_df["anomaly_id"], metadata_df["affected_channel"]))
    out: Dict[str, Any] = {}

    for anomaly_type in ANOMALY_TYPES:
        type_rows = scored_df[scored_df["scenario_anomaly_type"] == anomaly_type]
        type_meta = metadata_df[metadata_df["anomaly_type"] == anomaly_type]
        scoreable = type_rows[type_rows["initial_lstm_residual_score"].notna()]

        n_cases = int(len(type_meta))
        n_affected_timesteps = int(type_rows["is_anomaly"].sum())

        entry: Dict[str, Any] = {
            "n_cases": n_cases,
            "n_affected_timesteps": n_affected_timesteps,
            "n_scoreable_timesteps": int(len(scoreable)),
            "n_unavailable_timesteps": int(len(type_rows) - len(scoreable)),
        }

        if len(scoreable) > 0:
            for name, thr in [("p95", threshold_p95), ("p99", threshold_p99)]:
                y_true = scoreable["is_anomaly"].to_numpy()
                y_pred = (scoreable["initial_lstm_residual_score"] > thr).to_numpy()
                m = confusion_metrics(y_true, y_pred)
                entry[f"threshold_{name}"] = {
                    "precision": m["precision"], "recall": m["recall"], "f1": m["f1"],
                    "false_positive_rate": m["false_positive_rate"],
                }

            anomalous_rows = scoreable[scoreable["is_anomaly"]].copy()
            if len(anomalous_rows) > 0 and len(type_meta) > 0:
                anomalous_rows["primary_abs_residual"] = anomalous_rows.apply(
                    lambda r: _primary_abs_residual(r, affected_channel_by_id.get(r["anomaly_id"], "")), axis=1
                )
                per_case_max = anomalous_rows.groupby("anomaly_id")["primary_abs_residual"].max().dropna()
                if len(per_case_max) > 0:
                    entry["max_residual_median"] = float(per_case_max.median())
                    entry["max_residual_p95"] = float(np.percentile(per_case_max, 95))
                    entry["max_residual_p99"] = float(np.percentile(per_case_max, 99))
        out[anomaly_type] = entry
    return out


def main():
    parser = argparse.ArgumentParser(description="Stage 3 anomaly injection + LSTM residual evaluation")
    parser.add_argument("--injections-per-type", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    cfg = AnomalyInjectionConfig()
    if args.injections_per_type is not None:
        cfg.injections_per_type_per_station = args.injections_per_type
    if args.seed is not None:
        cfg.seed = args.seed
    if args.output_dir is not None:
        cfg.output_dir = Path(args.output_dir)

    start_time = time.time()
    print("=== ATHER Stage 3 — Anomaly Injection & LSTM Residual Calibration ===")

    print("Loading frozen Stage 2 model + scaler (read-only)...")
    model, scaler, lstm_cfg, device = load_stage2_artifacts(cfg.stage2_model_dir)
    fingerprint_before = _model_weight_fingerprint(model)

    print("Loading Stage 1 normal dataset (read-only)...")
    normal_df = load_stage1_normal_dataset(cfg)

    print("Running NORMAL VALIDATION baseline pass (calibration source)...")
    baseline_df = run_baseline_pass(normal_df, lstm_cfg, model, scaler, device)
    calibration_stats = compute_calibration_stats(baseline_df, lstm_cfg["target_columns"], cfg.calibration_percentiles)
    print(f"Calibration stats (NORMAL VALIDATION, n={len(baseline_df)}): {json.dumps(calibration_stats, indent=2)}")

    print(f"Injecting anomalies into TEST stations "
          f"({cfg.injections_per_type_per_station} per type per station, seed={cfg.seed})...")
    injected_df, metadata_df = generate_anomaly_dataset(normal_df, cfg, split="test", anomaly_types=ANOMALY_TYPES)
    print(f"Generated {len(metadata_df)} anomaly cases across {metadata_df['station_id'].nunique()} test stations.")

    print("Running dense LSTM pass over injected anomaly sequences...")
    anomaly_scored_df = run_anomaly_pass(injected_df, lstm_cfg, model, scaler, device)

    baseline_df = add_temporal_score(baseline_df, calibration_stats, lstm_cfg["target_columns"])
    anomaly_scored_df = add_temporal_score(anomaly_scored_df, calibration_stats, lstm_cfg["target_columns"])

    threshold_p95 = candidate_threshold_value(calibration_stats, lstm_cfg["target_columns"], 95)
    threshold_p99 = candidate_threshold_value(calibration_stats, lstm_cfg["target_columns"], 99)
    print(f"Candidate thresholds (initial_lstm_residual_score): P95-equivalent={threshold_p95:.4f}, "
          f"P99-equivalent={threshold_p99:.4f}")

    overall_metrics = {
        "p95_threshold": {"threshold_value": threshold_p95, **evaluate_at_threshold(anomaly_scored_df, threshold_p95)},
        "p99_threshold": {"threshold_value": threshold_p99, **evaluate_at_threshold(anomaly_scored_df, threshold_p99)},
    }
    print("Overall detection metrics (pooled across all anomaly test cases):")
    print(json.dumps(overall_metrics, indent=2))

    per_type_metrics = compute_per_type_metrics(anomaly_scored_df, metadata_df, threshold_p95, threshold_p99)

    from .special_analysis import run_special_analyses
    special_analysis = run_special_analyses(anomaly_scored_df, metadata_df, threshold_p99, cfg)

    fingerprint_after = _model_weight_fingerprint(model)
    assert fingerprint_before == fingerprint_after, "Stage 2 model weights changed during Stage 3 — this must never happen."

    # ── Save all artifacts ──────────────────────────────────────────────
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = cfg.output_dir / cfg.plots_dirname
    plots_dir.mkdir(parents=True, exist_ok=True)

    injected_df.to_csv(cfg.output_dir / cfg.injected_sequences_filename, index=False)
    metadata_df.to_csv(cfg.output_dir / cfg.anomaly_metadata_filename, index=False)
    anomaly_scored_df.to_csv(cfg.output_dir / cfg.residual_predictions_filename, index=False)

    with open(cfg.output_dir / cfg.calibration_stats_filename, "w") as f:
        json.dump({
            "normal_validation_residual_percentiles": calibration_stats,
            "stage2_test_residual_comparison_note": (
                "Compare against backend/models/temporal_lstm/residual_stats.json "
                "(Stage 2 TEST-split residuals) — expected to differ from these "
                "NORMAL-VALIDATION-split figures, not be identical."
            ),
        }, f, indent=2, default=str)

    with open(cfg.output_dir / cfg.detection_metrics_filename, "w") as f:
        json.dump({
            "candidate_thresholds": {"p95_equivalent_score": threshold_p95, "p99_equivalent_score": threshold_p99},
            "overall": overall_metrics,
            "disclaimer": "Experimental Stage 3 calibration results on SYNTHETIC injected anomalies — not production performance.",
        }, f, indent=2, default=str)

    with open(cfg.output_dir / cfg.per_type_metrics_filename, "w") as f:
        json.dump(per_type_metrics, f, indent=2, default=str)

    with open(cfg.output_dir / cfg.special_analysis_filename, "w") as f:
        json.dump(special_analysis, f, indent=2, default=str)

    with open(cfg.output_dir / cfg.config_filename, "w") as f:
        cfg_dict = dataclasses.asdict(cfg)
        cfg_dict["stage2_model_dir"] = str(cfg.stage2_model_dir)
        cfg_dict["stage1_dataset_dir"] = str(cfg.stage1_dataset_dir)
        cfg_dict["output_dir"] = str(cfg.output_dir)
        json.dump(cfg_dict, f, indent=2, default=str)

    print("Generating plots...")
    visualize.generate_all_plots(baseline_df, anomaly_scored_df, metadata_df, injected_df, plots_dir)

    elapsed = time.time() - start_time
    print(f"\nStage 3 complete in {elapsed:.1f}s. Artifacts written to: {cfg.output_dir}")

    return {
        "calibration_stats": calibration_stats,
        "overall_metrics": overall_metrics,
        "per_type_metrics": per_type_metrics,
        "special_analysis": special_analysis,
        "metadata_df": metadata_df,
        "elapsed_seconds": elapsed,
    }


if __name__ == "__main__":
    main()
