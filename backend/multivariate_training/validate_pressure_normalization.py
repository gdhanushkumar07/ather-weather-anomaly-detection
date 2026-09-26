"""
Stage 1 validation: are the training and runtime feature spaces comparable?

Run BEFORE any ECOD / Isolation Forest is trained. It checks that a normal
runtime station does not become an extreme outlier merely because of the
surface-vs-sea-level pressure convention.

ACCEPTANCE CRITERIA (fixed here, before the results were inspected):
  C1  median runtime z_pressure (NWP stations)            within [-2, +2]
  C2  95th percentile of |z_pressure| (NWP stations)      <= 5
  C3  fraction of NWP stations with ANY |z| > 6           <= 5 %
The un-normalised comparison is reported alongside purely to show the size of
the mismatch the normalisation removes; it is not an acceptance criterion.

Usage (from backend/):
    python3 -m multivariate_training.validate_pressure_normalization \
        --work-dir <scratch> --stations-json <geojson from GET /api/stations>
"""
import argparse
import json
import os
import sys

import numpy as np

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
from engine import multivariate_features as mf  # noqa: E402

BASELINES = os.path.join(BACKEND_DIR, "models", "multivariate_ecod_if", "baselines.json")
C1_MEDIAN_ZP = (-2.0, 2.0)
C2_P95_ABS_ZP = 5.0
C3_FRAC_ANY_ABS_Z_GT6 = 0.05


def stats(x):
    x = np.asarray(x, dtype=float)
    q = np.percentile(x, [0.1, 1, 50, 99, 99.9])
    med = np.median(x)
    return dict(median=med, mad=float(np.median(np.abs(x - med))), p0_1=q[0], p1=q[1], p99=q[3], p99_9=q[4],
                min=float(x.min()), max=float(x.max()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--stations-json", required=True)
    a = ap.parse_args()
    doc = json.load(open(BASELINES))
    bs = mf.BaselineSet.from_artifact(doc)

    print("=" * 78)
    print("1. CONVENTIONS")
    c = doc["conventions"]
    print(f"   dataset pressure convention : {c['pressure_source_convention']}  (surface/station pressure)")
    print(f"   runtime pressure convention : {c['runtime_pressure_convention']}  (Open-Meteo pressure_msl)")
    print(f"   normalisation method        : {c['pressure_normalization_method']}")
    print(f"   constants                   : {c['physical_constants']}")

    print("\n2. CITY EXAMPLES (reference period 1996-2015)")
    print(f"   {'city':10s} {'P_sfc med':>9s} {'P_sfc MAD':>9s} {'elev proxy':>10s} {'T med':>6s} {'MSL-eq med':>10s} {'MSL-eq MAD':>10s}")
    for n in ("Bengaluru", "Pune", "Hyderabad", "Mumbai", "Chennai", "New_Delhi", "Shimla", "Leh"):
        if n in bs.cities:
            b = bs.cities[n]
            print(f"   {n:10s} {b.pressure_surface_median:9.1f} {b.pressure_surface_mad:9.2f} "
                  f"{b.climatological_elevation_proxy:9.0f}m {b.temperature_median:6.1f} "
                  f"{b.pressure_msl_equivalent_median:10.2f} {b.pressure_msl_equivalent_mad:10.2f}")
    g = bs.global_baseline
    print(f"   GLOBAL     P_sfc med {g.pressure_surface_median:.1f}  MSL-eq med {g.pressure_msl_equivalent_median:.2f} "
          f"MAD {g.pressure_msl_equivalent_mad:.2f}  T med {g.temperature_median:.1f} MAD {g.temperature_mad:.1f}  RH med {g.humidity_median:.0f} MAD {g.humidity_mad:.0f}")
    allmsl = np.array([b.pressure_msl_equivalent_median for b in bs.cities.values()])
    print(f"   MSL-equivalent city medians across all {len(allmsl)} cities: min {allmsl.min():.1f}  median {np.median(allmsl):.1f}  max {allmsl.max():.1f}")
    allsfc = np.array([b.pressure_surface_median for b in bs.cities.values()])
    print(f"   (raw surface-pressure medians span {allsfc.min():.0f} .. {allsfc.max():.0f} hPa -> {allsfc.max()-allsfc.min():.0f} hPa spread removed by the conversion)")

    print("\n3. FEATURE STATISTICS ON THE STRATIFIED SAMPLE (features from the city baselines)")
    S = np.load(os.path.join(a.work_dir, "reference_sample.npz"), allow_pickle=True)
    names = list(S["cities"])
    base_for = {n: bs.cities.get(n) for n in names}
    feats = np.full((len(S["t"]), 3), np.nan)
    for ci, n in enumerate(names):
        b = base_for[n]
        if b is None:
            continue
        m = S["city"] == ci
        pm = mf.surface_to_msl_equivalent(S["ps"][m].astype(float), S["t"][m].astype(float), b.climatological_elevation_proxy)
        feats[m] = mf.feature_vector(S["t"][m].astype(float), pm, S["rh"][m].astype(float), b)
    pnames = ["reference", "calibration", "test"]
    for pi, pn in enumerate(pnames):
        f = feats[(S["period"] == pi) & ~np.isnan(feats[:, 0])]
        print(f"   [{pn:11s}] n={len(f):>7,}")
        for j, fn in enumerate(mf.FEATURE_NAMES):
            s = stats(f[:, j])
            print(f"      {fn:27s} median {s['median']:+6.2f}  MAD {s['mad']:5.2f}  p0.1 {s['p0_1']:+7.2f}  p99.9 {s['p99_9']:+7.2f}  min {s['min']:+8.1f}  max {s['max']:+8.1f}")

    print("\n4. RUNTIME COMPARISON (live stations from GET /api/stations)")
    feats_live = json.load(open(a.stations_json))["features"]
    rows = {"NWP_MODEL_REFERENCE": [], "AWS_IN_SITU": []}
    n_city = n_global = 0
    for f in feats_live:
        p = f["properties"]; lon, lat = f["geometry"]["coordinates"]
        src = p.get("source")
        if src not in rows or p.get("pressure") in (None, 0) or p.get("temperature") is None or p.get("humidity") is None:
            continue
        b, dist = bs.resolve(lat, lon)
        vec = mf.feature_vector(p["temperature"], p["pressure"], p["humidity"], b)
        naive = (p["pressure"] - b.pressure_surface_median) / mf.robust_scale(b.pressure_surface_mad, "pressure_hpa") if b.scope == "CITY" else np.nan
        rows[src].append(dict(id=p["id"], scope=b.scope, city=b.name, dist=dist, z=vec, naive_zp=naive, P=p["pressure"], lat=lat))
        n_city += b.scope == "CITY"; n_global += b.scope != "CITY"
    print(f"   matched to a city (<= {bs.max_match_km:.0f} km): {n_city}   GLOBAL_FALLBACK: {n_global}")
    verdict = {}
    for src, r in rows.items():
        cityrows = [x for x in r if x["scope"] == "CITY"]
        if not cityrows:
            print(f"   {src}: no city-matched stations"); continue
        Z = np.array([x["z"] for x in cityrows]); naive = np.array([x["naive_zp"] for x in cityrows])
        print(f"   {src}: {len(cityrows)} city-matched stations")
        print(f"      z_pressure  (NORMALISED)   median {np.median(Z[:,1]):+6.2f}   p5 {np.percentile(Z[:,1],5):+6.2f}   p95 {np.percentile(Z[:,1],95):+6.2f}   max|z| {np.abs(Z[:,1]).max():5.2f}")
        print(f"      z_pressure  (raw/unnorm.)  median {np.median(naive):+6.2f}   p95 {np.percentile(naive,95):+6.2f}   max {naive.max():+7.2f}   <- what the mismatch would have produced")
        print(f"      z_temperature median {np.median(Z[:,0]):+5.2f}  max|z| {np.abs(Z[:,0]).max():5.2f}   z_humidity median {np.median(Z[:,2]):+5.2f}  max|z| {np.abs(Z[:,2]).max():5.2f}")
        verdict[src] = dict(n=len(cityrows), med_zp=float(np.median(Z[:, 1])), p95_abs_zp=float(np.percentile(np.abs(Z[:, 1]), 95)),
                            frac_any_gt6=float((np.abs(Z) > 6).any(axis=1).mean()))
    print("   worked examples (runtime -> features):")
    for x in [x for x in rows["NWP_MODEL_REFERENCE"] if x["scope"] == "CITY"][:2] + [x for x in rows["AWS_IN_SITU"] if x["scope"] == "CITY"][:2]:
        print(f"      {x['id']:14s} city={x['city']:10s} ({x['dist']} km)  P_runtime={x['P']:7.1f}  ->  z=[{x['z'][0]:+.2f}, {x['z'][1]:+.2f}, {x['z'][2]:+.2f}]   raw z_P would be {x['naive_zp']:+.1f}")

    print("\n5. CITY-vs-GLOBAL FALLBACK")
    nonindian = [f for f in feats_live if f["geometry"]["coordinates"][0] > 120 or f["geometry"]["coordinates"][0] < 0][:3]
    for f in nonindian:
        p = f["properties"]; lon, lat = f["geometry"]["coordinates"]
        if p.get("pressure") in (None, 0) or p.get("temperature") is None or p.get("humidity") is None:
            continue
        b, dist = bs.resolve(lat, lon)
        v = mf.feature_vector(p["temperature"], p["pressure"], p["humidity"], b)
        print(f"      {p['id']:16s} lat/lon ({lat:.1f},{lon:.1f}) -> scope={b.scope}  z=[{v[0]:+.2f}, {v[1]:+.2f}, {v[2]:+.2f}]")
    print(f"      lat/lon 0/0 (missing coordinate) -> scope={bs.resolve(0.0, 0.0)[0].scope}")

    print("\n6. ACCEPTANCE CRITERIA (pre-registered)")
    ok = True
    v = verdict.get("NWP_MODEL_REFERENCE")
    if v:
        c1 = C1_MEDIAN_ZP[0] <= v["med_zp"] <= C1_MEDIAN_ZP[1]
        c2 = v["p95_abs_zp"] <= C2_P95_ABS_ZP
        c3 = v["frac_any_gt6"] <= C3_FRAC_ANY_ABS_Z_GT6
        print(f"   C1 median z_P in {C1_MEDIAN_ZP}            : {v['med_zp']:+.2f}   {'PASS' if c1 else 'FAIL'}")
        print(f"   C2 p95 |z_P| <= {C2_P95_ABS_ZP}                   : {v['p95_abs_zp']:.2f}    {'PASS' if c2 else 'FAIL'}")
        print(f"   C3 frac(any |z|>6) <= {C3_FRAC_ANY_ABS_Z_GT6:.0%}          : {v['frac_any_gt6']:.1%}   {'PASS' if c3 else 'FAIL'}")
        ok = c1 and c2 and c3
    else:
        ok = False; print("   no NWP city-matched stations -> cannot validate")
    print(f"\n   OVERALL: {'PASS - feature spaces comparable' if ok else 'FAIL - do NOT train'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
