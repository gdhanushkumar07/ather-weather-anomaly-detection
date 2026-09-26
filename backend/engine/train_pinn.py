"""
Offline trainer for the Layer 1 PINN (see PhysicsInformedNet in layer1_physics.py).

DATA: the repo has no historical multi-channel AWS time-series dataset (only
current-snapshot station metadata and infra lists) to learn from, so training
uses a synthetically generated, physically-consistent dataset instead:
  - altitude sampled across a realistic station-elevation mix (0-3500 m)
  - temperature: an altitude-adjusted lapse-rate profile plus noise
  - humidity: broad uniform coverage (Magnus dew point <= temperature holds
    automatically whenever RH <= 100, so no extra correlation is needed)
  - pressure: the exact hypsometric value for (temperature, altitude), plus
    sensor noise and a synoptic-variability term whose scale matches the
    rule layer's own 8% hypsometric tolerance (config.PhysicsThresholds).

If/when real historical AWS telemetry becomes available, point
`load_real_dataset()` at it (columns: temperature_c, pressure_hpa,
humidity_pct, elevation_m) and swap it in for generate_synthetic_dataset() —
everything else (training loop, physics loss, artifact format) stays the same.

Run: python -m engine.train_pinn
"""
import json
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG  # noqa: E402

try:
    import torch
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:
    print("PyTorch is required to train the PINN (pip install torch). Aborting.")
    sys.exit(1)

from engine.layer1_physics import (  # noqa: E402
    PhysicsInformedNet, PINN_CHANNELS, PINN_ARTIFACTS_DIR, PINN_WEIGHTS_PATH, PINN_NORM_STATS_PATH,
    magnus_dewpoint_torch, hypsometric_pressure_torch,
)

PHYS = CONFIG.physics
RNG = np.random.default_rng(42)


def hypsometric_pressure_np(temp_c: np.ndarray, altitude_m: np.ndarray) -> np.ndarray:
    exponent = PHYS.gravity / (PHYS.gas_constant * PHYS.temp_lapse_rate)
    base = np.clip(1.0 - (PHYS.temp_lapse_rate * altitude_m) / PHYS.sea_level_temp_k, 1e-3, None)
    return PHYS.sea_level_pressure_hpa * (base ** exponent)


def generate_synthetic_dataset(n: int = 40000) -> dict:
    altitude = np.concatenate([
        RNG.uniform(0, 500, int(n * 0.5)),
        RNG.uniform(500, 1500, int(n * 0.3)),
        RNG.uniform(1500, 3500, n - int(n * 0.5) - int(n * 0.3)),
    ])
    RNG.shuffle(altitude)

    t0_sea_level = RNG.normal(27.0, 8.0, n)  # tropical/subtropical baseline climate
    temperature_c = t0_sea_level - PHYS.temp_lapse_rate * altitude + RNG.normal(0, 1.0, n)
    temperature_c = np.clip(temperature_c, -35.0, 48.0)

    humidity_pct = RNG.uniform(10.0, 100.0, n)

    hyps = hypsometric_pressure_np(temperature_c, altitude)
    # Synoptic variability std chosen so ~98% of samples stay inside the
    # rule layer's 8% tolerance band (0.08 / 2.33 ≈ 3.4% at the 1% tail).
    synoptic_pct_noise = RNG.normal(0.0, 0.034, n)
    sensor_noise_hpa = RNG.normal(0.0, 0.5, n)
    pressure_hpa = hyps * (1.0 + synoptic_pct_noise) + sensor_noise_hpa
    pressure_hpa = np.clip(pressure_hpa, 300.0, 1080.0)

    return {
        "temperature_c": temperature_c.astype(np.float32),
        "pressure_hpa": pressure_hpa.astype(np.float32),
        "humidity_pct": humidity_pct.astype(np.float32),
        "elevation_m": altitude.astype(np.float32),
    }


def load_real_dataset(csv_path: str) -> dict:
    """Drop-in replacement for generate_synthetic_dataset() once real
    historical AWS telemetry with these columns is available."""
    import pandas as pd
    df = pd.read_csv(csv_path)
    return {
        "temperature_c": df["temperature_c"].to_numpy(dtype=np.float32),
        "pressure_hpa": df["pressure_hpa"].to_numpy(dtype=np.float32),
        "humidity_pct": df["humidity_pct"].to_numpy(dtype=np.float32),
        "elevation_m": df["elevation_m"].to_numpy(dtype=np.float32),
    }


def compute_norm_stats(data: dict) -> dict:
    stats = {}
    for key in PINN_CHANNELS + ["elevation_m"]:
        arr = data[key]
        stats[key] = {"mean": float(np.mean(arr)), "std": float(max(np.std(arr), 1e-3))}
    return stats


def normalize(data: dict, stats: dict) -> dict:
    return {k: (data[k] - stats[k]["mean"]) / stats[k]["std"] for k in data}


def build_training_tensors(norm_data: dict, mask_rng: np.random.Generator):
    """
    Denoising task: for every sample, randomly hide 0-2 of the 3 sensor
    channels (altitude is always given — it's station metadata, not a
    sensor reading) and ask the network to reconstruct all 3 true values.
    """
    n = len(norm_data["temperature_c"])
    x = np.zeros((n, 7), dtype=np.float32)
    y = np.stack([norm_data[c] for c in PINN_CHANNELS], axis=1).astype(np.float32)
    x[:, 3] = norm_data["elevation_m"]

    # Mask pattern per sample: 0 = all visible, 1 = one channel hidden,
    # 2 = two channels hidden — weighted so "all visible" (the common
    # inference-time case) dominates.
    n_hide = mask_rng.choice([0, 1, 2], size=n, p=[0.45, 0.35, 0.20])
    for i in range(n):
        visible = list(range(3))
        hidden = mask_rng.choice(visible, size=n_hide[i], replace=False) if n_hide[i] > 0 else []
        for ch_idx, ch in enumerate(PINN_CHANNELS):
            if ch_idx in hidden:
                x[i, ch_idx] = 0.0
                x[i, 4 + ch_idx] = 0.0
            else:
                x[i, ch_idx] = y[i, ch_idx]
                x[i, 4 + ch_idx] = 1.0

    return torch.from_numpy(x), torch.from_numpy(y)


def train(n_samples: int = 40000, epochs: int = 40, batch_size: int = 256, lr: float = 1e-3):
    os.makedirs(PINN_ARTIFACTS_DIR, exist_ok=True)

    raw = generate_synthetic_dataset(n_samples)
    stats = compute_norm_stats(raw)
    norm_data = normalize(raw, stats)

    mask_rng = np.random.default_rng(7)
    x, y = build_training_tensors(norm_data, mask_rng)
    alt_raw = torch.from_numpy(raw["elevation_m"].astype(np.float32))

    dataset = TensorDataset(x, y, alt_raw)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    model = PhysicsInformedNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    lambda_physics = CONFIG.pinn.lambda_physics
    margin = CONFIG.pinn.dew_point_margin_c
    tol_pct = CONFIG.pinn.hypsometric_tolerance_pct / 100.0

    model.train()
    for epoch in range(1, epochs + 1):
        total_data_loss, total_phys_loss, n_batches = 0.0, 0.0, 0
        for xb, yb, altb in loader:
            optimizer.zero_grad()
            pred = model(xb)
            data_loss = torch.mean((pred - yb) ** 2)

            t_hat = pred[:, 0] * stats["temperature_c"]["std"] + stats["temperature_c"]["mean"]
            p_hat = pred[:, 1] * stats["pressure_hpa"]["std"] + stats["pressure_hpa"]["mean"]
            rh_hat = pred[:, 2] * stats["humidity_pct"]["std"] + stats["humidity_pct"]["mean"]

            hyps_expected = hypsometric_pressure_torch(
                t_hat, altb, PHYS.sea_level_pressure_hpa, PHYS.temp_lapse_rate,
                PHYS.sea_level_temp_k, PHYS.gravity, PHYS.gas_constant,
            )
            pct_dev = torch.abs(p_hat - hyps_expected) / torch.clamp(hyps_expected, min=1.0)
            loss_hyps = torch.mean(torch.relu(pct_dev - tol_pct) ** 2)

            dew_hat = magnus_dewpoint_torch(t_hat, rh_hat)
            loss_dew = torch.mean(torch.relu(dew_hat - (t_hat + margin)) ** 2)

            loss_rh = torch.mean(torch.relu(-rh_hat) ** 2 + torch.relu(rh_hat - 100.0) ** 2)

            phys_loss = loss_hyps + loss_dew + loss_rh
            loss = data_loss + lambda_physics * phys_loss

            loss.backward()
            optimizer.step()

            total_data_loss += data_loss.item()
            total_phys_loss += phys_loss.item()
            n_batches += 1

        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            print(f"epoch {epoch:3d}/{epochs}  data_loss={total_data_loss/n_batches:.5f}  "
                  f"physics_loss={total_phys_loss/n_batches:.5f}")

    model.eval()
    torch.save(model.state_dict(), PINN_WEIGHTS_PATH)
    with open(PINN_NORM_STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\nSaved weights to {PINN_WEIGHTS_PATH}")
    print(f"Saved normalization stats to {PINN_NORM_STATS_PATH}")


if __name__ == "__main__":
    train()
