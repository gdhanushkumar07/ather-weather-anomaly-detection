"""
Configuration for the Stage 3 anomaly-injection / calibration experiment.

Physical bounds are NOT redefined here — they are imported from the
existing top-level `config.CONFIG.physics`, the same source Stage 1 and
the production physics layer both use.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Stage 2's already-trained, frozen artifacts (read-only in Stage 3).
STAGE2_MODEL_DIR = BACKEND_DIR / "models" / "temporal_lstm"

# Stage 1's untouched normal dataset (read-only in Stage 3).
STAGE1_DATASET_DIR = BACKEND_DIR / "data" / "temporal"
STAGE1_DATASET_FILENAME = "synthetic_temporal_normal.csv"

# Stage 3's own output location — never overwrites Stage 1/2 artifacts.
DEFAULT_OUTPUT_DIR = STAGE2_MODEL_DIR / "stage3_results"

ANOMALY_TYPES: List[str] = [
    "temperature_spike",
    "temperature_drop",
    "frozen_temperature",
    "frozen_humidity",
    "temperature_drift",
    "pressure_offset",
    "humidity_offset",
    "noise_burst",
    "missing_observation",
    "stale_packet",
]


@dataclass
class AnomalyInjectionConfig:
    seed: int = 42

    # ── Experiment size (spec section 8) ────────────────────────────────
    injections_per_type_per_station: int = 10

    # ── Injection-window placement (spec section 6) ─────────────────────
    min_history_before_anomaly: int = 144   # LSTM lookback requirement — never inject before this index
    lead_buffer_steps: int = 20             # extra clean steps kept before the lookback, for pre-onset comparison
    trailing_buffer_steps: int = 30         # clean steps kept after the anomaly ends, for recovery/persistence checks

    # ── Per-type magnitude / duration ranges ────────────────────────────
    spike_magnitude_c: Tuple[float, float] = (8.0, 15.0)
    drop_magnitude_c: Tuple[float, float] = (-15.0, -8.0)
    frozen_duration_steps: Tuple[int, int] = (12, 24)
    drift_rate_c_per_step: Tuple[float, float] = (0.3, 0.5)
    drift_duration_steps: Tuple[int, int] = (20, 30)
    pressure_offset_hpa: Tuple[float, float] = (3.0, 10.0)          # sign chosen independently, 50/50
    pressure_offset_duration_steps: Tuple[int, int] = (30, 60)      # "persistent for the anomaly interval" (spec F) — bounded here for interpretability
    humidity_offset_pct: Tuple[float, float] = (10.0, 25.0)         # sign chosen independently, 50/50
    humidity_offset_duration_steps: Tuple[int, int] = (30, 60)
    noise_burst_duration_steps: Tuple[int, int] = (1, 3)
    noise_burst_multiplier: Tuple[float, float] = (5.0, 10.0)       # x local normal noise std
    missing_duration_steps: Tuple[int, int] = (1, 6)
    stale_duration_steps: Tuple[int, int] = (2, 8)

    # ── Local noise estimation window for noise-burst magnitude (spec H) ─
    local_noise_window_steps: int = 12

    # ── Calibration / detection experiment (spec sections 11-13) ────────
    calibration_percentiles: Tuple[int, ...] = (50, 90, 95, 99)
    candidate_threshold_percentiles: Tuple[int, ...] = (95, 99)

    # ── Onset / drift analysis checkpoints (spec sections 15-17) ─────────
    drift_checkpoint_steps: Tuple[int, ...] = (0, 5, 10, 20)
    onset_detection_grace_steps: int = 10  # extra steps past anomaly end still scanned for a delayed detection

    # ── I/O ──────────────────────────────────────────────────────────────
    stage2_model_dir: Path = field(default_factory=lambda: STAGE2_MODEL_DIR)
    stage1_dataset_dir: Path = field(default_factory=lambda: STAGE1_DATASET_DIR)
    stage1_dataset_filename: str = STAGE1_DATASET_FILENAME
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)

    injected_sequences_filename: str = "injected_sequences_local.csv"
    anomaly_metadata_filename: str = "anomaly_metadata.csv"
    residual_predictions_filename: str = "residual_predictions.csv"
    calibration_stats_filename: str = "calibration_stats.json"
    detection_metrics_filename: str = "detection_metrics.json"
    per_type_metrics_filename: str = "per_anomaly_type_metrics.json"
    special_analysis_filename: str = "onset_frozen_drift_missing_analysis.json"
    config_filename: str = "stage3_config.json"
    plots_dirname: str = "plots"

    def duration_range_for(self, anomaly_type: str) -> Tuple[int, int]:
        return {
            "temperature_spike": (1, 1),
            "temperature_drop": (1, 1),
            "frozen_temperature": self.frozen_duration_steps,
            "frozen_humidity": self.frozen_duration_steps,
            "temperature_drift": self.drift_duration_steps,
            "pressure_offset": self.pressure_offset_duration_steps,
            "humidity_offset": self.humidity_offset_duration_steps,
            "noise_burst": self.noise_burst_duration_steps,
            "missing_observation": self.missing_duration_steps,
            "stale_packet": self.stale_duration_steps,
        }[anomaly_type]
