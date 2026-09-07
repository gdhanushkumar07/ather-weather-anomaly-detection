"""
Layer 3: Multivariate Consistency Engine.
Combines thermodynamic cross-variable relationships with PyOD multivariate outlier detectors
(ECOD: Empirical Cumulative Distribution Functions for Outlier Detection & Isolation Forest).
Validates joint (Temperature, Pressure, Relative Humidity) state manifolds.
"""
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from pyod.models.ecod import ECOD
from pyod.models.iforest import IForest

from ather.data.schema import AWSReading

class MultivariateConsistencyLayer:
    """
    Evaluates whether (T, P, RH) triple is mutually consistent with clean atmospheric manifolds.
    """
    def __init__(self, contamination: float = 0.01):
        self.contamination = contamination
        self.detector = ECOD(contamination=self.contamination)
        self.is_fitted = False
        self.calibrated_threshold = 0.75

        # Feature normalization bounds
        self.means = np.array([10.0, 989.0, 75.0])
        self.stds = np.array([8.5, 12.0, 18.0])

    def fit(self, df_clean: pd.DataFrame):
        """
        Fits the multivariate detector on a clean sample of joint readings.
        """
        features = df_clean[["temperature_c", "pressure_hpa", "humidity_pct"]].dropna().values
        self.means = np.mean(features, axis=0)
        self.stds = np.std(features, axis=0) + 1e-6

        scaled_features = (features - self.means) / self.stds
        self.detector.fit(scaled_features)
        self.is_fitted = True

        # Calibrate decision boundary
        scores = self.detector.decision_scores_
        self.calibrated_threshold = float(np.percentile(scores, 99.5))

    def evaluate(self, reading: AWSReading) -> Tuple[float, Optional[str]]:
        """
        Evaluates joint reading. Returns (anomaly_score [0, 1], reason).
        """
        x = np.array([[reading.temperature_c, reading.pressure_hpa, reading.humidity_pct]])
        x_scaled = (x - self.means) / self.stds

        reasons = []
        detector_score = 0.0

        if self.is_fitted:
            # ECOD raw decision score (higher = more anomalous)
            raw_score = float(self.detector.decision_function(x_scaled)[0])
            norm_score = max(0.0, min(1.0, raw_score / (self.calibrated_threshold * 1.4)))
            detector_score = norm_score
            if norm_score > 0.65:
                reasons.append(f"Joint (T, P, RH) distribution anomaly (ECOD score={norm_score:.2f})")
        else:
            # Heuristic Mahalanobis / Euclidean distance fallback if not yet fitted
            dist = float(np.linalg.norm(x_scaled))
            detector_score = min(1.0, max(0.0, (dist - 2.5) / 2.5))

        # Physical cross-variable constraint: Clausius-Clapeyron daytime anti-correlation
        # At high temperatures (> 30°C), 100% humidity is exceptionally rare in continental climates (Jena)
        if reading.temperature_c > 32.0 and reading.humidity_pct > 95.0:
            detector_score = max(detector_score, 0.85)
            reasons.append(f"Extreme vapor saturation at high temperature ({reading.temperature_c:.1f}°C with {reading.humidity_pct:.1f}% RH)")

        reason_str = "; ".join(reasons) if reasons else None
        return detector_score, reason_str
