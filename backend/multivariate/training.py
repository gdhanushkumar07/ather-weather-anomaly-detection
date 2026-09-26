"""
Training-set construction shared by the live reference library and the
offline evaluation, so both train models the same way.

Seasonal window: joint T/P/RH behaviour in India changes completely between
seasons (e.g. pre-monsoon hot/dry vs monsoon warm/saturated), so a model for
a given date is trained only on observations within +-window_days of that
calendar day (circular day-of-year distance, all eligible years).

Fit / calibration split: split_fit_calibration() (day-blocked interleave).
Everything a model is applied to — validation/test years offline, the live
observation online — is strictly newer than, and disjoint from, both parts.
"""
from typing import Optional

import numpy as np
import pandas as pd

from multivariate import schema as S
from multivariate.features import input_feature_names
from multivariate.models import DetectorPair


def seasonal_mask(timestamps: pd.Series, center_doy: int, window_days: int) -> np.ndarray:
    doy = pd.DatetimeIndex(timestamps).dayofyear.to_numpy()
    d = np.abs(doy - center_doy)
    return np.minimum(d, 366 - d) <= window_days


def month_center_doy(month: int) -> int:
    return int(pd.Timestamp(year=2001, month=month, day=15).dayofyear)


def feature_matrix(frame: pd.DataFrame, kind: str) -> np.ndarray:
    x = frame[input_feature_names(kind)].to_numpy(dtype=float)
    return x[np.isfinite(x).all(axis=1)]


def fit_pair(fit_frame: pd.DataFrame, cal_frame: pd.DataFrame, kind: str, cfg,
             min_rows: int = 20) -> Optional[DetectorPair]:
    x_fit = feature_matrix(fit_frame, kind)
    x_cal = feature_matrix(cal_frame, kind)
    if x_fit.shape[0] < min_rows or x_cal.shape[0] < 1:
        return None
    pair = DetectorPair(input_feature_names(kind), cfg)
    return pair if pair.fit(x_fit, x_cal) else None


def split_fit_calibration(frame: pd.DataFrame, cal_fraction: float):
    """
    Day-blocked interleaved fit/calibration split — the ONE split used by the
    live regional reference, a station's own models and offline validation.

    Every k-th UTC calendar day (k = round(1 / cal_fraction)) is calibration,
    the rest is fit. Why not "newest block = calibration": weather drifts
    (wet/dry spells, inter-annual differences); if the calibration block sits
    in a different regime than the fit block, every calibration score is
    inflated and genuine anomalies stop looking rare (observed: a +9 sd RH
    residual scored p=0.03 because the newest week was 6.5 %RH wetter than the
    fit weeks). Whole days are kept together so hour-to-hour autocorrelation
    does not leak across the split. Data being evaluated (validation/test
    years, or the live observation) is never in either part.
    """
    cal = calibration_day_mask(frame[S.TIMESTAMP], cal_fraction)
    return frame[~cal], frame[cal]


def calibration_day_mask(timestamps, cal_fraction: float) -> np.ndarray:
    """True for rows on calibration days. Depends only on the UTC calendar day,
    so it gives the same assignment on any subset of a station's rows."""
    k = max(2, int(round(1.0 / cal_fraction)))
    day = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)).normalize()
    ordinal = ((day - pd.Timestamp("2000-01-01", tz="UTC")).days).to_numpy()
    return (ordinal % k) == (k - 1)
