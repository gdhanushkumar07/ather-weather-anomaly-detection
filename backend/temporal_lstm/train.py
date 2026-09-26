"""
Stage 2 training entrypoint.

Usage (from backend/):
    python3 -m temporal_lstm.train
    python3 -m temporal_lstm.train --max-epochs 5 --batch-size 64   # quick smoke run

Trains ONLY on the Stage 1 "train" split stations, early-stops on
validation loss, saves the best checkpoint, then evaluates ONCE on the
held-out "test" split and writes all Stage 2 artifacts.
"""
import argparse
import dataclasses
import json
import pickle
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # no display available / needed
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from temporal_lstm.config import TemporalLSTMConfig
from temporal_lstm.dataset import prepare_all_splits, DataQualityError
from temporal_lstm.model import TemporalLSTM
from temporal_lstm.evaluate import evaluate_split
from temporal_lstm.utils import set_seed, get_device


def _config_to_jsonable(cfg: TemporalLSTMConfig) -> dict:
    d = dataclasses.asdict(cfg)
    d["dataset_dir"] = str(cfg.dataset_dir)
    d["output_dir"] = str(cfg.output_dir)
    return d


def _make_loader(X: np.ndarray, y: np.ndarray, batch_size: int, shuffle: bool) -> DataLoader:
    dataset = TensorDataset(torch.from_numpy(X), torch.from_numpy(y))
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle)


def _run_epoch(model, loader, device, optimizer=None) -> float:
    is_train = optimizer is not None
    model.train(is_train)
    loss_fn = nn.MSELoss()
    total_loss, total_n = 0.0, 0

    context = torch.enable_grad() if is_train else torch.no_grad()
    with context:
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            if is_train:
                optimizer.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            if is_train:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * len(xb)
            total_n += len(xb)

    return total_loss / max(1, total_n)


def train(cfg: TemporalLSTMConfig) -> dict:
    start_time = time.time()
    set_seed(cfg.seed)
    device = get_device()

    print("=== ATHER Stage 2 — LSTM Temporal Predictor Training ===")
    print(f"Device: {device}")
    print("Loading Stage 1 dataset and running data-quality checks...")

    data = prepare_all_splits(cfg)
    qc_report = data["quality_report"]
    scaler = data["scaler"]

    X_train, y_train = data["train"]["X"], data["train"]["y"]
    X_val, y_val = data["val"]["X"], data["val"]["y"]
    X_test, y_test = data["test"]["X"], data["test"]["y"]

    train_stations = data["train"]["station_ids"]
    val_stations = data["val"]["station_ids"]
    test_stations = data["test"]["station_ids"]

    print(f"Data quality checks passed: {qc_report}")
    print(f"Train windows: {len(X_train)} from {len(train_stations)} stations")
    print(f"Val windows:   {len(X_val)} from {len(val_stations)} stations")
    print(f"Test windows:  {len(X_test)} from {len(test_stations)} stations")

    assert X_train.shape[1] == cfg.sequence_length
    assert X_train.shape[2] == cfg.input_size
    assert y_train.shape[1] == cfg.output_size

    train_loader = _make_loader(X_train, y_train, cfg.batch_size, shuffle=True)
    val_loader = _make_loader(X_val, y_val, cfg.batch_size, shuffle=False)

    model = TemporalLSTM.from_config(cfg).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)

    train_losses, val_losses = [], []
    best_val_loss = float("inf")
    best_epoch = -1
    epochs_without_improvement = 0
    best_state_dict = None

    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, cfg.max_epochs + 1):
        train_loss = _run_epoch(model, train_loader, device, optimizer)
        val_loss = _run_epoch(model, val_loader, device, optimizer=None)
        train_losses.append(train_loss)
        val_losses.append(val_loss)
        print(f"Epoch {epoch:3d}/{cfg.max_epochs}  train_loss={train_loss:.6f}  val_loss={val_loss:.6f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            epochs_without_improvement = 0
            best_state_dict = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= cfg.patience:
                print(f"Early stopping at epoch {epoch} (no val improvement for {cfg.patience} epochs).")
                break

    assert best_state_dict is not None
    model.load_state_dict(best_state_dict)
    training_time_seconds = time.time() - start_time

    # ── Save model + scaler + config ────────────────────────────────────
    torch.save(model.state_dict(), cfg.output_dir / cfg.model_filename)
    with open(cfg.output_dir / cfg.scaler_filename, "wb") as f:
        pickle.dump(scaler, f)
    with open(cfg.output_dir / cfg.config_filename, "w") as f:
        json.dump(_config_to_jsonable(cfg), f, indent=2)

    # ── Test-set evaluation (held-out stations, evaluated once) ─────────
    print(f"\nEvaluating best checkpoint (epoch {best_epoch}) on {len(X_test)} held-out test windows...")
    y_true_phys, y_pred_phys, test_metrics, residual_percentiles = evaluate_split(
        model, X_test, y_test, scaler, cfg, device
    )

    with open(cfg.output_dir / cfg.residual_stats_filename, "w") as f:
        json.dump({
            "residual_percentiles_abs": residual_percentiles,
            "note": (
                "Absolute-residual percentiles on the held-out TEST split, in "
                "physical units. Reserved for FUTURE anomaly-score calibration "
                "(Stage 3+) — NOT converted into a threshold in Stage 2."
            ),
        }, f, indent=2)

    metrics = {
        "seed": cfg.seed,
        "device": str(device),
        "training_time_seconds": round(training_time_seconds, 2),
        "epochs_run": len(train_losses),
        "best_epoch": best_epoch,
        "best_val_loss_scaled_mse": best_val_loss,
        "train_loss_per_epoch": train_losses,
        "val_loss_per_epoch": val_losses,
        "dataset": {
            "train_windows": len(X_train), "val_windows": len(X_val), "test_windows": len(X_test),
            "train_stations": len(train_stations), "val_stations": len(val_stations), "test_stations": len(test_stations),
            "quality_report": {k: v for k, v in qc_report.items()},
        },
        "test_metrics_physical_units": test_metrics,
        "limitations": [
            "Trained and evaluated entirely on Stage 1's SYNTHETIC normal dataset.",
            "Does not measure real-world AWS anomaly-detection accuracy, production "
            "readiness, real IMD performance, or sensor-failure-prediction accuracy.",
            "No anomalies exist in this dataset — these are next-step PREDICTION "
            "metrics on normal data only, not detection metrics.",
        ],
    }
    with open(cfg.output_dir / cfg.metrics_filename, "w") as f:
        json.dump(metrics, f, indent=2)

    _plot_losses(train_losses, val_losses, best_epoch, cfg.output_dir / cfg.loss_plot_filename)
    _plot_example_predictions(y_true_phys, y_pred_phys, cfg.output_dir / cfg.prediction_plot_filename)

    print(f"\nBest epoch: {best_epoch}  best val loss (scaled MSE): {best_val_loss:.6f}")
    print("Test metrics (physical units):")
    print(json.dumps(test_metrics, indent=2))
    print(f"\nArtifacts written to: {cfg.output_dir}")
    print(f"Training time: {training_time_seconds:.1f}s")

    return {"metrics": metrics, "residual_percentiles": residual_percentiles}


def _plot_losses(train_losses, val_losses, best_epoch, path: Path):
    plt.figure(figsize=(7, 4))
    epochs = range(1, len(train_losses) + 1)
    plt.plot(epochs, train_losses, label="train loss")
    plt.plot(epochs, val_losses, label="val loss")
    if best_epoch > 0:
        plt.axvline(best_epoch, color="gray", linestyle="--", alpha=0.6, label=f"best epoch ({best_epoch})")
    plt.xlabel("epoch")
    plt.ylabel("MSE loss (scaled units)")
    plt.title("Stage 2 LSTM training/validation loss")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_example_predictions(y_true_phys: np.ndarray, y_pred_phys: np.ndarray, path: Path, n_examples: int = 200):
    n = min(n_examples, len(y_true_phys))
    if n == 0:
        return
    plt.figure(figsize=(8, 4))
    plt.plot(y_true_phys[:n, 0], label="actual temperature_c")
    plt.plot(y_pred_phys[:n, 0], label="predicted temperature_c")
    plt.xlabel("test window index (chronological within each station, stations concatenated)")
    plt.ylabel("Temperature (deg C)")
    plt.title(f"Stage 2: actual vs predicted temperature (first {n} test windows)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Stage 2 LSTM training")
    parser.add_argument("--max-epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--hidden-size", type=int, default=None)
    parser.add_argument("--num-layers", type=int, default=None)
    parser.add_argument("--stride", type=int, default=None)
    parser.add_argument("--patience", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    cfg = TemporalLSTMConfig()
    for attr, val in vars(args).items():
        if val is None:
            continue
        setattr(cfg, attr.replace("-", "_"), Path(val) if attr == "output_dir" else val)

    try:
        train(cfg)
    except DataQualityError as e:
        print(f"\nDATA QUALITY CHECK FAILED — stopping before training.\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
