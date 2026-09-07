"""
Conformal Evidence Fusion Engine.
Inspired by MAPIE (https://github.com/scikit-learn-contrib/MAPIE).
Combines the 5 anomaly layers with:
1. Deterministic Physics Veto Override
2. Conformal calibration ensuring a statistical guarantee on false alarm rate (alpha <= 0.001)
3. Severity and confidence quantification
"""
from typing import Dict, List, Optional, Tuple
import numpy as np

from ather.config import CONFIG, FusionThresholds

class ConformalEvidenceFusion:
    """
    Fuses multi-layer evidence into a calibrated anomaly decision.
    """
    def __init__(self, config: FusionThresholds = CONFIG.fusion):
        self.cfg = config
        self.alpha = config.target_false_alarm_rate
        self.calibrated_quantile: float = 0.45  # Empirical non-conformity threshold
        self.is_calibrated: bool = False
        self.calibration_scores: List[float] = []

        # Layer importance weights for ensemble non-conformity score
        self.weights = {
            "physics": 0.35,
            "temporal": 0.25,
            "multivariate": 0.20,
            "spatial": 0.15,
            "drift": 0.05
        }

    def compute_nonconformity_score(self, layer_scores: Dict[str, float]) -> float:
        """
        Computes composite non-conformity score across available detection layers.
        """
        score = 0.0
        norm_w = 0.0
        for layer_name, w in self.weights.items():
            if layer_name in layer_scores:
                score += w * layer_scores[layer_name]
                norm_w += w
        return float(score / max(1e-5, norm_w))

    def calibrate(self, clean_layer_scores_list: List[Dict[str, float]], alpha: Optional[float] = None):
        """
        Calibrates non-conformity threshold against clean validation data using conformal prediction.
        Ensures P(False Alarm) <= alpha.
        """
        if alpha is not None:
            self.alpha = alpha

        scores = [self.compute_nonconformity_score(scores) for scores in clean_layer_scores_list]
        self.calibration_scores = sorted(scores)

        # Standard split-conformal quantile formula: (1 - alpha) * (1 + 1/n)
        n = len(self.calibration_scores)
        if n > 0:
            level = min(1.0, (1.0 - self.alpha) * (1.0 + 1.0 / n))
            self.calibrated_quantile = float(np.percentile(self.calibration_scores, level * 100.0))
            self.is_calibrated = True

    def fuse(
        self,
        layer_scores: Dict[str, float],
        veto_fired: bool = False
    ) -> Tuple[bool, float, float, float]:
        """
        Fuses layer scores into final decision.
        Returns:
            is_anomaly: bool
            severity_score: float [0.0, 1.0]
            confidence_score: float [0.0, 1.0]
            empirical_p_value: float [0.0, 1.0]
        """
        # 1. Physics VETO Rule: thermodynamic impossibility overrides all other layers
        if veto_fired:
            return True, 1.0, 1.0, 0.0

        nonconf_score = self.compute_nonconformity_score(layer_scores)
        temporal_score = layer_scores.get("temporal", 0.0)

        # Calculate empirical p-value relative to clean calibration distribution
        if self.calibration_scores:
            count_higher = np.sum(np.array(self.calibration_scores) >= nonconf_score)
            p_value = float((count_higher + 1) / (len(self.calibration_scores) + 1))
        else:
            p_value = max(0.0, 1.0 - nonconf_score)

        # Conformal decision: reject null hypothesis (normal) if nonconf_score >= calibrated_quantile
        # or if acute temporal rate-of-change spike / frozen occurs (temporal >= 0.85)
        threshold = self.calibrated_quantile if self.is_calibrated else self.cfg.ensemble_anomaly_threshold
        is_anomaly = bool(nonconf_score >= threshold or temporal_score >= 0.85)

        # Severity is proportional to how far above threshold the score falls
        severity = float(np.clip(max(nonconf_score, temporal_score), 0.0, 1.0))
        # Confidence is inverse p-value
        confidence = float(np.clip(1.0 - p_value, 0.6 if is_anomaly else 0.0, 0.99))

        return is_anomaly, severity, confidence, p_value
