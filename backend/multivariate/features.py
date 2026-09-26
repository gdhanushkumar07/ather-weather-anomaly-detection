"""
Layer 3 feature engineering.

Feature vector (see FEATURE SETS below):

  Raw:       temperature_c, pressure_hpa, humidity_pct
  Derived:   dew_point_c — Magnus formula with the Alduchov & Eskridge (1996)
             coefficients (a=17.625, b=243.04 C), the standard WMO-recommended
             form; |error| < ~0.4 C over -40..50 C. Dew point is what makes the
             T-RH *relationship* visible to ECOD: ECOD scores each dimension's
             marginal tail, so T=32C and RH=88% can each look ordinary, but
             their joint implies a dew point (~29.6C) far in the station's tail.
  Temporal:  d_*_per_h — change since the station's previous observation,
             divided by the gap in hours so that hourly, 3-hourly and 10-min
             data (and irregular live polling) are comparable. Computed
             strictly within one station after sorting by time. Not computed
             (NaN -> static feature set) for the first observation or when the
             gap exceeds max_delta_gap_hours.
  Diurnal:   solar_hour_sin/cos — local SOLAR hour (UTC + longitude/15).
             Justified by the reference data: within a station-month,
             RH ~ T + hour explains a median R^2 of 0.71, and T/RH follow a
             strong daily cycle, so "32C at 03:00" and "32C at 15:00" are
             different joint states. Solar hour (not a timezone) keeps the
             feature consistent between the IST-stamped historical archive,
             the UTC live feed, and any station worldwide.

  Learned:   relationship residuals (rh_given_t_residual_z, p_given_t_residual_z)
             and diurnal deviations are added inside each DetectorPair
             (models.py), not here, because they are learned from that pair's
             fit rows. See models.RELATIONSHIPS and multivariate/README.md.

Deliberately NOT included: rolling standard deviations / volatility (that is
temporal behaviour — Layer 2's responsibility), and pressure-derived
relationships (the reference data shows no usable within-season P-T or P-RH
coupling: median |r| 0.26 and 0.12).

FEATURE SETS (input columns; models.model_feature_names() gives what the models see)
  static  = raw + dew point + solar hour          always available
  dynamic = static + the three deltas             when a recent previous obs exists
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from multivariate import schema as S

MAGNUS_A = 17.625
MAGNUS_B = 243.04

RAW_FEATURES = [S.TEMPERATURE, S.PRESSURE, S.HUMIDITY]
DEW_POINT = "dew_point_c"
DELTA_FEATURES = ["d_temperature_c_per_h", "d_pressure_hpa_per_h", "d_humidity_pct_per_h"]
DIURNAL_FEATURES = ["solar_hour_sin", "solar_hour_cos"]
GAP_HOURS = "gap_hours"

STATIC = "static"
DYNAMIC = "dynamic"


def dew_point_c(temperature_c, humidity_pct):
    """Vectorised Magnus dew point (Alduchov & Eskridge 1996). RH clipped to [0.1, 100]."""
    t = np.asarray(temperature_c, dtype=float)
    rh = np.clip(np.asarray(humidity_pct, dtype=float), 0.1, 100.0)
    gamma = np.log(rh / 100.0) + MAGNUS_A * t / (MAGNUS_B + t)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def relative_humidity_from_dew_point(temperature_c, dew_point):
    """Inverse of dew_point_c (same coefficients) — used by the ISD adapter and injector."""
    t = np.asarray(temperature_c, dtype=float)
    td = np.asarray(dew_point, dtype=float)
    return 100.0 * np.exp(MAGNUS_A * td / (MAGNUS_B + td) - MAGNUS_A * t / (MAGNUS_B + t))


def solar_hour(ts_utc, longitude) -> np.ndarray:
    ts = pd.DatetimeIndex(pd.to_datetime(ts_utc, utc=True)) if not isinstance(ts_utc, datetime) \
        else pd.DatetimeIndex([pd.Timestamp(ts_utc)])
    utc_hours = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    return np.mod(np.asarray(utc_hours, dtype=float) + np.asarray(longitude, dtype=float) / 15.0, 24.0)


def input_feature_names(kind: str) -> List[str]:
    """Columns handed to a DetectorPair. Which of them the models actually see
    (and the derived relationship residual) is decided by the pair — see
    models.model_feature_names()."""
    names = RAW_FEATURES + [DEW_POINT]
    if kind == DYNAMIC:
        names = names + DELTA_FEATURES
    return names + DIURNAL_FEATURES


def add_features(df: pd.DataFrame, max_delta_gap_hours: float) -> pd.DataFrame:
    """
    Batch feature engineering on a standard-schema frame. Rows are sorted per
    station by timestamp first; deltas never cross a station boundary.
    Missing longitude -> 0 (solar hour == UTC hour), recorded in the frame.
    """
    out = df.sort_values([S.STATION_ID, S.TIMESTAMP]).reset_index(drop=True)
    out[DEW_POINT] = dew_point_c(out[S.TEMPERATURE], out[S.HUMIDITY])

    grp = out.groupby(S.STATION_ID, sort=False)
    gap_h = grp[S.TIMESTAMP].diff().dt.total_seconds() / 3600.0
    valid_gap = (gap_h > 0) & (gap_h <= max_delta_gap_hours)
    out[GAP_HOURS] = gap_h
    for ch, name in zip(RAW_FEATURES, DELTA_FEATURES):
        rate = grp[ch].diff() / gap_h
        out[name] = rate.where(valid_gap)

    lon = out[S.LONGITUDE] if S.LONGITUDE in out.columns else pd.Series(0.0, index=out.index)
    hours = solar_hour(out[S.TIMESTAMP], lon.fillna(0.0).to_numpy())
    out[DIURNAL_FEATURES[0]] = np.sin(2 * np.pi * hours / 24.0)
    out[DIURNAL_FEATURES[1]] = np.cos(2 * np.pi * hours / 24.0)
    return out


@dataclass
class Observation:
    """One jointly-valid observation as seen by the online path."""
    time_utc: datetime
    temperature_c: float
    pressure_hpa: float
    humidity_pct: float
    longitude: float = 0.0


def observation_features(cur: Observation, prev: Optional[Observation],
                         max_delta_gap_hours: float) -> Dict[str, float]:
    """
    Single-observation equivalent of add_features() — the live path. Kept
    numerically identical to the batch path (tests assert this) so offline
    validation measures exactly what production computes.
    """
    feats: Dict[str, float] = {
        S.TEMPERATURE: float(cur.temperature_c),
        S.PRESSURE: float(cur.pressure_hpa),
        S.HUMIDITY: float(cur.humidity_pct),
        DEW_POINT: float(dew_point_c(cur.temperature_c, cur.humidity_pct)),
    }
    gap_h = None
    if prev is not None:
        gap_h = (_as_utc(cur.time_utc) - _as_utc(prev.time_utc)).total_seconds() / 3600.0
    if gap_h is not None and 0 < gap_h <= max_delta_gap_hours:
        feats[DELTA_FEATURES[0]] = (cur.temperature_c - prev.temperature_c) / gap_h
        feats[DELTA_FEATURES[1]] = (cur.pressure_hpa - prev.pressure_hpa) / gap_h
        feats[DELTA_FEATURES[2]] = (cur.humidity_pct - prev.humidity_pct) / gap_h
    else:
        for name in DELTA_FEATURES:
            feats[name] = float("nan")
    feats[GAP_HOURS] = float("nan") if gap_h is None else float(gap_h)
    h = float(solar_hour(_as_utc(cur.time_utc), cur.longitude)[0])
    feats[DIURNAL_FEATURES[0]] = float(np.sin(2 * np.pi * h / 24.0))
    feats[DIURNAL_FEATURES[1]] = float(np.cos(2 * np.pi * h / 24.0))
    return feats


def has_deltas(feats: Dict[str, float]) -> bool:
    return all(np.isfinite(feats.get(n, np.nan)) for n in DELTA_FEATURES)


def _as_utc(ts: datetime) -> datetime:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
