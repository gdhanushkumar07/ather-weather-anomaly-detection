"""Stage 5 calibration run configuration — deterministic, reproducible."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]

STAGE1_DATASET_PATH = BACKEND_DIR / "data" / "temporal" / "synthetic_temporal_normal.csv"
STAGE3_RESULTS_DIR = BACKEND_DIR / "models" / "temporal_lstm" / "stage3_results"
STAGE3_INJECTED_SEQUENCES_PATH = STAGE3_RESULTS_DIR / "injected_sequences_local.csv"
STAGE3_ANOMALY_METADATA_PATH = STAGE3_RESULTS_DIR / "anomaly_metadata.csv"

DEFAULT_OUTPUT_DIR = BACKEND_DIR / "stage5_results"


@dataclass
class Stage5Config:
    seed: int = 42

    # Phase 3: normal-traffic calibration source. "val" matches Stage 3's
    # own choice of calibration split (never the test split, never train).
    normal_calibration_split: str = "val"

    # Phase 6 candidate reason-report thresholds to sweep (spec section 12).
    candidate_reason_thresholds: Tuple[float, ...] = (0.25, 0.40, 0.50, 0.60, 0.75)

    # Reference thresholds used only to report "percentage exceeding X",
    # not to make any decision.
    reporting_thresholds: Tuple[float, ...] = (0.25, 0.50, 0.75, 1.0)

    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
