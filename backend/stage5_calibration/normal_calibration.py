"""
Phase 3/4: run the FROZEN Stage 4 layer (rules-only AND integrated) over
REPRESENTATIVE Stage 1 normal traffic (the actual AR(1)+diurnal synthetic
generator output — NOT the Stage 4 report's simple sine-wave demo
fixture), to determine whether normal traffic produces excessive temporal
evidence, and whether the Stage 4 demo's ~0.70 example was representative.
"""
from typing import Any, Dict

import pandas as pd

from .config import Stage5Config, STAGE1_DATASET_PATH
from .runner import make_layers, run_sequence
from .stats import summarize


def load_normal_calibration_data(cfg: Stage5Config) -> pd.DataFrame:
    df = pd.read_csv(STAGE1_DATASET_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    split_df = df[df["split"] == cfg.normal_calibration_split]
    return split_df


def run_normal_calibration(cfg: Stage5Config) -> Dict[str, Any]:
    split_df = load_normal_calibration_data(cfg)
    station_ids = sorted(split_df["station_id"].unique())
    layers = make_layers()

    all_records = []
    for station_id in station_ids:
        seq_df = split_df[split_df["station_id"] == station_id]
        all_records.extend(run_sequence(layers, seq_df))

    records_df = pd.DataFrame(all_records)

    result: Dict[str, Any] = {
        "dataset_source": str(STAGE1_DATASET_PATH),
        "split_used": cfg.normal_calibration_split,
        "n_stations": len(station_ids),
        "n_observations": len(records_df),
    }

    thresholds = list(cfg.reporting_thresholds)

    result["rule_only"] = {
        "overall": summarize(records_df["rules_only_overall_score"], thresholds),
        "temperature": summarize(records_df["rules_only_temperature_score"], thresholds),
        "pressure": summarize(records_df["rules_only_pressure_score"], thresholds),
        "humidity": summarize(records_df["rules_only_humidity_score"], thresholds),
    }

    # The first 1-2 readings per station (before the rule-based
    # _MIN_HISTORY_FOR_TEMPORAL early-return) never get a "lstm" detail key
    # at all (documented Stage 4 limitation) -> NaN here, not False.
    records_df["lstm_available"] = records_df["lstm_available"].fillna(False).astype(bool)
    lstm_available_df = records_df[records_df["lstm_available"]]
    result["lstm_only_instantaneous"] = {
        "overall": summarize(lstm_available_df["lstm_residual_score"], thresholds),
        "temperature": summarize(lstm_available_df["lstm_temperature_score"], thresholds),
        "pressure": summarize(lstm_available_df["lstm_pressure_score"], thresholds),
        "humidity": summarize(lstm_available_df["lstm_humidity_score"], thresholds),
        "note": "Computed only over rows where lstm_available=True.",
    }

    result["recent_peak"] = {
        "overall": summarize(lstm_available_df["recent_lstm_peak"], thresholds),
        "temperature": summarize(lstm_available_df["recent_lstm_peak_temperature"], thresholds),
        "pressure": summarize(lstm_available_df["recent_lstm_peak_pressure"], thresholds),
        "humidity": summarize(lstm_available_df["recent_lstm_peak_humidity"], thresholds),
    }

    result["integrated"] = {
        "overall": summarize(records_df["integrated_overall_score"], thresholds),
        "temperature": summarize(records_df["integrated_temperature_score"], thresholds),
        "pressure": summarize(records_df["integrated_pressure_score"], thresholds),
        "humidity": summarize(records_df["integrated_humidity_score"], thresholds),
    }

    result["reason_report_rate"] = {
        "rules_only_pct": float(100.0 * records_df["rules_only_reason"].notna().mean()),
        "integrated_pct": float(100.0 * records_df["integrated_reason"].notna().mean()),
    }

    result["reference_fusion_threshold_exceedance"] = {
        "note": "For reference only (CONFIG.fusion.ensemble_anomaly_threshold=0.55) — "
                "NOT a layer-level decision; layer2 itself has no binary anomaly flag.",
        "rules_only_pct_gt_0_55": float(100.0 * (records_df["rules_only_overall_score"] > 0.55).mean()),
        "integrated_pct_gt_0_55": float(100.0 * (records_df["integrated_overall_score"] > 0.55).mean()),
    }

    result["lstm_availability"] = {
        "available_pct": float(100.0 * records_df["lstm_available"].mean()),
        "skip_reason_counts": records_df.loc[~records_df["lstm_available"], "lstm_skip_reason"].value_counts().to_dict(),
    }

    # Phase 4: where does a 0.70 integrated score fall in this REAL distribution?
    integrated_scores = records_df["integrated_overall_score"].to_numpy()
    result["phase4_0p70_investigation"] = {
        "pct_of_normal_readings_with_integrated_score_gt_0_70": float(100.0 * (integrated_scores > 0.70).mean()),
        "pct_of_normal_readings_with_integrated_score_in_0p65_0p75_band": float(
            100.0 * ((integrated_scores >= 0.65) & (integrated_scores <= 0.75)).mean()
        ),
        "percentile_rank_of_score_0p70": float(100.0 * (integrated_scores < 0.70).mean()),
    }

    return {"summary": result, "records_df": records_df}
