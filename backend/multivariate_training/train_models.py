"""
Stage 2: fit ECOD + Isolation Forest on the pressure-normalised reference
features, calibrate operating thresholds on a CLEAN chronological holdout, and
measure the clean false-positive rate on a later, untouched test period.

Rules enforced here:
  * fit on the REFERENCE period only (1996-2015); calibrate on 2016-2020; the
    2021-2026 test period is never used to fit or to set a threshold
  * no injected anomaly is used anywhere in fitting or calibration
  * calibration is a fixed percentile rule declared below BEFORE evaluation

Usage (from backend/):
    python3 -m multivariate_training.train_models --work-dir <scratch>
"""
import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pyod
import sklearn
from pyod.models.ecod import ECOD
from sklearn.ensemble import IsolationForest

from multivariate_training.common import (ARTIFACT_DIR, ecod_single_row_scores, evidence_from_raw,
                                          load_baselines, sample_features, verify_ecod_single_row)

SEED = 42
ECOD_FIT_ROWS = 100_000            # measured latency trade-off: 45 ms/score vs 122 ms at 250k
ECOD_PARAMS = dict(contamination=0.01, n_jobs=1)   # contamination only sets pyod's own label cut-off; unused here
IF_PARAMS = dict(n_estimators=200, max_samples=256, max_features=1.0, bootstrap=False,
                 contamination="auto", random_state=SEED, n_jobs=1)

# Calibration rule (fixed before evaluation): percentiles of the CLEAN calibration scores.
CENTER_PCT = 95.0      # <= this -> evidence 0     ("typical operating range")
THRESHOLD_PCT = 99.5   # operating threshold -> evidence 0.5   (0.5% per-detector false-positive target)
EXTREME_PCT = 99.95    # >= this -> evidence 1.0
COMBINATION = "max"    # combined = max(ecod_evidence, isolation_forest_evidence)


def if_raw(model, X):
    """Isolation Forest raw anomaly score: -score_samples, so HIGHER = more anomalous."""
    return -model.score_samples(X)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out-dir", default=ARTIFACT_DIR)
    a = ap.parse_args()
    t0 = time.time()
    doc, bs = load_baselines(a.out_dir)
    F = sample_features(a.work_dir, bs)
    ref, cal, test = F["reference"]["X"], F["calibration"]["X"], F["test"]["X"]
    print(f"features  reference {ref.shape}  calibration {cal.shape}  test {test.shape}", flush=True)

    # ── fit (reference period only) ──────────────────────────────────────
    rng = np.random.default_rng(SEED)
    ecod_idx = np.sort(rng.choice(len(ref), size=min(ECOD_FIT_ROWS, len(ref)), replace=False))
    ecod = ECOD(**ECOD_PARAMS).fit(ref[ecod_idx])
    iso = IsolationForest(**IF_PARAMS).fit(ref)
    print(f"fitted ECOD on {len(ecod_idx):,} rows, IsolationForest on {len(ref):,} rows ({time.time()-t0:.0f}s)", flush=True)

    # ── calibrate on the clean holdout ───────────────────────────────────
    # ECOD is scored under the SAME single-row semantics the runtime uses (see
    # common.ecod_single_row_scores); its equality with the real PyOD call is asserted.
    err = verify_ecod_single_row(ecod, cal, k=300)
    print(f"verified ECOD single-row closed form == PyOD decision_function on 300 rows (max |diff| {err:.2e})", flush=True)
    cal_scores = {"ecod": ecod_single_row_scores(ecod, cal), "isolation_forest": if_raw(iso, cal)}
    anchors = {}
    for k, s in cal_scores.items():
        c, t_, e = np.percentile(s, [CENTER_PCT, THRESHOLD_PCT, EXTREME_PCT])
        anchors[k] = dict(center=float(c), threshold=float(t_), extreme=float(e),
                          calibration_rows=int(len(s)), calibration_min=float(s.min()), calibration_max=float(s.max()))
    print("anchors:", json.dumps(anchors, indent=1), flush=True)

    # ── clean false-positive rate on the untouched TEST period ───────────
    test_raw = {"ecod": ecod_single_row_scores(ecod, test), "isolation_forest": if_raw(iso, test)}
    ev = {k: evidence_from_raw(test_raw[k], **{x: anchors[k][x] for x in ("center", "threshold", "extreme")}) for k in test_raw}
    ev["combined"] = np.maximum(ev["ecod"], ev["isolation_forest"])
    fpr = {k: {f">={th}": float((v >= th).mean()) for th in (0.5, 0.7, 0.75)} for k, v in ev.items()}
    fpr_cal = {}
    ev_cal = {k: evidence_from_raw(cal_scores[k], **{x: anchors[k][x] for x in ("center", "threshold", "extreme")}) for k in cal_scores}
    ev_cal["combined"] = np.maximum(ev_cal["ecod"], ev_cal["isolation_forest"])
    fpr_cal = {k: {f">={th}": float((v >= th).mean()) for th in (0.5, 0.7, 0.75)} for k, v in ev_cal.items()}
    print("clean FPR on calibration (in-sample by construction):", json.dumps(fpr_cal), flush=True)
    print("clean FPR on TEST (2021-2026, untouched):            ", json.dumps(fpr), flush=True)
    agree = float(((ev['ecod'] >= 0.5) & (ev['isolation_forest'] >= 0.5)).sum() / max(1, ((ev['ecod'] >= 0.5) | (ev['isolation_forest'] >= 0.5)).sum()))

    # ── persist ──────────────────────────────────────────────────────────
    os.makedirs(a.out_dir, exist_ok=True)
    # PyOD stores per-call scratch arrays on the model (U_l, U_r, U_skew, O). They are
    # recomputed on every decision_function call, so drop them: smaller artifact and
    # no stale state carried between processes.
    for attr in ("U_l", "U_r", "U_skew", "O"):
        if hasattr(ecod, attr):
            delattr(ecod, attr)
    joblib.dump(ecod, os.path.join(a.out_dir, "ecod.joblib"), compress=3)
    joblib.dump(iso, os.path.join(a.out_dir, "isolation_forest.joblib"), compress=3)
    card = dict(
        artifact_type="multivariate_model_card", schema_version=1, model_version="mv-ecod-if-1.0.0",
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_dataset=doc["source_dataset"]["path"], dataset_row_count=doc["source_dataset"]["row_count"],
        valid_row_count=doc["source_dataset"]["valid_row_count"],
        sample_count=doc["sampling"]["achieved"], fit_rows=dict(ecod=int(len(ecod_idx)), isolation_forest=int(len(ref))),
        train_period=doc["split"]["periods"]["reference"], calibration_period=doc["split"]["periods"]["calibration"],
        test_period=doc["split"]["periods"]["test"],
        feature_names=doc["feature_names"],
        pressure_source_convention=doc["conventions"]["pressure_source_convention"],
        runtime_pressure_convention=doc["conventions"]["runtime_pressure_convention"],
        pressure_normalization_method=doc["conventions"]["pressure_normalization_method"],
        climatological_elevation_proxy_method=doc["conventions"]["climatological_elevation_proxy_method"],
        baseline_scope="CITY within %.0f km else GLOBAL_FALLBACK" % doc["city_match"]["max_km"],
        random_seed=SEED,
        ecod=dict(library="pyod", version=pyod.__version__, class_="pyod.models.ecod.ECOD", params=ECOD_PARAMS,
                  fit_rows=int(len(ecod_idx)), raw_score="decision_function (sum of per-feature tail log-probabilities); higher = more anomalous"),
        isolation_forest=dict(library="scikit-learn", version=sklearn.__version__, class_="sklearn.ensemble.IsolationForest",
                              params=IF_PARAMS, fit_rows=int(len(ref)), raw_score="-score_samples; higher = more anomalous"),
        calibration=dict(method=("Percentiles of each detector's raw scores on the CLEAN calibration period (2016-2020): "
                                 f"P{CENTER_PCT}->evidence 0, P{THRESHOLD_PCT}->0.5 (operating threshold), P{EXTREME_PCT}->1.0, "
                                 "linear in between; NOT a probability. No injected anomaly was used."),
                         percentiles=dict(center=CENTER_PCT, threshold=THRESHOLD_PCT, extreme=EXTREME_PCT),
                         detectors=anchors),
        ecod_scoring_note=("PyOD's ECOD.decision_function ranks a row against train UNION the rows scored with it, so "
                           "scores are batch-dependent. Runtime scores one reading at a time (train + 1 row); calibration "
                           "therefore uses the exact single-row closed form, asserted equal to the library call."),
        combination=dict(method=COMBINATION, formula="combined = max(ecod_evidence, isolation_forest_evidence)",
                         rationale="Simple and explainable: a joint state is flagged if EITHER detector finds it unusual; "
                                   "the driving detector is reported. Chosen a priori, not tuned on any fault.",
                         evidence_is_probability=False),
        clean_false_positive_rate=dict(on_calibration_in_sample=fpr_cal, on_test_2021_2026=fpr,
                                       detector_agreement_when_either_ge_0_5=agree),
        libraries=dict(python=platform.python_version(), pyod=pyod.__version__, scikit_learn=sklearn.__version__,
                       numpy=np.__version__, joblib=joblib.__version__),
    )
    json.dump(card, open(os.path.join(a.out_dir, "model_card.json"), "w"), indent=1, default=float)
    print(f"[done] {time.time()-t0:.0f}s -> {a.out_dir}", flush=True)
    for f in sorted(os.listdir(a.out_dir)):
        print(f"   {f:24s} {os.path.getsize(os.path.join(a.out_dir, f))/1e6:7.2f} MB")


if __name__ == "__main__":
    main()
