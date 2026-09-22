"""
Validation and statistics reporting for the Stage 1 synthetic temporal dataset.

Computes exactly the checks required by the Stage 1 spec (§8, §15):
per-channel distribution stats, lag-1 autocorrelation, diurnal range,
T/RH relationship, physical-bound/clipping accounting, and structural
integrity checks (duplicates, timestamp spacing, missing values).

No new ATHER detection thresholds are introduced here — physical bounds
are read from config.CONFIG.physics, the same source used everywhere else.
"""
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from config import CONFIG

try:
    import metpy.calc as mpcalc
    from metpy.units import units as metpy_units
    METPY_AVAILABLE = True
except ImportError:
    METPY_AVAILABLE = False


def _lag1_autocorr(series: np.ndarray) -> float:
    if len(series) < 3:
        return float("nan")
    x0 = series[:-1]
    x1 = series[1:]
    if np.std(x0) < 1e-9 or np.std(x1) < 1e-9:
        return float("nan")
    return float(np.corrcoef(x0, x1)[0, 1])


def _channel_stats(df: pd.DataFrame, col: str) -> Dict[str, float]:
    vals = df[col].to_numpy(dtype=float)
    return {
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "mean": float(np.mean(vals)),
        "std": float(np.std(vals)),
        "lag1_autocorrelation": _lag1_autocorr(vals),
    }


def _daily_range_stats(df: pd.DataFrame, col: str) -> Dict[str, float]:
    """Average of (per-calendar-day max - min) across all station-days."""
    tmp = df.copy()
    tmp["_date"] = pd.to_datetime(tmp["timestamp"]).dt.date
    grouped = tmp.groupby(["station_id", "_date"])[col].agg(["max", "min"])
    daily_range = (grouped["max"] - grouped["min"])
    return {
        "mean_daily_range": float(daily_range.mean()) if len(daily_range) else float("nan"),
        "max_daily_range": float(daily_range.max()) if len(daily_range) else float("nan"),
    }


def _dewpoint_sanity_check(df: pd.DataFrame, sample_n: int = 2000) -> Dict[str, Any]:
    """
    Optional MetPy-based sanity check (validation only, per Stage 1 spec):
    dew point derived from generated T/RH must never exceed generated T —
    the exact physical relationship layer1_physics.py already vetoes on.
    Uses the same fallback-free MetPy path when available; skipped
    (not failed) when MetPy is unavailable, matching the try/except
    pattern already used in engine/layer1_physics.py.
    """
    if not METPY_AVAILABLE or len(df) == 0:
        return {"performed": False, "reason": "metpy_unavailable" if not METPY_AVAILABLE else "empty_dataset"}

    sample = df.sample(n=min(sample_n, len(df)), random_state=0)
    violations = 0
    checked = 0
    for t, rh in zip(sample["temperature_c"], sample["relative_humidity_pct"]):
        try:
            safe_rh = max(0.5, min(100.0, float(rh)))
            dewpoint = mpcalc.dewpoint_from_relative_humidity(
                float(t) * metpy_units.degC, safe_rh * metpy_units.percent
            ).to("degC").magnitude
            checked += 1
            if dewpoint > float(t) + 0.5:  # matches PhysicsThresholds.dew_point_margin_c
                violations += 1
        except Exception:
            continue

    return {
        "performed": True,
        "sample_size": checked,
        "dewpoint_exceeds_temperature_count": violations,
        "dewpoint_exceeds_temperature_pct": round(100.0 * violations / checked, 4) if checked else None,
    }


def build_validation_report(
    df: pd.DataFrame,
    cfg,
    station_selection_report: Dict[str, Any],
    split_report: Dict[str, Any],
    clip_report: Dict[str, Any],
) -> Dict[str, Any]:
    phys = CONFIG.physics
    n_stations = df["station_id"].nunique()
    n_obs = len(df)
    obs_per_station = df.groupby("station_id").size()

    # ── Structural integrity checks ─────────────────────────────────────
    dup_station_ts = int(df.duplicated(subset=["station_id", "timestamp"]).sum())
    missing_counts = {
        col: int(df[col].isna().sum())
        for col in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]
    }

    spacing_violations = 0
    for _, g in df.groupby("station_id"):
        ts = pd.to_datetime(g["timestamp"]).sort_values()
        diffs = ts.diff().dropna()
        expected = pd.Timedelta(minutes=cfg.sampling_interval_minutes)
        spacing_violations += int((diffs != expected).sum())

    # NOTE: `df` here already reflects post-clip values (clipping happens in
    # sequence_generator.py before rows are assembled) — so this counts
    # violations remaining in the OUTPUT dataset, which must always be 0 if
    # clipping worked correctly. The count of values that NEEDED clipping
    # (the pre-clip violation count) is reported separately below via
    # clip_report, which is captured by the generator before clipping.
    bound_violations_in_output = {
        "temperature_c": int(((df["temperature_c"] < phys.temp_min_c) | (df["temperature_c"] > phys.temp_max_c)).sum()),
        "pressure_hpa": int(((df["pressure_hpa"] < phys.pressure_min_hpa) | (df["pressure_hpa"] > phys.pressure_max_hpa)).sum()),
        "relative_humidity_pct": int(((df["relative_humidity_pct"] < phys.humidity_min_pct) | (df["relative_humidity_pct"] > phys.humidity_max_pct)).sum()),
    }

    # ── Relationships ────────────────────────────────────────────────────
    t_rh_corr = float(df[["temperature_c", "relative_humidity_pct"]].corr().iloc[0, 1])

    # Per-station T/RH correlation distribution (sanity check the coupling
    # direction is consistently negative, not just on average).
    per_station_corr = df.groupby("station_id")[["temperature_c", "relative_humidity_pct"]].apply(
        lambda g: g["temperature_c"].corr(g["relative_humidity_pct"])
    )
    per_station_corr = per_station_corr.dropna()

    # Clausius-Clapeyron-style joint-state check: normal synthetic data
    # should almost never land in the same "rare joint state" region
    # layer3_multivariate.py flags (T > 32C and RH > 95%).
    rare_joint_state_count = int(((df["temperature_c"] > 32.0) & (df["relative_humidity_pct"] > 95.0)).sum())

    total_clipped = sum(clip_report.get("total_clipped_by_channel", {}).values())

    report = {
        "dataset": {
            "num_stations": n_stations,
            "num_observations": n_obs,
            "observations_per_station_min": int(obs_per_station.min()) if n_stations else 0,
            "observations_per_station_max": int(obs_per_station.max()) if n_stations else 0,
            "days_per_station": cfg.history_days,
            "sampling_interval_minutes": cfg.sampling_interval_minutes,
            "random_seed": cfg.seed,
        },
        "station_selection": station_selection_report,
        "splits": split_report,
        "temperature": {**_channel_stats(df, "temperature_c"), **_daily_range_stats(df, "temperature_c")},
        "pressure": _channel_stats(df, "pressure_hpa"),
        "humidity": _channel_stats(df, "relative_humidity_pct"),
        "relationships": {
            "temperature_humidity_correlation_overall": t_rh_corr,
            "temperature_humidity_correlation_per_station_mean": float(per_station_corr.mean()) if len(per_station_corr) else None,
            "temperature_humidity_correlation_per_station_std": float(per_station_corr.std()) if len(per_station_corr) else None,
            "temperature_humidity_coupling_expected_sign": "negative",
            "rare_joint_state_count_T_gt_32_RH_gt_95": rare_joint_state_count,
            "rare_joint_state_pct": round(100.0 * rare_joint_state_count / n_obs, 4) if n_obs else 0.0,
            "dewpoint_sanity_check": _dewpoint_sanity_check(df),
        },
        "quality": {
            "missing_values_by_channel": missing_counts,
            "physical_bound_violations_remaining_in_output": bound_violations_in_output,
            "values_that_required_clipping_by_channel": clip_report.get("total_clipped_by_channel", {}),
            "total_clipped_values": total_clipped,
            "total_clipped_pct": round(100.0 * total_clipped / (n_obs * 3), 6) if n_obs else 0.0,
            "duplicate_station_timestamp_pairs": dup_station_ts,
            "timestamp_spacing_violations": spacing_violations,
            "physics_bounds_used": station_selection_report.get("physics_bounds_used"),
        },
        "limitations": [
            "This is a synthetic normal-weather approximation (diurnal cycle + AR(1) "
            "slow/fast correlated components), not a physical weather model.",
            "It does not reproduce fronts, rainfall, cloud-driven irregular temperature "
            "changes, monsoon transitions, or real sensor-specific behavior.",
            "It must not be presented as real Indian AWS telemetry or as a measure of "
            "real-world anomaly-detection accuracy.",
            "Local solar time used to phase the diurnal cycle is a coarse longitude-based "
            "approximation (15 deg longitude ~= 1 hour), not a real timezone conversion.",
        ],
    }
    return report
