"""
Phase 5/6/7: LSTM-vs-rule contribution per anomaly type, reason-threshold
sweep, and recent-peak persistence/onset analysis.

Reuses Stage 3's ALREADY-GENERATED injected_sequences_local.csv (same
seed=42, same 75 held-out test stations, unmodified) rather than
regenerating it. For runtime efficiency, Stage 5 evaluates a DETERMINISTIC
SUBSAMPLE of Stage 3's 750 cases/type (the alphabetically-first N
anomaly_ids per type) through the two production layers — Stage 3 already
established full-n=750 detection-rate statistics; Stage 5's new
contribution is comparing against RULE scores, which Stage 3 never
computed (Stage 3 evaluated the standalone LSTM only, not the integrated
production layer).
"""
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .config import Stage5Config, STAGE3_INJECTED_SEQUENCES_PATH, STAGE3_ANOMALY_METADATA_PATH
from .runner import make_layers, run_sequence

ANOMALY_TYPES = [
    "temperature_spike", "temperature_drop", "frozen_temperature", "frozen_humidity",
    "temperature_drift", "pressure_offset", "humidity_offset", "noise_burst",
    "missing_observation", "stale_packet",
]

CHANNEL_BY_TYPE_PRIMARY = {
    "temperature_spike": "temperature", "temperature_drop": "temperature",
    "frozen_temperature": "temperature", "temperature_drift": "temperature",
    "frozen_humidity": "humidity", "humidity_offset": "humidity",
    "pressure_offset": "pressure", "noise_burst": None,
    "missing_observation": None, "stale_packet": None,
}


def select_subsample_anomaly_ids(cfg: Stage5Config, n_per_type: int = 20) -> pd.DataFrame:
    meta = pd.read_csv(STAGE3_ANOMALY_METADATA_PATH)
    subsample = (
        meta.sort_values("anomaly_id")
        .groupby("anomaly_type", group_keys=False)
        .head(n_per_type)
    )
    return subsample


def run_anomaly_contribution(cfg: Stage5Config, n_per_type: int = 20) -> Dict[str, Any]:
    subsample_meta = select_subsample_anomaly_ids(cfg, n_per_type)
    selected_ids = set(subsample_meta["anomaly_id"])

    layers = make_layers()

    all_records: List[Dict[str, Any]] = []
    # injected_sequences_local.csv is large (227MB) -> stream in chunks and
    # only keep rows for the selected subsample's anomaly_ids.
    chunks = []
    for chunk in pd.read_csv(STAGE3_INJECTED_SEQUENCES_PATH, chunksize=200_000):
        matched = chunk[chunk["anomaly_id"].isin(selected_ids)]
        if len(matched):
            chunks.append(matched)
    injected_df = pd.concat(chunks, ignore_index=True)
    injected_df["timestamp"] = pd.to_datetime(injected_df["timestamp"], utc=True)

    for anomaly_id, seq_df in injected_df.groupby("anomaly_id", sort=False):
        records = run_sequence(layers, seq_df, extra_label_columns=["is_anomaly", "anomaly_type"])
        for r in records:
            r["anomaly_id"] = anomaly_id
        all_records.extend(records)

    records_df = pd.DataFrame(all_records)
    records_df["is_anomaly"] = records_df["is_anomaly"].astype(bool)
    records_df["lstm_available"] = records_df["lstm_available"].fillna(False).astype(bool)

    per_type: Dict[str, Any] = {}
    for atype in ANOMALY_TYPES:
        type_rows = records_df[records_df["anomaly_type"] == atype]
        anomalous_rows = type_rows[type_rows["is_anomaly"]]
        normal_rows_in_scenario = type_rows[~type_rows["is_anomaly"]]

        if len(anomalous_rows) == 0:
            per_type[atype] = {"n_cases": int(subsample_meta[subsample_meta.anomaly_type == atype].shape[0]),
                                "n_anomalous_rows": 0, "note": "no anomalous rows scored (e.g. missing_observation)"}
            continue

        rule_max = float(anomalous_rows.groupby("anomaly_id")["rules_only_overall_score"].max().median())
        lstm_max = float(anomalous_rows.groupby("anomaly_id")["lstm_residual_score"].max().median()) \
            if anomalous_rows["lstm_available"].any() else None
        peak_max = float(anomalous_rows.groupby("anomaly_id")["recent_lstm_peak"].max().median()) \
            if anomalous_rows["lstm_available"].any() else None
        integrated_max = float(anomalous_rows.groupby("anomaly_id")["integrated_overall_score"].max().median())

        rule_median_normal = float(normal_rows_in_scenario["rules_only_overall_score"].median()) if len(normal_rows_in_scenario) else None
        lstm_median_normal = float(normal_rows_in_scenario["lstm_residual_score"].median()) if len(normal_rows_in_scenario) else None

        # Classification A/B/C/D (spec section 11 / report section 7)
        rule_strong = rule_max >= 0.7
        lstm_strong = (lstm_max or 0) >= 0.7
        if rule_strong and lstm_strong:
            classification = "B: LSTM confirms existing rule evidence (both strong, largely redundant)"
        elif (not rule_strong) and lstm_strong:
            classification = "A: LSTM adds evidence rules alone would miss"
        elif rule_strong and not lstm_strong:
            classification = "C: LSTM contributes little (rules already strong, LSTM weak)"
        else:
            classification = "C: LSTM contributes little (neither strong on this median measure)"

        per_type[atype] = {
            "n_cases": int(subsample_meta[subsample_meta.anomaly_type == atype].shape[0]),
            "n_anomalous_rows": int(len(anomalous_rows)),
            "median_max_rule_score_during_anomaly": round(rule_max, 4),
            "median_max_lstm_instantaneous_score_during_anomaly": round(lstm_max, 4) if lstm_max is not None else None,
            "median_max_recent_peak_during_anomaly": round(peak_max, 4) if peak_max is not None else None,
            "median_max_integrated_score_during_anomaly": round(integrated_max, 4),
            "median_lstm_instantaneous_score_on_normal_segment_of_same_scenario": round(lstm_median_normal, 4) if lstm_median_normal is not None else None,
            "median_rule_score_on_normal_segment_of_same_scenario": round(rule_median_normal, 4) if rule_median_normal is not None else None,
            "classification": classification,
        }

    # ── Phase 6: reason-threshold sweep (post-hoc, no re-inference needed) ──
    threshold_sweep = {}
    for thr in cfg.candidate_reason_thresholds:
        anomalous = records_df[records_df["is_anomaly"]]
        normal_in_scenarios = records_df[~records_df["is_anomaly"]]
        anomaly_explain_rate = float(100.0 * (anomalous["recent_lstm_peak"] > thr).mean()) if len(anomalous) else None
        normal_explain_rate = float(100.0 * (normal_in_scenarios["recent_lstm_peak"] > thr).mean()) if len(normal_in_scenarios) else None
        threshold_sweep[str(thr)] = {
            "anomaly_row_explanation_rate_pct": anomaly_explain_rate,
            "normal_row_explanation_rate_pct_within_anomaly_scenarios": normal_explain_rate,
        }

    return {
        "per_type": per_type,
        "reason_threshold_sweep_on_anomaly_data": threshold_sweep,
        "n_scenarios_evaluated": int(records_df["anomaly_id"].nunique()),
        "n_rows_evaluated": int(len(records_df)),
        "subsample_size_per_type": n_per_type,
        "records_df": records_df,
    }
