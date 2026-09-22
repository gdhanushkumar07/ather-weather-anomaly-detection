"""
Stage 3 injection orchestration.

For every (test station x anomaly type x injection index), builds ONE
independent LOCAL SLICE copy of that station's own Stage 1 normal
timeline (never the shared original — see config.STAGE1_DATASET_FILENAME,
loaded read-only), injects exactly ONE anomaly instance into it (spec
section 6: one anomaly per scenario sequence), and records full metadata.

STORAGE NOTE: a "local slice" spans only [anomaly_start - 144 - lead_buffer,
anomaly_end + trailing_buffer] of the station's 1008-row timeline, not the
full station. This is sufficient for every Stage 3 metric requested
(onset residual, max residual, persistence/recovery, detection delay) —
the excluded rows are byte-identical to Stage 1's untouched normal data
and evaluating them again would be redundant. This keeps the generated
"injected anomaly dataset" a manageable size instead of ~7,500 full
1008-row duplicates.
"""
import uuid
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from .config import ANOMALY_TYPES, AnomalyInjectionConfig
from .scenarios import (
    find_valid_frozen_humidity_start, inject_frozen_channel, inject_humidity_offset,
    inject_missing_observation, inject_noise_burst, inject_pressure_offset,
    inject_stale_packet, inject_temperature_drift, inject_temperature_step,
)
from .utils import scenario_rng

CHANNELS = ["temperature_c", "pressure_hpa", "relative_humidity_pct"]


def _pick_start_index(rng: np.random.Generator, cfg: AnomalyInjectionConfig, station_len: int, max_duration: int) -> int:
    lo = cfg.min_history_before_anomaly
    hi = station_len - cfg.trailing_buffer_steps - max_duration - 1
    if hi <= lo:
        raise ValueError("Station too short for the configured buffers/durations.")
    return int(rng.integers(lo, hi + 1))


def _slice_bounds(start_index: int, cfg: AnomalyInjectionConfig, station_len: int) -> Tuple[int, int]:
    slice_start = max(0, start_index - cfg.min_history_before_anomaly - cfg.lead_buffer_steps)
    return slice_start, station_len  # upper bound trimmed later once the actual end_index is known


def _run_one_injection(
    station_df: pd.DataFrame,
    anomaly_type: str,
    injection_index: int,
    cfg: AnomalyInjectionConfig,
    source_split: str,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    station_id = str(station_df["station_id"].iloc[0])
    rng = scenario_rng(cfg.seed, station_id, anomaly_type, injection_index)
    station_len = len(station_df)
    max_duration = cfg.duration_range_for(anomaly_type)[1]

    # Frozen humidity needs a retry loop to avoid near-saturation baselines
    # (spec 4D / existing ATHER convention — see scenarios.find_valid_frozen_humidity_start).
    for attempt in range(25):
        start_index = _pick_start_index(rng, cfg, station_len, max_duration)
        if anomaly_type != "frozen_humidity" or find_valid_frozen_humidity_start(station_df, start_index):
            break
    else:
        raise RuntimeError(f"Could not find a valid frozen_humidity start for station {station_id} after 25 attempts.")

    slice_start, _ = _slice_bounds(start_index, cfg, station_len)
    # Generous upper bound; trimmed to the anomaly's actual end after injection.
    provisional_slice_end = min(station_len - 1, start_index + max_duration + cfg.trailing_buffer_steps)

    local_df = station_df.iloc[slice_start:provisional_slice_end + 1].reset_index(drop=True)
    local_df["is_anomaly"] = False
    local_df["anomaly_type"] = "none"
    local_df["missing_channel"] = None
    local_start_index = start_index - slice_start
    assert local_start_index >= cfg.min_history_before_anomaly, (
        f"Local slice does not retain {cfg.min_history_before_anomaly} lookback steps before the anomaly "
        f"(station={station_id}, type={anomaly_type})."
    )

    if anomaly_type == "temperature_spike":
        local_df, meta = inject_temperature_step(local_df, local_start_index, cfg, rng, direction="spike")
    elif anomaly_type == "temperature_drop":
        local_df, meta = inject_temperature_step(local_df, local_start_index, cfg, rng, direction="drop")
    elif anomaly_type == "frozen_temperature":
        local_df, meta = inject_frozen_channel(local_df, local_start_index, cfg, rng, channel="temperature_c")
    elif anomaly_type == "frozen_humidity":
        local_df, meta = inject_frozen_channel(local_df, local_start_index, cfg, rng, channel="relative_humidity_pct")
    elif anomaly_type == "temperature_drift":
        local_df, meta = inject_temperature_drift(local_df, local_start_index, cfg, rng)
    elif anomaly_type == "pressure_offset":
        local_df, meta = inject_pressure_offset(local_df, local_start_index, cfg, rng)
    elif anomaly_type == "humidity_offset":
        local_df, meta = inject_humidity_offset(local_df, local_start_index, cfg, rng)
    elif anomaly_type == "noise_burst":
        channel = rng.choice(CHANNELS)
        local_df, meta = inject_noise_burst(local_df, local_start_index, cfg, rng, channel=channel)
    elif anomaly_type == "missing_observation":
        channel = rng.choice(CHANNELS)
        local_df, meta = inject_missing_observation(local_df, local_start_index, cfg, rng, channel=channel)
    elif anomaly_type == "stale_packet":
        local_df, meta = inject_stale_packet(local_df, local_start_index, cfg, rng)
    else:
        raise ValueError(f"Unknown anomaly type: {anomaly_type}")

    # Trim the slice's trailing rows down to end_index + trailing_buffer
    # (the provisional slice used the WORST-CASE max_duration; the actual
    # sampled duration is usually shorter).
    end_index_local = local_start_index + meta["duration_steps"] - 1
    final_end_local = min(len(local_df) - 1, end_index_local + cfg.trailing_buffer_steps)
    local_df = local_df.iloc[:final_end_local + 1].reset_index(drop=True)

    anomaly_id = f"{station_id}-{anomaly_type}-{injection_index:03d}"
    local_df["anomaly_id"] = anomaly_id
    local_df["source_split"] = source_split

    meta.update({
        "anomaly_id": anomaly_id,
        "station_id": station_id,
        "source_split": source_split,
        "injection_index": injection_index,
        "local_slice_start_index": local_start_index,
    })
    return local_df, meta


def generate_anomaly_dataset(
    normal_df: pd.DataFrame,
    cfg: AnomalyInjectionConfig,
    split: str = "test",
    anomaly_types: List[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Builds the full Stage 3 injected-anomaly dataset for every station in
    `split` (spec section 7: must be the held-out TEST stations for the
    final detection experiment; NORMAL VALIDATION is evaluated separately,
    uninjected, in evaluate.py).

    Returns (injected_sequences_df, anomaly_metadata_df).
    """
    anomaly_types = anomaly_types or ANOMALY_TYPES
    station_ids = sorted(normal_df.loc[normal_df["split"] == split, "station_id"].unique())

    all_local_dfs: List[pd.DataFrame] = []
    all_meta: List[Dict[str, Any]] = []

    for station_id in station_ids:
        station_df = normal_df[normal_df["station_id"] == station_id].sort_values("timestamp").reset_index(drop=True)
        for anomaly_type in anomaly_types:
            for injection_index in range(cfg.injections_per_type_per_station):
                local_df, meta = _run_one_injection(station_df, anomaly_type, injection_index, cfg, split)
                all_local_dfs.append(local_df)
                all_meta.append(meta)

    injected_df = pd.concat(all_local_dfs, ignore_index=True)
    metadata_df = pd.DataFrame(all_meta)
    return injected_df, metadata_df
