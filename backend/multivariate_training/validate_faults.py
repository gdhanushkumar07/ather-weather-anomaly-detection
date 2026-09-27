"""
Stage 3: controlled fault-injection validation of the fitted Multivariate layer.

* Faults are injected into IN-MEMORY COPIES of held-out TEST-period rows
  (2021-2026). The source dataset, the fit sample and the calibration sample are
  never modified or used here.
* Injection magnitudes are fixed below, in physical units, BEFORE any result was
  seen. Nothing is tuned to make a scenario look good.
* Ground truth is known by construction: injected rows are positives, the
  untouched copies of the same rows are the clean control.
* The vectorised batch path used for the large runs is cross-checked against the
  real runtime layer (MultivariateConsistencyLayer) on a subset.

Usage (from backend/):
    python3 -m multivariate_training.validate_faults --work-dir <scratch>
"""
import argparse
import json
import os
import sys

import numpy as np

from multivariate_training.common import (ARTIFACT_DIR, ecod_single_row_scores, load_baselines, sample_features,
                                          verify_ecod_single_row)
from engine import multivariate_features as mf
from engine.layer3_multivariate import MultivariateConsistencyLayer, load_artifacts
from schema import AWSReading, ObservationSource

SEED = 7
N_BASE = 3000                       # base rows drawn from the TEST period
N_RUNTIME_CHECK = 60
N_GATING = 150
# --- fixed injection magnitudes (physical units) ---
DOSES = {
    "temperature_spike":  [("+5C", "t", +5.0), ("+10C", "t", +10.0), ("+15C", "t", +15.0)],
    "temperature_drop":   [("-5C", "t", -5.0), ("-10C", "t", -10.0), ("-15C", "t", -15.0)],
    "pressure_offset_pos": [("+5hPa", "p", +5.0), ("+15hPa", "p", +15.0), ("+30hPa", "p", +30.0)],
    "pressure_offset_neg": [("-5hPa", "p", -5.0), ("-15hPa", "p", -15.0), ("-30hPa", "p", -30.0)],
    "humidity_offset_pos": [("+15%", "h", +15.0), ("+30%", "h", +30.0), ("+50%", "h", +50.0)],
    "humidity_offset_neg": [("-15%", "h", -15.0), ("-30%", "h", -30.0), ("-50%", "h", -50.0)],
}
NOISE_SIGMA_MULT = 3.0              # noise burst: sigma = 3 x the city's robust scale, per channel
CHANNEL = {"t": 0, "p": 1, "h": 2}
CH_NAME = {"t": "temperature_c", "p": "pressure_hpa", "h": "humidity_pct"}


def base_rows(F, bs, rng):
    T = F["test"]
    idx = np.sort(rng.choice(len(T["t"]), size=min(N_BASE, len(T["t"])), replace=False))
    names = T["names"]
    return dict(t=T["t"][idx].copy(), h=T["rh"][idx].copy(), p=T["msl"][idx].copy(),
                city=T["city"][idx].copy(), month=T["month"][idx].copy(), names=names,
                all_t=T["t"], all_h=T["rh"], all_city=T["city"], all_month=T["month"])


def features(t, p, h, city, names, bs):
    X = np.zeros((len(t), 3))
    for ci in np.unique(city):
        b = bs.cities[names[ci]]
        m = city == ci
        X[m] = mf.feature_vector(t[m], p[m], h[m], b)
    return X


def scores(X, art):
    e_raw = ecod_single_row_scores(art.ecod, X)      # runtime (single-row) semantics
    i_raw = -art.iforest.score_samples(X)
    e = mf.evidence_from_raw(e_raw, **art.anchors["ecod"])
    i = mf.evidence_from_raw(i_raw, **art.anchors["isolation_forest"])
    return e, i, np.maximum(e, i)


def summarize(e, i, c, X_scaled_dom=None, channel=None, dom=None):
    r = dict(n=int(len(c)),
             ecod_ge_0_5=float((e >= 0.5).mean()), isolation_forest_ge_0_5=float((i >= 0.5).mean()),
             combined_ge_0_5=float((c >= 0.5).mean()), combined_ge_0_75=float((c >= 0.75).mean()),
             combined_mean=float(c.mean()), ecod_median=float(np.median(e)), isolation_forest_median=float(np.median(i)),
             combined_median=float(np.median(c)),
             driver_ecod=float((e >= i).mean()), driver_isolation_forest=float((i > e).mean()))
    if channel is not None:
        r["dominant_channel_correct"] = float((dom == CHANNEL[channel]).mean())
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    a = ap.parse_args()
    doc, bs = load_baselines()
    art = load_artifacts()
    F = sample_features(a.work_dir, bs)
    rng = np.random.default_rng(SEED)
    B = base_rows(F, bs, rng)
    names = B["names"]
    n = len(B["t"])
    X0 = features(B["t"], B["p"], B["h"], B["city"], names, bs)
    e0, i0, c0 = scores(X0, art)
    out = {"design": dict(base_rows=n, source="held-out TEST period 2021-2026 (never used for fit/calibration)",
                          magnitudes=DOSES, noise_sigma_multiplier=NOISE_SIGMA_MULT, seed=SEED,
                          note="Ground truth known by construction. Nothing was tuned on these results."),
           "scenarios": {}}
    out["scenarios"]["clean_control"] = dict(ground_truth="CLEAN", **summarize(e0, i0, c0))

    # -- single-channel offsets / spikes / drops ------------------------------
    for scen, doses in DOSES.items():
        for label, ch, delta in doses:
            t, p, h = B["t"].copy(), B["p"].copy(), B["h"].copy()
            {"t": t, "p": p, "h": h}[ch][:] += delta
            h = np.clip(h, 0.0, 100.0)
            X = features(t, p, h, B["city"], names, bs)
            e, i, c = scores(X, art)
            dom = np.argmax(np.abs(X), axis=1)
            out["scenarios"][f"{scen} {label}"] = dict(ground_truth=f"FAULT ({CH_NAME[ch]} {delta:+g})", **summarize(e, i, c, channel=ch, dom=dom))

    # -- frozen / stale T+RH from the opposite season -------------------------
    rngf = np.random.default_rng(SEED + 1)
    t, p, h = B["t"].copy(), B["p"].copy(), B["h"].copy()
    keep = np.zeros(n, dtype=bool)
    for k in range(n):
        want = (B["month"][k] + 5) % 12 + 1
        pool = np.where((B["all_city"] == B["city"][k]) & (B["all_month"] == want))[0]
        if len(pool):
            j = rngf.choice(pool); t[k], h[k] = B["all_t"][j], B["all_h"][j]; keep[k] = True
    X = features(t[keep], p[keep], h[keep], B["city"][keep], names, bs)
    e, i, c = scores(X, art)
    out["scenarios"]["frozen_stale T+RH (opposite-season values, P live)"] = dict(
        ground_truth="FAULT (stale T and RH)", **summarize(e, i, c))

    # -- noise burst -----------------------------------------------------------
    rngn = np.random.default_rng(SEED + 2)
    t, p, h = B["t"].copy(), B["p"].copy(), B["h"].copy()
    for ci in np.unique(B["city"]):
        b = bs.cities[names[ci]]; m = B["city"] == ci; k = int(m.sum())
        t[m] += rngn.normal(0, NOISE_SIGMA_MULT * mf.robust_scale(b.temperature_mad, "temperature_c"), k)
        p[m] += rngn.normal(0, NOISE_SIGMA_MULT * mf.robust_scale(b.pressure_msl_equivalent_mad, "pressure_hpa"), k)
        h[m] += rngn.normal(0, NOISE_SIGMA_MULT * mf.robust_scale(b.humidity_mad, "humidity_pct"), k)
    h = np.clip(h, 0, 100)
    e, i, c = scores(features(t, p, h, B["city"], names, bs), art)
    out["scenarios"]["noise_burst (3 sigma on all channels)"] = dict(ground_truth="FAULT (noise on T,P,RH)", **summarize(e, i, c))

    # -- combined multivariate abnormal state ---------------------------------
    t, p, h = B["t"].copy(), B["p"].copy(), B["h"].copy()
    for ci in np.unique(B["city"]):
        b = bs.cities[names[ci]]; m = B["city"] == ci
        t[m] = b.temperature_median + 3 * mf.robust_scale(b.temperature_mad, "temperature_c")
        p[m] = b.pressure_msl_equivalent_median - 3 * mf.robust_scale(b.pressure_msl_equivalent_mad, "pressure_hpa")
        h[m] = 100.0
    e, i, c = scores(features(t, p, h, B["city"], names, bs), art)
    out["scenarios"]["combined_abnormal (T +3sd, P -3sd, RH 100)"] = dict(
        ground_truth="FAULT (joint state)", **summarize(e, i, c))

    # -- data-quality gating, through the REAL runtime layer ------------------
    layer = MultivariateConsistencyLayer()
    sel = np.arange(N_GATING)
    g = {}
    def rd(k, drop=(), conv="MSL"):
        b = bs.cities[names[B["city"][k]]]
        kw = dict(station_id=f"V{k}", temperature_c=float(B["t"][k]), pressure_hpa=float(B["p"][k]),
                  humidity_pct=float(B["h"][k]), lat=b.lat, lon=b.lon, source=ObservationSource.SYNTHETIC_TEST,
                  pressure_convention=conv)
        for d_ in drop:
            kw[d_] = None
        return AWSReading(**kw)
    for label, drop, conv in (("all 3 channels valid (control)", (), "MSL"),
                              ("pressure missing", ("pressure_hpa",), "MSL"),
                              ("humidity missing", ("humidity_pct",), "MSL"),
                              ("temperature + humidity missing", ("temperature_c", "humidity_pct"), "MSL"),
                              ("all 3 valid, pressure convention UNKNOWN", (), "UNKNOWN")):
        st, ex, sc = {}, 0, []
        for k in sel:
            s, _r, d = layer.evaluate(rd(k, drop, conv))
            st[d["status"]] = st.get(d["status"], 0) + 1
            ex += int(d["detectors"]["ecod"]["executed"] and d["detectors"]["isolation_forest"]["executed"])
            sc.append(s)
        g[label] = dict(n=len(sel), status_counts=st, ecod_and_if_executed=ex, mean_score=float(np.mean(sc)))
    out["data_quality_gating"] = g

    # -- batch path == runtime layer -----------------------------------------
    diffs = []
    for k in np.random.default_rng(SEED + 3).choice(n, N_RUNTIME_CHECK, replace=False):
        s, _r, d = layer.evaluate(rd(int(k)))
        diffs.append(abs(d["combined_score"] - float(c0[k])))
    out["batch_vs_runtime_layer_max_abs_diff"] = float(max(diffs))

    path = os.path.join(ARTIFACT_DIR, "validation_report.json")
    json.dump(out, open(path, "w"), indent=1, default=float)

    print(f"base rows {n}; batch-vs-runtime max |diff| = {max(diffs):.4f}\n")
    print(f"{'scenario':58s} {'ECOD>=.5':>8s} {'IF>=.5':>7s} {'comb>=.5':>8s} {'comb>=.75':>9s} {'meanComb':>8s}")
    for k, v in out["scenarios"].items():
        print(f"{k:58s} {v['ecod_ge_0_5']:8.1%} {v['isolation_forest_ge_0_5']:7.1%} {v['combined_ge_0_5']:8.1%} {v['combined_ge_0_75']:9.1%} {v['combined_mean']:8.3f}")
    print("\nDATA-QUALITY GATING (real runtime layer):")
    for k, v in g.items():
        print(f"  {k:44s} status={v['status_counts']}  ECOD&IF executed on {v['ecod_and_if_executed']}/{v['n']}  mean score {v['mean_score']:.3f}")


if __name__ == "__main__":
    main()
