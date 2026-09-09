"""
Root-Cause Classifier (v2).

BUG FIXES (v2):
  - REMOVED catch-all default FaultType.SENSOR_SPIKE.
  - Added INSUFFICIENT_EVIDENCE classification for ambiguous/weak evidence.
  - Added POSSIBLE_WEATHER_CHANGE classification.
  - Returns structured DiagnosisResult with primary, confidence, evidence, alternatives.
  - Confidence tiers: HIGH, MEDIUM, LOW, INSUFFICIENT_DATA.
  - Weather vs sensor distinction requires spatial corroboration.

CLASSIFICATION HIERARCHY:
  1. INSUFFICIENT_EVIDENCE  — not enough signal across layers
  2. FROZEN_SENSOR          — zero variance across frozen window (high confidence)
  3. GENUINE_EXTREME_WEATHER — temporal high + spatial LOW (neighbors agree) + valid physics
  4. POSSIBLE_WEATHER_CHANGE — temporal moderate + spatial low (fewer neighbors)
  5. SENSOR_SPIKE           — temporal high + spatial HIGH (station isolated)
  6. CALIBRATION_DRIFT      — drift layer elevated + persistent CUSUM
  7. NOISE_BURST            — statistical outlier alone, no spike
  8. SINGLE_CHANNEL_FAULT   — spatial high + physics valid (isolated spatial outlier)
  9. COMMUNICATION_OUTAGE   — all channels null/stale (handled upstream, not here)
"""
from typing import Dict, List, Optional, Any
from schema import FaultType, DiagnosisConfidence


class DiagnosisResult:
    """Structured root-cause diagnosis with uncertainty representation."""
    __slots__ = (
        "fault_type", "confidence", "primary_signal",
        "evidence", "alternatives", "operator_action"
    )

    def __init__(
        self,
        fault_type:      FaultType,
        confidence:      DiagnosisConfidence,
        primary_signal:  str,
        evidence:        List[str],
        alternatives:    List[str],
        operator_action: str,
    ):
        self.fault_type      = fault_type
        self.confidence      = confidence
        self.primary_signal  = primary_signal
        self.evidence        = evidence
        self.alternatives    = alternatives
        self.operator_action = operator_action


class RootCauseClassifier:
    """
    Diagnoses root cause using a structured hierarchy with uncertainty tiers.
    """

    def classify(
        self,
        is_anomaly:      bool,
        layer_scores:    Dict[str, float],
        veto_fired:      bool,
        channel_scores:  Dict[str, float],
        spatial_score:   float,
        reasons:         List[str],
        layer_details:   Optional[Dict[str, Any]] = None,
        valid_channel_count: int = 0,
    ) -> DiagnosisResult:
        """
        Classifies anomaly into a fault type with structured evidence.
        """
        layer_details = layer_details or {}

        if not is_anomaly:
            return DiagnosisResult(
                fault_type      = FaultType.NORMAL,
                confidence      = DiagnosisConfidence.HIGH,
                primary_signal  = "All layers within normal parameters",
                evidence        = [],
                alternatives    = [],
                operator_action = "No action required. Continue monitoring.",
            )

        temporal_score = layer_scores.get("temporal",     0.0)
        drift_score    = layer_scores.get("drift",        0.0)
        multi_score    = layer_scores.get("multivariate", 0.0)
        physics_score  = layer_scores.get("physics",      0.0)
        reasons_text   = " ".join(reasons).lower()

        # ── 1. Physics VETO — real physical impossibility ─────────────────
        if veto_fired:
            evid = reasons.copy()
            return DiagnosisResult(
                fault_type      = FaultType.SINGLE_CHANNEL_FAULT,
                confidence      = DiagnosisConfidence.HIGH,
                primary_signal  = "Measured value violates physical law",
                evidence        = evid,
                alternatives    = ["Extreme weather event — but physics still requires investigation"],
                operator_action = "Inspect the specific sensor channel reporting the impossible value.",
            )

        # ── 2. Insufficient evidence check ───────────────────────────────
        # Only one layer triggered with a low score — not enough for a reliable diagnosis
        meaningful = sum(1 for v in layer_scores.values() if v > 0.20)
        if meaningful <= 1 and max(layer_scores.values(), default=0.0) < 0.60:
            return DiagnosisResult(
                fault_type      = FaultType.INSUFFICIENT_EVIDENCE,
                confidence      = DiagnosisConfidence.INSUFFICIENT_DATA,
                primary_signal  = "Anomaly detected but evidence is limited",
                evidence        = reasons,
                alternatives    = [
                    "Normal statistical fluctuation",
                    "Transient environmental change",
                ],
                operator_action = "Monitor the station over the next few readings before taking action.",
            )

        # ── 3. Frozen sensor ──────────────────────────────────────────────
        if "frozen" in reasons_text or "constant" in reasons_text:
            return DiagnosisResult(
                fault_type      = FaultType.FROZEN_SENSOR,
                confidence      = DiagnosisConfidence.HIGH,
                primary_signal  = "Sensor output stuck at a constant value",
                evidence        = [r for r in reasons if "frozen" in r.lower() or "constant" in r.lower()],
                alternatives    = ["Extremely stable atmospheric conditions — rare"],
                operator_action = "Inspect sensor for physical obstruction or ADC lockup. Power-cycle if possible.",
            )

        # ── 4. Genuine extreme weather (temporal high + neighbors agree) ──
        # Spatial score LOW with validated neighbors means neighbors show similar change → regional signal
        n_neighbors = 0
        if "spatial" in layer_details:
            n_neighbors = (
                layer_details["spatial"].get("neighbor_count", 0)
                or layer_details["spatial"].get("total_neighbors_in_radius", 0)
            )

        if temporal_score > 0.60 and spatial_score < 0.30 and n_neighbors >= 2:
            if n_neighbors >= 4:
                # Strong corroboration from many neighbors
                return DiagnosisResult(
                    fault_type      = FaultType.GENUINE_EXTREME_WEATHER,
                    confidence      = DiagnosisConfidence.MEDIUM,
                    primary_signal  = f"Rapid atmospheric change corroborated by {n_neighbors} nearby stations",
                    evidence        = reasons,
                    alternatives    = [
                        "Sensor anomaly — spatially consistent changes can occasionally be coincidental",
                    ],
                    operator_action = "This appears to be a real weather event. Continue monitoring. No hardware intervention needed.",
                )
            else:
                # Fewer neighbors (2-3) — less certain about regional vs station
                return DiagnosisResult(
                    fault_type      = FaultType.POSSIBLE_WEATHER_CHANGE,
                    confidence      = DiagnosisConfidence.LOW,
                    primary_signal  = f"Rapid change recorded; {n_neighbors} nearby stations show consistent atmospheric trend",
                    evidence        = reasons,
                    alternatives    = [
                        "Station-level sensor spike",
                        "Localized microclimate event",
                    ],
                    operator_action = (
                        f"Compare with nearest stations manually. "
                        f"Only {n_neighbors} neighbor(s) available for spatial cross-check."
                    ),
                )

        # ── 5. Sensor spike (temporal high + spatial HIGH → station isolated) ──
        if "abrupt" in reasons_text or "spike" in reasons_text:
            if spatial_score >= 0.50:
                # Isolated station spike — stronger evidence of sensor fault
                return DiagnosisResult(
                    fault_type      = FaultType.SENSOR_SPIKE,
                    confidence      = DiagnosisConfidence.MEDIUM,
                    primary_signal  = "Abrupt sensor change not reflected in neighboring stations",
                    evidence        = reasons,
                    alternatives    = [
                        "Highly localized weather phenomenon",
                        "Data transmission glitch",
                    ],
                    operator_action = (
                        "Verify sensor physically. Compare against nearby station data. "
                        "If repeated, schedule sensor inspection."
                    ),
                )
            else:
                # Abrupt change but spatial context limited
                return DiagnosisResult(
                    fault_type      = FaultType.SENSOR_SPIKE,
                    confidence      = DiagnosisConfidence.LOW,
                    primary_signal  = "Abrupt measurement change detected",
                    evidence        = reasons,
                    alternatives    = [
                        "Real rapid weather change (frontal passage)",
                        "Insufficient spatial data to confirm station-level origin",
                    ],
                    operator_action = "Monitor next few readings. Compare with neighbors if available.",
                )

        # ── 6. Calibration drift ──────────────────────────────────────────
        if drift_score > 0.60 or "drift" in reasons_text or "cusum" in reasons_text:
            drift_tier = "POSSIBLE_DRIFT"
            if "layer_drift" in layer_details or "drift" in layer_details:
                drift_detail = layer_details.get("drift", {})
                worst_tier   = drift_detail.get("worst_drift_tier", "POSSIBLE_DRIFT")
                drift_tier   = worst_tier

            conf = DiagnosisConfidence.MEDIUM if drift_score > 0.70 else DiagnosisConfidence.LOW
            return DiagnosisResult(
                fault_type      = FaultType.CALIBRATION_DRIFT,
                confidence      = conf,
                primary_signal  = f"Systematic cumulative bias accumulating ({drift_tier})",
                evidence        = reasons,
                alternatives    = [
                    "Seasonal or diurnal baseline shift",
                    "Gradual environmental change at the station site",
                ],
                operator_action = (
                    "Monitor over next 24–48 hours. If bias persists, schedule recalibration "
                    "against a secondary reference sensor."
                ),
            )

        # ── 7. Noise burst / statistical outlier ──────────────────────────
        if "outlier" in reasons_text or "z=" in reasons_text or "modified z" in reasons_text:
            return DiagnosisResult(
                fault_type      = FaultType.NOISE_BURST,
                confidence      = DiagnosisConfidence.LOW,
                primary_signal  = "Statistical outlier in sensor time series",
                evidence        = reasons,
                alternatives    = [
                    "Real short-duration weather anomaly",
                    "Random measurement noise",
                ],
                operator_action = "Monitor the next reading. Single statistical outliers often self-resolve.",
            )

        # ── 8. Spatial outlier (isolated station) ─────────────────────────
        if spatial_score >= 0.65:
            return DiagnosisResult(
                fault_type      = FaultType.SINGLE_CHANNEL_FAULT,
                confidence      = DiagnosisConfidence.MEDIUM,
                primary_signal  = "This station diverges significantly from nearby stations",
                evidence        = reasons,
                alternatives    = [
                    "Highly localised microclimate",
                    "Nearby stations may themselves have data quality issues",
                ],
                operator_action = (
                    "Compare raw data from this station against neighboring stations manually. "
                    "Inspect the station if divergence persists across multiple readings."
                ),
            )

        # ── 9. Multivariate inconsistency ─────────────────────────────────
        if multi_score >= 0.65:
            return DiagnosisResult(
                fault_type      = FaultType.NOISE_BURST,
                confidence      = DiagnosisConfidence.LOW,
                primary_signal  = "Combination of sensor readings is jointly unusual",
                evidence        = reasons,
                alternatives    = [
                    "Unusual atmospheric conditions",
                    "Single-sensor error affecting computed variables",
                ],
                operator_action = "Review the combination of temperature, pressure, and humidity readings.",
            )

        # ── Fallback: genuine insufficient evidence ────────────────────────
        return DiagnosisResult(
            fault_type      = FaultType.INSUFFICIENT_EVIDENCE,
            confidence      = DiagnosisConfidence.LOW,
            primary_signal  = "Anomaly threshold crossed but pattern does not match known fault signatures",
            evidence        = reasons,
            alternatives    = [
                "Normal variability near detection threshold",
                "Multiple concurrent minor deviations",
            ],
            operator_action = "Monitor over the next several readings. No immediate action required.",
        )
