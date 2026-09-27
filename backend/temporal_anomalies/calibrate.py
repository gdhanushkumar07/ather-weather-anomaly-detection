"""
Stage 3 calibration: normal-validation-derived residual statistics, the
initial_lstm_residual_score, and candidate-threshold detection metrics.

CRITICAL LEAKAGE GUARD (spec section 7): every percentile/threshold here
must be computed from NORMAL VALIDATION residuals only. Nothing in this
module ever reads the anomalous test residuals to choose a threshold —
callers must pass in pre-computed calibration stats, not raw test data.
"""
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

PHYSICAL_COLUMNS = ["temperature_c", "pressure_hpa", "relative_humidity_pct"]


def compute_calibration_stats(baseline_df: pd.DataFrame, target_columns: List[str],
                                percentiles: Tuple[int, ...]) -> Dict[str, Dict[str, float]]:
    """Per-channel absolute-residual percentiles from NORMAL VALIDATION
    predictions only (baseline_df must contain no injected anomalies)."""
    valid = baseline_df[baseline_df["residual_available"]]
    stats: Dict[str, Dict[str, float]] = {}
    for ch in target_columns:
        abs_res = valid[f"abs_residual_{ch}"].to_numpy(dtype=float)
        stats[ch] = {f"p{p}": float(np.percentile(abs_res, p)) for p in percentiles}
        stats[ch]["mean"] = float(np.mean(abs_res))
        stats[ch]["std"] = float(np.std(abs_res))
        stats[ch]["n_samples"] = int(len(abs_res))
    return stats


def add_temporal_score(df: pd.DataFrame, calibration_stats: Dict[str, Dict[str, float]],
                         target_columns: List[str]) -> pd.DataFrame:
    """
    Adds per-channel normalized_residual_<ch> = abs_residual_<ch> / P99(channel, NORMAL VALIDATION)
    and the combined initial_lstm_residual_score = max over channels.
    Rows with residual_available=False get NaN (score cannot be computed).
    """
    df = df.copy()
    normalized_cols = []
    for ch in target_columns:
        p99 = calibration_stats[ch]["p99"]
        col = f"normalized_residual_{ch}"
        df[col] = df[f"abs_residual_{ch}"] / p99
        normalized_cols.append(col)
    df["initial_lstm_residual_score"] = df[normalized_cols].max(axis=1)
    return df


def confusion_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = np.asarray(y_pred, dtype=bool)
    tp = int(np.sum(y_true & y_pred))
    fp = int(np.sum(~y_true & y_pred))
    tn = int(np.sum(~y_true & ~y_pred))
    fn = int(np.sum(y_true & ~y_pred))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": fpr, "true_positive_rate": recall,
        "n_samples": int(len(y_true)),
    }


def candidate_threshold_value(calibration_stats: Dict[str, Dict[str, float]], target_columns: List[str],
                                percentile: int) -> float:
    """
    The initial_lstm_residual_score is normalized by each channel's own
    P99 (spec section 12). A candidate threshold at percentile P therefore
    corresponds to the score value P{percentile}/P99, AVERAGED across
    channels here for a single scalar cut-point (channels' P99-normalized
    ratios are typically close since each channel is normalized by its
    own scale already) — e.g. P99 itself always corresponds to score=1.0.
    """
    ratios = [calibration_stats[ch][f"p{percentile}"] / calibration_stats[ch]["p99"] for ch in target_columns]
    return float(np.mean(ratios))


def evaluate_at_threshold(df: pd.DataFrame, threshold: float) -> Dict[str, float]:
    """Detection metrics at one threshold, over rows with an available score."""
    scored = df[df["initial_lstm_residual_score"].notna()]
    y_true = scored["is_anomaly"].to_numpy()
    y_pred = (scored["initial_lstm_residual_score"] > threshold).to_numpy()
    return confusion_metrics(y_true, y_pred)
