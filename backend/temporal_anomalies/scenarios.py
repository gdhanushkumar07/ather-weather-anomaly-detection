"""
Stage 3 anomaly-injection functions — one per locked ATHER Stage 3 fault
scenario (spec section 4).

Each function:
  - takes a STATION-LOCAL DataFrame copy (never the shared original),
    a start index already guaranteed >= min_history_before_anomaly,
    the experiment config, and a per-scenario deterministic RNG
  - mutates ONLY the affected physical channel(s) for the affected rows
  - sets is_anomaly=True / anomaly_type=<type> on every affected row
  - clips to the EXISTING ATHER physics bounds (config.CONFIG.physics)
    only if a generated value would otherwise leave that range, and
    records whether clipping occurred — never silently
  - returns (mutated_df, metadata_dict) with the fields required by
    spec section 3 (station_id/source_split/anomaly_id are filled in by
    the caller, injector.py, which has that context)
"""
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from config import CONFIG

from .config import AnomalyInjectionConfig

PHYS = CONFIG.physics


def _clip(value: float, lo: float, hi: float) -> Tuple[float, bool]:
    if value < lo:
        return lo, True
    if value > hi:
        return hi, True
    return value, False


def _label_rows(df: pd.DataFrame, indices, anomaly_type: str) -> None:
    df.loc[indices, "is_anomaly"] = True
    df.loc[indices, "anomaly_type"] = anomaly_type


def _base_meta(df: pd.DataFrame, start_index: int, end_index: int, anomaly_type: str,
                affected_channel: str, magnitude: float, severity: float, clipped: bool) -> Dict[str, Any]:
    return {
        "anomaly_type": anomaly_type,
        "affected_channel": affected_channel,
        "start_index": int(start_index),
        "duration_steps": int(end_index - start_index + 1),
        "start_timestamp": df["timestamp"].iloc[start_index].isoformat(),
        "end_timestamp": df["timestamp"].iloc[end_index].isoformat(),
        "magnitude": float(magnitude),
        "severity": float(severity),
        "clipped": bool(clipped),
    }


# ── A/B. Sudden temperature spike / drop (spec 4A, 4B) ──────────────────
def inject_temperature_step(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                              rng: np.random.Generator, direction: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    assert direction in ("spike", "drop")
    lo, hi = cfg.spike_magnitude_c if direction == "spike" else cfg.drop_magnitude_c
    delta = rng.uniform(lo, hi)
    anomaly_type = "temperature_spike" if direction == "spike" else "temperature_drop"

    original = df.loc[start_index, "temperature_c"]
    new_value, clipped = _clip(original + delta, PHYS.temp_min_c, PHYS.temp_max_c)
    df.loc[start_index, "temperature_c"] = new_value
    _label_rows(df, [start_index], anomaly_type)

    span = cfg.spike_magnitude_c if direction == "spike" else cfg.drop_magnitude_c
    severity = min(1.0, abs(delta) / max(abs(span[0]), abs(span[1])))
    meta = _base_meta(df, start_index, start_index, anomaly_type, "temperature_c", delta, severity, clipped)
    return df, meta


# ── C/D. Frozen temperature / humidity (spec 4C, 4D) ─────────────────────
def inject_frozen_channel(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                            rng: np.random.Generator, channel: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    assert channel in ("temperature_c", "relative_humidity_pct")
    lo_d, hi_d = cfg.frozen_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    frozen_value = df.loc[start_index - 1, channel]  # last valid reading before the fault
    df.loc[start_index:end_index, channel] = frozen_value

    anomaly_type = "frozen_temperature" if channel == "temperature_c" else "frozen_humidity"
    _label_rows(df, list(range(start_index, end_index + 1)), anomaly_type)

    severity = (end_index - start_index + 1) / hi_d
    meta = _base_meta(df, start_index, end_index, anomaly_type, channel, frozen_value, min(1.0, severity), False)
    return df, meta


def find_valid_frozen_humidity_start(df: pd.DataFrame, candidate_start: int) -> bool:
    """
    ATHER's existing rule-based logic (engine/layer2_temporal.py) never
    flags humidity as 'frozen' when the constant value is >= 99.5% (near-
    saturation naturally has ~zero variance, not a stuck sensor). Reuse
    that same exception here so the injected fault is an unambiguous test
    case, per spec section 4D.
    """
    return df.loc[candidate_start - 1, "relative_humidity_pct"] < 99.5


# ── E. Slow temperature drift (spec 4E) ──────────────────────────────────
def inject_temperature_drift(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                               rng: np.random.Generator) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_r, hi_r = cfg.drift_rate_c_per_step
    lo_d, hi_d = cfg.drift_duration_steps
    rate = rng.uniform(lo_r, hi_r)
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    clipped_any = False
    for offset, idx in enumerate(range(start_index, end_index + 1), start=1):
        new_value, clipped = _clip(df.loc[idx, "temperature_c"] + rate * offset, PHYS.temp_min_c, PHYS.temp_max_c)
        df.loc[idx, "temperature_c"] = new_value
        clipped_any = clipped_any or clipped

    # Design choice (documented Stage 3 limitation): drift is modeled as a
    # BOUNDED transient episode for interpretability — after `end_index`,
    # the sequence resumes its original (undrifted) trajectory rather than
    # persisting the final offset forever. A permanently-persisting drift
    # model is an equally valid alternative better suited to a later stage.
    _label_rows(df, list(range(start_index, end_index + 1)), "temperature_drift")

    severity = (end_index - start_index + 1) / hi_d
    meta = _base_meta(df, start_index, end_index, "temperature_drift", "temperature_c", rate, min(1.0, severity), clipped_any)
    return df, meta


# ── F. Pressure offset (spec 4F) ─────────────────────────────────────────
def inject_pressure_offset(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                             rng: np.random.Generator) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_d, hi_d = cfg.pressure_offset_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    lo_m, hi_m = cfg.pressure_offset_hpa
    magnitude = rng.uniform(lo_m, hi_m)
    if rng.uniform() < 0.5:
        magnitude = -magnitude

    clipped_any = False
    for idx in range(start_index, end_index + 1):
        new_value, clipped = _clip(df.loc[idx, "pressure_hpa"] + magnitude, PHYS.pressure_min_hpa, PHYS.pressure_max_hpa)
        df.loc[idx, "pressure_hpa"] = new_value
        clipped_any = clipped_any or clipped

    _label_rows(df, list(range(start_index, end_index + 1)), "pressure_offset")

    severity = abs(magnitude) / max(abs(lo_m), abs(hi_m))
    meta = _base_meta(df, start_index, end_index, "pressure_offset", "pressure_hpa", magnitude, min(1.0, severity), clipped_any)
    return df, meta


# ── G. Humidity offset (spec 4G) ─────────────────────────────────────────
def inject_humidity_offset(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                             rng: np.random.Generator) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_d, hi_d = cfg.humidity_offset_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    lo_m, hi_m = cfg.humidity_offset_pct
    magnitude = rng.uniform(lo_m, hi_m)
    if rng.uniform() < 0.5:
        magnitude = -magnitude

    clipped_any = False
    for idx in range(start_index, end_index + 1):
        new_value, clipped = _clip(df.loc[idx, "relative_humidity_pct"] + magnitude, PHYS.humidity_min_pct, PHYS.humidity_max_pct)
        df.loc[idx, "relative_humidity_pct"] = new_value
        clipped_any = clipped_any or clipped

    _label_rows(df, list(range(start_index, end_index + 1)), "humidity_offset")

    severity = abs(magnitude) / max(abs(lo_m), abs(hi_m))
    meta = _base_meta(df, start_index, end_index, "humidity_offset", "relative_humidity_pct", magnitude, min(1.0, severity), clipped_any)
    return df, meta


# ── H. Short noise burst (spec 4H) ───────────────────────────────────────
def inject_noise_burst(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                         rng: np.random.Generator, channel: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_d, hi_d = cfg.noise_burst_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    bounds = {
        "temperature_c": (PHYS.temp_min_c, PHYS.temp_max_c),
        "pressure_hpa": (PHYS.pressure_min_hpa, PHYS.pressure_max_hpa),
        "relative_humidity_pct": (PHYS.humidity_min_pct, PHYS.humidity_max_pct),
    }[channel]

    # Local normal noise scale, estimated from this station's own recent
    # variability (spec: "use the local normal signal variability", not an
    # arbitrary global constant).
    window = df.loc[max(0, start_index - cfg.local_noise_window_steps):start_index - 1, channel]
    local_std = float(window.diff().dropna().std()) if len(window) > 1 else 0.1
    local_std = max(local_std, 1e-3)

    lo_mult, hi_mult = cfg.noise_burst_multiplier
    multiplier = rng.uniform(lo_mult, hi_mult)

    clipped_any = False
    for idx in range(start_index, end_index + 1):
        perturbation = rng.normal(loc=0.0, scale=local_std * multiplier)
        new_value, clipped = _clip(df.loc[idx, channel] + perturbation, *bounds)
        df.loc[idx, channel] = new_value
        clipped_any = clipped_any or clipped

    _label_rows(df, list(range(start_index, end_index + 1)), "noise_burst")

    meta = _base_meta(df, start_index, end_index, "noise_burst", channel, multiplier, min(1.0, multiplier / hi_mult), clipped_any)
    return df, meta


# ── I. Missing observations (spec 4I) ────────────────────────────────────
def inject_missing_observation(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                                 rng: np.random.Generator, channel: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_d, hi_d = cfg.missing_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    df.loc[start_index:end_index, channel] = np.nan  # NEVER zero-substituted

    anomaly_type = f"missing_{channel.split('_')[0]}" if channel != "relative_humidity_pct" else "missing_humidity"
    # Normalize label name to match spec's requested field names exactly.
    anomaly_type = {
        "temperature_c": "missing_temperature",
        "pressure_hpa": "missing_pressure",
        "relative_humidity_pct": "missing_humidity",
    }[channel]
    _label_rows(df, list(range(start_index, end_index + 1)), "missing_observation")
    df.loc[start_index:end_index, "missing_channel"] = channel

    meta = _base_meta(df, start_index, end_index, "missing_observation", channel, float("nan"), 1.0, False)
    meta["missing_channel"] = channel
    return df, meta


# ── J. Stale / repeated packet (spec 4J) ─────────────────────────────────
def inject_stale_packet(df: pd.DataFrame, start_index: int, cfg: AnomalyInjectionConfig,
                          rng: np.random.Generator) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    lo_d, hi_d = cfg.stale_duration_steps
    duration = int(rng.integers(lo_d, hi_d + 1))
    end_index = min(start_index + duration - 1, len(df) - 1)

    stale_row = df.loc[start_index - 1, ["temperature_c", "pressure_hpa", "relative_humidity_pct"]].copy()
    for ch in ["temperature_c", "pressure_hpa", "relative_humidity_pct"]:
        df.loc[start_index:end_index, ch] = stale_row[ch]

    _label_rows(df, list(range(start_index, end_index + 1)), "stale_packet")

    meta = _base_meta(df, start_index, end_index, "stale_packet", "temperature_c,pressure_hpa,relative_humidity_pct",
                        0.0, 1.0, False)
    return df, meta
