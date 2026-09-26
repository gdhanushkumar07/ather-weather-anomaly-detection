"""
Layer 3: Multivariate Intelligence — ATHER pipeline entry point (v4).

RESPONSIBILITY (vs the other layers)
  Layer 1  hard physical limits / thermodynamic impossibility
  Layer 2  temporal behaviour of each channel (spikes, drift, frozen)
  Layer 3  whether the JOINT state of T, P, RH (+ dew point, joint rates of
           change, time of day) is unusual for THIS station/region and
           season, even when every value is individually plausible.

FLOW (3 valid channels)
    AWSReading -> Observation (observation time, T, P, RH, longitude)
      -> multivariate.online.OnlineMultivariateEngine.score()
           features -> model choice (station's own history, else the nearest
           regional historical reference for the same season)
           -> ECOD + Isolation Forest -> conformal p-values
           -> explicit decision (multivariate/decision.py):
              both flag = ANOMALY (HIGH), one flags = SUSPICIOUS (LOW), else NORMAL
      -> physical joint-state rule (Clausius-Clapeyron heuristic)
      -> trust gate -> commit(): only trusted observations become training data

  No model available (station far from any reference site AND fewer than
  min_train_samples trusted observations), or no verified observation time
  (season/time of day unknowable — "now" is never assumed): a static
  climatological-prior distance check is used and reported as such — never
  presented as a trained-model verdict, and the reading is not learned.

  2 valid channels: targeted bivariate rule (unchanged from v2).
  0-1 valid channels: INSUFFICIENT_DATA.

The public contract used by app/anomaly/detector.py is unchanged:
    evaluate(reading, upstream_suspect=False) -> (score [0,1], reason|None, detail)
`upstream_suspect` (new, optional) lets the pipeline withhold observations
that Layer 1/2 already found suspicious from Layer 3's training history.

See backend/multivariate/README.md for datasets, validation and limitations.
"""
import logging
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import CONFIG, MultivariateThresholds
from schema import AWSReading
from multivariate.decision import NORMAL
from multivariate.features import Observation
from multivariate.models import PYOD_AVAILABLE, SKLEARN_AVAILABLE
from multivariate.online import OnlineMultivariateEngine
from multivariate.reference import ReferenceLibrary

logger = logging.getLogger(__name__)


def _is_finite(x: Optional[float]) -> bool:
    """True only for a real, finite float — guards against NaN/Inf reaching the models."""
    return x is not None and np.isfinite(x)


class MultivariateConsistencyLayer:
    def __init__(self, config: MultivariateThresholds = CONFIG.multivariate,
                 reference: Optional[ReferenceLibrary] = None):
        self.cfg = config
        if reference is None and config.reference_enabled:
            reference = ReferenceLibrary(config)
        self.engine = OnlineMultivariateEngine(config, reference)

        # Static priors — used ONLY when no learned model exists for a station.
        self.means_3d = np.array([18.0, 1012.0, 65.0])
        self.stds_3d = np.array([10.0, 15.0, 20.0])
        self.bivar_params = {
            ("humidity_pct", "temperature_c"): (np.array([65.0, 18.0]), np.array([20.0, 10.0])),
            ("pressure_hpa", "temperature_c"): (np.array([1012.0, 18.0]), np.array([15.0, 10.0])),
            ("humidity_pct", "pressure_hpa"): (np.array([65.0, 1012.0]), np.array([20.0, 15.0])),
        }
        if not PYOD_AVAILABLE:
            logger.warning("pyod is not installed — ECOD disabled; Layer 3 decisions degrade to SUSPICIOUS at most.")
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn is not installed — Isolation Forest disabled.")

    @property
    def states(self):
        return self.engine.states

    def evaluate(self, reading: AWSReading, upstream_suspect: bool = False) -> Tuple[float, Optional[str], Dict[str, Any]]:
        detail: Dict[str, Any] = {}
        t = reading.temperature_c if (reading.channel_valid("temperature_c") and _is_finite(reading.temperature_c)) else None
        p = reading.pressure_hpa if (reading.channel_valid("pressure_hpa") and _is_finite(reading.pressure_hpa)) else None
        rh = reading.humidity_pct if (reading.channel_valid("humidity_pct") and _is_finite(reading.humidity_pct)) else None

        valid_channels = [ch for ch, v in [("T", t), ("P", p), ("RH", rh)] if v is not None]
        n_valid = len(valid_channels)
        detail["valid_channels"] = valid_channels
        detail["n_valid"] = n_valid
        # Read by detector.py for fusion coverage weighting and the Layer 3 card.
        detail["valid_channel_count"] = n_valid
        detail["layer"] = "multivariate"

        if n_valid < 2:
            detail["status"] = "INSUFFICIENT_DATA"
            detail["note"] = ("No valid sensor channels available for multivariate analysis." if n_valid == 0 else
                              f"Only 1 valid channel ({valid_channels[0]}). Multivariate analysis requires >= 2 channels.")
            return 0.0, None, detail

        reasons: List[str] = []
        scores: List[float] = []
        rule_flag = False

        # ── Physical joint-state rule ──────────────────────────────────────
        if t is not None and rh is not None and t > self.cfg.clausius_clapeyron_temp_c and rh > self.cfg.clausius_clapeyron_rh_pct:
            rule_flag = True
            scores.append(self.cfg.clausius_clapeyron_score)
            reasons.append(f"Rare joint state: {t:.1f}°C with {rh:.1f}% RH (extreme vapor saturation at high temperature)")
            detail["clausius_clapeyron"] = {
                "temperature_c": t, "humidity_pct": rh, "score": self.cfg.clausius_clapeyron_score,
                "note": f"T > {self.cfg.clausius_clapeyron_temp_c}°C with RH > {self.cfg.clausius_clapeyron_rh_pct}% "
                        f"implies a dew point above ~31°C",
            }

        if n_valid == 3:
            score, reason, ml = self._evaluate_three_channel(reading, t, p, rh, upstream_suspect or rule_flag)
            detail.update(ml)
            if score is not None:
                scores.append(score)
            if reason:
                reasons.append(reason)
        else:
            self._evaluate_bivariate(t, p, rh, detail, scores, reasons)

        final_score = max(scores) if scores else 0.0
        detail["status"] = "EVALUATED"
        detail["anomaly"] = bool(final_score >= 0.80)
        reason_str = "; ".join(reasons) if reasons else None
        detail["reason"] = reason_str
        return float(final_score), reason_str, detail

    # ── 3 channels ──────────────────────────────────────────────────────
    def _evaluate_three_channel(self, reading: AWSReading, t: float, p: float, rh: float,
                                suspect: bool) -> Tuple[Optional[float], Optional[str], Dict[str, Any]]:
        if reading.observation_timestamp is None:
            # The learned models are conditioned on season and time of day and use
            # rates of change between observations; with no verified observation
            # time (e.g. the static stations.json snapshot, freshness UNKNOWN) none
            # of that can be computed honestly, and the reading must not become
            # training data either.
            score, reason, d = self._static_fallback(t, p, rh)
            d["status_ml"] = "OBSERVATION_TIME_UNKNOWN"
            d["note"] = ("Observation time not verified — season/time-of-day-conditioned ECOD/Isolation Forest "
                         "models are not applicable; generic static prior used and the reading is not learned.")
            d["trusted_for_update"] = False
            return score, reason, d

        obs_time = reading.observation_timestamp
        if obs_time.tzinfo is None:
            # Naive times in ATHER come from Open-Meteo `current.time`, which is UTC by default.
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        obs = Observation(time_utc=obs_time, temperature_c=t, pressure_hpa=p, humidity_pct=rh,
                          longitude=float(reading.lon or 0.0))

        res = self.engine.score(reading.station_id, obs, lat=float(reading.lat or 0.0), lon=float(reading.lon or 0.0))
        feats_raw = res.pop("_features_raw")

        if res["status_ml"] == "EVALUATED":
            d: Dict[str, Any] = dict(res)
            dec = res["decision"]
            d["method"] = "ECOD_IsolationForest"
            d["test_performed"] = f"ECOD+IsolationForest ({res['model_source']}, {res['feature_set']} features)"
            d["layer3_anomaly"] = dec["layer3_anomaly"]
            d["confidence"] = dec["confidence"]
            d["ecod_score"] = res["ecod"]["score"]
            d["isolation_forest_score"] = res["isolation_forest"]["score"]
            normal = dec["status"] == NORMAL
            score = dec["layer_score"]
            reason = res["reason"]
        else:
            score, reason, d = self._static_fallback(t, p, rh)
            d.update(res)
            d["status_ml"] = "INSUFFICIENT_TRAINING_DATA"
            d["training_samples"] = res["station_trusted_history"]
            d["note"] = (f"No regional reference site within {self.cfg.reference_max_distance_km:.0f} km and "
                         f"{res['station_trusted_history']}/{self.cfg.min_train_samples} trusted observations of "
                         f"this station's own history — ECOD/Isolation Forest not applied; generic static prior used.")
            normal = score is None

        self.engine.commit(reading.station_id, obs, dict(res, _features_raw=feats_raw),
                           trusted=normal and not suspect)
        d["trusted_for_update"] = bool(normal and not suspect and not res["duplicate_observation"])
        d["upstream_suspect"] = bool(suspect)
        return score, reason, d

    def _static_fallback(self, t: float, p: float, rh: float) -> Tuple[Optional[float], Optional[str], Dict[str, Any]]:
        """Generic static-prior distance — never presented as a trained-model verdict."""
        dist = float(np.linalg.norm((np.array([t, p, rh]) - self.means_3d) / self.stds_3d))
        nd_score = min(1.0, max(0.0, (dist - 2.5) / 2.5))
        d = {"method": "3D_static_prior_fallback",
             "test_performed": "3D static climatological prior (no applicable trained model)",
             "layer3_anomaly": False, "confidence": "INSUFFICIENT_DATA",
             "euclidean_fallback": {"distance_sigma": round(dist, 3), "score": round(nd_score, 4)}}
        if nd_score <= 0.65:
            return None, None, d
        return nd_score, (f"Joint (T={t:.1f}°C, P={p:.1f} hPa, RH={rh:.1f}%) is {dist:.1f}σ from a generic "
                          f"climatological prior (provisional — no applicable station/regional model)"), d

    # ── 2 channels ──────────────────────────────────────────────────────
    def _evaluate_bivariate(self, t, p, rh, detail, scores, reasons) -> None:
        pair_vals = {k: v for k, v in (("temperature_c", t), ("pressure_hpa", p), ("humidity_pct", rh)) if v is not None}
        pair_key = tuple(sorted(pair_vals))
        if pair_key not in self.bivar_params:
            detail["method"] = "2D_no_matching_bivariate_rule"
            return
        means, stds = self.bivar_params[pair_key]
        vals = np.array([pair_vals[k] for k in pair_key])
        dist_2d = float(np.linalg.norm((vals - means) / stds))
        bi_score = min(1.0, max(0.0, (dist_2d - 2.0) / 2.5))
        detail["method"] = f"2D_bivariate({','.join(pair_key)})"
        detail["test_performed"] = "bivariate static prior (2 valid channels)"
        detail["distance"] = round(dist_2d, 3)
        detail["bi_score"] = round(bi_score, 4)
        if bi_score > 0.65:
            scores.append(bi_score)
            pair_str = (f"{pair_key[0].split('_')[0].upper()}={vals[0]:.1f}, "
                        f"{pair_key[1].split('_')[0].upper()}={vals[1]:.1f}")
            reasons.append(f"Bivariate ({pair_str}) joint state is unusual ({dist_2d:.1f}σ from expected)")

    def fit(self, records: list) -> None:
        """Legacy entry point: recalibrate the static 3-D fallback prior from clean (T, P, RH) triples."""
        try:
            features = np.array(records, dtype=float)
            if features.ndim == 2 and features.shape[1] == 3 and len(features) > 20:
                self.means_3d = np.mean(features, axis=0)
                self.stds_3d = np.std(features, axis=0) + 1e-6
        except Exception:
            logger.exception("MultivariateConsistencyLayer.fit() failed; static prior left unchanged.")
