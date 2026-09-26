"""
Shared Stage 5 execution utilities: build AWSReading objects from Stage
1/3 CSV rows and run a sequence through TWO parallel, FROZEN Stage 4
TemporalPatternLayer instances — one with LSTM disabled (rule-only
reference) and one with LSTM enabled (the real integrated behavior) — so
"rule-only vs LSTM-only vs integrated" can be measured directly from what
the production code actually computes, without modifying it.
"""
from typing import Any, Dict, List, Optional

import pandas as pd

from config import CONFIG, LSTMTemporalConfig, TemporalThresholds
from schema import AWSReading
from engine.layer2_temporal import TemporalPatternLayer

PHYSICAL_CHANNELS = ["temperature_c", "pressure_hpa", "humidity_pct"]


def make_layers() -> Dict[str, TemporalPatternLayer]:
    """One rules-only and one integrated layer, EACH loading its own state
    independently — but only the integrated layer actually loads the LSTM
    (rules-only skips that work entirely via enabled=False)."""
    rules_only = TemporalPatternLayer(CONFIG.temporal, lstm_config=LSTMTemporalConfig(enabled=False))
    integrated = TemporalPatternLayer(CONFIG.temporal)
    return {"rules_only": rules_only, "integrated": integrated}


def _reading_from_row(row: pd.Series) -> AWSReading:
    return AWSReading(
        station_id=str(row["station_id"]),
        timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
        temperature_c=None if pd.isna(row.get("temperature_c")) else float(row["temperature_c"]),
        pressure_hpa=None if pd.isna(row.get("pressure_hpa")) else float(row["pressure_hpa"]),
        humidity_pct=None if pd.isna(row.get("relative_humidity_pct")) else float(row["relative_humidity_pct"]),
        lat=17.0, lon=78.0,
    )


def run_sequence(
    layers: Dict[str, TemporalPatternLayer],
    seq_df: pd.DataFrame,
    extra_label_columns: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Feeds one station's (or one Stage 3 scenario's) rows, IN TIMESTAMP
    ORDER, through both layers and returns one record per row with both
    layers' outputs side by side.
    """
    seq_df = seq_df.sort_values("timestamp").reset_index(drop=True)
    extra_label_columns = extra_label_columns or []
    records: List[Dict[str, Any]] = []

    for _, row in seq_df.iterrows():
        reading = _reading_from_row(row)

        rec: Dict[str, Any] = {
            "station_id": reading.station_id,
            "timestamp": reading.timestamp,
        }
        for col in extra_label_columns:
            rec[col] = row.get(col)

        for layer_name, layer in layers.items():
            score, scores, reason, detail = layer.evaluate(reading)
            rec[f"{layer_name}_overall_score"] = score
            rec[f"{layer_name}_temperature_score"] = scores["temperature_c"]
            rec[f"{layer_name}_pressure_score"] = scores["pressure_hpa"]
            rec[f"{layer_name}_humidity_score"] = scores["humidity_pct"]
            rec[f"{layer_name}_reason"] = reason
            lstm_detail = detail.get("lstm")
            if layer_name == "integrated" and lstm_detail is not None:
                rec["lstm_available"] = lstm_detail["lstm_available"]
                rec["lstm_skip_reason"] = lstm_detail["lstm_skip_reason"]
                rec["lstm_residual_score"] = lstm_detail["lstm_residual_score"]
                rec["lstm_temperature_score"] = lstm_detail["temperature_lstm_score"]
                rec["lstm_pressure_score"] = lstm_detail["pressure_lstm_score"]
                rec["lstm_humidity_score"] = lstm_detail["humidity_lstm_score"]
                rec["recent_lstm_peak"] = lstm_detail["recent_lstm_peak"]
                rec["recent_lstm_peak_temperature"] = lstm_detail["recent_lstm_peak_by_channel"]["temperature_c"]
                rec["recent_lstm_peak_pressure"] = lstm_detail["recent_lstm_peak_by_channel"]["pressure_hpa"]
                rec["recent_lstm_peak_humidity"] = lstm_detail["recent_lstm_peak_by_channel"]["humidity_pct"]
                rec["lstm_temperature_raw_score"] = lstm_detail["temperature_lstm_raw_score"]
                rec["lstm_pressure_raw_score"] = lstm_detail["pressure_lstm_raw_score"]
                rec["lstm_humidity_raw_score"] = lstm_detail["humidity_lstm_raw_score"]

        records.append(rec)

    return records
