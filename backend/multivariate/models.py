"""
ECOD + Isolation Forest detectors with split-conformal calibration.

ECOD  (pyod.models.ecod.ECOD, Li et al. 2022): per-dimension empirical-CDF
      tail probabilities, summed over the feature vector. Parameter-free.
IFOR  (sklearn.ensemble.IsolationForest, Liu et al. 2008): random axis-aligned
      partitioning of the JOINT feature space; points in sparsely populated
      combinations isolate in fewer splits.

Neither needs feature scaling (ECOD works on ranks; Isolation Forest draws
split values uniformly within each feature's own range).

SCORING NEW POINTS — pyod ECOD.decision_function(X) recomputes its ECDFs over
the training data PLUS every row of X, so a batch's score depends on what else
is in the batch (a batch full of anomalies shifts its own ECDF). ATHER scores
one live observation at a time, so every ECOD score here is defined as pyod's
decision_function applied to that ONE row on its own.

Calling pyod once per row costs ~7-10 ms (it re-sorts the whole fit set every
time), which made each regional model take ~10 s to calibrate. For a single
appended point x the quantities pyod computes reduce exactly to
    U_l = -log((#fit <= x + 1)/(n + 1)),   U_r = -log((#fit >= x + 1)/(n + 1)),
    skew sign of (fit + x),  O = max(U_l, U_r, U_skew),  score = sum_j O_j
so ECODDetector evaluates that for many rows at once from the pyod-fitted
model's own training matrix. After every fit it re-scores sample rows with
pyod's decision_function and falls back to per-row pyod calls if the two ever
disagree (e.g. a future pyod changes its formula). tests assert equality,
including heavy ties (integer-valued RH). Isolation Forest scores are
row-independent and computed in batch by sklearn directly.

CALIBRATION — raw scores from the two models live on unrelated scales. Each
is converted to a split-conformal p-value against a held-out calibration set
of trusted normal observations (chronologically AFTER the fit rows, never
the fit rows themselves, whose in-sample scores are optimistically low):
        p(x) = (1 + #{calibration scores >= score(x)}) / (n_cal + 1)
Under exchangeability of normal data, P(p <= alpha) <= alpha — so `alpha` is
each model's target false-alarm rate. With n_cal calibration points the
smallest attainable p is 1/(n_cal+1); `min_attainable_p` is reported so a
too-small calibration set is visible rather than silently mis-calibrated.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from pyod.models.ecod import ECOD
    PYOD_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency declared in requirements.txt
    PYOD_AVAILABLE = False

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    SKLEARN_AVAILABLE = False

logger = logging.getLogger(__name__)


class ConformalCalibrator:
    def __init__(self):
        self.sorted_scores: Optional[np.ndarray] = None

    def fit(self, calibration_scores: np.ndarray) -> None:
        s = np.asarray(calibration_scores, dtype=float)
        self.sorted_scores = np.sort(s[np.isfinite(s)])

    @property
    def n(self) -> int:
        return 0 if self.sorted_scores is None else int(self.sorted_scores.size)

    def p_values(self, scores: np.ndarray) -> np.ndarray:
        s = np.asarray(scores, dtype=float)
        if self.n == 0:
            return np.full(s.shape, np.nan)
        n_ge = self.n - np.searchsorted(self.sorted_scores, s, side="left")
        return (1.0 + n_ge) / (self.n + 1.0)


def _stride_subsample(x: np.ndarray, max_rows: int) -> np.ndarray:
    if max_rows <= 0 or x.shape[0] <= max_rows:
        return x
    idx = np.linspace(0, x.shape[0] - 1, max_rows).round().astype(int)
    return x[idx]


class ECODDetector:
    name = "ecod"

    def __init__(self):
        self.model = None
        self.active_cols: Optional[np.ndarray] = None
        self.use_pyod_per_row = False
        self._sorted: Optional[np.ndarray] = None
        self._mu = self._c2 = self._c3 = None

    def fit(self, x: np.ndarray) -> bool:
        if not PYOD_AVAILABLE or x.shape[0] < 2:
            return False
        # Zero-variance columns make ECOD's skewness NaN, which would poison
        # every score; they carry no information, so they are excluded.
        self.active_cols = np.flatnonzero(np.nanstd(x, axis=0) > 0)
        if self.active_cols.size == 0:
            return False
        try:
            self.model = ECOD()
            self.model.fit(x[:, self.active_cols])
        except Exception:
            logger.exception("ECOD fit failed")
            self.model = None
            return False
        xt = np.asarray(self.model.X_train, dtype=float)
        self._sorted = np.sort(xt, axis=0)
        self._mu = xt.mean(axis=0)
        dev = xt - self._mu
        self._c2, self._c3 = (dev ** 2).sum(axis=0), (dev ** 3).sum(axis=0)
        self._self_check(x[:, self.active_cols])
        return True

    def _self_check(self, xa: np.ndarray) -> None:
        idx = np.unique(np.linspace(0, xa.shape[0] - 1, 5).round().astype(int))
        probe = np.vstack([xa[idx], xa[idx[:2]] + 3.0 * xa.std(axis=0)])   # include out-of-range points
        fast = self._vectorised(probe)
        ref = np.array([self.model.decision_function(probe[i:i + 1])[0] for i in range(probe.shape[0])])
        if not np.allclose(fast, ref, rtol=1e-9, atol=1e-9):
            logger.warning("Vectorised ECOD scoring disagrees with pyod (max |diff| %.3g); using per-row pyod calls.",
                           float(np.max(np.abs(fast - ref))))
            self.use_pyod_per_row = True

    def _vectorised(self, xa: np.ndarray) -> np.ndarray:
        n = self._sorted.shape[0]
        n_le = np.empty_like(xa)
        n_ge = np.empty_like(xa)
        for j in range(xa.shape[1]):
            n_le[:, j] = np.searchsorted(self._sorted[:, j], xa[:, j], side="right")
            n_ge[:, j] = n - np.searchsorted(self._sorted[:, j], xa[:, j], side="left")
        u_l = -np.log((n_le + 1.0) / (n + 1.0))
        u_r = -np.log((n_ge + 1.0) / (n + 1.0))
        # Sign of the biased sample skewness of (fit rows + this row), per column.
        d = xa - self._mu
        delta = d / (n + 1.0)
        m2 = (self._c2 + n * delta ** 2 + (d - delta) ** 2) / (n + 1.0)
        m3 = (self._c3 - 3 * delta * self._c2 - n * delta ** 3 + (d - delta) ** 3) / (n + 1.0)
        s = np.sign(m3 / m2 ** 1.5)
        u_skew = u_l * -1 * np.sign(s - 1) + u_r * np.sign(s + 1)
        return np.maximum(np.maximum(u_l, u_r), u_skew).sum(axis=1)

    def score(self, x: np.ndarray) -> np.ndarray:
        """pyod's single-row ECOD score for every row (see module docstring)."""
        xa = np.asarray(x, dtype=float)[:, self.active_cols]
        if not self.use_pyod_per_row:
            return self._vectorised(xa)
        return np.array([float(self.model.decision_function(xa[i:i + 1])[0]) for i in range(xa.shape[0])])


class IsolationForestDetector:
    name = "isolation_forest"

    def __init__(self, n_estimators: int, max_samples, random_state: int):
        self.params = dict(n_estimators=n_estimators, max_samples=max_samples, random_state=random_state)
        self.model = None

    def fit(self, x: np.ndarray) -> bool:
        if not SKLEARN_AVAILABLE or x.shape[0] < 2:
            return False
        try:
            self.model = IsolationForest(**self.params).fit(x)
            return True
        except Exception:
            logger.exception("IsolationForest fit failed")
            self.model = None
            return False

    def score(self, x: np.ndarray) -> np.ndarray:
        # Negated so that higher = more anomalous, matching ECOD.
        return -self.model.score_samples(x)



ANOMALY_SUFFIX = "_anomaly"
_DIURNAL = ("solar_hour_sin", "solar_hour_cos")


@dataclass(frozen=True)
class Relationship:
    """
    A learned cross-variable relationship, fit per DetectorPair on its own fit
    rows by least squares:  target ~ 1 + predictors + solar-hour harmonics.
    The model column is the standardized residual (observed - expected) / sd:
    how far the target is from what the OTHER variable(s) and the time of day
    imply for this station/region and season.
    """
    feature: str
    key: str
    target: str
    predictors: Tuple[str, ...]
    harmonics: int
    config_flag: str


RELATIONSHIPS = (
    # T-RH: strong in the reference data (median within-season r = -0.82;
    # RH ~ T + hour explains a median 71% of RH variance).
    Relationship("rh_given_t_residual_z", "t_rh", "humidity_pct", ("temperature_c",), 1,
                 "use_rh_temperature_residual"),
    # T-P: weak (median r = -0.26; P ~ T + hour explains a median 15%). Two
    # harmonics because pressure's daily cycle is the semi-diurnal tide. It is
    # a model column by project decision (config.use_pressure_temperature_residual),
    # accepting a measured cost on 2022 validation (normal any-flag rate 1.56%
    # vs 1.32% without it; multivariate F1 .503 vs .554) for detection of
    # pressure-context and joint T/RH/P anomalies. Its fitted strength (r2) is
    # always reported so the evidence is not presented as stronger than it is.
    Relationship("p_given_t_residual_z", "t_p", "pressure_hpa", ("temperature_c",), 2,
                 "use_pressure_temperature_residual"),
    # RH-P is intentionally absent: after removing the daily cycle the
    # reference data shows no RH-P coupling (median r = 0.01), so a residual
    # would be noise presented as a relationship.
)


def _enabled_relationships(cfg) -> List[Relationship]:
    return [r for r in RELATIONSHIPS if getattr(cfg, r.config_flag, False)]


def model_feature_names(input_names: List[str], cfg) -> List[str]:
    """
    representation "raw":              features as measured (+ optional solar-hour sin/cos)
    representation "diurnal_anomaly":  every T/P/RH/dew-point/delta feature expressed as its
        departure from THIS pair's learned diurnal expectation (harmonic
        regression on solar hour, 1st+2nd harmonics — the 2nd captures the
        semi-diurnal pressure tide). Solar hour is then already accounted for
        and is not a separate model column.
    Relationship residuals (RELATIONSHIPS) are appended when enabled and when
    their input columns exist.
    """
    has_hour = all(d in input_names for d in _DIURNAL)
    if getattr(cfg, "feature_representation", "raw") == "diurnal_anomaly" and has_hour:
        names = [n + ANOMALY_SUFFIX for n in input_names if n not in _DIURNAL]
    else:
        names = [n for n in input_names if cfg.use_diurnal_features or n not in _DIURNAL]
    for rel in _enabled_relationships(cfg):
        if has_hour and rel.target in input_names and all(p in input_names for p in rel.predictors):
            names.append(rel.feature)
    return names


def _harmonic_design(sin_h: np.ndarray, cos_h: np.ndarray, order: int = 2) -> np.ndarray:
    cols = [np.ones_like(sin_h), sin_h, cos_h]
    if order >= 2:
        cols += [2 * sin_h * cos_h, cos_h ** 2 - sin_h ** 2]
    return np.column_stack(cols)


class DetectorPair:
    """
    ECOD + Isolation Forest fit on one feature set of one station/region.

    Takes INPUT columns (features.input_feature_names) and derives the MODEL
    columns itself (model_feature_names): contextual (diurnal) deviations and
    the learned relationship residuals, all fit on the pair's own fit rows.
    Live and offline scoring both go through score(), so the transform is
    identical in both.
    """

    def __init__(self, input_names: List[str], cfg):
        self.input_names = list(input_names)
        self.feature_names = model_feature_names(self.input_names, cfg)
        self.cfg = cfg
        self.detectors = {}
        if cfg.ecod_enabled:
            self.detectors["ecod"] = ECODDetector()
        if cfg.isolation_forest_enabled:
            self.detectors["isolation_forest"] = IsolationForestDetector(
                cfg.if_n_estimators, cfg.if_max_samples, cfg.if_random_state)
        self.calibrators: Dict[str, ConformalCalibrator] = {}
        self.fitted: Dict[str, bool] = {}
        self.n_fit = 0
        self.n_cal = 0
        self._sorted_cols: Optional[np.ndarray] = None
        self._relations: Dict[str, Dict] = {}
        self._diurnal_beta: Optional[np.ndarray] = None

    # ── training ────────────────────────────────────────────────────────
    def fit(self, x_fit_in: np.ndarray, x_cal_in: np.ndarray) -> bool:
        x_fit_in = _stride_subsample(np.asarray(x_fit_in, dtype=float), self.cfg.fit_max_rows)
        # Every relationship whose inputs exist is fit — enabled ones become model
        # columns, the rest are explanation aids only (never in the decision).
        has_hour = all(d in self.input_names for d in _DIURNAL)
        for rel in RELATIONSHIPS:
            if has_hour and rel.target in self.input_names and all(p in self.input_names for p in rel.predictors):
                self._relations[rel.feature] = self._fit_relationship(rel, x_fit_in)
        if any(n.endswith(ANOMALY_SUFFIX) for n in self.feature_names):
            h = self._harmonics(x_fit_in)
            self._diurnal_beta, *_ = np.linalg.lstsq(h, x_fit_in[:, self._value_cols()], rcond=None)
        x_fit = self.transform(x_fit_in)
        x_cal = self.transform(np.asarray(x_cal_in, dtype=float))
        self.n_fit, self.n_cal = int(x_fit.shape[0]), int(x_cal.shape[0])
        for name, det in self.detectors.items():
            ok = det.fit(x_fit)
            self.fitted[name] = ok
            if ok:
                cal = ConformalCalibrator()
                cal.fit(det.score(x_cal) if x_cal.shape[0] else np.array([]))
                self.calibrators[name] = cal
        self._sorted_cols = np.sort(x_fit, axis=0)
        return self.usable

    @property
    def usable(self) -> bool:
        return any(self.fitted.get(n) and self.calibrators[n].n > 0 for n in self.detectors)

    def _relation_design(self, rel: Relationship, x_in: np.ndarray, with_predictors: bool = True) -> np.ndarray:
        h = self._harmonics(x_in, rel.harmonics)
        if not with_predictors:
            return h
        return np.column_stack([h] + [x_in[:, self.input_names.index(p)] for p in rel.predictors])

    def _fit_relationship(self, rel: Relationship, x_in: np.ndarray) -> Dict:
        y = x_in[:, self.input_names.index(rel.target)]
        a = self._relation_design(rel, x_in)
        beta, *_ = np.linalg.lstsq(a, y, rcond=None)
        resid = y - a @ beta
        a0 = self._relation_design(rel, x_in, with_predictors=False)
        beta0, *_ = np.linalg.lstsq(a0, y, rcond=None)
        var_y = float(np.var(y)) or 1e-12
        r2 = 1.0 - float(np.var(resid)) / var_y
        r2_hour = 1.0 - float(np.var(y - a0 @ beta0)) / var_y
        return {"rel": rel, "beta": beta, "sd": max(float(np.std(resid)), 1e-6),
                "r2": r2, "r2_gain_from_predictors": r2 - r2_hour}

    def _expected(self, feature: str, x_in: np.ndarray) -> np.ndarray:
        m = self._relations[feature]
        return self._relation_design(m["rel"], x_in) @ m["beta"]

    def _value_cols(self) -> List[int]:
        return [i for i, n in enumerate(self.input_names) if n not in _DIURNAL]

    def _harmonics(self, x_in: np.ndarray, order: int = 2) -> np.ndarray:
        return _harmonic_design(x_in[:, self.input_names.index(_DIURNAL[0])],
                                x_in[:, self.input_names.index(_DIURNAL[1])], order)

    def diurnal_expectation(self, x_in: np.ndarray) -> Optional[np.ndarray]:
        """Expected value of each non-diurnal input column at the row's solar hour."""
        if self._diurnal_beta is None:
            return None
        return self._harmonics(np.atleast_2d(x_in)) @ self._diurnal_beta

    def transform(self, x_in: np.ndarray) -> np.ndarray:
        """Input columns -> model columns (see model_feature_names)."""
        x_in = np.atleast_2d(np.asarray(x_in, dtype=float))
        if self._diurnal_beta is not None:
            x = x_in[:, self._value_cols()] - self.diurnal_expectation(x_in)
        else:
            keep = [self.input_names.index(n) for n in self.feature_names if n not in self._relations]
            x = x_in[:, keep]
        for feature, m in self._relations.items():
            if feature in self.feature_names:
                z = (x_in[:, self.input_names.index(m["rel"].target)] - self._expected(feature, x_in)) / m["sd"]
                x = np.column_stack([x, z])
        return x

    # ── scoring ─────────────────────────────────────────────────────────
    def score(self, x_in: np.ndarray) -> Dict[str, np.ndarray]:
        x = self.transform(x_in)
        out: Dict[str, np.ndarray] = {}
        for name, det in self.detectors.items():
            if self.fitted.get(name) and self.calibrators[name].n > 0:
                raw = det.score(x)
                out[f"{name}_score"] = raw
                out[f"{name}_p"] = self.calibrators[name].p_values(raw)
        return out

    def min_attainable_p(self) -> Optional[float]:
        ns = [c.n for c in self.calibrators.values() if c.n > 0]
        return 1.0 / (min(ns) + 1.0) if ns else None

    # ── explanation aids (never used in the decision) ───────────────────
    def feature_tails(self, x_in_row: np.ndarray) -> List[Dict[str, float]]:
        """Per-model-feature position within the fit distribution (percentile)
        and two-sided empirical tail probability — the same per-dimension
        quantity ECOD aggregates. Sorted most-extreme first."""
        x_row = self.transform(x_in_row)[0]
        n = self._sorted_cols.shape[0]
        res = []
        for j, name in enumerate(self.feature_names):
            col = self._sorted_cols[:, j]
            lo = np.searchsorted(col, x_row[j], side="left")
            hi = np.searchsorted(col, x_row[j], side="right")
            pct = 100.0 * (lo + hi) / (2.0 * n)
            tail = min((hi + 1.0) / (n + 1.0), (n - lo + 1.0) / (n + 1.0))
            res.append({"feature": name, "value": float(x_row[j]),
                        "percentile": round(float(pct), 2), "tail_probability": float(tail)})
        return sorted(res, key=lambda d: d["tail_probability"])

    def expected_by_relationship(self, key: str, x_in: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
        """(expected target values, residual sd) of relationship `key` ("t_rh"/"t_p") for input rows."""
        for feature, m in self._relations.items():
            if m["rel"].key == key:
                return self._expected(feature, np.atleast_2d(np.asarray(x_in, dtype=float))), m["sd"]
        return None

    def relationships(self, x_in_row: np.ndarray) -> Dict[str, Dict[str, float]]:
        """Per relationship: expected target value given the other variable(s)
        and time of day, the residual in sd units, and the fitted strength."""
        x = np.atleast_2d(np.asarray(x_in_row, dtype=float))
        out = {}
        for feature, m in self._relations.items():
            rel = m["rel"]
            exp = float(self._expected(feature, x)[0])
            obs = float(x[0, self.input_names.index(rel.target)])
            out[rel.key] = {"target": rel.target, "used_by_models": feature in self.feature_names,
                            "observed": round(obs, 2), "expected": round(exp, 2),
                            "residual_sd": round(m["sd"], 2), "residual_z": round((obs - exp) / m["sd"], 2),
                            "r2": round(m["r2"], 3), "r2_gain_from_predictors": round(m["r2_gain_from_predictors"], 3)}
        return out
