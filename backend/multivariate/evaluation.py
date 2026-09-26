"""
Layer 3 validation runner.

Two purposes, reported separately:
  A. NORMAL data  — held-out real observations with nothing injected. Reports
     how often each decision tier fires (false-positive behaviour) and the
     p-value / layer-score distributions. These datasets carry no anomaly
     labels, so this is an alarm RATE on presumed-normal data, never "accuracy".
  B. INJECTED data — the same held-out rows with controlled multivariate
     anomalies (multivariate/injection.py). Labels are known, so TP/FP/FN/TN,
     precision, recall, F1 (row-level) and event-level recall are reported,
     overall and per anomaly type.

Splits are chronological, within each station:
  seasonal_years (hourly/3-hourly multi-year data): for every station and
      calendar month, models are trained on the TRAINING years' rows within
      +-season_window_days of the 15th (split into fit / conformal
      calibration by training.split_fit_calibration — the same function the
      live path uses), then applied to that month in the VALIDATION and TEST
      years. Test years are never used for any choice.
  fraction (short series, e.g. the 7-day synthetic dataset): the first
      train_frac of each station's rows are training (same fit/calibration
      split), the rest are test.

Scoring uses exactly the classes the live path uses (training.fit_pair ->
models.DetectorPair -> decision thresholds), one row at a time semantics.

Per-type precision is computed per SCENARIO: all clean held-out rows plus
only that type's injected events. Each event's following row is re-scored
with the injected history (its deltas change) and counts as a negative.
"""
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from multivariate import schema as S
from multivariate.decision import decide
from multivariate.features import DYNAMIC, STATIC, add_features, input_feature_names
from multivariate.injection import (ALL_TYPES, CONTROL_TYPES, MULTIVARIATE_TYPES, SeasonStats,
                                    plan_and_inject)
from multivariate.training import calibration_day_mask, fit_pair, month_center_doy, seasonal_mask

TIERS = ["anomaly", "any_flag", "ecod_alone", "iforest_alone", "univariate_baseline"]


@dataclass
class SplitSpec:
    mode: str                                   # "seasonal_years" | "fraction"
    train_years: Tuple[int, ...] = ()
    val_years: Tuple[int, ...] = ()
    test_years: Tuple[int, ...] = ()
    train_frac: float = 0.75
    # the seasonal window itself is cfg.season_window_days — the same value the live reference uses


DATASET_SPECS = {
    "open_meteo": SplitSpec("seasonal_years", train_years=tuple(range(2015, 2022)),
                            val_years=(2022,), test_years=(2023, 2024)),
    "isd": SplitSpec("seasonal_years", train_years=(2019, 2020, 2021, 2022),
                     val_years=(), test_years=(2023, 2024)),
    "synthetic_temporal": SplitSpec("fraction"),
    "csv": SplitSpec("fraction"),
}


# ─────────────────────────────────────────────────────────────────────
# Per-station work (runs in a worker process)
# ─────────────────────────────────────────────────────────────────────

def _solar_hour_from_features(f: pd.DataFrame) -> np.ndarray:
    return np.mod(np.arctan2(f["solar_hour_sin"], f["solar_hour_cos"]) * 24.0 / (2 * np.pi), 24.0)


class _Baseline:
    """Univariate reference: flag if ANY single channel leaves its own
    [0.5, 99.5] percentile band for this station, season and 3-hour solar-time
    bucket (fit data only). What a per-channel diurnal-climatology check sees."""

    def __init__(self, fit: pd.DataFrame):
        b = (_solar_hour_from_features(fit) // 3).astype(int)
        self.bands = {}
        for k in range(8):
            sub = fit[b == k] if (b == k).sum() >= 30 else fit
            self.bands[k] = {c: (np.quantile(sub[c], 0.005), np.quantile(sub[c], 0.995)) for c in S.CHANNELS}

    def flags(self, rows: pd.DataFrame) -> np.ndarray:
        b = (_solar_hour_from_features(rows) // 3).astype(int).to_numpy()
        out = np.zeros(len(rows), dtype=bool)
        for c in S.CHANNELS:
            lo = np.array([self.bands[k][c][0] for k in b])
            hi = np.array([self.bands[k][c][1] for k in b])
            v = rows[c].to_numpy(float)
            out |= (v < lo) | (v > hi)
        return out


def _score_rows(pairs: Dict[str, object], rows: pd.DataFrame, cfg) -> Dict[str, np.ndarray]:
    n = len(rows)
    res = {k: np.full(n, np.nan) for k in ("ecod_p", "if_p", "ecod_score", "if_score")}
    res["feature_set"] = np.array([""] * n, dtype=object)
    dyn = np.isfinite(rows[input_feature_names(DYNAMIC)].to_numpy(float)).all(axis=1)
    for kind, mask in ((DYNAMIC, dyn), (STATIC, ~dyn)):
        pair = pairs.get(kind)
        if pair is None or not mask.any():
            continue
        x = rows.loc[mask, pair.input_names].to_numpy(float)
        sc = pair.score(x)
        for src, dst in (("ecod_p", "ecod_p"), ("isolation_forest_p", "if_p"),
                         ("ecod_score", "ecod_score"), ("isolation_forest_score", "if_score")):
            if src in sc:
                res[dst][mask] = sc[src]
        res["feature_set"][mask] = kind
    return res


def _explain(pair, row: pd.Series) -> Dict:
    x = row[pair.input_names].to_numpy(float)
    return {"top_features": pair.feature_tails(x)[:3], "relationships": pair.relationships(x)}


def _station_job(station_id: str, sframe: pd.DataFrame, spec: SplitSpec, cfg, inj: Dict, seed: int,
                 splits: Sequence[str]) -> Tuple[pd.DataFrame, Dict]:
    sframe = sframe.sort_values(S.TIMESTAMP).reset_index(drop=True)
    years = sframe[S.TIMESTAMP].dt.year.to_numpy()
    n = len(sframe)
    split = np.array(["unused"] * n, dtype=object)
    if spec.mode == "seasonal_years":
        train = np.isin(years, spec.train_years)
        split[np.isin(years, spec.val_years)] = "validation"
        split[np.isin(years, spec.test_years)] = "test"
    else:
        train = np.arange(n) < int(n * spec.train_frac)
        split[~train] = "test"
    cal_day = calibration_day_mask(sframe[S.TIMESTAMP], cfg.calibration_fraction)
    split[train & ~cal_day] = "fit"
    split[train & cal_day] = "calibration"
    eval_mask = np.isin(split, list(splits))

    clean = add_features(sframe, cfg.max_delta_gap_hours)
    months = clean[S.TIMESTAMP].dt.month.to_numpy()

    # Tasks: (task key, fit mask, cal mask, eval-row mask)
    if spec.mode == "seasonal_years":
        tasks = []
        for m in range(1, 13):
            win = seasonal_mask(clean[S.TIMESTAMP], month_center_doy(m), cfg.season_window_days)
            tasks.append((m, win & (split == "fit"), win & (split == "calibration"), eval_mask & (months == m)))
    else:
        tasks = [(0, split == "fit", split == "calibration", eval_mask)]

    stats_by_task = {k: SeasonStats.from_fit(sframe[fm]) for k, fm, _, _ in tasks if fm.sum() >= 50}
    task_of_row = months if spec.mode == "seasonal_years" else np.zeros(n, dtype=int)

    n_eval_years = max(1, len(set(years[eval_mask]))) if spec.mode == "seasonal_years" else 1
    injected, events, inj_report = plan_and_inject(
        sframe, eval_mask, lambda i: stats_by_task[task_of_row[i]],
        events_per_type=inj["events_per_type_per_year"] * n_eval_years, duration=inj["duration"],
        max_gap_hours=cfg.max_delta_gap_hours, spacing=inj["spacing"], seed=seed, types=inj["types"])
    inj_feats = add_features(injected.drop(columns=[c for c in injected.columns if c.startswith("orig_")]),
                             cfg.max_delta_gap_hours)
    post_rows = np.zeros(n, dtype=bool)
    post_rows[[e["post_row"] for e in events if e["post_row"] < n]] = True
    post_type = np.array(["none"] * n, dtype=object)
    for e in events:
        if e["post_row"] < n:
            post_type[e["post_row"]] = e["type"]
    rescore = injected["is_injected"].to_numpy() | post_rows

    out_cols = {k: np.full(n, np.nan) for k in (
        "clean_ecod_p", "clean_if_p", "clean_ecod_score", "clean_if_score",
        "inj_ecod_p", "inj_if_p", "inj_ecod_score", "inj_if_score")}
    out_bool = {k: np.zeros(n, dtype=bool) for k in ("clean_baseline", "inj_baseline")}
    feature_set = np.array([""] * n, dtype=object)
    calib_n = np.zeros(n)
    examples = {}

    for key, fit_m, cal_m, ev_m in tasks:
        if not ev_m.any() or fit_m.sum() < 50:
            continue
        fit_rows, cal_rows = clean[fit_m], clean[cal_m]
        pairs = {kind: fit_pair(fit_rows, cal_rows, kind, cfg) for kind in (DYNAMIC, STATIC)}
        base = _Baseline(fit_rows)

        rows = clean[ev_m]
        sc = _score_rows(pairs, rows, cfg)
        idx = np.flatnonzero(ev_m)
        out_cols["clean_ecod_p"][idx], out_cols["clean_if_p"][idx] = sc["ecod_p"], sc["if_p"]
        out_cols["clean_ecod_score"][idx], out_cols["clean_if_score"][idx] = sc["ecod_score"], sc["if_score"]
        feature_set[idx] = sc["feature_set"]
        out_bool["clean_baseline"][idx] = base.flags(rows)
        calib_n[idx] = (pairs.get(DYNAMIC) or pairs.get(STATIC)).n_cal if (pairs.get(DYNAMIC) or pairs.get(STATIC)) else 0

        rm = ev_m & rescore
        if rm.any():
            irows = inj_feats[rm]
            isc = _score_rows(pairs, irows, cfg)
            ii = np.flatnonzero(rm)
            out_cols["inj_ecod_p"][ii], out_cols["inj_if_p"][ii] = isc["ecod_p"], isc["if_p"]
            out_cols["inj_ecod_score"][ii], out_cols["inj_if_score"][ii] = isc["ecod_score"], isc["if_score"]
            out_bool["inj_baseline"][ii] = base.flags(irows)
            for e in events:
                r0 = e["rows"][0]
                if ev_m[r0] and e["event_id"] not in examples:
                    kind = DYNAMIC if np.isfinite(inj_feats.loc[r0, input_feature_names(DYNAMIC)].to_numpy(float)).all() else STATIC
                    pair = pairs.get(kind)
                    if pair is not None:
                        examples[e["event_id"]] = {
                            "clean": _explain(pair, clean.loc[r0]), "injected": _explain(pair, inj_feats.loc[r0])}

    res = pd.DataFrame({
        S.STATION_ID: station_id, S.TIMESTAMP: sframe[S.TIMESTAMP], "split": split,
        "is_injected": injected["is_injected"].to_numpy(), "anomaly_type": injected["anomaly_type"].to_numpy(),
        "event_id": injected["event_id"].to_numpy(), "is_post_event_row": post_rows, "post_event_type": post_type,
        "feature_set": feature_set, "calibration_n": calib_n,
        **{f"orig_{c}": sframe[c].to_numpy() for c in S.CHANNELS},
        **{f"inj_{c}": injected[c].to_numpy() for c in S.CHANNELS},
        "orig_dew_point_c": clean["dew_point_c"].to_numpy(), "inj_dew_point_c": inj_feats["dew_point_c"].to_numpy(),
        **out_cols, **out_bool,
    })
    res = res[eval_mask].reset_index(drop=True)
    ev_info = []
    for e in events:
        r0 = e["rows"][0]
        ev_info.append({"station_id": station_id, "event_id": e["event_id"], "type": e["type"],
                        "start": str(sframe.loc[r0, S.TIMESTAMP]), "split": split[r0],
                        "explanation": examples.get(e["event_id"])})
    return res, {"station_id": station_id, "injection": inj_report, "events": ev_info}


# ─────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────

def _tier_flags(ecod_p, if_p, baseline, alpha) -> Dict[str, np.ndarray]:
    e = np.nan_to_num(ecod_p, nan=1.0) <= alpha
    i = np.nan_to_num(if_p, nan=1.0) <= alpha
    return {"anomaly": e & i, "any_flag": e | i, "ecod_alone": e, "iforest_alone": i, "univariate_baseline": baseline}


def _prf(tp, fp, fn, tn) -> Dict:
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if (tp + fp and tp + fn and prec + rec) else float("nan")
    return {"TP": int(tp), "FP": int(fp), "FN": int(fn), "TN": int(tn),
            "precision": _r(prec), "recall": _r(rec), "f1": _r(f1),
            "false_positive_rate": _r(fp / (fp + tn) if fp + tn else float("nan")),
            "prevalence": _r((tp + fn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) else float("nan"))}


def _r(v, nd=4):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)


def scenario_metrics(res: pd.DataFrame, types: Sequence[str], alpha: float) -> Dict[str, Dict]:
    """Rows of `types` events use injected scores (positives); their post-event
    rows use injected scores (negatives); everything else uses clean scores."""
    use_inj = (res["is_injected"] & res["anomaly_type"].isin(types)) | \
              (res["is_post_event_row"] & res["post_event_type"].isin(types))
    ecod_p = np.where(use_inj, res["inj_ecod_p"], res["clean_ecod_p"])
    if_p = np.where(use_inj, res["inj_if_p"], res["clean_if_p"])
    base = np.where(use_inj, res["inj_baseline"], res["clean_baseline"])
    y = (res["is_injected"] & res["anomaly_type"].isin(types)).to_numpy()
    scored = np.isfinite(ecod_p) | np.isfinite(if_p)
    out = {}
    for tier, flag in _tier_flags(ecod_p, if_p, base, alpha).items():
        f, yy = flag[scored], y[scored]
        m = _prf(np.sum(f & yy), np.sum(f & ~yy), np.sum(~f & yy), np.sum(~f & ~yy))
        ev = res.loc[scored & y].assign(flag=f[yy])
        if len(ev):
            m["event_recall"] = _r(ev.groupby([S.STATION_ID, "event_id"])["flag"].any().mean())
            m["events"] = int(ev.groupby([S.STATION_ID, "event_id"]).ngroups)
        out[tier] = m
    return out


def normal_metrics(res: pd.DataFrame, alpha: float) -> Dict:
    ok = np.isfinite(res["clean_ecod_p"]) | np.isfinite(res["clean_if_p"])
    r = res[ok]
    flags = _tier_flags(r["clean_ecod_p"].to_numpy(), r["clean_if_p"].to_numpy(), r["clean_baseline"].to_numpy(), alpha)
    out = {"observations": int(len(r)), "stations": int(r[S.STATION_ID].nunique()),
           "flag_rate_by_tier": {k: _r(v.mean(), 5) for k, v in flags.items()},
           "flag_count_by_tier": {k: int(v.sum()) for k, v in flags.items()},
           "ecod_p_quantiles": {q: _r(np.nanquantile(r["clean_ecod_p"], q), 5) for q in (0.001, 0.01, 0.05, 0.5)},
           "if_p_quantiles": {q: _r(np.nanquantile(r["clean_if_p"], q), 5) for q in (0.001, 0.01, 0.05, 0.5)}}
    samp = r.sample(min(len(r), 20000), random_state=0)
    ls = np.array([decide(_nan_none(a), _nan_none(b), alpha).layer_score for a, b in zip(samp["clean_ecod_p"], samp["clean_if_p"])])
    out["layer_score_quantiles_sampled"] = {q: _r(np.quantile(ls, q)) for q in (0.5, 0.9, 0.99, 0.999)}
    per_st = r.assign(anomaly=flags["anomaly"], any_flag=flags["any_flag"]).groupby(S.STATION_ID)[["anomaly", "any_flag"]].mean()
    out["per_station_anomaly_rate"] = {"min": _r(per_st["anomaly"].min(), 5), "median": _r(per_st["anomaly"].median(), 5),
                                       "max": _r(per_st["anomaly"].max(), 5)}
    return out


def _nan_none(v):
    return None if v is None or not np.isfinite(v) else float(v)


def evaluate(res: pd.DataFrame, alpha: float, split: str) -> Dict:
    r = res[res["split"] == split]
    rep = {"split": split, "alpha": alpha, "normal_data": normal_metrics(r, alpha),
           "injected": {"all_multivariate_types": scenario_metrics(r, MULTIVARIATE_TYPES, alpha)}}
    for t in ALL_TYPES:
        if (r["anomaly_type"] == t).any():
            rep["injected"][t] = scenario_metrics(r, [t], alpha)
    return rep


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

def run(frame: pd.DataFrame, spec: SplitSpec, cfg, splits: Sequence[str] = ("test",),
        events_per_type_per_year: int = 12, duration: int = 6, spacing: int = 48,
        types: Sequence[str] = ALL_TYPES, seed: int = 7, n_jobs: int = -2) -> Tuple[pd.DataFrame, List[Dict]]:
    inj = {"events_per_type_per_year": events_per_type_per_year, "duration": duration,
           "spacing": spacing, "types": list(types)}
    stations = sorted(frame[S.STATION_ID].unique())
    jobs = Parallel(n_jobs=n_jobs)(
        delayed(_station_job)(s, frame[frame[S.STATION_ID] == s], spec, cfg, inj, seed + i, splits)
        for i, s in enumerate(stations))
    return pd.concat([j[0] for j in jobs], ignore_index=True), [j[1] for j in jobs]


def write_report(out_dir: Path, name: str, payload: Dict, res: pd.DataFrame, station_info: List[Dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (out_dir / f"{name}_events.json").write_text(json.dumps(station_info, indent=2, default=_json_default), encoding="utf-8")
    keep = res["is_injected"] | res["is_post_event_row"]
    sample = pd.concat([res[keep], res[~keep].sample(min(5000, int((~keep).sum())), random_state=0)])
    sample.sort_values([S.STATION_ID, S.TIMESTAMP]).to_csv(out_dir / f"{name}_scored_rows_sample.csv", index=False)


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)
