"""Shared helpers for the multivariate training / validation scripts."""
import json
import os
import sys

import numpy as np

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from engine import multivariate_features as mf  # noqa: E402

ARTIFACT_DIR = os.path.join(BACKEND_DIR, "models", "multivariate_ecod_if")
PERIOD_NAMES = ["reference", "calibration", "test"]


def load_baselines(artifact_dir=ARTIFACT_DIR):
    doc = json.load(open(os.path.join(artifact_dir, "baselines.json")))
    return doc, mf.BaselineSet.from_artifact(doc)


def sample_features(work_dir, baselines: "mf.BaselineSet"):
    """Feature matrices for each period, built with the SAME functions the
    runtime layer uses: surface -> sea-level-equivalent pressure (city proxy),
    then the robust city-conditioned z-features.

    Returns {period: dict(X=(n,3) features, city=(n,) index, month=(n,), t/rh/msl raw)}."""
    S = np.load(os.path.join(work_dir, "reference_sample.npz"), allow_pickle=True)
    names = list(S["cities"])
    X = np.full((len(S["t"]), 3), np.nan)
    MSL = np.full(len(S["t"]), np.nan)
    for ci, n in enumerate(names):
        b = baselines.cities.get(n)
        if b is None:
            continue
        m = S["city"] == ci
        t = S["t"][m].astype(float); rh = S["rh"][m].astype(float); ps = S["ps"][m].astype(float)
        pm = mf.surface_to_msl_equivalent(ps, t, b.climatological_elevation_proxy)
        MSL[m] = pm
        X[m] = mf.feature_vector(t, pm, rh, b)
    out = {}
    for pi, pn in enumerate(PERIOD_NAMES):
        m = (S["period"] == pi) & ~np.isnan(X[:, 0])
        out[pn] = dict(X=X[m], city=S["city"][m], month=S["month"][m], year=S["year"][m],
                       t=S["t"][m].astype(float), rh=S["rh"][m].astype(float), msl=MSL[m], names=names)
    return out


evidence_from_raw = mf.evidence_from_raw   # single shared definition (engine/multivariate_features.py)


def ecod_single_row_scores(model, X):
    """Vectorised, EXACT equivalent of `model.decision_function(row[None, :])`
    evaluated independently for every row of X.

    Why this exists: PyOD's ECOD.decision_function concatenates the training data
    with the rows being scored and takes ECDF ranks over that union, so a row's
    score depends on which other rows are scored with it. The runtime always
    scores ONE reading at a time (train + that one row), so thresholds must be
    calibrated under those same single-row semantics. Calling the library once
    per calibration row would take hours; this closed form does it in seconds.

    For one appended row x the union has N = n + 1 points and, per feature j:
        U_l = -log( (#train <= x_j + 1) / N )      U_r = -log( (#train >= x_j + 1) / N )
        score = sum_j max(U_l, U_r)
    (PyOD's skewness term only changes the result when sign(skew) is exactly 0,
    which does not occur for real data.) `verify_ecod_single_row` asserts equality
    with the real library call, so this is a fast path for the library's own
    formula, not a substitute algorithm.
    """
    Xt = np.asarray(model.X_train, dtype=float)
    n = Xt.shape[0]
    N = n + 1
    X = np.asarray(X, dtype=float)
    score = np.zeros(len(X))
    for j in range(Xt.shape[1]):
        col = np.sort(Xt[:, j])
        le = np.searchsorted(col, X[:, j], side="right") + 1          # (#train <= x) + the row itself
        ge = (n - np.searchsorted(col, X[:, j], side="left")) + 1     # (#train >= x) + the row itself
        u_l = -np.log(le / N)
        u_r = -np.log(ge / N)
        score += np.maximum(u_l, u_r)
    return score


def verify_ecod_single_row(model, X, k=200, seed=0, tol=1e-8):
    """Assert the closed form equals the real PyOD single-row call on k random rows."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X), size=min(k, len(X)), replace=False)
    fast = ecod_single_row_scores(model, X[idx])
    real = np.array([model.decision_function(X[i:i + 1])[0] for i in idx])
    err = float(np.max(np.abs(fast - real)))
    assert err < tol, f"ECOD single-row closed form differs from PyOD by {err}"
    return err
