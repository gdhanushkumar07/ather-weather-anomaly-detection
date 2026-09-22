"""
Stage 3 plots (spec section 19) — kept to exactly the requested set, no more:
  1-3. Normal vs anomalous residual distribution, per channel
  4-7. Example actual-vs-predicted traces: spike, frozen temperature,
       drift, stale packet
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _plot_residual_distribution(baseline_df: pd.DataFrame, anomaly_df: pd.DataFrame, channel: str,
                                  label: str, path: Path):
    normal_vals = baseline_df.loc[baseline_df["residual_available"], f"abs_residual_{channel}"]
    anomalous_vals = anomaly_df.loc[anomaly_df["residual_available"] & anomaly_df["is_anomaly"], f"abs_residual_{channel}"]

    plt.figure(figsize=(7, 4))
    plt.hist(normal_vals, bins=60, density=True, alpha=0.6, label="normal (validation baseline)")
    plt.hist(anomalous_vals, bins=60, density=True, alpha=0.6, label="anomalous (injected test)")
    plt.xlabel(f"absolute residual ({label})")
    plt.ylabel("density")
    plt.title(f"Stage 3: normal vs anomalous residual distribution — {label}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_example_case(anomaly_df: pd.DataFrame, metadata_df: pd.DataFrame, anomaly_type: str,
                         channel: str, path: Path):
    type_meta = metadata_df[metadata_df["anomaly_type"] == anomaly_type]
    if len(type_meta) == 0:
        return
    example = type_meta.iloc[0]
    case_rows = anomaly_df[anomaly_df["anomaly_id"] == example["anomaly_id"]].sort_values("target_index")
    if len(case_rows) == 0:
        return

    start_index = int(example["start_index"])
    end_index = start_index + int(example["duration_steps"]) - 1

    plt.figure(figsize=(8, 4))
    plt.plot(case_rows["target_index"], case_rows[f"actual_{channel}"], label="actual", linewidth=1.5)
    plt.plot(case_rows["target_index"], case_rows[f"predicted_{channel}"], label="predicted", linewidth=1.5, linestyle="--")
    plt.axvspan(start_index, end_index, color="red", alpha=0.15, label="injected anomaly window")
    plt.xlabel("target index (within local slice)")
    plt.ylabel(channel)
    plt.title(f"Stage 3 example: {anomaly_type} ({example['anomaly_id']})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def generate_all_plots(baseline_df: pd.DataFrame, anomaly_scored_df: pd.DataFrame,
                         metadata_df: pd.DataFrame, injected_df: pd.DataFrame, plots_dir: Path):
    _plot_residual_distribution(baseline_df, anomaly_scored_df, "temperature_c", "temperature (deg C)",
                                  plots_dir / "residual_distribution_temperature.png")
    _plot_residual_distribution(baseline_df, anomaly_scored_df, "pressure_hpa", "pressure (hPa)",
                                  plots_dir / "residual_distribution_pressure.png")
    _plot_residual_distribution(baseline_df, anomaly_scored_df, "relative_humidity_pct", "humidity (%)",
                                  plots_dir / "residual_distribution_humidity.png")

    _plot_example_case(anomaly_scored_df, metadata_df, "temperature_spike", "temperature_c",
                         plots_dir / "example_temperature_spike.png")
    _plot_example_case(anomaly_scored_df, metadata_df, "frozen_temperature", "temperature_c",
                         plots_dir / "example_frozen_temperature.png")
    _plot_example_case(anomaly_scored_df, metadata_df, "temperature_drift", "temperature_c",
                         plots_dir / "example_temperature_drift.png")
    _plot_example_case(anomaly_scored_df, metadata_df, "stale_packet", "temperature_c",
                         plots_dir / "example_stale_packet.png")
