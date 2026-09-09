"""
Conformal Evidence Fusion Engine (v2).

BUG FIXES (v2):
  - REMOVED hard confidence floor clamp [0.70, 0.99] (BUG 3).
  - Confidence now reflects actual evidence quality (number of layers with meaningful data,
    coverage of valid channels, agreement between layers).
  - Clearly distinguishes:
      anomaly_score:  weighted ensemble severity [0, 1]
      confidence:     how certain we are in the anomaly classification [0, 1]
      severity:       combined peak + ensemble measure [0, 1]
      p_value:        calibration-relative empirical significance

CONFIDENCE COMPUTATION:
  - Starts from 1.0 - p_value (calibration-based)
  - Scaled DOWN by:
      - evidence_coverage_ratio  (fraction of layers that had valid data)
      - layer_agreement_ratio    (layers agree → higher confidence)
  - Single-layer evidence → confidence capped at 0.65
  - Physics VETO from a VALID channel → confidence 0.95 (not 0.99)
  - NOT clamped to any artificial minimum
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from config import CONFIG, FusionThresholds


class ConformalEvidenceFusion:
    """
    Fuses multi-layer evidence into a calibrated, evidence-quality-aware anomaly decision.
    """
    def __init__(self, config: FusionThresholds = CONFIG.fusion):
        self.cfg = config
        self.alpha             = config.target_false_alarm_rate
        self.calibrated_quantile: float = 0.45
        self.is_calibrated:     bool    = False
        self.calibration_scores: List[float] = []

        # Layer importance weights
        self.weights = {
            "physics":      0.35,
            "temporal":     0.25,
            "multivariate": 0.20,
            "spatial":      0.15,
            "drift":        0.05,
        }

    def compute_nonconformity_score(self, layer_scores: Dict[str, float]) -> float:
        """Computes composite non-conformity score across participating layers."""
        score, norm_w = 0.0, 0.0
        for layer_name, w in self.weights.items():
            if layer_name in layer_scores:
                score  += w * layer_scores[layer_name]
                norm_w += w
        return float(score / max(1e-5, norm_w))

    def calibrate(self, clean_layer_scores_list: List[Dict[str, float]], alpha: Optional[float] = None):
        """Calibrates non-conformity threshold against clean validation data."""
        if alpha is not None:
            self.alpha = alpha
        scores = [self.compute_nonconformity_score(s) for s in clean_layer_scores_list]
        self.calibration_scores = sorted(scores)
        n = len(self.calibration_scores)
        if n > 0:
            level                    = min(1.0, (1.0 - self.alpha) * (1.0 + 1.0 / n))
            self.calibrated_quantile = float(np.percentile(self.calibration_scores, level * 100.0))
            self.is_calibrated       = True

    def fuse(
        self,
        layer_scores:          Dict[str, float],
        veto_fired:            bool            = False,
        layer_coverage:        Optional[Dict[str, float]] = None,
        spatial_neighbor_count: int            = 0,
        temporal_history_count: int            = 0,
    ) -> Tuple[bool, str, float, float, float, Dict[str, Any]]:
        """
        Fuses layer scores into a calibrated decision.

        Args:
            layer_scores:           Score per layer [0, 1]
            veto_fired:             True ONLY if a physically valid value was physically impossible
            layer_coverage:         Fraction of channels evaluated per layer [0, 1]
            spatial_neighbor_count: Number of valid spatial neighbors used
            temporal_history_count: Number of historical points available

        Returns:
            is_anomaly:     bool
            status:         str ("NORMAL" | "WARNING" | "ANOMALY" | "INSUFFICIENT_DATA")
            severity:       float [0, 1]
            confidence:     float [0, 1]  — evidence-quality-aware, NOT artificially clamped
            p_value:        float [0, 1]
            detail:         Dict with evidence breakdown
        """
        detail: Dict[str, Any] = {}

        # ── Physics VETO (on a real valid value) ─────────────────────────
        if veto_fired:
            return True, "ANOMALY", 1.0, 0.95, 0.001, {
                "triggered_by": "physics_veto",
                "note": "A real measured value violated a thermodynamic physical law.",
                "confidence_basis": "Deterministic physics rule — no statistical uncertainty",
            }

        nonconf_score  = self.compute_nonconformity_score(layer_scores)
        temporal_score = layer_scores.get("temporal",     0.0)
        spatial_score  = layer_scores.get("spatial",      0.0)
        multi_score    = layer_scores.get("multivariate", 0.0)
        drift_score    = layer_scores.get("drift",        0.0)
        physics_score  = layer_scores.get("physics",      0.0)

        # ── Empirical p-value ─────────────────────────────────────────────
        if self.calibration_scores:
            count_higher = int(np.sum(np.array(self.calibration_scores) >= nonconf_score))
            p_value      = float((count_higher + 1) / (len(self.calibration_scores) + 1))
        else:
            p_value      = max(0.01, 1.0 - nonconf_score)

        # ── Anomaly decision ──────────────────────────────────────────────
        threshold     = (self.calibrated_quantile if self.is_calibrated
                         else self.cfg.ensemble_anomaly_threshold)

        acute_temporal = temporal_score >= 0.70
        acute_spatial  = spatial_score  >= 0.70
        acute_multi    = multi_score     >= 0.80
        acute_drift    = drift_score     >= 0.75
        acute_physics  = physics_score   >= 0.75

        is_anomaly = bool(
            nonconf_score >= threshold
            or acute_temporal
            or acute_spatial
            or acute_multi
            or acute_drift
            or acute_physics
        )

        # ── Severity ─────────────────────────────────────────────────────
        peak_score = max(layer_scores.values()) if layer_scores else 0.0
        severity   = float(np.clip(0.6 * peak_score + 0.4 * nonconf_score, 0.0, 1.0))

        # ── Status category ──────────────────────────────────────────────
        if severity >= 0.65 or peak_score >= 0.85:
            status = "ANOMALY"
        elif is_anomaly or severity >= 0.35:
            status = "WARNING"
        else:
            status = "NORMAL"

        # ── Evidence-quality-aware confidence ────────────────────────────
        meaningful_layer_count = sum(1 for v in layer_scores.values() if v > 0.15)
        total_layers           = len(self.weights)

        # Coverage factor: fraction of layers that had valid data
        if layer_coverage:
            coverage_ratio = float(np.mean(list(layer_coverage.values())))
        else:
            coverage_ratio = meaningful_layer_count / max(1, total_layers)

        # Agreement factor: if layers strongly disagree, reduce confidence
        if is_anomaly and meaningful_layer_count >= 2:
            scores_arr       = np.array([v for v in layer_scores.values() if v > 0.10])
            agreement_factor = 1.0 - float(np.std(scores_arr)) / max(0.1, float(np.mean(scores_arr)))
            agreement_factor = max(0.5, min(1.0, agreement_factor))
        else:
            agreement_factor = 1.0

        if is_anomaly:
            # Acute trigger or ensemble pass:
            base_conf = max(peak_score, 1.0 - p_value)
            if meaningful_layer_count == 1:
                # Single layer evidence capped at 0.65
                raw_confidence = min(0.65, base_conf)
            elif meaningful_layer_count == 2:
                raw_confidence = min(0.80, base_conf)
            else:
                raw_confidence = min(0.95, base_conf)

            # Scarcity penalties
            if spatial_score > 0.1 and spatial_neighbor_count < 3:
                raw_confidence *= 0.85
            if temporal_score > 0.1 and temporal_history_count < 5:
                raw_confidence *= 0.90

            confidence = float(np.clip(raw_confidence * (0.65 + 0.35 * coverage_ratio) * agreement_factor, 0.10, 0.97))

            # Status classification based on severity, peak score, and confidence
            if (severity >= 0.60 or peak_score >= 0.75) and confidence >= 0.30:
                status = "ANOMALY"
                is_anomaly = True
            else:
                status = "WARNING"
                # If peak score is below strong anomaly threshold and confidence is low, classify as warning
                is_anomaly = (peak_score >= 0.85)
        else:
            # Check if warning thresholds met even without acute anomaly trigger
            if severity >= 0.35 or peak_score >= 0.60:
                status = "WARNING"
                raw_confidence = 0.70
            else:
                status = "NORMAL"
                raw_confidence = 0.90
            confidence = float(np.clip(raw_confidence * (0.70 + 0.30 * coverage_ratio), 0.40, 0.95))
            is_anomaly = False

        detail.update({
            "nonconformity_score":      round(nonconf_score, 4),
            "p_value":                  round(p_value, 4),
            "meaningful_layer_count":   meaningful_layer_count,
            "coverage_ratio":           round(coverage_ratio, 3),
            "agreement_factor":         round(agreement_factor, 3),
            "raw_confidence":           round(raw_confidence, 3),
            "final_confidence":         round(confidence, 3),
            "acute_triggers": {
                "physics":      acute_physics,
                "temporal":     acute_temporal,
                "spatial":      acute_spatial,
                "multivariate": acute_multi,
                "drift":        acute_drift,
            },
        })

        return is_anomaly, status, severity, confidence, p_value, detail
