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

PHASE 4 (evidence-aware attribution): the classifier consumes the fusion context
(layer availability / evidence sufficiency, the persistent-degradation state) and
the Spatial attribution / counterfactual ("do nearby stations support this
reading?"). Regional support downgrades a sensor-fault call to LOW and lets a
weather-like reading be recognised even when Spatial's distance-weighted score
alone is ambiguous; a NORMAL result reached from little evidence carries a low
confidence tier; persistent-degradation evidence is a maintenance WARNING
(CALIBRATION_DRIFT, low/medium certainty), never an acute anomaly.
"""
from typing import Dict, List, Optional, Any
from schema import FaultType, DiagnosisConfidence


class DiagnosisResult:
    """Structured root-cause diagnosis with uncertainty representation."""
    __slots__ = (
        "fault_type", "confidence", "primary_signal",
        "evidence", "alternatives", "operator_action",
        "spatial_corroboration",
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
        # S7: structured S3/S6 corroboration context (evidence states, not
        # probabilities). None when spatial evidence is unavailable or the
        # fault type is not a weather-vs-sensor distinction.
        self.spatial_corroboration = None


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
        Public entry point. The fault-type / confidence decision is made by
        _classify_core (UNCHANGED by S7). This wrapper then ADDS S3
        (regional attribution) and S6 (counterfactual verification) spatial
        evidence as corroborating/conflicting context on the result, without
        altering which category or confidence tier was selected -- so the
        same spatial neighborhood is never counted twice in the decision.
        """
        result = self._classify_core(
            is_anomaly, layer_scores, veto_fired, channel_scores,
            spatial_score, reasons, layer_details, valid_channel_count,
        )
        return self._attach_spatial_corroboration(result, layer_details or {})

    @staticmethod
    def _normal_confidence_tier(sufficiency: Optional[float]) -> DiagnosisConfidence:
        """How sure a NORMAL call is, from how much evidence actually assessed the
        observation. None (a caller that supplies no fusion context) keeps the
        legacy HIGH."""
        if sufficiency is None:
            return DiagnosisConfidence.HIGH
        if sufficiency >= 0.75:
            return DiagnosisConfidence.HIGH
        if sufficiency >= 0.50:
            return DiagnosisConfidence.MEDIUM
        if sufficiency >= 0.30:
            return DiagnosisConfidence.LOW
        return DiagnosisConfidence.INSUFFICIENT_DATA

    @staticmethod
    def _attach_spatial_corroboration(result: DiagnosisResult, layer_details: Dict[str, Any]) -> DiagnosisResult:
        weather_like = (FaultType.GENUINE_EXTREME_WEATHER, FaultType.POSSIBLE_WEATHER_CHANGE)
        sensor_like = (FaultType.SENSOR_SPIKE, FaultType.SINGLE_CHANNEL_FAULT)
        if result.fault_type not in weather_like + sensor_like:
            return result

        spatial = layer_details.get("spatial") or {}
        ra = (spatial.get("regional_attribution") or {}).get("classification")
        cv = (spatial.get("counterfactual_verification") or {}).get("overall_status")
        if ra is None and cv is None:
            return result

        regional_signals = (ra == "REGIONAL_EVENT", cv == "SUPPORTED")
        isolated_signals = (ra == "ISOLATED_SENSOR_ANOMALY", cv == "CONTRADICTED")
        if result.fault_type in weather_like:
            agrees, conflicts = any(regional_signals), any(isolated_signals)
            hypothesis = "genuine regional weather response"
        else:
            agrees, conflicts = any(isolated_signals), any(regional_signals)
            hypothesis = "isolated sensor anomaly"

        if agrees and not conflicts:
            state, note = "CORROBORATED", f"Spatial evidence (attribution={ra}, counterfactual={cv}) is consistent with a {hypothesis}."
        elif conflicts and not agrees:
            state, note = "CONFLICTING", f"Spatial evidence (attribution={ra}, counterfactual={cv}) points AWAY from a {hypothesis}; treat this diagnosis with caution."
        elif agrees and conflicts:
            state, note = "MIXED", f"Spatial evidence is mixed (attribution={ra}, counterfactual={cv}); no clear support for a {hypothesis}."
        else:
            state, note = "INSUFFICIENT", f"Spatial attribution/counterfactual evidence is inconclusive (attribution={ra}, counterfactual={cv})."

        evidence = list(result.evidence)   # copy: never mutate the shared reasons list
        evidence.append(note)              # append at END only
        result.evidence = evidence
        result.spatial_corroboration = {
            "state": state, "regional_attribution": ra, "counterfactual_status": cv,
            "note": "Evidence states, not calibrated probabilities. The category/confidence above already account for this evidence (Phase 4); this block only reports how it lines up.",
        }
        return result

    def _classify_core(
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

        fusion_ctx     = layer_details.get("fusion") or {}
        persistent     = fusion_ctx.get("persistent_degradation") or {}
        pd_state       = persistent.get("state")
        sufficiency    = fusion_ctx.get("evidence_sufficiency")
        spatial_detail = layer_details.get("spatial") or {}
        ra = (spatial_detail.get("regional_attribution") or {}).get("classification")
        cf = (spatial_detail.get("counterfactual_verification") or {}).get("overall_status")
        regional_support  = (ra == "REGIONAL_EVENT") or (cf == "SUPPORTED")
        isolated_evidence = (ra == "ISOLATED_SENSOR_ANOMALY") or (cf == "CONTRADICTED")

        if not is_anomaly:
            if pd_state in ("CORROBORATED_BY_SPATIAL", "UNCORROBORATED"):
                corroborated = pd_state == "CORROBORATED_BY_SPATIAL"
                return DiagnosisResult(
                    fault_type      = FaultType.CALIBRATION_DRIFT,
                    confidence      = DiagnosisConfidence.MEDIUM if corroborated else DiagnosisConfidence.LOW,
                    primary_signal  = "Sustained change in the sensor's own behavior (possible calibration drift)",
                    evidence        = list(reasons) + [persistent.get("note", "")],
                    alternatives    = [
                        "Natural weather variation (drift is measured against the sensor's own recent baseline)",
                        "A real regional change that neighbors cannot resolve",
                    ],
                    operator_action = (
                        "Sensor-health evidence for a maintenance investigation, not an acute anomaly. Compare "
                        "against a secondary reference or nearby stations before acting."
                    ),
                )
            tier = self._normal_confidence_tier(sufficiency)
            n_avail = fusion_ctx.get("available_layer_count")
            if sufficiency is not None and sufficiency < 0.75:
                signal = (f"No anomaly detected by the available evidence "
                          f"({n_avail} of 4 evidence layers could assess this observation)")
            else:
                signal = "All layers within normal parameters"
            return DiagnosisResult(
                fault_type      = FaultType.NORMAL,
                confidence      = tier,
                primary_signal  = signal,
                evidence        = [persistent["note"]] if persistent else [],
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
        anomaly_scores = [v for k, v in layer_scores.items() if k != "drift"]
        meaningful = sum(1 for v in anomaly_scores if v > 0.20)
        if meaningful <= 1 and max(anomaly_scores, default=0.0) < 0.60:
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

        if temporal_score > 0.60 and n_neighbors >= 2 and (spatial_score < 0.30 or regional_support):
            if n_neighbors >= 4 and spatial_score < 0.30 and not isolated_evidence:
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
                # Isolated station spike — stronger evidence of sensor fault, unless nearby
                # stations support the reading (then it is a contested call: LOW, not MEDIUM)
                return DiagnosisResult(
                    fault_type      = FaultType.SENSOR_SPIKE,
                    confidence      = DiagnosisConfidence.LOW if regional_support else DiagnosisConfidence.MEDIUM,
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
        if pd_state != "REGIONALLY_EXPLAINED" and (
                drift_score > 0.60 or "drift" in reasons_text or "cusum" in reasons_text):
            drift_tier = "POSSIBLE_DRIFT"
            if "layer_drift" in layer_details or "drift" in layer_details:
                drift_detail = layer_details.get("drift", {})
                worst_tier   = drift_detail.get("worst_drift_tier", "POSSIBLE_DRIFT")
                drift_tier   = worst_tier

            conf = (DiagnosisConfidence.MEDIUM
                    if (drift_score > 0.70 and pd_state != "UNCORROBORATED") else DiagnosisConfidence.LOW)
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
                confidence      = DiagnosisConfidence.LOW if regional_support else DiagnosisConfidence.MEDIUM,
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
            n_avail = fusion_ctx.get("available_layer_count")
            if n_avail is not None and n_avail <= 2 and meaningful <= 1:
                # A lone multivariate signal while (almost) no other layer could assess the
                # observation: naming a specific fault would claim more than the evidence supports.
                return DiagnosisResult(
                    fault_type      = FaultType.INSUFFICIENT_EVIDENCE,
                    confidence      = DiagnosisConfidence.INSUFFICIENT_DATA,
                    primary_signal  = "Joint (T, P, RH) state is unusual, but too few evidence layers could assess this observation",
                    evidence        = reasons,
                    alternatives    = [
                        "Unusual atmospheric conditions",
                        "A sensor fault that other layers could confirm once temporal / neighbor evidence exists",
                    ],
                    operator_action = "Wait for more observations (temporal history) and neighboring stations before acting.",
                )
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
