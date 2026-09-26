"""
Evidence Fusion Engine (v3 - Phase 4 validation).

NOTE ON THE NAME: the class is still called ConformalEvidenceFusion for API
compatibility, but it is NOT conformal prediction in practice. `calibrate()` is
never called in production, so `is_calibrated` is False and every decision uses
the fixed thresholds below. The `confidence` it returns is a HEURISTIC
evidence-quality score in [0, 1]; it is NOT a calibrated probability and carries
no statistical guarantee. `detail["calibrated"]` and `detail["confidence_basis"]`
say so in every response, and `detail["p_value"]` is None unless calibrated.

WHAT FUSION DOES (it is not majority voting)
  1. EVIDENCE AVAILABILITY. A layer that could not assess the observation
     (insufficient history / neighbors / samples, layer failure, not applicable)
     is UNAVAILABLE - that is not the same as "assessed and normal". Unavailable
     layers are excluded from the ensemble (weights renormalized over the
     available ones) and from the "acute" checks, and they LOWER the evidence
     sufficiency that scales confidence. The old behaviour scored them 0.0, which
     both diluted real evidence and let a mostly-blind decision look confident.
  2. ANOMALY EVIDENCE = physics, temporal, multivariate, spatial. A physics veto
     (a measured value that is physically impossible) short-circuits to ANOMALY.
     Otherwise: a weighted ensemble over the available layers plus per-layer
     "acute" triggers. A single available layer is never an "ensemble".
  3. SENSOR HEALTH (drift / CUSUM) IS NOT ANOMALY EVIDENCE. It measures a
     persistent change in a sensor's own behavior. It is excluded from the
     ensemble, the acute triggers and the severity peak. On its own it can
     produce at most a WARNING ("persistent degradation") whose strength depends
     on whether Spatial corroborates it: neighbors DISAGREEING with the sensor
     corroborates it; neighbors AGREEING with it means the change is consistent
     with a shared regional weather change (or a drift too small for Spatial to
     resolve), so it is "regionally explained" and does not raise the status.
  4. SPATIAL ATTRIBUTION / COUNTERFACTUAL are preserved as CONTEXT
     (`evidence_context`), never added as another numeric score (Spatial's one
     primary score is already in the ensemble; adding them would double-count).
     A specific contradiction - Spatial agrees with the target while another
     layer flags it, or Spatial's own IDW score and its counterfactual disagree -
     is recorded as a conflict and lowers confidence; it never silently picks a
     side. The classifier (root_cause/classifier.py) uses the same context for
     the final sensor-vs-weather attribution.
  5. SEVERITY = 0.6 * worst available anomaly layer + 0.4 * weighted ensemble.
     Explainable and independent of confidence.
  6. CONFIDENCE (heuristic): starts from the strongest evidence, is capped by how
     many independent layers corroborate (1 -> 0.65, 2 -> 0.80, 3+ -> 0.95),
     scaled by evidence sufficiency (availability-weighted coverage) and by a
     contradiction/agreement factor. For NORMAL it is scaled by sufficiency, so a
     "normal" reached from little evidence is reported with low confidence.
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from config import CONFIG, FusionThresholds

# ── Layer roles ───────────────────────────────────────────────────────────
ANOMALY_LAYERS = ("physics", "temporal", "multivariate", "spatial")   # acute / anomaly evidence
HEALTH_LAYER = "drift"                                                 # sensor health: NOT acute evidence

# ── Named heuristic thresholds (engineering defaults, NOT calibrated) ─────
ACUTE_THRESHOLD = {"physics": 0.75, "temporal": 0.70, "multivariate": 0.80, "spatial": 0.70}
DRIFT_STRONG = 0.75                # sensor-health evidence considered "strong"
SPATIAL_AGREES_BELOW = 0.30        # Spatial score below this: the target agrees with its neighbors
SPATIAL_DISAGREES_AT = 0.45        # Spatial score at/above this: the target disagrees with its neighbors
QUIET_BELOW = 0.10                 # an available layer below this is "no evidence of anomaly"
MEANINGFUL_ABOVE = 0.15            # a layer above this counts as corroborating evidence
CONFLICT_PENALTY = 0.75            # confidence multiplier when a specific contradiction is present
CONFIDENCE_CAP_BY_LAYERS = {1: 0.65, 2: 0.80}   # 3+ corroborating layers -> 0.95
CONFIDENCE_CAP_MANY = 0.95
PERSISTENT_DEGRADATION_SEVERITY = 0.45          # maintenance-level (WARNING band), not acute
PERSISTENT_DEGRADATION_CONF = {"CORROBORATED_BY_SPATIAL": 0.70, "UNCORROBORATED": 0.50}

CONFIDENCE_BASIS = (
    "Heuristic evidence-quality score (evidence strength, availability, corroboration and "
    "agreement). NOT a calibrated probability; no statistical guarantee."
)


def _is_available(entry: Any) -> bool:
    if isinstance(entry, dict):
        if "available" in entry:
            return bool(entry["available"])
        return str(entry.get("state", "AVAILABLE")).upper() == "AVAILABLE"
    if entry is None:
        return True
    return bool(entry)


class ConformalEvidenceFusion:
    """
    Fuses multi-layer evidence into an evidence-quality-aware anomaly decision.
    See the module docstring: heuristic, NOT calibrated/conformal in practice.
    """
    def __init__(self, config: FusionThresholds = CONFIG.fusion):
        self.cfg = config
        self.alpha             = config.target_false_alarm_rate
        self.calibrated_quantile: float = 0.45
        self.is_calibrated:     bool    = False
        self.calibration_scores: List[float] = []

        # Layer importance weights (anomaly layers are renormalized over the
        # AVAILABLE ones; "drift" is sensor-health context and is not part of the ensemble)
        self.weights = {
            "physics":      0.35,
            "temporal":     0.25,
            "multivariate": 0.20,
            "spatial":      0.15,
            "drift":        0.05,
        }

    # ── ensemble ─────────────────────────────────────────────────────────
    def _ensemble(self, layer_scores: Dict[str, float], available: Optional[Dict[str, bool]] = None) -> float:
        """Weighted mean over the AVAILABLE anomaly layers (weights renormalized)."""
        score, norm_w = 0.0, 0.0
        for name in ANOMALY_LAYERS:
            if name not in layer_scores:
                continue
            if available is not None and not available.get(name, True):
                continue
            w = self.weights[name]
            score += w * layer_scores[name]
            norm_w += w
        return float(score / norm_w) if norm_w > 0 else 0.0

    def compute_nonconformity_score(self, layer_scores: Dict[str, float]) -> float:
        """Composite score over the anomaly layers (all treated as available)."""
        return self._ensemble(layer_scores, None)

    def calibrate(self, clean_layer_scores_list: List[Dict[str, float]], alpha: Optional[float] = None):
        """Calibrates the ensemble threshold against clean validation data (NOT used in production)."""
        if alpha is not None:
            self.alpha = alpha
        scores = [self._ensemble(s, None) for s in clean_layer_scores_list]
        self.calibration_scores = sorted(scores)
        n = len(self.calibration_scores)
        if n > 0:
            level                    = min(1.0, (1.0 - self.alpha) * (1.0 + 1.0 / n))
            self.calibrated_quantile = float(np.percentile(self.calibration_scores, level * 100.0))
            self.is_calibrated       = True

    # ── helpers ──────────────────────────────────────────────────────────
    def _availability(
        self, layer_scores: Dict[str, float], layer_availability: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, bool], Dict[str, Dict[str, Any]]]:
        avail: Dict[str, bool] = {}
        report: Dict[str, Dict[str, Any]] = {}
        for name in ANOMALY_LAYERS + (HEALTH_LAYER,):
            entry = (layer_availability or {}).get(name)
            ok = _is_available(entry)
            avail[name] = ok
            report[name] = {
                "available": ok,
                "reason": (entry.get("reason") if isinstance(entry, dict) else None),
            }
        return avail, report

    def _sufficiency(self, avail: Dict[str, bool], layer_coverage: Optional[Dict[str, float]]) -> float:
        """Importance-weighted evidence coverage over the anomaly layers; an
        unavailable layer contributes 0."""
        num, den = 0.0, 0.0
        for name in ANOMALY_LAYERS:
            w = self.weights[name]
            den += w
            if avail[name]:
                cov = 1.0 if layer_coverage is None else float(layer_coverage.get(name, 1.0))
                num += w * max(0.0, min(1.0, cov))
        return float(num / den) if den > 0 else 0.0

    @staticmethod
    def _spatial_view(avail: bool, score: float) -> str:
        if not avail:
            return "UNAVAILABLE"
        if score < SPATIAL_AGREES_BELOW:
            return "AGREES_WITH_NEIGHBORS"
        if score >= SPATIAL_DISAGREES_AT:
            return "DISAGREES_WITH_NEIGHBORS"
        return "AMBIGUOUS"

    def fuse(
        self,
        layer_scores:          Dict[str, float],
        veto_fired:            bool            = False,
        layer_coverage:        Optional[Dict[str, float]] = None,
        spatial_neighbor_count: int            = 0,
        temporal_history_count: int            = 0,
        layer_availability:    Optional[Dict[str, Any]] = None,
        spatial_context:       Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, float, float, float, Dict[str, Any]]:
        """
        Fuses layer evidence into a decision.

        Args:
            layer_scores:           Score per layer [0, 1] (a score is only MEANINGFUL for an available layer)
            veto_fired:             True ONLY if a physically valid channel value was physically impossible
            layer_coverage:         Fraction of channels/evidence each layer had [0, 1]
            spatial_neighbor_count: eligible (simultaneous, same-source) neighbors Spatial used
            temporal_history_count: valid history points Temporal had
            layer_availability:     {layer: {"available": bool, "reason": str}}; omit for "all available"
            spatial_context:        {"attribution": REGIONAL_EVENT|ISOLATED_SENSOR_ANOMALY|UNCERTAIN|None,
                                     "counterfactual": SUPPORTED|CONTRADICTED|INSUFFICIENT_EVIDENCE|None}
                                    - preserved as context; never added as a numeric score.

        Returns:
            is_anomaly, status ("NORMAL" | "WARNING" | "ANOMALY"), severity [0,1],
            confidence [0,1] (heuristic, NOT a calibrated probability),
            p_value (legacy slot; only meaningful when `calibrated`), detail dict
        """
        avail, availability_report = self._availability(layer_scores, layer_availability)
        sufficiency = self._sufficiency(avail, layer_coverage)
        s = {name: float(layer_scores.get(name, 0.0)) for name in ANOMALY_LAYERS + (HEALTH_LAYER,)}
        sctx = spatial_context or {}
        attribution = sctx.get("attribution")
        counterfactual = sctx.get("counterfactual")

        base_detail: Dict[str, Any] = {
            "evidence_availability":  availability_report,
            "available_layer_count":  sum(1 for n in ANOMALY_LAYERS if avail[n]),
            "evidence_sufficiency":   round(sufficiency, 3),
            "calibrated":             self.is_calibrated,
            "confidence_basis":       CONFIDENCE_BASIS,
        }

        # ── Physics VETO (on a real valid value) ─────────────────────────
        if veto_fired:
            return True, "ANOMALY", 1.0, 0.95, 0.001, {
                **base_detail,
                "triggered_by": "physics_veto",
                "note": "A real measured value violated a thermodynamic physical law.",
                "confidence_basis": "Deterministic physics rule - no statistical uncertainty (not a probability)",
                "acute_triggers": {"physics": True, "temporal": False, "spatial": False, "multivariate": False, "drift": False},
                "p_value": None,
            }

        # ── Ensemble over AVAILABLE anomaly evidence ─────────────────────
        n_avail = base_detail["available_layer_count"]
        nonconf = self._ensemble(s, avail)
        avail_scores = {n: s[n] for n in ANOMALY_LAYERS if avail[n]}
        peak_score = max(avail_scores.values()) if avail_scores else 0.0
        peak_layer = max(avail_scores, key=avail_scores.get) if avail_scores else None

        # legacy p-value slot: only a statistic when actually calibrated
        if self.calibration_scores:
            count_higher = int(np.sum(np.array(self.calibration_scores) >= nonconf))
            p_value = float((count_higher + 1) / (len(self.calibration_scores) + 1))
        else:
            p_value = max(0.01, 1.0 - nonconf)

        threshold = self.calibrated_quantile if self.is_calibrated else self.cfg.ensemble_anomaly_threshold

        # Acute triggers: ANOMALY evidence only (drift is sensor-health context) and only from
        # layers that could actually assess the observation.
        acute = {n: bool(avail[n] and s[n] >= ACUTE_THRESHOLD[n]) for n in ANOMALY_LAYERS}
        acute["drift"] = False
        ensemble_hit = bool(n_avail >= 2 and nonconf >= threshold)   # a lone layer is not an "ensemble"
        is_anomaly = bool(ensemble_hit or any(acute.values()))

        severity = float(np.clip(0.6 * peak_score + 0.4 * nonconf, 0.0, 1.0))

        # ── Sensor-health (persistent degradation) interpretation ────────
        spatial_view = self._spatial_view(avail["spatial"], s["spatial"])
        persistent: Optional[Dict[str, Any]] = None
        if avail[HEALTH_LAYER] and s[HEALTH_LAYER] >= DRIFT_STRONG:
            if spatial_view == "DISAGREES_WITH_NEIGHBORS" or attribution == "ISOLATED_SENSOR_ANOMALY":
                state = "CORROBORATED_BY_SPATIAL"
                note = ("Sustained change in the sensor's own behavior, and neighbors disagree with this sensor: "
                        "consistent with sensor degradation (maintenance evidence, not an acute anomaly).")
            elif spatial_view == "AGREES_WITH_NEIGHBORS":
                state = "REGIONALLY_EXPLAINED"
                note = ("Sustained change in the sensor's own behavior, but neighbors agree with this sensor: consistent "
                        "with a shared regional weather change (or a drift below what Spatial can resolve). Not treated as sensor degradation.")
            else:
                state = "UNCORROBORATED"
                note = ("Sustained change in the sensor's own behavior; no independent reference confirms or excludes "
                        "natural weather variation. Possible degradation - low certainty.")
            persistent = {"state": state, "drift_score": round(s[HEALTH_LAYER], 3), "note": note}

        # ── Evidence context (attribution/counterfactual preserved, not scored) ──
        conflicts: List[Dict[str, Any]] = []
        other_acute = [n for n in ("physics", "temporal", "multivariate") if acute[n]]
        if spatial_view == "AGREES_WITH_NEIGHBORS" and other_acute:
            conflicts.append({
                "between": other_acute + ["spatial"],
                "note": (f"{'/'.join(other_acute)} flag this observation as unusual, but the target agrees with its "
                         "neighbors: consistent with a genuine regional change, or with a false positive in the flagging layer."),
            })
        if avail["spatial"] and s["spatial"] >= ACUTE_THRESHOLD["spatial"] and (
                counterfactual == "SUPPORTED" or attribution == "REGIONAL_EVENT"):
            conflicts.append({
                "between": ["spatial_score", "spatial_counterfactual"],
                "note": ("The target differs from the distance-weighted neighbor consensus, yet a coherent group of "
                         "nearby stations supports the same deviation (regional-event / counterfactual SUPPORTED)."),
            })
        sensor_indicators: List[str] = []
        weather_indicators: List[str] = []
        if attribution == "ISOLATED_SENSOR_ANOMALY":
            sensor_indicators.append("spatial attribution: ISOLATED_SENSOR_ANOMALY")
        if counterfactual == "CONTRADICTED":
            sensor_indicators.append("counterfactual: neighbors do not support the reading (CONTRADICTED)")
        if persistent and persistent["state"] == "CORROBORATED_BY_SPATIAL":
            sensor_indicators.append("sustained change in own behavior, corroborated by neighbor disagreement")
        if attribution == "REGIONAL_EVENT":
            weather_indicators.append("spatial attribution: REGIONAL_EVENT")
        if counterfactual == "SUPPORTED":
            weather_indicators.append("counterfactual: neighbors support the reading (SUPPORTED)")
        if spatial_view == "AGREES_WITH_NEIGHBORS" and other_acute:
            weather_indicators.append("target agrees with neighbors while another layer flags it")
        if persistent and persistent["state"] == "REGIONALLY_EXPLAINED":
            weather_indicators.append("sustained change in own behavior is shared by neighbors")
        evidence_context = {
            "spatial_view": spatial_view,
            "regional_attribution": attribution,
            "counterfactual": counterfactual,
            "conflicts": conflicts,
            "sensor_fault_indicators": sensor_indicators,
            "genuine_weather_indicators": weather_indicators,
            "note": "Context only - preserved for attribution; NOT an additional score (no double counting).",
        }

        meaningful_layers = [n for n in ANOMALY_LAYERS if avail[n] and s[n] > MEANINGFUL_ABOVE]
        meaningful_layer_count = len(meaningful_layers)

        # ── Decision, status and confidence ──────────────────────────────
        if is_anomaly:
            supporting = [s[n] for n in meaningful_layers if s[n] > QUIET_BELOW]
            if meaningful_layer_count >= 2 and supporting:
                arr = np.array(supporting)
                std_factor = 1.0 - float(np.std(arr)) / max(0.1, float(np.mean(arr)))
                std_factor = max(0.5, min(1.0, std_factor))
            else:
                std_factor = 1.0
            conflict_factor = CONFLICT_PENALTY if conflicts else 1.0
            agreement_factor = float(std_factor * conflict_factor)

            base_conf = peak_score
            cap = CONFIDENCE_CAP_BY_LAYERS.get(meaningful_layer_count, CONFIDENCE_CAP_MANY) if meaningful_layer_count >= 1 else CONFIDENCE_CAP_BY_LAYERS[1]
            raw_confidence = min(cap, base_conf)

            # Scarcity penalties (unchanged): thin spatial / temporal support for a signal from that layer
            if s["spatial"] > 0.1 and spatial_neighbor_count < 3:
                raw_confidence *= 0.85
            if s["temporal"] > 0.1 and temporal_history_count < 5:
                raw_confidence *= 0.90

            confidence = float(np.clip(raw_confidence * (0.65 + 0.35 * sufficiency) * agreement_factor, 0.10, 0.97))

            if (severity >= 0.60 or peak_score >= 0.75) and confidence >= 0.30:
                status = "ANOMALY"
                is_anomaly = True
            else:
                status = "WARNING"
                is_anomaly = (peak_score >= 0.85)
        else:
            agreement_factor = 1.0
            raw_confidence = 0.0
            if persistent and persistent["state"] in PERSISTENT_DEGRADATION_CONF:
                # Persistent sensor degradation evidence only: a maintenance-level WARNING, never ANOMALY.
                status = "WARNING"
                severity = max(severity, PERSISTENT_DEGRADATION_SEVERITY)
                raw_confidence = PERSISTENT_DEGRADATION_CONF[persistent["state"]]
            elif severity >= 0.35 or peak_score >= 0.60:
                status = "WARNING"
                raw_confidence = 0.70
            else:
                status = "NORMAL"
                raw_confidence = 0.90
            # Confidence scales with how much evidence there actually was.
            confidence = float(np.clip(raw_confidence * (0.30 + 0.70 * sufficiency), 0.10, 0.95))

        base_detail.update({
            "nonconformity_score":      round(nonconf, 4),
            "ensemble_score":           round(nonconf, 4),
            "p_value":                  round(p_value, 4) if self.is_calibrated else None,
            "meaningful_layer_count":   meaningful_layer_count,
            "coverage_ratio":           round(sufficiency, 3),   # legacy name for evidence_sufficiency
            "agreement_factor":         round(agreement_factor, 3),
            "raw_confidence":           round(raw_confidence, 3),
            "final_confidence":         round(confidence, 3),
            "acute_triggers":           acute,
            "ensemble_hit":             ensemble_hit,
            "persistent_degradation":   persistent,
            "evidence_context":         evidence_context,
            "severity_basis": {
                "formula": "0.6 * worst available anomaly layer + 0.4 * weighted ensemble (drift excluded)",
                "peak_layer": peak_layer,
                "peak": round(peak_score, 3),
                "ensemble": round(nonconf, 3),
            },
        })
        return is_anomaly, status, severity, confidence, p_value, base_detail
