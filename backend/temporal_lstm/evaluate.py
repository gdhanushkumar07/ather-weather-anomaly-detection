"""
Stage 2 evaluation: converts scaled model predictions back to physical
units and computes MAE/RMSE/residual statistics per channel — never
reports only normalized MSE (spec section 8/9).

No anomaly-detection metrics (precision/recall/F1/threshold) are computed
here — Stage 1's dataset has no injected anomalies, and Stage 2 only
asks "can the LSTM learn normal temporal behavior and predict the next
reading?" (spec section 2).
"""
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from temporal_lstm.config import TemporalLSTMConfig
from temporal_lstm.model import TemporalLSTM
from temporal_lstm.utils import get_device

PERCENTILES = [50, 90, 95, 99]


@torch.no_grad()
def predict_scaled(model: TemporalLSTM, X: np.ndarray, device: torch.device, batch_size: int = 512) -> np.ndarray:
    model.eval()
    preds = []
    for start in range(0, len(X), batch_size):
        batch = torch.from_numpy(X[start:start + batch_size]).to(device)
        out = model(batch)
        preds.append(out.cpu().numpy())
    if not preds:
        return np.empty((0, model.fc.out_features), dtype=np.float32)
    return np.concatenate(preds, axis=0)


def inverse_transform(scaled: np.ndarray, scaler, scale_columns) -> np.ndarray:
    """scaler was fit on `scale_columns`; target_columns == scale_columns
    (same 3 physical channels, same order) in this Stage 2 design."""
    return scaler.inverse_transform(scaled)


def compute_metrics(y_true_phys: np.ndarray, y_pred_phys: np.ndarray, target_columns) -> Dict[str, Dict[str, float]]:
    metrics: Dict[str, Dict[str, float]] = {}
    for i, col in enumerate(target_columns):
        residual = y_true_phys[:, i] - y_pred_phys[:, i]  # actual - predicted, sign kept
        abs_residual = np.abs(residual)
        mae = float(np.mean(abs_residual))
        rmse = float(np.sqrt(np.mean(residual ** 2)))
        metrics[col] = {
            "mae": mae,
            "rmse": rmse,
            "mean_residual": float(np.mean(residual)),
            "std_residual": float(np.std(residual)),
            "n_samples": int(len(residual)),
        }
    return metrics


def compute_residual_percentiles(y_true_phys: np.ndarray, y_pred_phys: np.ndarray, target_columns) -> Dict[str, Dict[str, float]]:
    """Absolute-residual percentiles per channel — for FUTURE anomaly-score
    calibration (Stage 3+). NOT converted into a threshold here."""
    out: Dict[str, Dict[str, float]] = {}
    for i, col in enumerate(target_columns):
        abs_residual = np.abs(y_true_phys[:, i] - y_pred_phys[:, i])
        out[col] = {f"p{p}": float(np.percentile(abs_residual, p)) for p in PERCENTILES}
    return out


def evaluate_split(
    model: TemporalLSTM,
    X: np.ndarray,
    y_scaled: np.ndarray,
    scaler,
    cfg: TemporalLSTMConfig,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Returns (y_true_phys, y_pred_phys, metrics, residual_percentiles)."""
    y_pred_scaled = predict_scaled(model, X, device)
    y_true_phys = inverse_transform(y_scaled, scaler, cfg.scale_columns)
    y_pred_phys = inverse_transform(y_pred_scaled, scaler, cfg.scale_columns)
    metrics = compute_metrics(y_true_phys, y_pred_phys, cfg.target_columns)
    percentiles = compute_residual_percentiles(y_true_phys, y_pred_phys, cfg.target_columns)
    return y_true_phys, y_pred_phys, metrics, percentiles


def main():
    """Standalone CLI: reload saved artifacts + Stage 1 dataset, evaluate
    on the held-out TEST split only, print results.
    Usage: python3 -m temporal_lstm.evaluate [--model-dir DIR]
    """
    import argparse
    import pickle
    from temporal_lstm.dataset import load_dataset, add_time_features, build_split_windows

    parser = argparse.ArgumentParser(description="Stage 2 standalone test-set evaluation")
    parser.add_argument("--model-dir", type=str, default=None)
    args = parser.parse_args()

    cfg = TemporalLSTMConfig()
    model_dir = Path(args.model_dir) if args.model_dir else cfg.output_dir

    with open(model_dir / cfg.config_filename) as f:
        saved_cfg_dict = json.load(f)
    cfg.sequence_length = saved_cfg_dict["sequence_length"]
    cfg.stride = saved_cfg_dict["stride"]
    cfg.hidden_size = saved_cfg_dict["hidden_size"]
    cfg.num_layers = saved_cfg_dict["num_layers"]

    with open(model_dir / cfg.scaler_filename, "rb") as f:
        scaler = pickle.load(f)

    device = get_device()
    model = TemporalLSTM.from_config(cfg).to(device)
    model.load_state_dict(torch.load(model_dir / cfg.model_filename, map_location=device))

    df = load_dataset(cfg)
    df = add_time_features(df)
    X_test, y_test, test_station_ids = build_split_windows(df, "test", cfg, scaler)

    print(f"Evaluating on {len(X_test)} test windows from {len(test_station_ids)} test stations...")
    y_true_phys, y_pred_phys, metrics, percentiles = evaluate_split(model, X_test, y_test, scaler, cfg, device)

    print(json.dumps({"metrics": metrics, "residual_percentiles": percentiles}, indent=2))


if __name__ == "__main__":
    main()
