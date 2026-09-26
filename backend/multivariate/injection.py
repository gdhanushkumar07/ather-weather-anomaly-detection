"""
Controlled MULTIVARIATE anomaly injection for Layer 3 evaluation.

Unlike temporal_anomalies/ (steps, drift, frozen, noise — Layer 2's job),
every type here keeps each channel INDIVIDUALLY plausible for the station and
season, and breaks a JOINT relationship instead. Plausibility is enforced,
not assumed: each injected value must lie inside the station's own
[0.5, 99.5] percentile band for that channel in the same seasonal window of
the FIT data (never test data), and inside ATHER's hard physical limits.
Events that cannot satisfy this are skipped and counted.

Types (all events last `duration` consecutive observations):
  t_rh_decoupling          T unchanged; RH replaced by the typical RH of the
                           station's OPPOSITE thermal regime (warm hour ->
                           RH typical of the coolest quartile, and vice
                           versa). Tests the strong T-RH anticorrelation
                           (median within-season r = -0.82 in the reference data).
  rh_offset                T unchanged; RH shifted by +-20 %RH (clipped into the
                           plausible band; skipped if < 10 %RH remains).
  joint_t_rh_extreme       T raised to >= the season's 90th percentile AND RH
                           raised to >= its 90th percentile at the same time —
                           each common alone, rare together.
  dew_point_inconsistency  T unchanged; RH set so the implied dew point is
                           1 C above the station-season 99.9th percentile,
                           with RH itself still inside the plausible band.
  pressure_offset_control  CONTROL, not a multivariate test: P moved to the
                           opposite 2.5th/97.5th percentile. The reference
                           data shows no usable within-season P-T / P-RH
                           relationship, so Layer 3 is NOT expected to catch
                           this better than a univariate check; it is reported
                           separately and excluded from multivariate totals.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import CONFIG
from multivariate import schema as S
from multivariate.features import dew_point_c, relative_humidity_from_dew_point

MULTIVARIATE_TYPES = ["t_rh_decoupling", "rh_offset", "joint_t_rh_extreme", "dew_point_inconsistency"]
CONTROL_TYPES = ["pressure_offset_control"]
ALL_TYPES = MULTIVARIATE_TYPES + CONTROL_TYPES


@dataclass
class SeasonStats:
    q: Dict[str, Dict[float, float]]
    rh_cool_regime: float
    rh_warm_regime: float

    @classmethod
    def from_fit(cls, fit: pd.DataFrame) -> "SeasonStats":
        qs = [0.005, 0.01, 0.025, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999]
        td = dew_point_c(fit[S.TEMPERATURE], fit[S.HUMIDITY])
        cols = {S.TEMPERATURE: fit[S.TEMPERATURE], S.PRESSURE: fit[S.PRESSURE],
                S.HUMIDITY: fit[S.HUMIDITY], "dew_point_c": pd.Series(td)}
        q = {k: {p: float(np.quantile(v, p)) for p in qs} for k, v in cols.items()}
        t = fit[S.TEMPERATURE]
        return cls(q=q,
                   rh_cool_regime=float(fit.loc[t <= q[S.TEMPERATURE][0.25], S.HUMIDITY].median()),
                   rh_warm_regime=float(fit.loc[t >= q[S.TEMPERATURE][0.75], S.HUMIDITY].median()))

    def plausible(self, ch: str, v: np.ndarray) -> bool:
        lo, hi = self.q[ch][0.005], self.q[ch][0.995]
        return bool(np.all((v >= lo) & (v <= hi)))


def _inject_values(kind: str, t: np.ndarray, p: np.ndarray, rh: np.ndarray, st: SeasonStats,
                   rng: np.random.Generator) -> Optional[Dict[str, np.ndarray]]:
    t2, p2, rh2 = t.copy(), p.copy(), rh.copy()
    q = st.q
    if kind == "t_rh_decoupling":
        target = st.rh_cool_regime if t[0] >= q[S.TEMPERATURE][0.5] else st.rh_warm_regime
        if abs(target - rh[0]) < 15:
            return None
        rh2[:] = round(target)
    elif kind == "rh_offset":
        lo, hi = q[S.HUMIDITY][0.01], q[S.HUMIDITY][0.99]
        for sign in rng.permutation([1.0, -1.0]):
            cand = np.clip(rh + sign * 20.0, lo, hi)
            if np.min(np.abs(cand - rh)) >= 10:
                rh2 = np.round(cand)
                break
        else:
            return None
    elif kind == "joint_t_rh_extreme":
        if t[0] >= q[S.TEMPERATURE][0.9] and rh[0] >= q[S.HUMIDITY][0.9]:
            return None
        t2 = np.round(np.maximum(t, q[S.TEMPERATURE][0.9]), 1)
        rh2 = np.round(np.maximum(rh, q[S.HUMIDITY][0.9]))
    elif kind == "dew_point_inconsistency":
        td_target = q["dew_point_c"][0.999] + 1.0
        rh2 = np.round(relative_humidity_from_dew_point(t, td_target))
        if np.any(rh2 > q[S.HUMIDITY][0.99]) or np.any(rh2 < rh + 5):
            return None
    elif kind == "pressure_offset_control":
        target = q[S.PRESSURE][0.975] if p[0] < q[S.PRESSURE][0.5] else q[S.PRESSURE][0.025]
        p2[:] = round(target, 1)
    else:
        raise ValueError(kind)

    phys = CONFIG.physics
    if not (st.plausible(S.TEMPERATURE, t2) and st.plausible(S.PRESSURE, p2) and st.plausible(S.HUMIDITY, rh2)):
        return None
    if not (np.all((t2 >= phys.temp_min_c) & (t2 <= phys.temp_max_c)) and np.all((rh2 >= 0) & (rh2 <= 100))):
        return None
    return {S.TEMPERATURE: t2, S.PRESSURE: p2, S.HUMIDITY: rh2}


def plan_and_inject(station_frame: pd.DataFrame, eval_mask: np.ndarray, stats_for_row, events_per_type: int,
                    duration: int, max_gap_hours: float, spacing: int, seed: int,
                    types: List[str] = ALL_TYPES):
    """
    station_frame: one station, standard schema, sorted by time.
    eval_mask: rows eligible for injection (validation/test rows only).
    stats_for_row(i) -> SeasonStats for row i (built from FIT data only).
    Returns (injected_frame, events list, skipped counts). Unmodified rows keep
    their original values; injected rows get is_injected / anomaly_type / event_id.
    """
    rng = np.random.default_rng(seed)
    df = station_frame.reset_index(drop=True).copy()
    n = len(df)
    ts = df[S.TIMESTAMP]
    gap = ts.diff().dt.total_seconds().to_numpy() / 3600.0
    month = ts.dt.month.to_numpy()
    ok_start = np.zeros(n, dtype=bool)
    for i in range(1, n - duration - 1):
        w = slice(i, i + duration + 1)   # event rows + the following row, all contiguous, one month
        if eval_mask[w].all() and np.all(gap[i:i + duration + 1] <= max_gap_hours) and len(set(month[i:i + duration])) == 1:
            ok_start[i] = True
    candidates = rng.permutation(np.flatnonzero(ok_start))

    df["is_injected"] = False
    df["anomaly_type"] = "none"
    df["event_id"] = -1
    for c in S.CHANNELS:
        df[f"orig_{c}"] = df[c]

    blocked = np.zeros(n, dtype=bool)
    counts = {k: 0 for k in types}
    skipped = {k: 0 for k in types}
    events = []
    order = [k for _ in range(events_per_type) for k in types]
    rng.shuffle(order)
    ci = 0
    for kind in order:
        placed = False
        tries = 0
        while ci < len(candidates) and tries < 200:
            i = int(candidates[ci]); ci += 1; tries += 1
            lo, hi = max(0, i - spacing), min(n, i + duration + spacing)
            if blocked[lo:hi].any():
                continue
            rows = np.arange(i, i + duration)
            vals = _inject_values(kind, df.loc[rows, S.TEMPERATURE].to_numpy(float),
                                  df.loc[rows, S.PRESSURE].to_numpy(float),
                                  df.loc[rows, S.HUMIDITY].to_numpy(float), stats_for_row(i), rng)
            if vals is None:
                skipped[kind] += 1
                continue
            eid = len(events)
            for c, v in vals.items():
                df.loc[rows, c] = v
            df.loc[rows, "is_injected"] = True
            df.loc[rows, "anomaly_type"] = kind
            df.loc[rows, "event_id"] = eid
            blocked[lo:hi] = True
            events.append({"event_id": eid, "type": kind, "start_row": i, "rows": rows.tolist(),
                           "post_row": i + duration})
            counts[kind] += 1
            placed = True
            break
        if not placed:
            skipped[kind] += 1
    return df, events, {"placed": counts, "skipped_attempts": skipped}
