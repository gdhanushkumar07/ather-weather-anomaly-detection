"""
Stage 1 CLI/entrypoint: generate the synthetic temporal dataset.

Usage (run from the backend/ directory, matching run.py's convention):
    python3 -m temporal_dataset.generate_dataset --num-stations 500
    python3 -m temporal_dataset.generate_dataset --num-stations 8 --output-dir /tmp/tiny_test

This module performs ONLY Stage 1 (dataset generation). It does not
implement, train, or reference any LSTM model.
"""
import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from temporal_dataset.config import TemporalGeneratorConfig
from temporal_dataset.station_selection import load_raw_stations, filter_clean_stations, select_stations
from temporal_dataset.splits import assign_station_splits
from temporal_dataset.sequence_generator import generate_station_sequence
from temporal_dataset.validation import build_validation_report


def _config_to_jsonable(cfg: TemporalGeneratorConfig) -> Dict[str, Any]:
    d = dataclasses.asdict(cfg)
    d["source_stations_path"] = str(cfg.source_stations_path)
    d["output_dir"] = str(cfg.output_dir)
    return d


def run_generation(cfg: TemporalGeneratorConfig) -> Dict[str, Any]:
    """
    Executes the full Stage 1 pipeline in-process (no file I/O) and returns
    the generated DataFrame plus metadata/validation dicts. File writing is
    handled separately by main() so this function stays unit-testable.
    """
    raw_stations = load_raw_stations(cfg.source_stations_path)
    clean_stations, selection_report_pre = filter_clean_stations(raw_stations, cfg)
    selected_stations, selection_report_post = select_stations(clean_stations, cfg)
    station_selection_report = {**selection_report_pre, **selection_report_post}

    split_assignment, split_report = assign_station_splits(selected_stations, cfg)

    rows = []
    per_station_meta = []
    clip_totals = {"temperature_c": 0, "pressure_hpa": 0, "relative_humidity_pct": 0}

    for station in selected_stations:
        result = generate_station_sequence(station, cfg)
        split_name = split_assignment[result.station_id]
        sequence_id = f"{result.station_id}-seq001"

        for i, ts in enumerate(result.timestamps):
            rows.append({
                "station_id": result.station_id,
                "timestamp": ts.isoformat(),
                "temperature_c": round(float(result.temperature_c[i]), 3),
                "pressure_hpa": round(float(result.pressure_hpa[i]), 3),
                "relative_humidity_pct": round(float(result.relative_humidity_pct[i]), 3),
                "sequence_id": sequence_id,
                "split": split_name,
                "is_anomaly": False,
                "anomaly_type": None,
            })

        for ch in clip_totals:
            clip_totals[ch] += result.clip_counts[ch]

        per_station_meta.append({
            "station_id": result.station_id,
            "name": station.get("name"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "baseline_temperature_c": station.get("temperature"),
            "baseline_pressure_hpa": station.get("pressure"),
            "baseline_humidity_pct": station.get("humidity"),
            "split": split_name,
            "sequence_id": sequence_id,
            "num_observations": len(result.timestamps),
            "start_timestamp": result.timestamps[0].isoformat(),
            "end_timestamp": result.timestamps[-1].isoformat(),
            "clip_counts": result.clip_counts,
        })

    df = pd.DataFrame(rows)
    clip_report = {"total_clipped_by_channel": clip_totals}

    validation_report = build_validation_report(
        df=df,
        cfg=cfg,
        station_selection_report=station_selection_report,
        split_report=split_report,
        clip_report=clip_report,
    )

    metadata = {
        "generator": "ather.temporal_dataset (Stage 1 — synthetic normal dataset)",
        "config": _config_to_jsonable(cfg),
        "station_selection": station_selection_report,
        "splits": split_report,
        "stations": per_station_meta,
    }

    return {"dataframe": df, "metadata": metadata, "validation": validation_report}


def write_outputs(result: Dict[str, Any], cfg: TemporalGeneratorConfig) -> Dict[str, Path]:
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / cfg.normal_dataset_filename
    metadata_path = out_dir / cfg.metadata_filename
    validation_path = out_dir / cfg.validation_filename

    result["dataframe"].to_csv(csv_path, index=False)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(result["metadata"], f, indent=2, default=str)
    with open(validation_path, "w", encoding="utf-8") as f:
        json.dump(result["validation"], f, indent=2, default=str)

    return {"csv": csv_path, "metadata": metadata_path, "validation": validation_path}


def _print_summary(result: Dict[str, Any], paths: Dict[str, Path]) -> None:
    v = result["validation"]
    print("\n=== ATHER Stage 1 — Synthetic Temporal Dataset Generation ===")
    print(f"Output CSV:        {paths['csv']}")
    print(f"Metadata JSON:     {paths['metadata']}")
    print(f"Validation JSON:   {paths['validation']}")
    print()
    print(f"Stations selected: {v['dataset']['num_stations']}")
    print(f"Observations:      {v['dataset']['num_observations']}")
    print(f"Splits:            train={v['splits']['train_stations']} "
          f"val={v['splits']['val_stations']} test={v['splits']['test_stations']}")
    print()
    t, p, h = v["temperature"], v["pressure"], v["humidity"]
    print(f"Temperature (C):   min={t['min']:.2f} max={t['max']:.2f} mean={t['mean']:.2f} "
          f"std={t['std']:.2f} lag1_autocorr={t['lag1_autocorrelation']:.3f} "
          f"mean_daily_range={t['mean_daily_range']:.2f}")
    print(f"Pressure (hPa):    min={p['min']:.2f} max={p['max']:.2f} mean={p['mean']:.2f} "
          f"std={p['std']:.2f} lag1_autocorr={p['lag1_autocorrelation']:.3f}")
    print(f"Humidity (%):      min={h['min']:.2f} max={h['max']:.2f} mean={h['mean']:.2f} "
          f"std={h['std']:.2f} lag1_autocorr={h['lag1_autocorrelation']:.3f}")
    print()
    r = v["relationships"]
    print(f"T/RH correlation:  overall={r['temperature_humidity_correlation_overall']:.3f} "
          f"per-station mean={r['temperature_humidity_correlation_per_station_mean']:.3f}")
    print(f"Rare joint states (T>32C & RH>95%): {r['rare_joint_state_count_T_gt_32_RH_gt_95']} "
          f"({r['rare_joint_state_pct']}%)")
    print()
    q = v["quality"]
    print(f"Clipped values:    {q['total_clipped_values']} ({q['total_clipped_pct']}%) "
          f"by channel: {q['values_that_required_clipping_by_channel']}")
    print(f"Duplicate (station,timestamp) pairs: {q['duplicate_station_timestamp_pairs']}")
    print(f"Timestamp spacing violations:        {q['timestamp_spacing_violations']}")
    print(f"Missing values by channel:           {q['missing_values_by_channel']}")
    print("\nSTAGE 1 COMPLETE — dataset generation only. No LSTM was trained.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="ATHER Stage 1 synthetic temporal dataset generator")
    parser.add_argument("--num-stations", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--source-stations-path", type=str, default=None)
    args = parser.parse_args(argv)

    cfg = TemporalGeneratorConfig()
    if args.num_stations is not None:
        cfg.num_stations = args.num_stations
    if args.seed is not None:
        cfg.seed = args.seed
    if args.history_days is not None:
        cfg.history_days = args.history_days
    if args.output_dir is not None:
        cfg.output_dir = Path(args.output_dir)
    if args.source_stations_path is not None:
        cfg.source_stations_path = Path(args.source_stations_path)

    result = run_generation(cfg)
    paths = write_outputs(result, cfg)
    _print_summary(result, paths)


if __name__ == "__main__":
    main()
