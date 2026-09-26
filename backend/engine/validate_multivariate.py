"""
Layer 3 (Multivariate Intelligence) validation CLI.

Runs the station-specific ECOD + Isolation Forest pipeline (backend/multivariate)
on a real or synthetic dataset with a chronological split and reports:
  A. normal held-out data: alarm rate per decision tier (NOT accuracy — these
     datasets have no anomaly labels)
  B. controlled multivariate injected anomalies: TP/FP/FN/TN, precision,
     recall, F1, event recall — overall and per anomaly type

Run from backend/:
  python engine/validate_multivariate.py --dataset open_meteo --splits validation          # model selection
  python engine/validate_multivariate.py --dataset open_meteo --splits test                # final numbers
  python engine/validate_multivariate.py --dataset isd --splits test                       # real station obs
  python engine/validate_multivariate.py --dataset synthetic_temporal --splits test        # controlled synthetic
  python engine/validate_multivariate.py --dataset csv --csv obs.csv --station-col id \\
      --time-col time --temp-col t --pressure-col p --humidity-col rh --timezone UTC

Reports are written to backend/reports/multivariate/.
"""
import argparse
import copy
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from multivariate import datasets
from multivariate.evaluation import DATASET_SPECS, evaluate, run, write_report
from multivariate.injection import ALL_TYPES

# Injection geometry per dataset cadence: events of `duration` observations,
# at least `spacing` observations apart.
INJECTION_DEFAULTS = {
    "open_meteo": dict(duration=6, spacing=48, events_per_type_per_year=12),          # 6 h events, hourly data
    "isd": dict(duration=3, spacing=16, events_per_type_per_year=12),                 # 9 h events, 3-hourly data
    "synthetic_temporal": dict(duration=6, spacing=12, events_per_type_per_year=2),   # 1 h events, 10-min data, 7 days
    "csv": dict(duration=6, spacing=24, events_per_type_per_year=4),
}
ALPHA_SWEEP = [0.001, 0.0025, 0.005, 0.01, 0.02, 0.05]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate Layer 3 multivariate intelligence")
    ap.add_argument("--dataset", choices=list(DATASET_SPECS), default="open_meteo")
    ap.add_argument("--splits", default="test", help="comma list of: validation,test")
    ap.add_argument("--alpha", type=float, default=None, help=f"decision alpha (default config: {CONFIG.multivariate.alpha})")
    ap.add_argument("--no-diurnal", action="store_true", help="disable solar-hour model features (variant study)")
    ap.add_argument("--no-residual", action="store_true", help="disable both learned relationship residuals (variant study)")
    ap.add_argument("--no-pressure-residual", action="store_true", help="disable the P|T residual model column (variant study)")
    ap.add_argument("--season-window", type=int, default=None, help="seasonal window +-days (variant study)")
    ap.add_argument("--representation", choices=["raw", "diurnal_anomaly"], default=None, help="variant study")
    ap.add_argument("--stations", default=None, help="comma list of station ids to include")
    ap.add_argument("--tag", default=None, help="report name suffix")
    ap.add_argument("--n-jobs", type=int, default=-2)
    ap.add_argument("--csv"); ap.add_argument("--station-col", default="station_id"); ap.add_argument("--time-col", default="timestamp")
    ap.add_argument("--temp-col", default="temperature_c"); ap.add_argument("--pressure-col", default="pressure_hpa")
    ap.add_argument("--humidity-col", default="humidity_pct"); ap.add_argument("--timezone", default="UTC")
    ap.add_argument("--lat-col"); ap.add_argument("--lon-col")
    args = ap.parse_args(argv)

    cfg = copy.deepcopy(CONFIG.multivariate)
    if args.no_diurnal:
        cfg.use_diurnal_features = False
    if args.no_residual:
        cfg.use_rh_temperature_residual = cfg.use_pressure_temperature_residual = False
    if args.no_pressure_residual:
        cfg.use_pressure_temperature_residual = False
    if args.season_window is not None:
        cfg.season_window_days = args.season_window
    if args.representation is not None:
        cfg.feature_representation = args.representation
    alpha = args.alpha if args.alpha is not None else cfg.alpha
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]

    t0 = time.time()
    if args.dataset == "csv":
        frame, data_rep = datasets.load_csv(Path(args.csv), args.station_col, args.time_col, args.temp_col,
                                            args.pressure_col, args.humidity_col, args.timezone, args.lat_col, args.lon_col)
    else:
        frame, data_rep = datasets.LOADERS[args.dataset]()
    if args.stations:
        frame = frame[frame["station_id"].isin([s.strip() for s in args.stations.split(",")])]
    spec = DATASET_SPECS[args.dataset]
    inj = INJECTION_DEFAULTS[args.dataset]
    print(f"[data] {data_rep['dataset']}: {data_rep['rows_retained']} rows, {frame['station_id'].nunique()} stations "
          f"(removed: missing/non-finite {data_rep['dropped_missing_or_nonfinite_channel']}, "
          f"out-of-bounds {data_rep['dropped_outside_physical_bounds']}, duplicates {data_rep['dropped_duplicate_station_timestamp']})")

    res, station_info = run(frame, spec, cfg, splits=splits, types=ALL_TYPES, n_jobs=args.n_jobs, **inj)
    print(f"[run] scored {len(res)} held-out rows in {time.time() - t0:.0f}s")

    payload = {
        "dataset": {k: v for k, v in data_rep.items() if k != "stations_manifest"},
        "stations_manifest": data_rep.get("stations_manifest"),
        "split_spec": asdict(spec),
        "config": {k: v for k, v in asdict(cfg).items()},
        "injection": {**inj, "types": ALL_TYPES,
                      "placed_by_type": _sum_placed(station_info)},
        "results": {},
    }
    for split in splits:
        rep = evaluate(res, alpha, split)
        rep["alpha_sweep"] = {str(a): _sweep_row(evaluate(res, a, split)) for a in ALPHA_SWEEP}
        payload["results"][split] = rep
        _print_split(rep)

    name = f"{args.dataset}{'_' + args.tag if args.tag else ''}"
    out_dir = Path(BASE_DIR) / "reports" / "multivariate"
    write_report(out_dir, name, payload, res, station_info)
    print(f"\n[report] {out_dir / (name + '_summary.json')}")


def _sum_placed(info):
    tot = {}
    for s in info:
        for k, v in s["injection"]["placed"].items():
            tot[k] = tot.get(k, 0) + v
    return tot


def _sweep_row(rep):
    mv = rep["injected"]["all_multivariate_types"]
    nd = rep["normal_data"]["flag_rate_by_tier"]
    return {"normal_anomaly_rate": nd["anomaly"], "normal_any_flag_rate": nd["any_flag"],
            "anomaly_tier": {k: mv["anomaly"][k] for k in ("precision", "recall", "f1", "false_positive_rate")},
            "any_flag_tier": {k: mv["any_flag"][k] for k in ("precision", "recall", "f1", "false_positive_rate")}}


def _print_split(rep):
    nd = rep["normal_data"]
    print(f"\n=== {rep['split'].upper()}  (alpha={rep['alpha']}) ===")
    print(f"A. Normal held-out data: {nd['observations']} obs, {nd['stations']} stations — alarm RATE (no labels, not accuracy)")
    for k, v in nd["flag_rate_by_tier"].items():
        print(f"   {k:<20} {v * 100:6.3f}%  ({nd['flag_count_by_tier'][k]})")
    print("B. Injected multivariate anomalies (row-level; event recall in last column)")
    print(f"   {'type':<26}{'tier':<20}{'TP':>6}{'FP':>7}{'FN':>6}{'prec':>7}{'rec':>7}{'F1':>7}{'FPR':>8}{'evRec':>7}")
    for t, tiers in rep["injected"].items():
        for tier in ("anomaly", "any_flag", "univariate_baseline"):
            m = tiers[tier]
            print(f"   {t:<26}{tier:<20}{m['TP']:>6}{m['FP']:>7}{m['FN']:>6}{_f(m['precision']):>7}{_f(m['recall']):>7}"
                  f"{_f(m['f1']):>7}{_f(m['false_positive_rate'], 4):>8}{_f(m.get('event_recall')):>7}")
    print("   alpha sweep (all multivariate types):")
    for a, s in rep.get("alpha_sweep", {}).items():
        print(f"     alpha={a:<7} normal anomaly-rate={s['normal_anomaly_rate']:.4f} any-rate={s['normal_any_flag_rate']:.4f} | "
              f"ANOMALY P/R/F1={_f(s['anomaly_tier']['precision'])}/{_f(s['anomaly_tier']['recall'])}/{_f(s['anomaly_tier']['f1'])} | "
              f"ANY P/R/F1={_f(s['any_flag_tier']['precision'])}/{_f(s['any_flag_tier']['recall'])}/{_f(s['any_flag_tier']['f1'])}")


def _f(v, nd=3):
    return "  n/a" if v is None else f"{v:.{nd}f}"


if __name__ == "__main__":
    main()
