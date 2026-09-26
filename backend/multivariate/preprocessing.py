"""
Dataset-independent preprocessing onto the standard schema.

Applied identically to every dataset after its adapter has renamed columns:
  0. keep ONLY station_id, timestamp, temperature_c, pressure_hpa,
     humidity_pct (+ latitude/longitude); every other column is dropped
  1. require the standard columns, coerce channels to numeric
  2. timestamps -> tz-aware UTC
  3. drop rows where any of T/P/RH is missing or non-finite (Layer 3 only
     models jointly-valid observations; it never imputes)
  4. drop rows outside ATHER's hard physical bounds (config.CONFIG.physics).
     Those are Layer 1's responsibility — they must not enter Layer 3's
     learned "normal" distribution.
  5. drop duplicate (station_id, timestamp) rows, keep the first
  6. sort by station, then time

Every removal is counted and returned, never silent.
"""
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from config import CONFIG
from multivariate import schema as S


def standardize(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    missing = [c for c in S.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing standard columns {missing}; available: {list(df.columns)}")

    report: Dict[str, int] = {"rows_received": int(len(df))}
    # Explicit column selection: Layer 3 consumes T, RH, P + time, and station
    # location (only to map a station to its regional reference and to compute
    # local solar time). Any other column a dataset carries (wind, rain,
    # surface pressure, labels, ...) is dropped here, never silently modelled.
    keep = [c for c in S.REQUIRED_COLUMNS + [S.LATITUDE, S.LONGITUDE] if c in df.columns]
    report["columns_dropped"] = sorted(set(df.columns) - set(keep))
    out = df[keep].copy()
    out[S.STATION_ID] = out[S.STATION_ID].astype(str)
    for c in S.CHANNELS:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    ts = pd.to_datetime(out[S.TIMESTAMP], errors="coerce", utc=False)
    if getattr(ts.dt, "tz", None) is None:
        raise ValueError("Adapter must provide tz-aware timestamps (localize before standardize()).")
    out[S.TIMESTAMP] = ts.dt.tz_convert("UTC")

    bad_ts = out[S.TIMESTAMP].isna()
    report["dropped_bad_timestamp"] = int(bad_ts.sum())
    out = out[~bad_ts]

    finite = np.isfinite(out[S.CHANNELS].to_numpy(dtype=float)).all(axis=1)
    report["dropped_missing_or_nonfinite_channel"] = int((~finite).sum())
    out = out[finite]

    phys = CONFIG.physics
    in_bounds = (
        out[S.TEMPERATURE].between(phys.temp_min_c, phys.temp_max_c)
        & out[S.PRESSURE].between(phys.pressure_min_hpa, phys.pressure_max_hpa)
        & out[S.HUMIDITY].between(phys.humidity_min_pct, phys.humidity_max_pct)
    )
    report["dropped_outside_physical_bounds"] = int((~in_bounds).sum())
    out = out[in_bounds]

    dup = out.duplicated([S.STATION_ID, S.TIMESTAMP], keep="first")
    report["dropped_duplicate_station_timestamp"] = int(dup.sum())
    out = out[~dup]

    out = out.sort_values([S.STATION_ID, S.TIMESTAMP]).reset_index(drop=True)
    report["rows_retained"] = int(len(out))
    report["stations"] = int(out[S.STATION_ID].nunique())
    return out, report
