"""
Stage 3 special analyses (spec sections 15-18): onset-detection delay,
frozen-value residual behavior over time, drift residual growth, and
missing-data residual-availability behavior.

These deliberately look BEYOND a single pooled recall number, per spec
section 16/17: a frozen sensor's residual is not assumed to stay high for
the whole frozen interval, and drift is examined at multiple checkpoints
rather than a single timestep.
"""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .config import AnomalyInjectionConfig

ONSET_ANALYSIS_TYPES = [
    "frozen_temperature", "frozen_humidity", "temperature_drift",
    "pressure_offset", "humidity_offset", "stale_packet",
]


def _detection_delay_for_case(case_rows: pd.DataFrame, start_index: int, end_index: int,
                                grace: int, threshold: float) -> Optional[int]:
    window = case_rows[(case_rows["target_index"] >= start_index) & (case_rows["target_index"] <= end_index + grace)]
    window = window[window["initial_lstm_residual_score"].notna()]
    hits = window[window["initial_lstm_residual_score"] > threshold]
    if len(hits) == 0:
        return None
    first_hit_index = int(hits["target_index"].min())
    return first_hit_index - start_index


def compute_onset_delays(scored_df: pd.DataFrame, metadata_df: pd.DataFrame,
                           threshold: float, grace: int) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for anomaly_type in ONSET_ANALYSIS_TYPES:
        type_meta = metadata_df[metadata_df["anomaly_type"] == anomaly_type]
        delays_steps: List[int] = []
        n_missed = 0
        for _, row in type_meta.iterrows():
            case_rows = scored_df[scored_df["anomaly_id"] == row["anomaly_id"]]
            delay = _detection_delay_for_case(case_rows, int(row["start_index"]),
                                                int(row["start_index"]) + int(row["duration_steps"]) - 1,
                                                grace, threshold)
            if delay is None:
                n_missed += 1
            else:
                delays_steps.append(delay)

        entry: Dict[str, Any] = {
            "n_cases": int(len(type_meta)),
            "n_detected": len(delays_steps),
            "n_missed": n_missed,
        }
        if delays_steps:
            arr = np.array(delays_steps)
            entry["median_delay_steps"] = float(np.median(arr))
            entry["median_delay_minutes"] = float(np.median(arr) * 10)
            entry["p90_delay_steps"] = float(np.percentile(arr, 90))
            entry["p90_delay_minutes"] = float(np.percentile(arr, 90) * 10)
        else:
            entry["median_delay_steps"] = None
            entry["note"] = "No cases were detected within the anomaly window + grace period."
        results[anomaly_type] = entry
    return results


def _residual_series_for_channel(case_rows: pd.DataFrame, channel: str) -> pd.Series:
    return case_rows.set_index("target_index")[f"abs_residual_{channel}"]


def analyze_frozen_values(scored_df: pd.DataFrame, metadata_df: pd.DataFrame, threshold: float,
                            channel: str, anomaly_type: str) -> Dict[str, Any]:
    """Spec section 16: does NOT assume residual stays large for the whole
    frozen interval — explicitly measures onset / max / near-end."""
    type_meta = metadata_df[metadata_df["anomaly_type"] == anomaly_type]
    onset_vals, max_vals, near_end_vals, persists_flags = [], [], [], []

    for _, row in type_meta.iterrows():
        case_rows = scored_df[scored_df["anomaly_id"] == row["anomaly_id"]]
        start_index = int(row["start_index"])
        end_index = start_index + int(row["duration_steps"]) - 1
        series = _residual_series_for_channel(case_rows, channel)
        window = series[(series.index >= start_index) & (series.index <= end_index)].dropna()
        if len(window) == 0:
            continue
        onset_vals.append(float(window.iloc[0]))
        max_vals.append(float(window.max()))
        near_end_vals.append(float(window.iloc[-1]))

        score_series = case_rows.set_index("target_index")["initial_lstm_residual_score"]
        score_window = score_series[(score_series.index >= start_index) & (score_series.index <= end_index)].dropna()
        persists_flags.append(bool((score_window > threshold).iloc[-1]) if len(score_window) else False)

    def _summary(vals):
        return {"median": float(np.median(vals)), "p95": float(np.percentile(vals, 95))} if vals else None

    return {
        "n_cases_analyzed": len(onset_vals),
        "residual_at_onset": _summary(onset_vals),
        "residual_max": _summary(max_vals),
        "residual_near_end": _summary(near_end_vals),
        "detection_persists_to_end_fraction": float(np.mean(persists_flags)) if persists_flags else None,
        "interpretation_note": (
            "residual_at_onset vs residual_near_end shows whether the LSTM's "
            "prediction 'catches up' to a frozen/stale value over the interval "
            "(residual shrinking) rather than staying elevated throughout."
        ),
    }


def analyze_drift(scored_df: pd.DataFrame, metadata_df: pd.DataFrame, threshold: float,
                    checkpoints: List[int]) -> Dict[str, Any]:
    """Spec section 17: residual at multiple checkpoints into the drift,
    not just one timestep."""
    type_meta = metadata_df[metadata_df["anomaly_type"] == "temperature_drift"]
    checkpoint_vals: Dict[int, List[float]] = {c: [] for c in checkpoints}
    max_vals, threshold_crossed_flags = [], []

    for _, row in type_meta.iterrows():
        case_rows = scored_df[scored_df["anomaly_id"] == row["anomaly_id"]]
        start_index = int(row["start_index"])
        duration = int(row["duration_steps"])
        end_index = start_index + duration - 1
        series = _residual_series_for_channel(case_rows, "temperature_c")

        for c in checkpoints:
            idx = min(start_index + c, end_index)
            if idx in series.index and not pd.isna(series.loc[idx]):
                checkpoint_vals[c].append(float(series.loc[idx]))

        window = series[(series.index >= start_index) & (series.index <= end_index)].dropna()
        if len(window) > 0:
            max_vals.append(float(window.max()))

        score_series = case_rows.set_index("target_index")["initial_lstm_residual_score"]
        score_window = score_series[(score_series.index >= start_index) & (score_series.index <= end_index)].dropna()
        threshold_crossed_flags.append(bool((score_window > threshold).any()) if len(score_window) else False)

    result: Dict[str, Any] = {"n_cases": int(len(type_meta))}
    for c in checkpoints:
        vals = checkpoint_vals[c]
        result[f"residual_after_{c}_steps_median_c"] = float(np.median(vals)) if vals else None
    result["residual_max_median_c"] = float(np.median(max_vals)) if max_vals else None
    result["fraction_cases_threshold_crossed"] = float(np.mean(threshold_crossed_flags)) if threshold_crossed_flags else None
    result["note"] = "This measures whether accumulated residual identifies gradual drift — NOT a failure-date or predictive-maintenance claim."
    return result


def analyze_missing_data(scored_df: pd.DataFrame, metadata_df: pd.DataFrame) -> Dict[str, Any]:
    """Spec section 18: explicitly distinguishes 'residual unavailable
    because data is missing' from an actual (or absent) prediction
    anomaly — never forces a residual through NaN input."""
    type_meta = metadata_df[metadata_df["anomaly_type"] == "missing_observation"]
    if len(type_meta) == 0:
        return {"n_cases": 0}

    unavailable_run_lengths = []
    within_window_unavailable_fraction = []

    for _, row in type_meta.iterrows():
        case_rows = scored_df[scored_df["anomaly_id"] == row["anomaly_id"]].sort_values("target_index")
        start_index = int(row["start_index"])
        end_index = start_index + int(row["duration_steps"]) - 1

        within_window = case_rows[(case_rows["target_index"] >= start_index) & (case_rows["target_index"] <= end_index)]
        if len(within_window) > 0:
            within_window_unavailable_fraction.append(float((~within_window["residual_available"]).mean()))

        # How many CONSECUTIVE timesteps (from the missing window's start)
        # have residual_available == False, including the "tail" caused by
        # the missing rows still sitting inside later windows' 144-step
        # lookback (NOT just the injected duration itself).
        after_start = case_rows[case_rows["target_index"] >= start_index].sort_values("target_index")
        run_length = 0
        for available in after_start["residual_available"]:
            if not available:
                run_length += 1
            else:
                break
        unavailable_run_lengths.append(run_length)

    return {
        "n_cases": int(len(type_meta)),
        "within_injected_window_unavailable_fraction_mean": float(np.mean(within_window_unavailable_fraction))
            if within_window_unavailable_fraction else None,
        "unavailable_run_length_steps_median": float(np.median(unavailable_run_lengths)) if unavailable_run_lengths else None,
        "unavailable_run_length_steps_max": float(np.max(unavailable_run_lengths)) if unavailable_run_lengths else None,
        "finding": (
            "Missing data is a DATA-QUALITY condition, not a prediction-residual "
            "anomaly: the LSTM never receives NaN, so no residual is computed for "
            "the missing timesteps themselves. Importantly, residual unavailability "
            "extends beyond the missing window's own duration, because those NaN "
            "rows remain inside the 144-step lookback of every subsequent window "
            "until they age out — see unavailable_run_length_steps_median above. "
            "Detecting 'data is missing' should be a separate, simple presence/"
            "absence check (already possible from the raw feed) rather than an "
            "LSTM-residual-based detection, and is intentionally NOT scored as a "
            "residual-detection recall figure in this experiment."
        ),
    }


def run_special_analyses(scored_df: pd.DataFrame, metadata_df: pd.DataFrame, threshold: float,
                           cfg: AnomalyInjectionConfig) -> Dict[str, Any]:
    return {
        "onset_detection_delay": compute_onset_delays(scored_df, metadata_df, threshold, cfg.onset_detection_grace_steps),
        "frozen_temperature_analysis": analyze_frozen_values(scored_df, metadata_df, threshold, "temperature_c", "frozen_temperature"),
        "frozen_humidity_analysis": analyze_frozen_values(scored_df, metadata_df, threshold, "relative_humidity_pct", "frozen_humidity"),
        "drift_analysis": analyze_drift(scored_df, metadata_df, threshold, list(cfg.drift_checkpoint_steps)),
        "missing_data_analysis": analyze_missing_data(scored_df, metadata_df),
    }
