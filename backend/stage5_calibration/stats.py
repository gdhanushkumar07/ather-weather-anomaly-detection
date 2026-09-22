"""Shared percentile / threshold-exceedance summary helper."""
from typing import Any, Dict

import numpy as np
import pandas as pd


def summarize(series: pd.Series, thresholds=(0.25, 0.50, 0.75, 1.0)) -> Dict[str, Any]:
    arr = series.dropna().to_numpy(dtype=float)
    if len(arr) == 0:
        return {"n": 0}
    out = {
        "n": int(len(arr)),
        "min": float(np.min(arr)),
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
    }
    for t in thresholds:
        if t >= 1.0:
            key = "pct_eq_1_0"
            out[key] = float(100.0 * np.mean(arr >= 0.999999))
        else:
            key = f"pct_gt_{str(t).replace('.', '')}"
            out[key] = float(100.0 * np.mean(arr > t))
    return out
