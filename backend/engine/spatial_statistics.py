"""
S2 — Robust Spatial Statistics.

Small, independently-testable statistical helpers used by
engine/layer4_spatial.py to compute a robust (median/MAD-based) regional
baseline ALONGSIDE the existing IDW baseline, per channel.

WHY: the existing IDW consensus is a distance-weighted MEAN of neighbor
values. A mean (and a plain standard deviation) can be pulled substantially
by a single extreme or faulty neighboring station -- exactly the failure
mode S2 targets. The median and MAD (median absolute deviation) are
"breakdown-robust": up to (almost) half the sample can be arbitrarily
extreme before the median itself moves by more than the sample's own
spread. This module does NOT decide what to do with that extra evidence
(no scoring/threshold changes happen here) -- it only computes it. See
engine/layer4_spatial.py's module docstring for why the existing IDW-based
score is intentionally left unchanged in S2.

This module implements ONLY the statistics themselves. It has no knowledge
of AWSReading, DataQuality, elevation, or the Spatial layer's scoring —
callers pass in plain, already-filtered/already-adjusted numeric lists.
"""
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

# Standard robust-statistics constant: scales MAD so that, for a normally
# distributed sample, MAD * (1 / 0.6745) is a consistent estimator of the
# population standard deviation. Equivalently, robust_z = 0.6745 * (x -
# median) / MAD is on the same scale as an ordinary z-score. This is a
# well-known, textbook constant (not an invented threshold) -- see e.g.
# Rousseeuw & Croux (1993) for the underlying consistency argument.
MAD_CONSISTENCY_CONSTANT = 0.6745


def compute_median(values: Sequence[float]) -> float:
    """Regional median of a channel's (already DataQuality-filtered,
    already elevation-adjusted where applicable) neighbor estimates."""
    if not values:
        raise ValueError("compute_median requires at least one value")
    return float(np.median(np.asarray(values, dtype=float)))


def compute_mad(values: Sequence[float], center: Optional[float] = None) -> float:
    """
    Median Absolute Deviation: MAD = median(|x_i - median(x)|).

    `center` lets a caller reuse an already-computed median instead of
    recomputing it (both compute_median and compute_mad are pure/cheap, but
    the layer4 caller already needs the median as its own field, so this
    avoids computing it twice per channel per station).
    """
    if not values:
        raise ValueError("compute_mad requires at least one value")
    arr = np.asarray(values, dtype=float)
    c = center if center is not None else float(np.median(arr))
    return float(np.median(np.abs(arr - c)))


def compute_robust_z(
    value: float,
    median: float,
    mad: float,
    *,
    min_scale: float,
) -> Tuple[float, str]:
    """
    robust_z = 0.6745 * (value - median) / MAD -- the standard MAD-based
    robust z-score. Signed (not absolute value): positive means `value` is
    above the regional median, negative means below.

    SAFETY (no division by zero, no arbitrary new threshold): MAD is
    exactly zero whenever more than half the sample shares one value --
    not a rare edge case for weather data reported at coarse rounding (e.g.
    several neighbors all reading exactly the same rounded humidity%).
    Rather than inventing a new epsilon, this reuses the SAME per-channel
    `min_std` floor the existing IDW z-score already uses (see
    layer4_spatial.py's `std = max(min_std, np.std(estimates))`), converted
    into MAD units via the same MAD_CONSISTENCY_CONSTANT:

        effective_mad = max(MAD, min_scale * MAD_CONSISTENCY_CONSTANT)
        robust_z = MAD_CONSISTENCY_CONSTANT * (value - median) / effective_mad

    When MAD is already >= min_scale * MAD_CONSISTENCY_CONSTANT, the floor
    never engages and this is numerically IDENTICAL to the textbook
    formula. When MAD is zero or below that, effective_mad collapses to
    exactly `min_scale * MAD_CONSISTENCY_CONSTANT`, which algebraically
    reduces robust_z to `(value - median) / min_scale` -- the same
    "deviation / channel floor" shape the existing IDW z-score already
    falls back to, just computed from the median instead of the IDW mean.
    Returns (robust_z, method) where method is "MAD" or
    "MIN_SCALE_FALLBACK" so the fallback is visible in output/debugging,
    never silent.
    """
    floor = min_scale * MAD_CONSISTENCY_CONSTANT
    if mad >= floor:
        effective_mad = mad
        method = "MAD"
    else:
        effective_mad = floor
        method = "MIN_SCALE_FALLBACK"
    robust_z = MAD_CONSISTENCY_CONSTANT * (value - median) / effective_mad
    return robust_z, method


def compute_idw_statistics(
    estimates: Sequence[float],
    weights: Sequence[float],
    target_value: float,
    min_std: float,
) -> Dict[str, float]:
    """
    The existing IDW consensus + dispersion + z-score, factored out of
    layer4_spatial.py's _channel_consensus() as a small, independently
    testable helper. Mathematically IDENTICAL to the original inline
    computation (a pure refactor, not a behavior change):
        idw_mean = distance-weighted mean of `estimates`
        idw_std  = max(min_std, population std of `estimates`)  [same floor as before]
        idw_z    = |target_value - idw_mean| / idw_std
    """
    if not estimates or not weights:
        raise ValueError("compute_idw_statistics requires at least one estimate/weight")
    w_arr = np.asarray(weights, dtype=float)
    w_norm = w_arr / np.sum(w_arr)
    idw_mean = float(np.sum(w_norm * np.asarray(estimates, dtype=float)))
    deviation = abs(target_value - idw_mean)
    idw_std = max(min_std, float(np.std(estimates)))
    idw_z = deviation / idw_std
    return {
        "idw_mean": idw_mean,
        "idw_std": idw_std,
        "idw_z": idw_z,
        "deviation": deviation,
    }


def compute_robust_spatial_evidence(
    estimates: Sequence[float],
    weights: Sequence[float],
    target_value: float,
    min_std: float,
) -> Dict[str, object]:
    """
    Convenience wrapper bundling both baselines (IDW and median/MAD) for
    one channel in a single call, so engine/layer4_spatial.py does not need
    to orchestrate 5 separate function calls per channel. Returns a flat
    dict with both families of statistics plus the fallback method used
    for robust_z, ready to be merged into layer4's existing per-channel
    `ch_result` dict.
    """
    idw = compute_idw_statistics(estimates, weights, target_value, min_std)
    median = compute_median(estimates)
    mad = compute_mad(estimates, center=median)
    robust_z, robust_z_method = compute_robust_z(target_value, median, mad, min_scale=min_std)
    return {
        "idw_mean": idw["idw_mean"],
        "idw_std": idw["idw_std"],
        "idw_z": idw["idw_z"],
        "deviation": idw["deviation"],
        "regional_median": median,
        "regional_mad": mad,
        "robust_z": robust_z,
        "robust_z_method": robust_z_method,
    }
