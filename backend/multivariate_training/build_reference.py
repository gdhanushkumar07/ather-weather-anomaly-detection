"""
Stage 1: build the pressure-normalized, city-conditioned reference.

Two chunked passes over the historical dataset (never loaded whole):

  pass 1  validity, per-(city, period, month) counts, and REFERENCE-period
          histograms of T / RH / surface pressure  ->  per-city medians  ->
          climatological elevation proxy
  pass 2  REFERENCE-period histogram of the sea-level-equivalent pressure, and a
          deterministic, stratified (city x month) sample per period

Baselines (median/MAD) are computed from the REFERENCE period ONLY, so nothing
from the calibration/test periods leaks into the reference statistics.

Only temperature_C, humidity_pct and pressure_hPa are used as values. city /
lat / lon / datetime are used solely for grouping, sampling, splitting and
provenance.

Usage (from backend/):
    python3 -m multivariate_training.build_reference --work-dir <scratch-dir>
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from engine import multivariate_features as mf  # noqa: E402

DEFAULT_DATASET = os.path.expanduser(
    "~/Desktop/sih win/ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv")
DEFAULT_OUT_DIR = os.path.join(BACKEND_DIR, "models", "multivariate_ecod_if")
COLS = ["datetime", "city", "lat", "lon", "temperature_C", "humidity_pct", "pressure_hPa"]

# Chronological split, chosen AFTER inspecting the actual range (1996-01-01 ..
# 2026-03-18): ~20 y reference, ~5 y calibration, ~5.2 y held-out test.
PERIODS = [
    ("reference",   "1996-01-01", "2016-01-01"),
    ("calibration", "2016-01-01", "2021-01-01"),
    ("test",        "2021-01-01", "2100-01-01"),
]
PERIOD_TARGETS = {"reference": 250_000, "calibration": 150_000, "test": 100_000}

# A city needs at least one year of hourly REFERENCE-period rows to receive a
# robust baseline. Cities below this (e.g. a one-row typo entry) are excluded and
# listed in the artifact; they are never silently given a baseline.
MIN_REFERENCE_ROWS = 8760

# Sanity bounds used only to drop obviously corrupted rows (counted + reported).
VALID_T = (-50.0, 60.0)
VALID_RH = (0.0, 100.0)
VALID_P = (300.0, 1100.0)

# Histogram grids (0.1 resolution == the dataset's own resolution).
GRIDS = {
    "T": (-50.0, 60.0, 0.1),
    "RH": (0.0, 100.0, 0.1),
    "PS": (300.0, 1100.0, 0.1),
    "PM": (700.0, 1400.0, 0.1),
}


def nbins(g):
    lo, hi, st = GRIDS[g]
    return int(round((hi - lo) / st)) + 1


def bin_index(values, g):
    lo, hi, st = GRIDS[g]
    return np.clip(np.rint((values - lo) / st).astype(np.int64), 0, nbins(g) - 1)


def hist_median_mad(counts, g):
    """Exact median and MAD of data discretised on grid `g` (bin centres)."""
    lo, hi, st = GRIDS[g]
    centres = lo + st * np.arange(len(counts))
    n = int(counts.sum())
    if n == 0:
        return None, None, 0
    cs = np.cumsum(counts)
    med = float(centres[np.searchsorted(cs, 0.5 * n)])
    dev = np.abs(centres - med)
    order = np.argsort(dev, kind="stable")
    cs2 = np.cumsum(counts[order])
    mad = float(dev[order][np.searchsorted(cs2, 0.5 * n)])
    return med, mad, n


def period_of(year_arr):
    p = np.full(len(year_arr), 2, dtype=np.int8)
    p[year_arr < 2021] = 1
    p[year_arr < 2016] = 0
    return p


def read_chunks(path, chunksize):
    return pd.read_csv(path, usecols=COLS, chunksize=chunksize,
                       dtype={"datetime": "string", "city": "string"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--work-dir", required=True, help="scratch dir for the sample (kept out of the repo)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunksize", type=int, default=2_000_000)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.work_dir, exist_ok=True)
    t0 = time.time()

    # ── pass 0: city registry ────────────────────────────────────────────
    reg = {}
    total_rows = 0
    for c in read_chunks(a.dataset, a.chunksize):
        total_rows += len(c)
        g = c.groupby("city").agg(lat=("lat", "first"), lon=("lon", "first"),
                                  lat_min=("lat", "min"), lat_max=("lat", "max"),
                                  lon_min=("lon", "min"), lon_max=("lon", "max"))
        for name, r in g.iterrows():
            e = reg.setdefault(name, dict(lat=float(r.lat), lon=float(r.lon)))
            assert abs(r.lat_min - r.lat_max) < 1e-9 and abs(r.lon_min - r.lon_max) < 1e-9, \
                f"{name}: lat/lon not constant per city"
    cities = sorted(reg)
    cidx = {n: i for i, n in enumerate(cities)}
    NC = len(cities)
    print(f"[pass0] {total_rows:,} rows, {NC} cities  ({time.time()-t0:.0f}s)", flush=True)

    # ── pass 1: validity, counts, reference histograms ───────────────────
    cell_counts = np.zeros((3, NC, 12), dtype=np.int64)          # period, city, month
    h_ref = {g: np.zeros(NC * nbins(g), dtype=np.int64) for g in ("T", "RH", "PS")}
    invalid = {"non_numeric_or_null": 0, "temperature_out_of_bounds": 0,
               "humidity_out_of_bounds": 0, "pressure_out_of_bounds": 0}
    valid_rows = 0
    dmin, dmax = "9999", "0000"
    for c in read_chunks(a.dataset, a.chunksize):
        for col in ("temperature_C", "humidity_pct", "pressure_hPa"):
            c[col] = pd.to_numeric(c[col], errors="coerce")
        bad_null = c[["temperature_C", "humidity_pct", "pressure_hPa"]].isna().any(axis=1).to_numpy()
        t = c["temperature_C"].to_numpy(dtype=float)
        rh = c["humidity_pct"].to_numpy(dtype=float)
        p = c["pressure_hPa"].to_numpy(dtype=float)
        bt = ~bad_null & ((t < VALID_T[0]) | (t > VALID_T[1]))
        bh = ~bad_null & ((rh < VALID_RH[0]) | (rh > VALID_RH[1]))
        bp = ~bad_null & ((p < VALID_P[0]) | (p > VALID_P[1]))
        ok = ~(bad_null | bt | bh | bp)
        invalid["non_numeric_or_null"] += int(bad_null.sum())
        invalid["temperature_out_of_bounds"] += int(bt.sum())
        invalid["humidity_out_of_bounds"] += int(bh.sum())
        invalid["pressure_out_of_bounds"] += int(bp.sum())
        valid_rows += int(ok.sum())
        d = c["datetime"].to_numpy(dtype=str)[ok]
        if len(d):
            # ISO-8601 strings sort chronologically; use Python str min/max (numpy
            # string arrays do not support min()).
            dmin, dmax = min(dmin, str(np.min(d.astype(object)))), max(dmax, str(np.max(d.astype(object))))
        year = np.array([int(x[:4]) for x in d], dtype=np.int16) if len(d) else np.array([], dtype=np.int16)
        month = np.array([int(x[5:7]) for x in d], dtype=np.int8) if len(d) else np.array([], dtype=np.int8)
        per = period_of(year)
        cc = c["city"].map(cidx).to_numpy(dtype=np.int64)[ok]
        np.add.at(cell_counts, (per, cc, month - 1), 1)
        r = per == 0
        for g, v in (("T", t[ok]), ("RH", rh[ok]), ("PS", p[ok])):
            idx = cc[r] * nbins(g) + bin_index(v[r], g)
            h_ref[g] += np.bincount(idx, minlength=NC * nbins(g))
    print(f"[pass1] valid {valid_rows:,} / {total_rows:,}  ({time.time()-t0:.0f}s)", flush=True)

    # per-city medians -> eligibility -> climatological elevation proxy
    med = {}
    for i, n in enumerate(cities):
        m = {}
        for g in ("T", "RH", "PS"):
            nb = nbins(g)
            m[g] = hist_median_mad(h_ref[g][i * nb:(i + 1) * nb], g)
        med[n] = m
    ref_rows = {n: med[n]["T"][2] for n in cities}
    excluded = {n: dict(reference_rows=int(ref_rows[n]),
                        reason=f"fewer than {MIN_REFERENCE_ROWS} reference-period rows")
                for n in cities if ref_rows[n] < MIN_REFERENCE_ROWS}
    eligible_mask = np.array([n not in excluded for n in cities])
    for pi in range(3):
        cell_counts[pi][~eligible_mask] = 0        # excluded cities take no sampling quota
    print(f"[eligibility] excluded {list(excluded)}", flush=True)
    proxy = {n: mf.climatological_elevation_proxy(med[n]["PS"][0], med[n]["T"][0])
             for n in cities if n not in excluded}

    # ── pass 2: MSL-equivalent histogram (reference) + stratified sample ──
    rng = np.random.default_rng(a.seed)
    quota = {}
    for pi, (pname, _, _) in enumerate(PERIODS):
        nonempty = int((cell_counts[pi] > 0).sum())
        quota[pi] = PERIOD_TARGETS[pname] / max(nonempty, 1)
    prob = {pi: np.minimum(1.0, quota[pi] / np.maximum(cell_counts[pi], 1)) for pi in range(3)}
    proxy_arr = np.array([proxy.get(n, 0.0) for n in cities], dtype=float)
    h_pm = np.zeros(NC * nbins("PM"), dtype=np.int64)
    S = {k: [] for k in ("city", "year", "month", "period", "t", "rh", "ps")}
    for c in read_chunks(a.dataset, a.chunksize):
        for col in ("temperature_C", "humidity_pct", "pressure_hPa"):
            c[col] = pd.to_numeric(c[col], errors="coerce")
        t = c["temperature_C"].to_numpy(dtype=float)
        rh = c["humidity_pct"].to_numpy(dtype=float)
        p = c["pressure_hPa"].to_numpy(dtype=float)
        ok = (~(np.isnan(t) | np.isnan(rh) | np.isnan(p))
              & (t >= VALID_T[0]) & (t <= VALID_T[1]) & (rh >= VALID_RH[0]) & (rh <= VALID_RH[1])
              & (p >= VALID_P[0]) & (p <= VALID_P[1]))
        u = rng.random(len(c))                       # drawn for EVERY row -> reproducible
        ok = ok & eligible_mask[c["city"].map(cidx).to_numpy(dtype=np.int64)]
        d = c["datetime"].to_numpy(dtype=str)[ok]
        year = np.array([int(x[:4]) for x in d], dtype=np.int16)
        month = np.array([int(x[5:7]) for x in d], dtype=np.int8)
        per = period_of(year)
        cc = c["city"].map(cidx).to_numpy(dtype=np.int64)[ok]
        t_, rh_, p_, u_ = t[ok], rh[ok], p[ok], u[ok]
        # reference-period MSL-equivalent histogram (uses the CITY proxy + the row's own T)
        r = per == 0
        pm = mf.surface_to_msl_equivalent(p_[r], t_[r], proxy_arr[cc[r]])
        h_pm += np.bincount(cc[r] * nbins("PM") + bin_index(pm, "PM"), minlength=NC * nbins("PM"))
        # stratified sample
        keep = np.zeros(len(u_), dtype=bool)
        for pi in range(3):
            m = per == pi
            if m.any():
                keep[m] = u_[m] < prob[pi][cc[m], month[m] - 1]
        for k, arr in (("city", cc), ("year", year), ("month", month), ("period", per),
                       ("t", t_), ("rh", rh_), ("ps", p_)):
            S[k].append(arr[keep])
    S = {k: np.concatenate(v) for k, v in S.items()}
    print(f"[pass2] sample {len(S['t']):,} rows  ({time.time()-t0:.0f}s)", flush=True)

    # ── assemble baselines ───────────────────────────────────────────────
    out_cities = {}
    for i, n in enumerate(cities):
        if n in excluded:
            continue
        nb = nbins("PM")
        pm_med, pm_mad, _ = hist_median_mad(h_pm[i * nb:(i + 1) * nb], "PM")
        (tm, tmad, cnt), (hm, hmad, _), (psm, psmad, _) = med[n]["T"], med[n]["RH"], med[n]["PS"]
        out_cities[n] = dict(
            lat=reg[n]["lat"], lon=reg[n]["lon"], n_reference_rows=cnt,
            temperature_median=tm, temperature_mad=tmad,
            humidity_median=hm, humidity_mad=hmad,
            pressure_surface_median=psm, pressure_surface_mad=psmad,
            pressure_msl_equivalent_median=pm_med, pressure_msl_equivalent_mad=pm_mad,
            climatological_elevation_proxy=round(proxy[n], 1),
            pressure_normalization_method=mf.PRESSURE_NORMALIZATION_METHOD,
        )
    keep_rows = np.where(eligible_mask)[0]
    gT = h_ref["T"].reshape(NC, -1)[keep_rows].sum(axis=0)
    gH = h_ref["RH"].reshape(NC, -1)[keep_rows].sum(axis=0)
    gPS = h_ref["PS"].reshape(NC, -1)[keep_rows].sum(axis=0)
    gPM = h_pm.reshape(NC, -1)[keep_rows].sum(axis=0)
    gt, gtm, gn = hist_median_mad(gT, "T"); gh, ghm, _ = hist_median_mad(gH, "RH")
    gps, gpsm, _ = hist_median_mad(gPS, "PS"); gpm, gpmm, _ = hist_median_mad(gPM, "PM")
    global_fb = dict(
        temperature_median=gt, temperature_mad=gtm, humidity_median=gh, humidity_mad=ghm,
        pressure_surface_median=gps, pressure_surface_mad=gpsm,
        pressure_msl_equivalent_median=gpm, pressure_msl_equivalent_mad=gpmm,
        climatological_elevation_proxy=None, n_reference_rows=gn,
        note=("Pooled robust statistics over ALL reference cities (pressure pooled in "
              "sea-level-equivalent space). Wide by construction: it mixes climates, so it is a "
              "coarser baseline than a city and is used only when no city is within the match radius."),
    )
    elig = [n for n in cities if n not in excluded]
    lat = np.array([reg[n]["lat"] for n in elig]); lon = np.array([reg[n]["lon"] for n in elig]); NE = len(elig)
    nn = sorted(min(mf.haversine_km(lat[i], lon[i], lat[j], lon[j]) for j in range(NE) if j != i) for i in range(NE))
    doc = dict(
        artifact_type="multivariate_baselines", schema_version=1,
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_dataset=dict(
            path=a.dataset, size_bytes=os.path.getsize(a.dataset), row_count=total_rows,
            valid_row_count=valid_rows, invalid_row_counts=invalid,
            date_min=dmin, date_max=dmax, n_cities=NC, n_cities_with_baseline=len(out_cities),
            excluded_cities=excluded, min_reference_rows_for_baseline=MIN_REFERENCE_ROWS,
            columns_used_for_values=["temperature_C", "humidity_pct", "pressure_hPa"],
            columns_used_for_grouping_only=["datetime", "city", "lat", "lon"],
            validity_bounds=dict(temperature_C=VALID_T, humidity_pct=VALID_RH, pressure_hPa=VALID_P)),
        conventions=dict(
            pressure_source_convention=mf.DATASET_PRESSURE_CONVENTION,
            runtime_pressure_convention=mf.RUNTIME_PRESSURE_CONVENTION,
            pressure_normalization_method=mf.PRESSURE_NORMALIZATION_METHOD,
            climatological_elevation_proxy_method=mf.ELEVATION_PROXY_METHOD,
            physical_constants=dict(g=mf.GRAVITY_M_S2, R_dry=mf.R_DRY_AIR, lapse_rate=mf.LAPSE_RATE_K_PER_M,
                                    P_ref_hpa=mf.P_REF_HPA, exponent=mf.BAROMETRIC_EXPONENT)),
        feature_names=list(mf.FEATURE_NAMES), scale_floor=mf.SCALE_FLOOR, mad_to_sigma=mf.MAD_TO_SIGMA,
        split=dict(method="chronological", periods={n: dict(start=s, end_exclusive=e) for n, s, e in PERIODS},
                   baselines_computed_from="reference period only"),
        sampling=dict(method="deterministic stratified (city x month) per period via seeded per-row uniform draws",
                      random_seed=a.seed, chunksize=a.chunksize, targets=PERIOD_TARGETS,
                      achieved={n: int((S["period"] == i).sum()) for i, (n, _, _) in enumerate(PERIODS)},
                      total_sample_rows=int(len(S["t"]))),
        city_match=dict(max_km=mf.MAX_CITY_MATCH_KM, method="nearest reference city (haversine) within max_km, else GLOBAL_FALLBACK",
                        nearest_city_spacing_km=dict(min=round(nn[0], 1), median=round(nn[len(nn)//2], 1),
                                                     p75=round(nn[3*len(nn)//4], 1), max=round(nn[-1], 1))),
        global_fallback=global_fb, cities=out_cities,
    )
    path = os.path.join(a.out_dir, "baselines.json")
    json.dump(doc, open(path, "w"), indent=1, default=float)
    np.savez_compressed(os.path.join(a.work_dir, "reference_sample.npz"),
                        city=S["city"], year=S["year"], month=S["month"], period=S["period"],
                        t=S["t"].astype(np.float32), rh=S["rh"].astype(np.float32), ps=S["ps"].astype(np.float32),
                        cities=np.array(cities))
    print(f"[done] {time.time()-t0:.0f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
