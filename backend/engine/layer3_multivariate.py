"""
Layer 3: Multivariate Consistency Engine (v2).

BUG FIX (v2):
  - REMOVED silent mean-imputation of missing channels.
  - Only evaluates channels with DataQuality == VALID.
  - If < 2 channels are VALID, returns score=0.0 and status=INSUFFICIENT_DATA.
  - Explains exactly which check was performed (1D, 2D bivariate, or 3D manifold).
  - ECOD/Mahalanobis only runs when all 3 channels are valid.
  - 2-channel checks use targeted bivariate consistency rules.

Checks available by channel coverage:
  - 3 channels VALID  → Full ECOD + Clausius-Clapeyron
  - 2 channels VALID  → Bivariate targeted rule (T+RH, T+P, or P+RH)
  - 1 channel VALID   → Univariate range check only (returns INSUFFICIENT_DATA for multivariate)
  - 0 channels VALID  → INSUFFICIENT_DATA, score=0.0
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

try:
    from pyod.models.ecod import ECOD
    PYOD_AVAILABLE = True
except ImportError:
    PYOD_AVAILABLE = False

from schema import AWSReading, DataQuality


class MultivariateConsistencyLayer:
    """
    Evaluates whether the available (T, P, RH) readings are mutually consistent.
    Only uses VALID channel readings — never imputes missing values.
    """
    def __init__(self, contamination: float = 0.01):
        self.contamination = contamination
        self.detector = ECOD(contamination=contamination) if PYOD_AVAILABLE else None
        self.is_fitted = False
        self.calibrated_threshold = 0.75

        # Normalization parameters for the full 3D case
        self.means_3d = np.array([18.0, 1012.0, 65.0])
        self.stds_3d  = np.array([10.0,   15.0, 20.0])

        # Bivariate normalization: [T+RH], [T+P], [P+RH]
        self.bivar_params = {
            ("temperature_c", "humidity_pct"): (np.array([18.0, 65.0]), np.array([10.0, 20.0])),
            ("temperature_c", "pressure_hpa"): (np.array([18.0, 1012.0]), np.array([10.0, 15.0])),
            ("pressure_hpa",  "humidity_pct"): (np.array([1012.0, 65.0]), np.array([15.0, 20.0])),
        }

    def evaluate(self, reading: AWSReading) -> Tuple[float, Optional[str], Dict[str, Any]]:
        """
        Evaluates joint reading consistency.
        Returns (anomaly_score [0, 1], reason, detail_dict).
        """
        detail: Dict[str, Any] = {}

        t  = reading.temperature_c  if reading.channel_valid("temperature_c") else None
        p  = reading.pressure_hpa   if reading.channel_valid("pressure_hpa")  else None
        rh = reading.humidity_pct   if reading.channel_valid("humidity_pct")  else None

        valid_channels = [ch for ch, v in [("T", t), ("P", p), ("RH", rh)] if v is not None]
        n_valid = len(valid_channels)

        detail["valid_channels"] = valid_channels
        detail["n_valid"] = n_valid

        # ── Insufficient data ──────────────────────────────────────────────
        if n_valid == 0:
            detail["status"] = "INSUFFICIENT_DATA"
            detail["note"] = "No valid sensor channels available for multivariate analysis."
            return 0.0, None, detail

        if n_valid == 1:
            detail["status"] = "INSUFFICIENT_DATA"
            detail["note"] = f"Only 1 valid channel ({valid_channels[0]}). Multivariate analysis requires ≥ 2 channels."
            return 0.0, None, detail

        reasons: List[str] = []
        scores:  List[float] = []

        # ── Clausius-Clapeyron physical cross-variable constraint ──────────
        # At high temperatures (> 32°C), > 95% RH is exceptionally rare in most continental regions
        if t is not None and rh is not None:
            if t > 32.0 and rh > 95.0:
                score = 0.85
                scores.append(score)
                reasons.append(
                    f"Rare joint state: {t:.1f}°C with {rh:.1f}% RH "
                    f"(extreme vapor saturation at high temperature)"
                )
                detail["clausius_clapeyron"] = {
                    "temperature_c": t, "humidity_pct": rh,
                    "note": "T > 32°C with RH > 95% is rare in continental climates",
                    "score": score
                }

        # ── Full 3D ECOD / Euclidean check ────────────────────────────────
        if n_valid == 3:
            detail["method"] = "3D_ECOD_manifold" if (self.is_fitted and PYOD_AVAILABLE) else "3D_Euclidean"
            x = np.array([[t, p, rh]])
            x_scaled = (x - self.means_3d) / self.stds_3d

            if self.is_fitted and self.detector is not None:
                try:
                    raw_score  = float(self.detector.decision_function(x_scaled)[0])
                    norm_score = max(0.0, min(1.0, raw_score / (self.calibrated_threshold * 1.4)))
                    if norm_score > 0.65:
                        scores.append(norm_score)
                        reasons.append(
                            f"Joint (T={t:.1f}°C, P={p:.1f} hPa, RH={rh:.1f}%) is an outlier "
                            f"relative to historical distribution (ECOD score={norm_score:.2f})"
                        )
                    detail["ecod"] = {"raw_score": round(raw_score, 4), "norm_score": round(norm_score, 4)}
                except Exception:
                    # Fallback to Euclidean distance
                    dist = float(np.linalg.norm(x_scaled))
                    nd_score = min(1.0, max(0.0, (dist - 2.5) / 2.5))
                    if nd_score > 0.65:
                        scores.append(nd_score)
                        reasons.append(
                            f"Joint (T, P, RH) state is {dist:.1f}σ from expected distribution "
                            f"(Euclidean fallback)"
                        )
                    detail["euclidean_fallback"] = {"distance_sigma": round(dist, 3), "score": round(nd_score, 4)}
            else:
                dist = float(np.linalg.norm(x_scaled))
                nd_score = min(1.0, max(0.0, (dist - 2.5) / 2.5))
                if nd_score > 0.65:
                    scores.append(nd_score)
                    reasons.append(
                        f"Joint (T={t:.1f}°C, P={p:.1f} hPa, RH={rh:.1f}%) is {dist:.1f}σ "
                        f"from expected atmospheric distribution"
                    )
                detail["euclidean"] = {"distance_sigma": round(dist, 3), "score": round(nd_score, 4)}

        # ── 2-channel bivariate checks ─────────────────────────────────────
        elif n_valid == 2:
            # Determine which pair we have
            pair_vals = {}
            if t  is not None: pair_vals["temperature_c"] = t
            if p  is not None: pair_vals["pressure_hpa"]  = p
            if rh is not None: pair_vals["humidity_pct"]  = rh

            pair_key = tuple(sorted(pair_vals.keys()))
            if pair_key in self.bivar_params:
                means, stds = self.bivar_params[pair_key]
                vals_arr    = np.array([pair_vals[k] for k in pair_key])
                scaled      = (vals_arr - means) / stds
                dist_2d     = float(np.linalg.norm(scaled))
                bi_score    = min(1.0, max(0.0, (dist_2d - 2.0) / 2.5))

                detail["method"]    = f"2D_bivariate({','.join(pair_key)})"
                detail["distance"]  = round(dist_2d, 3)
                detail["bi_score"]  = round(bi_score, 4)

                if bi_score > 0.65:
                    scores.append(bi_score)
                    pair_str = f"{pair_key[0].split('_')[0].upper()}={vals_arr[0]:.1f}, " \
                               f"{pair_key[1].split('_')[0].upper()}={vals_arr[1]:.1f}"
                    reasons.append(
                        f"Bivariate ({pair_str}) joint state is unusual ({dist_2d:.1f}σ from expected)"
                    )
            else:
                detail["method"] = "2D_no_matching_bivariate_rule"

        final_score = max(scores) if scores else 0.0
        detail["status"] = "EVALUATED"

        reason_str = "; ".join(reasons) if reasons else None
        return final_score, reason_str, detail

    def fit(self, records: list):
        """
        Optional: fit ECOD model on a list of clean (T, P, RH) triples.
        Only used when all three channels are valid for all records.
        """
        if not PYOD_AVAILABLE:
            return
        try:
            features = np.array(records)
            if features.ndim == 2 and features.shape[1] == 3 and len(features) > 20:
                self.means_3d = np.mean(features, axis=0)
                self.stds_3d  = np.std(features, axis=0) + 1e-6
                scaled        = (features - self.means_3d) / self.stds_3d
                self.detector.fit(scaled)
                self.is_fitted = True
                self.calibrated_threshold = float(np.percentile(self.detector.decision_scores_, 99.5))
        except Exception:
            pass
