"""
Stage 2 dataset loading, data-quality checks, time-feature construction,
station-safe windowing, and train-only scaling.

CRITICAL INVARIANTS (Stage 2 spec section 4/19):
  - Windows are built independently per station and never cross a station
    boundary (structurally guaranteed: windows are sliced from one
    station's own contiguous row block, never concatenated across
    stations before windowing).
  - Windows never cross the Stage 1 train/validation/test station split
    (structurally guaranteed: each station belongs to exactly one split,
    and windows are built per-split from only that split's stations).
  - The StandardScaler is fit ONLY on training-station rows.
"""
import dataclasses
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

from sklearn.preprocessing import StandardScaler

from .config import TemporalLSTMConfig


class DataQualityError(RuntimeError):
    """Raised when a critical Stage 2 data-quality check fails. Training
    must stop rather than proceed on data that failed these checks."""


def load_dataset(cfg: TemporalLSTMConfig) -> pd.DataFrame:
    path = cfg.dataset_dir / cfg.dataset_filename
    if not path.exists():
        raise DataQualityError(
            f"Stage 1 dataset not found at {path}. Run "
            f"'python3 -m temporal_dataset.generate_dataset' first (Stage 1)."
        )
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def run_data_quality_checks(df: pd.DataFrame, cfg: TemporalLSTMConfig) -> Dict[str, object]:
    """
    Verifies the Stage 2 spec's section-19 preconditions. Raises
    DataQualityError (stopping the pipeline) on any critical failure,
    otherwise returns a small report dict.
    """
    report: Dict[str, object] = {}

    # 1. Expected columns exist.
    required_cols = {"station_id", "timestamp", "temperature_c", "pressure_hpa",
                      "relative_humidity_pct", "split"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise DataQualityError(f"Missing required columns: {sorted(missing_cols)}")
    report["required_columns_present"] = True

    # 2. Timestamps parse correctly (no NaT after to_datetime in load_dataset).
    if df["timestamp"].isna().any():
        raise DataQualityError("Unparseable timestamps found (NaT after pd.to_datetime).")
    report["timestamps_parse_correctly"] = True

    # 3. Sampling interval is 10 minutes, per station.
    expected_delta = pd.Timedelta(minutes=cfg.expected_sampling_interval_minutes)
    spacing_violations = 0
    for _, g in df.groupby("station_id"):
        ts = g["timestamp"].sort_values()
        diffs = ts.diff().dropna()
        spacing_violations += int((diffs != expected_delta).sum())
    if spacing_violations > 0:
        raise DataQualityError(
            f"{spacing_violations} timestamp-spacing violations found "
            f"(expected exactly {cfg.expected_sampling_interval_minutes}-minute spacing)."
        )
    report["sampling_interval_ok"] = True

    # 4. No duplicate station/timestamp rows.
    dup_count = int(df.duplicated(subset=["station_id", "timestamp"]).sum())
    if dup_count > 0:
        raise DataQualityError(f"{dup_count} duplicate (station_id, timestamp) rows found.")
    report["duplicate_rows"] = 0

    # 5. No missing values in the physical channels.
    missing_counts = df[["temperature_c", "pressure_hpa", "relative_humidity_pct"]].isna().sum()
    if missing_counts.sum() > 0:
        raise DataQualityError(f"Missing values found: {missing_counts.to_dict()}")
    report["missing_values"] = 0

    # 6. Train/validation/test station sets do not overlap (each station
    #    belongs to exactly one split).
    splits_per_station = df.groupby("station_id")["split"].nunique()
    stations_with_multiple_splits = int((splits_per_station > 1).sum())
    if stations_with_multiple_splits > 0:
        raise DataQualityError(
            f"{stations_with_multiple_splits} station(s) appear in more than one split."
        )
    report["station_split_overlap"] = 0
    report["stations_per_split"] = df.groupby("split")["station_id"].nunique().to_dict()

    return report


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds hour_sin/hour_cos derived ONLY from the timestamp column (UTC),
    per the Stage 2 spec: no station latitude/longitude is used here
    (unlike Stage 1's generation-time local-solar-hour approximation) —
    the model input must not depend on station metadata.
    """
    df = df.copy()
    hour_of_day = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
    df["hour_sin"] = np.sin(2.0 * np.pi * hour_of_day / 24.0)
    df["hour_cos"] = np.cos(2.0 * np.pi * hour_of_day / 24.0)
    return df


def fit_scaler(df: pd.DataFrame, cfg: TemporalLSTMConfig) -> StandardScaler:
    """Fits a StandardScaler on TRAINING-SPLIT rows only (leakage guard)."""
    train_rows = df.loc[df["split"] == "train", cfg.scale_columns]
    scaler = StandardScaler()
    scaler.fit(train_rows.to_numpy(dtype=np.float64))
    return scaler


def _build_station_windows(
    station_df: pd.DataFrame,
    cfg: TemporalLSTMConfig,
    scaler: StandardScaler,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Builds (X, y) windows for a SINGLE station's own contiguous timeline.
    X: (n_windows, sequence_length, n_features)
    y: (n_windows, n_targets) — scaled, matching the scaled feature columns.
    """
    station_df = station_df.sort_values("timestamp").reset_index(drop=True)
    n = len(station_df)
    seq_len = cfg.sequence_length

    scaled_physical = scaler.transform(station_df[cfg.scale_columns].to_numpy(dtype=np.float64))
    scaled_df = station_df.copy()
    scaled_df[cfg.scale_columns] = scaled_physical
    feature_matrix = scaled_df[cfg.feature_columns].to_numpy(dtype=np.float32)
    target_matrix = scaled_df[cfg.target_columns].to_numpy(dtype=np.float32)
    timestamps = station_df["timestamp"].to_numpy()

    xs, ys = [], []
    for start in range(0, n - seq_len, cfg.stride):
        end = start + seq_len          # exclusive end of the input window
        target_idx = end               # the single next timestep to predict

        # Invariant check (spec section 19, item 8): the target must be
        # exactly ONE sampling interval after the window's last reading,
        # regardless of stride (stride only spaces consecutive WINDOWS
        # apart, not the window-to-target gap within a single window).
        window_last_ts = timestamps[end - 1]
        target_ts = timestamps[target_idx]
        gap_minutes = (target_ts - window_last_ts) / np.timedelta64(1, "m")
        if gap_minutes != cfg.expected_sampling_interval_minutes:
            # Can only happen if the underlying rows weren't contiguous
            # 10-minute steps, which run_data_quality_checks already
            # guarantees is not the case for the full dataset.
            raise DataQualityError(
                f"Window-to-target gap is {gap_minutes} minutes, expected "
                f"{cfg.expected_sampling_interval_minutes} "
                f"(station={station_df['station_id'].iloc[0]}, start={start})."
            )

        xs.append(feature_matrix[start:end])
        ys.append(target_matrix[target_idx])

    if not xs:
        return (np.empty((0, seq_len, len(cfg.feature_columns)), dtype=np.float32),
                np.empty((0, len(cfg.target_columns)), dtype=np.float32))

    X = np.stack(xs, axis=0)
    y = np.stack(ys, axis=0)

    # Structural invariants (spec section 19, items 7/9): every window has
    # exactly sequence_length steps, and (by construction from one
    # station's own slice) never crosses a station boundary.
    assert X.shape[1] == seq_len
    return X, y


def build_split_windows(
    df: pd.DataFrame,
    split_name: str,
    cfg: TemporalLSTMConfig,
    scaler: StandardScaler,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Builds windows for ALL stations in one split (train/val/test), never
    mixing stations from a different split (df is pre-filtered to one
    split before this is called from the caller's perspective — but this
    function also filters defensively).
    """
    split_df = df[df["split"] == split_name]
    station_ids = sorted(split_df["station_id"].unique())  # deterministic order

    all_X, all_y = [], []
    for station_id in station_ids:
        station_df = split_df[split_df["station_id"] == station_id]
        X, y = _build_station_windows(station_df, cfg, scaler)
        if len(X) > 0:
            all_X.append(X)
            all_y.append(y)

    if not all_X:
        return (np.empty((0, cfg.sequence_length, len(cfg.feature_columns)), dtype=np.float32),
                np.empty((0, len(cfg.target_columns)), dtype=np.float32), station_ids)

    X = np.concatenate(all_X, axis=0)
    y = np.concatenate(all_y, axis=0)
    return X, y, station_ids


def prepare_all_splits(cfg: TemporalLSTMConfig) -> Dict[str, object]:
    """
    Full Stage 2 data pipeline entrypoint: load -> quality-check ->
    time-features -> fit scaler on train only -> window each split.
    """
    df = load_dataset(cfg)
    qc_report = run_data_quality_checks(df, cfg)
    df = add_time_features(df)

    scaler = fit_scaler(df, cfg)

    result = {"quality_report": qc_report, "scaler": scaler}
    for split_name in ["train", "val", "test"]:
        X, y, station_ids = build_split_windows(df, split_name, cfg, scaler)
        result[split_name] = {"X": X, "y": y, "station_ids": station_ids}

    return result
