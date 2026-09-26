"""
Layer 3: Multivariate Consistency Engine -- ECOD + Isolation Forest.

Question answered: "Is the JOINT temperature / pressure / humidity state unusual
compared with the learned reference distribution?"  (Not: unusual vs its own
recent history -> Temporal; supported by neighbours -> Spatial; physically
impossible -> Physics; persistently drifting -> Sensor Health.)

RUNTIME FLOW
    observation
      -> DataQuality validation (only VALID channels are used; nothing imputed)
      -> pressure-convention resolution (MSL / SURFACE / UNKNOWN)
      -> city-conditioned robust normalisation (nearest reference city within
         75 km, else GLOBAL_FALLBACK)  -> [z_temperature, z_pressure_msl_equivalent, z_humidity]
      -> ECOD                 (real pyod ECOD, fitted offline)
      -> Isolation Forest     (real scikit-learn model, fitted offline)
      -> combined evidence = max(ECOD evidence, Isolation Forest evidence)

HONESTY CONTRACT
  * The models are fitted OFFLINE by backend/multivariate_training/ on the Indian
    historical dataset (pressure converted to sea-level-equivalent first) and
    loaded from backend/models/multivariate_ecod_if/. Nothing here fits at runtime.
  * `detail["method_executed"]` and `detail["detectors"]` state exactly what ran.
    A detector is reported executed=True ONLY if it produced a score for this
    reading. There is NO silent switch to another algorithm: if the models cannot
    be loaded, evaluate() raises MultivariateArtifactError, which the detector's
    guarded-layer path reports as a layer UNAVAILABLE (missing evidence, never
    "normal").
  * ECOD / Isolation Forest need ALL THREE channels AND a sea-level-comparable
    pressure. With fewer valid channels, or an UNKNOWN pressure convention, they
    are NOT executed and are reported as such, and the layer reports
    INSUFFICIENT_DATA -- never PASS. The only thing that can still contribute is
    the pressure-independent Clausius-Clapeyron rule, which is reported as a
    separate, labelled deterministic rule and never as a model.
  * APPLICABILITY: the models are only applied where a CITY baseline matches the
    station (baseline_scope == "CITY"). For GLOBAL_FALLBACK (no supported city
    within the match radius) the layer reports INSUFFICIENT_DATA with an explicit
    skip reason and runs neither detector.
  * Scores are anomaly EVIDENCE in [0, 1] calibrated on a clean chronological
    holdout. They are not probabilities.
"""
import json
import os
import threading
import warnings
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np

from engine import multivariate_features as mf
from schema import AWSReading, DataQuality, ObservationSource

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ARTIFACT_DIR = os.path.join(BACKEND_DIR, "models", "multivariate_ecod_if")
STRICT_ENV = "ATHER_MULTIVARIATE_STRICT"
_REQUIRED_FILES = ("baselines.json", "model_card.json", "ecod.joblib", "isolation_forest.joblib")

# Clausius-Clapeyron rule: T > 32 C together with RH > 95 % is exceptionally rare
# in continental climates. It is pressure-independent, pre-dates the trained
# models, and is kept as an explicitly-reported deterministic rule -- not as a
# model and not as part of the ECOD/Isolation Forest claim.
CC_TEMP_C = 32.0
CC_RH_PCT = 95.0
CC_SCORE = 0.85

_CHANNEL_OF_FEATURE = ("temperature_c", "pressure_hpa", "humidity_pct")


class MultivariateArtifactError(RuntimeError):
    """Raised when the fitted ECOD / Isolation Forest artifacts cannot be loaded."""


class _Artifacts:
    def __init__(self, baselines: mf.BaselineSet, card: Dict[str, Any], ecod, iforest, directory: str):
        self.baselines = baselines
        self.card = card
        self.ecod = ecod
        self.iforest = iforest
        self.directory = directory
        cal = card["calibration"]["detectors"]
        self.anchors = {
            "ecod": {k: cal["ecod"][k] for k in ("center", "threshold", "extreme")},
            "isolation_forest": {k: cal["isolation_forest"][k] for k in ("center", "threshold", "extreme")},
        }
        self.model_version = card.get("model_version")


def load_artifacts(directory: str = DEFAULT_ARTIFACT_DIR) -> _Artifacts:
    """Load the fitted models + baselines. Raises MultivariateArtifactError with a
    clear message if anything required is missing or unreadable."""
    missing = [f for f in _REQUIRED_FILES if not os.path.isfile(os.path.join(directory, f))]
    if missing:
        raise MultivariateArtifactError(
            f"Multivariate model artifacts missing in {directory}: {', '.join(missing)}. "
            f"Run backend/multivariate_training/ to (re)build them. ECOD/Isolation Forest will "
            f"NOT be reported as executed and no substitute algorithm is used.")
    try:
        doc = json.load(open(os.path.join(directory, "baselines.json")))
        card = json.load(open(os.path.join(directory, "model_card.json")))
        ecod = joblib.load(os.path.join(directory, "ecod.joblib"))
        iforest = joblib.load(os.path.join(directory, "isolation_forest.joblib"))
        baselines = mf.BaselineSet.from_artifact(doc)
    except Exception as e:  # corrupt / incompatible artifact
        raise MultivariateArtifactError(f"Multivariate artifacts in {directory} could not be loaded: {e}") from e

    # A pickled model from a different library version can load yet misbehave.
    import pyod
    import sklearn
    want = card.get("libraries", {})
    for name, have in (("pyod", pyod.__version__), ("scikit_learn", sklearn.__version__)):
        w = want.get(name)
        if w and w.split(".")[:2] != have.split(".")[:2]:
            warnings.warn(f"Multivariate model was trained with {name} {w} but {have} is installed; "
                          f"inference may differ. Re-run backend/multivariate_training/.")
    return _Artifacts(baselines, card, ecod, iforest, directory)


def resolve_pressure_convention(reading: AWSReading) -> Tuple[str, str]:
    """(convention, basis).

    Only a convention DECLARED on the reading counts. It is never inferred from
    the source name (an Open-Meteo reading can fall back from pressure_msl to
    surface_pressure, so "NWP" does not imply MSL) and never from the pressure's
    magnitude. Anything undeclared is UNKNOWN.
    """
    declared = getattr(reading, "pressure_convention", None)
    if declared in (mf.PRESSURE_MSL, mf.PRESSURE_SURFACE, mf.PRESSURE_UNKNOWN):
        return declared, "declared_on_reading"
    return mf.PRESSURE_UNKNOWN, "not_declared"


class MultivariateConsistencyLayer:
    """Joint T/P/RH consistency via ECOD + Isolation Forest (see module docstring)."""

    def __init__(self, artifact_dir: Optional[str] = None, strict: Optional[bool] = None):
        self.artifact_dir = artifact_dir or DEFAULT_ARTIFACT_DIR
        if strict is None:
            strict = os.environ.get(STRICT_ENV, "").strip().lower() in ("1", "true", "yes")
        self.artifacts: Optional[_Artifacts] = None
        self.load_error: Optional[str] = None
        # PyOD's ECOD.decision_function mutates scratch arrays on the shared model
        # object, so concurrent API requests must not call it at the same time.
        self._ecod_lock = threading.Lock()
        try:
            self.artifacts = load_artifacts(self.artifact_dir)
        except MultivariateArtifactError as e:
            if strict:
                raise
            self.load_error = str(e)
            print(f"WARNING: {self.load_error}")

    # ── public ───────────────────────────────────────────────────────────
    def evaluate(self, reading: AWSReading) -> Tuple[float, Optional[str], Dict[str, Any]]:
        """Returns (anomaly_score in [0, 1], reason, detail)."""
        t = reading.temperature_c if reading.channel_valid("temperature_c") else None
        p = reading.pressure_hpa if reading.channel_valid("pressure_hpa") else None
        rh = reading.humidity_pct if reading.channel_valid("humidity_pct") else None
        valid = [(k, v) for k, v in (("T", t), ("P", p), ("RH", rh)) if v is not None]
        n_valid = len(valid)

        detail: Dict[str, Any] = {
            "valid_channels": [k for k, _ in valid],
            "n_valid": n_valid,
            # Same real count under the name the canonical card reads.
            "valid_channel_count": n_valid,
            "pressure_source_convention": mf.DATASET_PRESSURE_CONVENTION,
            "pressure_normalization_method": mf.PRESSURE_NORMALIZATION_METHOD,
            "detectors": self._detectors_off("not evaluated"),
            "method_executed": None,
            "baseline_scope": None,
            "baseline_city": None,
            "baseline_distance_km": None,
            # combined_score = the ECOD/Isolation Forest combination ONLY (None when
            # no detector ran). final_score = the layer's score, i.e. the maximum of
            # that combination and any deterministic rule. They differ exactly when a
            # rule, not a model, produced the evidence.
            "combined_score": None,
            "final_score": None,
            # What produced the score ("ecod", "isolation_forest", "ecod+isolation_forest",
            # "rule:clausius_clapeyron") or None when nothing did. Always present.
            "score_driver": None,
        }
        # The pressure convention is reported on EVERY path (including insufficient
        # channels) so a consumer never has to guess it.
        convention, basis = resolve_pressure_convention(reading)
        detail["pressure_convention"] = convention
        detail["pressure_convention_basis"] = basis
        rule = self._clausius_clapeyron(t, rh)
        detail["rules"] = {"clausius_clapeyron": rule}

        if n_valid < 2:
            detail["status"] = "INSUFFICIENT_DATA"
            detail["note"] = (f"Only {n_valid} valid channel(s). Multivariate analysis requires "
                              f"≥ 2 valid channels; ECOD and Isolation Forest need all 3.")
            detail["detectors"] = self._detectors_off("fewer than 3 valid channels")
            detail["method"] = None
            return 0.0, None, detail

        if n_valid == 3:
            return self._evaluate_joint(reading, t, p, rh, detail, rule)
        return self._evaluate_two_channel(reading, t, p, rh, detail, rule)

    # ── 3 valid channels: ECOD + Isolation Forest ────────────────────────
    def _evaluate_joint(self, reading, t, p, rh, detail, rule):
        convention = detail["pressure_convention"]

        p_msl: Optional[float] = None
        not_comparable: Optional[str] = None
        if convention == mf.PRESSURE_MSL:
            p_msl = float(p)
        elif convention == mf.PRESSURE_SURFACE:
            elev = reading.elevation_m
            if elev is not None and elev > 0:
                p_msl = mf.surface_to_msl_equivalent(float(p), float(t), float(elev))
                detail["pressure_conversion"] = {
                    "applied": True, "elevation_m": float(elev),
                    "elevation_source": "supplied with the reading (not inferred)"}
            else:
                not_comparable = ("Pressure is SURFACE pressure but no authoritative station elevation was "
                                  "supplied, so it cannot be converted to sea level; no elevation is invented.")
        else:
            not_comparable = ("Pressure convention unavailable (UNKNOWN): the observation does not declare whether its "
                              "pressure is sea-level (MSL) or station (SURFACE), so it cannot be compared with the "
                              "sea-level-equivalent reference; it is not assumed to be MSL.")

        if p_msl is None:
            return self._joint_not_executed(detail, rule, not_comparable)

        if self.artifacts is None:
            raise MultivariateArtifactError(self.load_error or "Multivariate artifacts are not loaded.")

        a = self.artifacts
        baseline, dist_km = a.baselines.resolve(reading.lat, reading.lon)

        # SCOPE GATE. The models were trained on the Indian historical dataset and are
        # only valid where a city-conditioned baseline exists. The pooled GLOBAL_FALLBACK
        # baseline mixes Indian climates and is NOT a reference for stations elsewhere
        # (ordinary non-Indian weather scored as anomalous against it), so it is not used
        # to produce evidence: the layer reports "not assessed" -- never PASS.
        if baseline.scope != mf.SCOPE_CITY:
            detail["baseline_scope"] = baseline.scope
            return self._joint_not_executed(detail, rule, (
                f"Multivariate not assessed: no supported city baseline within {mf.MAX_CITY_MATCH_KM:g} km of this "
                f"station (baseline_scope={baseline.scope}). ECOD and Isolation Forest were trained on the Indian "
                f"historical dataset and are only applied where a matching city baseline exists; the pooled "
                f"fallback baseline is not used to score stations outside that scope."))

        x = mf.feature_vector(float(t), float(p_msl), float(rh), baseline).reshape(1, -1)
        if not np.isfinite(x).all():
            return self._joint_not_executed(detail, rule, "Non-finite normalised feature; models were not run.")

        with self._ecod_lock:
            ecod_raw = float(a.ecod.decision_function(x)[0])
        if_raw = float(-a.iforest.score_samples(x)[0])
        ecod_ev = float(mf.evidence_from_raw(ecod_raw, **a.anchors["ecod"]))
        if_ev = float(mf.evidence_from_raw(if_raw, **a.anchors["isolation_forest"]))
        combined = max(ecod_ev, if_ev)

        rule_score = rule["score"] if rule["triggered"] else 0.0
        final = max(combined, rule_score)
        # What actually produced the score. Nothing did when the score is 0, and an
        # exact tie is reported as a tie rather than arbitrarily credited to ECOD.
        if final <= 0.0:
            driver = None
        elif rule_score > combined:
            driver = "rule:clausius_clapeyron"
        elif ecod_ev > if_ev:
            driver = "ecod"
        elif if_ev > ecod_ev:
            driver = "isolation_forest"
        else:
            driver = "ecod+isolation_forest"
        z = x[0]
        dominant = _CHANNEL_OF_FEATURE[int(np.argmax(np.abs(z)))]

        detail.update({
            "status": "EVALUATED",
            "method_executed": "ECOD+IsolationForest",
            "method": "ECOD+IsolationForest",
            "baseline_scope": baseline.scope,
            "baseline_city": baseline.name,
            "baseline_distance_km": dist_km,
            "climatological_elevation_proxy": baseline.climatological_elevation_proxy,
            "feature_names": list(mf.FEATURE_NAMES),
            "features": {n: round(float(v), 4) for n, v in zip(mf.FEATURE_NAMES, z)},
            "pressure_msl_equivalent_hpa": round(float(p_msl), 2),
            "dominant_channel": dominant,
            "detectors": {
                "ecod": {
                    "executed": True, "raw_score": round(ecod_raw, 4), "evidence_score": round(ecod_ev, 4),
                    "threshold": round(a.anchors["ecod"]["threshold"], 4),
                    "center": round(a.anchors["ecod"]["center"], 4),
                    "extreme": round(a.anchors["ecod"]["extreme"], 4),
                    "library": "pyod.ECOD"},
                "isolation_forest": {
                    "executed": True, "raw_score": round(if_raw, 4), "evidence_score": round(if_ev, 4),
                    "threshold": round(a.anchors["isolation_forest"]["threshold"], 4),
                    "center": round(a.anchors["isolation_forest"]["center"], 4),
                    "extreme": round(a.anchors["isolation_forest"]["extreme"], 4),
                    "library": "sklearn.IsolationForest"},
            },
            "combined_score": round(combined, 4),
            "final_score": round(final, 4),
            "combination": "max(ecod_evidence, isolation_forest_evidence)",
            "score_driver": driver,
            "evidence_is_probability": False,
            "model_version": a.model_version,
            "reference_period": a.card.get("train_period"),
            "calibration_period": a.card.get("calibration_period"),
        })
        reasons: List[str] = []
        if rule["triggered"]:
            reasons.append(rule["reason"])
        if combined >= 0.5:
            scope = f"{baseline.name} reference" if baseline.scope == mf.SCOPE_CITY else "global fallback reference"
            reasons.append(
                f"Joint (T={t:.1f}°C, P={p:.1f} hPa, RH={rh:.1f}%) is statistically unusual relative to the "
                f"{scope} (ECOD evidence {ecod_ev:.2f}, Isolation Forest evidence {if_ev:.2f}; "
                f"dominant channel {dominant})")
        return final, ("; ".join(reasons) if reasons else None), detail

    def _joint_not_executed(self, detail, rule, why: str):
        """3 valid channels but ECOD/IF cannot run (pressure not comparable). The
        pressure-independent rule may still supply evidence; otherwise the layer
        reports INSUFFICIENT_DATA -- never PASS."""
        detail["detectors"] = self._detectors_off(why)
        detail["skip_reason"] = why
        if rule["triggered"]:
            # No model ran, so there is NO ECOD/Isolation Forest combination:
            # combined_score stays None and the rule evidence is reported only as
            # the rule score / final_score / score_driver.
            detail.update({"status": "EVALUATED", "method_executed": "RULE_ONLY:CLAUSIUS_CLAPEYRON",
                           "method": "RULE_ONLY:CLAUSIUS_CLAPEYRON",
                           "combined_score": None, "final_score": rule["score"],
                           "score_driver": "rule:clausius_clapeyron", "note": why})
            return rule["score"], rule["reason"], detail
        detail.update({"status": "INSUFFICIENT_DATA", "method": None, "note": why})
        return 0.0, None, detail

    # ── fewer than 3 valid channels: models cannot run ──────────────────
    def _evaluate_two_channel(self, reading, t, p, rh, detail, rule):
        """Exactly 2 valid channels. ECOD and Isolation Forest were fitted on the
        joint (T, P, RH) state and need all three, and no channel is ever imputed,
        so neither runs. The layer reports INSUFFICIENT_DATA (never PASS); only the
        pressure-independent Clausius-Clapeyron rule can still contribute.

        (A legacy 2-channel "bivariate" check used to live here; its lookup key was
        built with sorted channel names but the table was keyed in a different
        order, so it never matched and every 2-channel reading silently returned
        EVALUATED with score 0. It has been removed rather than kept as a dead
        code path that reported a check that never ran.)"""
        why = "ECOD and Isolation Forest require all 3 valid channels (temperature, pressure, humidity); no channel is imputed."
        return self._joint_not_executed(detail, rule, why)

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _detectors_off(why: str) -> Dict[str, Any]:
        off = {"executed": False, "raw_score": None, "evidence_score": None, "threshold": None, "skip_reason": why}
        return {"ecod": dict(off, library="pyod.ECOD"), "isolation_forest": dict(off, library="sklearn.IsolationForest")}

    @staticmethod
    def _clausius_clapeyron(t: Optional[float], rh: Optional[float]) -> Dict[str, Any]:
        if t is None or rh is None:
            return {"executed": False, "triggered": False, "score": 0.0}
        hit = t > CC_TEMP_C and rh > CC_RH_PCT
        out = {"executed": True, "triggered": bool(hit), "score": CC_SCORE if hit else 0.0,
               "note": f"T > {CC_TEMP_C:g}°C with RH > {CC_RH_PCT:g}% is rare in continental climates; "
                       f"deterministic, pressure-independent rule (not ECOD/Isolation Forest)."}
        if hit:
            out["reason"] = (f"Rare joint state: {t:.1f}°C with {rh:.1f}% RH "
                             f"(extreme vapor saturation at high temperature)")
        return out
