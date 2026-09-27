"""
Configuration for the Stage 2 LSTM next-step predictor.

All architecture/training knobs live here so nothing is hardcoded inline
(sequence_length, hidden_size, num_layers, learning_rate, batch_size,
epochs, stride are all configurable per the Stage 2 spec).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

BACKEND_DIR = Path(__file__).resolve().parents[1]

DEFAULT_DATASET_DIR = BACKEND_DIR / "data" / "temporal"
DEFAULT_DATASET_FILENAME = "synthetic_temporal_normal.csv"
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "models" / "temporal_lstm"

PHYSICAL_COLUMNS: List[str] = ["temperature_c", "pressure_hpa", "relative_humidity_pct"]
TIME_FEATURE_COLUMNS: List[str] = ["hour_sin", "hour_cos"]
FEATURE_COLUMNS: List[str] = PHYSICAL_COLUMNS + TIME_FEATURE_COLUMNS  # order defines input tensor column order
TARGET_COLUMNS: List[str] = PHYSICAL_COLUMNS


@dataclass
class TemporalLSTMConfig:
    # ── Data source ──────────────────────────────────────────────────────
    dataset_dir: Path = field(default_factory=lambda: DEFAULT_DATASET_DIR)
    dataset_filename: str = DEFAULT_DATASET_FILENAME
    expected_sampling_interval_minutes: int = 10  # used only for the data-quality check

    # ── Windowing (locked design + configurable stride) ──────────────────
    sequence_length: int = 144   # 24h of history at 10-min cadence
    stride: int = 6              # one training window per hour by default

    # ── Features / targets ────────────────────────────────────────────────
    feature_columns: List[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    target_columns: List[str] = field(default_factory=lambda: list(TARGET_COLUMNS))
    scale_columns: List[str] = field(default_factory=lambda: list(PHYSICAL_COLUMNS))

    # ── Model architecture ────────────────────────────────────────────────
    hidden_size: int = 64
    num_layers: int = 1
    output_size: int = 3

    # ── Training ─────────────────────────────────────────────────────────
    batch_size: int = 128
    learning_rate: float = 0.001
    max_epochs: int = 40
    patience: int = 5
    seed: int = 42

    # ── Output artifacts ────────────────────────────────────────────────
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    model_filename: str = "model.pt"
    scaler_filename: str = "scaler.pkl"
    config_filename: str = "config.json"
    metrics_filename: str = "metrics.json"
    residual_stats_filename: str = "residual_stats.json"
    loss_plot_filename: str = "training_loss.png"
    prediction_plot_filename: str = "example_predictions.png"

    @property
    def input_size(self) -> int:
        return len(self.feature_columns)
