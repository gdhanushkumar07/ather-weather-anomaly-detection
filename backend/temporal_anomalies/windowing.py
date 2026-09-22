"""
Dense (stride=1), NaN-aware windowing shared by:
  - the NORMAL VALIDATION baseline pass (evaluate.py: calibration)
  - the injected ANOMALOUS TEST local-slice pass (evaluate.py: detection)

Unlike temporal_lstm/dataset.py's training-time windowing (stride=6,
assumes no missing values), this evaluates EVERY timestep (needed for
onset-delay / persistence analysis, spec sections 15-17) and explicitly
never feeds a window containing NaN into the model (spec section 18) —
such samples are marked residual_available=False instead of crashing or
silently imputing.
"""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import torch

from temporal_lstm.model import TemporalLSTM

PHYSICAL_COLUMNS = ["temperature_c", "pressure_hpa", "relative_humidity_pct"]


def build_dense_predictions(
    df: pd.DataFrame,
    sequence_length: int,
    feature_columns: List[str],
    target_columns: List[str],
    scale_columns: List[str],
    scaler,
    model: TemporalLSTM,
    device: torch.device,
) -> pd.DataFrame:
    """
    df: ONE contiguous sequence (single station or single Stage 3 local
    slice), sorted ascending by timestamp, with hour_sin/hour_cos already
    added. May optionally carry is_anomaly / anomaly_type / anomaly_id /
    missing_channel columns (pass-through only, not used for windowing).

    Returns a per-evaluated-timestep DataFrame: one row per target index
    from `sequence_length` to len(df)-1.
    """
    n = len(df)
    if n <= sequence_length:
        return pd.DataFrame()

    has_labels = "is_anomaly" in df.columns

    scale_arr = df[scale_columns].to_numpy(dtype=np.float64)  # keep NaN as-is
    feature_arr_raw = df[feature_columns].to_numpy(dtype=np.float64)
    nan_row_mask = np.isnan(scale_arr).any(axis=1)  # True if ANY physical channel is missing at that row

    # Scale only the non-NaN rows (StandardScaler.transform tolerates NaN
    # by propagating it, but we compute explicitly to avoid relying on
    # that implementation detail).
    scaled_scale_cols = np.full_like(scale_arr, np.nan)
    valid_rows = ~nan_row_mask
    if valid_rows.any():
        scaled_scale_cols[valid_rows] = scaler.transform(scale_arr[valid_rows])

    # Rebuild the full feature matrix with scaled physical columns +
    # untouched time features, preserving feature_columns' order.
    scale_col_positions = [feature_columns.index(c) for c in scale_columns]
    feature_arr = feature_arr_raw.copy()
    for j, col_pos in enumerate(scale_col_positions):
        feature_arr[:, col_pos] = scaled_scale_cols[:, j]

    target_col_positions = [scale_columns.index(c) for c in target_columns]

    records: List[Dict[str, Any]] = []
    batch_windows: List[np.ndarray] = []
    batch_meta_idx: List[int] = []

    def _base_record(target_idx: int) -> Dict[str, Any]:
        rec = {
            "target_index": int(target_idx),
            "timestamp": df["timestamp"].iloc[target_idx],
        }
        if has_labels:
            rec["is_anomaly"] = bool(df["is_anomaly"].iloc[target_idx])
            rec["anomaly_type"] = df["anomaly_type"].iloc[target_idx]
            rec["anomaly_id"] = df["anomaly_id"].iloc[target_idx] if "anomaly_id" in df.columns else None
            rec["missing_channel"] = df["missing_channel"].iloc[target_idx] if "missing_channel" in df.columns else None
        for ch in PHYSICAL_COLUMNS:
            rec[f"actual_{ch}"] = df[ch].iloc[target_idx]
        return rec

    for start in range(0, n - sequence_length):
        end = start + sequence_length
        target_idx = end

        window_has_nan = bool(nan_row_mask[start:end].any())
        target_has_nan = bool(nan_row_mask[target_idx])
        residual_available = not (window_has_nan or target_has_nan)

        rec = _base_record(target_idx)
        rec["residual_available"] = residual_available
        rec["window_contains_missing"] = window_has_nan
        rec["target_is_missing"] = target_has_nan

        if residual_available:
            batch_windows.append(feature_arr[start:end])
            batch_meta_idx.append(len(records))
        else:
            for ch in target_columns:
                rec[f"predicted_{ch}"] = np.nan
                rec[f"residual_{ch}"] = np.nan
                rec[f"abs_residual_{ch}"] = np.nan
        records.append(rec)

    if batch_windows:
        X = np.stack(batch_windows, axis=0).astype(np.float32)
        with torch.no_grad():
            model.eval()
            pred_scaled = model(torch.from_numpy(X).to(device)).cpu().numpy()

        pred_phys = pred_scaled * scaler.scale_[target_col_positions] + scaler.mean_[target_col_positions]

        for row_i, rec_idx in enumerate(batch_meta_idx):
            rec = records[rec_idx]
            for j, ch in enumerate(target_columns):
                predicted = float(pred_phys[row_i, j])
                actual = rec[f"actual_{ch}"]
                residual = actual - predicted
                rec[f"predicted_{ch}"] = predicted
                rec[f"residual_{ch}"] = residual
                rec[f"abs_residual_{ch}"] = abs(residual)

    return pd.DataFrame(records)
