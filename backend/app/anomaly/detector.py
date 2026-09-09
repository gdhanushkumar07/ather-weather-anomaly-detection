"""
ATHER Anomaly Detection Engine (v2)
-----------------------------------
Integrates the 5-Layer Physics, Temporal, Multivariate, Spatial, and Sensor Drift layers
with Conformal Evidence Fusion, Root-Cause Diagnosis, Self-Healing Imputation,
Meteorological Weather Analysis, and Canonical AnalysisResult generation.
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from config import CONFIG
from schema import (
    AWSReading, AnomalyAlert, FaultType, DiagnosisConfidence,
    DataQuality, station_dict_to_reading
)

from engine.layer1_physics import PhysicsValidationLayer
from engine.layer2_temporal import TemporalPatternLayer
from engine.layer3_multivariate import MultivariateConsistencyLayer
from engine.layer4_spatial import SpatialNeighborLayer
from engine.layer5_drift import SensorDriftHealthLayer
from fusion.conformal_fusion import ConformalEvidenceFusion
from root_cause.classifier import RootCauseClassifier, DiagnosisResult
from root_cause.explainability import ExplanationGenerator
from root_cause.self_healing import SelfHealingImputer


class AnomalyDetector:
    """
    Comprehensive anomaly detection system combining 5 meteorological detection layers,
    conformal evidence fusion, automated root cause analysis, weather interpretation,
    and canonical result synthesis.
    """
    def __init__(self):
        self.layer1 = PhysicsValidationLayer(CONFIG.physics)
        self.layer2 = TemporalPatternLayer(CONFIG.temporal)
        self.layer3 = MultivariateConsistencyLayer()
        self.layer4 = SpatialNeighborLayer(CONFIG.spatial)
        self.layer5 = SensorDriftHealthLayer(CONFIG.drift)

        self.fusion = ConformalEvidenceFusion(CONFIG.fusion)
        self.classifier = RootCauseClassifier()
        self.explainer = ExplanationGenerator()
        self.imputer = SelfHealingImputer()

        # Cache of latest AnomalyAlert and CanonicalResult per station
        self._alerts_cache: Dict[str, AnomalyAlert] = {}
        self._canonical_cache: Dict[str, Dict[str, Any]] = {}
        # Reference readings for spatial neighbor lookups
        self._spatial_pool: Dict[str, AWSReading] = {}
        # Station metadata cache (name, etc.)
        self._station_meta: Dict[str, Dict[str, Any]] = {}

    def update_spatial_pool(self, readings: List[AWSReading]):
        """Updates the internal spatial neighbor registry."""
        for r in readings:
            self._spatial_pool[r.station_id] = r

    def register_station_metadata(self, station_id: str, meta: Dict[str, Any]):
        """Stores station metadata for canonical result enrichment."""
        self._station_meta[station_id] = meta

    def get_neighbors_for_reading(self, reading: AWSReading, max_neighbors: int = 8) -> List[AWSReading]:
        """Finds nearest neighbor readings within spatial radius."""
        if not self._spatial_pool:
            return []

        neighbors = []
        lat = reading.lat
        lon = reading.lon

        # Bounding box pre-filter (~3 degrees lat/lon is ~330km)
        for n in self._spatial_pool.values():
            if n.station_id == reading.station_id:
                continue
            if abs(n.lat - lat) <= 3.0 and abs(n.lon - lon) <= 3.0:
                neighbors.append(n)
                if len(neighbors) >= max_neighbors:
                    break
        return neighbors

    def evaluate_station(
        self,
        station_data: Dict[str, Any],
        neighbors: Optional[List[AWSReading]] = None
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Evaluates current station observations and returns:
        (status, legacy_anomaly_dict_or_None)
        """
        stn_id = str(station_data.get("id", ""))
        if stn_id and station_data.get("name"):
            self.register_station_metadata(stn_id, station_data)

        reading = station_dict_to_reading(station_data)
        alert = self.evaluate_reading(reading, neighbors=neighbors, station_data=station_data)
        return alert.status, alert.to_legacy_dict()

    def evaluate_reading(
        self,
        reading: AWSReading,
        neighbors: Optional[List[AWSReading]] = None,
        station_data: Optional[Dict[str, Any]] = None
    ) -> AnomalyAlert:
        """
        Full 5-layer anomaly evaluation pipeline producing both an AnomalyAlert
        and a Canonical §16 AnalysisResult.
        """
        stn_id = reading.station_id
        meta = station_data or self._station_meta.get(stn_id, {})
        stn_name = meta.get("name", f"Station {stn_id}")

        # ── 1. Layer 1: Physics Validation (MetPy & Psychrometric boundaries) ──
        score_l1, veto_fired, reason_l1, detail_l1 = self.layer1.evaluate(reading)

        # ── 2. Layer 2: Temporal Pattern (Spikes, Frozen Sensor, Statistical Z-score) ──
        score_l2, ch_scores_l2, reason_l2, detail_l2 = self.layer2.evaluate(reading)

        # ── 3. Layer 3: Multivariate Consistency (Joint State Manifold) ──
        score_l3, reason_l3, detail_l3 = self.layer3.evaluate(reading)

        # ── 4. Layer 4: Spatial Neighbor Consensus (IDW Lapse-rate cross check) ──
        if neighbors is None:
            neighbors = self.get_neighbors_for_reading(reading)
        score_l4, spatial_consensus, reason_l4, detail_l4 = self.layer4.evaluate(reading, neighbors)

        # ── 5. Layer 5: Sensor Drift & Health Tracking (CUSUM & Days to failure) ──
        recent_is_anomaly = bool(veto_fired or score_l1 > 0.7 or score_l2 > 0.7)
        score_l5, health_score, days_to_failure, reason_l5, detail_l5 = self.layer5.evaluate(
            reading, recent_is_anomaly=recent_is_anomaly
        )

        # Assemble layer scores
        layer_scores = {
            "physics": round(float(score_l1), 3),
            "temporal": round(float(score_l2), 3),
            "multivariate": round(float(score_l3), 3),
            "spatial": round(float(score_l4), 3),
            "drift": round(float(score_l5), 3)
        }

        # Gather diagnostic reasons
        reasons = [r for r in [reason_l1, reason_l2, reason_l3, reason_l4, reason_l5] if r]

        # Identify affected channels
        affected = []
        if ch_scores_l2.get("temperature_c", 0) > 0.5 or (score_l1 > 0.5 and "temp" in (reason_l1 or "").lower()):
            affected.append("temperature_c")
        if ch_scores_l2.get("pressure_hpa", 0) > 0.5 or (score_l1 > 0.5 and "press" in (reason_l1 or "").lower()):
            affected.append("pressure_hpa")
        if ch_scores_l2.get("humidity_pct", 0) > 0.5 or (score_l1 > 0.5 and "humid" in (reason_l1 or "").lower()):
            affected.append("humidity_pct")
        if not affected and (score_l4 > 0.5 or score_l3 > 0.5 or veto_fired):
            if reading.channel_valid("temperature_c"):
                affected.append("temperature_c")
            elif reading.channel_valid("pressure_hpa"):
                affected.append("pressure_hpa")
            elif reading.channel_valid("humidity_pct"):
                affected.append("humidity_pct")

        # Layer coverage metrics for conformal fusion
        layer_coverage = {
            "physics": len(detail_l1.get("channels_evaluated", [])) / 3.0,
            "temporal": 1.0 if detail_l2.get("history_points", 0) >= 3 else 0.2,
            "multivariate": detail_l3.get("valid_channel_count", 0) / 3.0,
            "spatial": min(1.0, detail_l4.get("neighbor_count", 0) / 4.0),
            "drift": min(1.0, detail_l5.get("samples_tracked", 0) / 20.0),
        }

        spatial_neighbor_count = detail_l4.get("neighbor_count", 0)
        temporal_history_count = detail_l2.get("history_points", 0)

        # ── 6. Conformal Evidence Fusion (v2: quality-aware, no artificial floor) ──
        is_anomaly, status, severity, confidence, p_val, detail_fusion = self.fusion.fuse(
            layer_scores=layer_scores,
            veto_fired=veto_fired,
            layer_coverage=layer_coverage,
            spatial_neighbor_count=spatial_neighbor_count,
            temporal_history_count=temporal_history_count
        )

        layer_details = {
            "physics": detail_l1,
            "temporal": detail_l2,
            "multivariate": detail_l3,
            "spatial": detail_l4,
            "drift": detail_l5,
            "fusion": detail_fusion,
        }

        # ── 7. Root Cause Analysis (v2: uncertainty tiers & weather vs sensor) ──
        diagnosis_res: DiagnosisResult = self.classifier.classify(
            is_anomaly=is_anomaly,
            layer_scores=layer_scores,
            veto_fired=veto_fired,
            channel_scores=ch_scores_l2,
            spatial_score=score_l4,
            reasons=reasons,
            layer_details=layer_details,
            valid_channel_count=reading.valid_channel_count
        )

        # ── 8. Explainability (v2: confidence-gated language) ──
        explanation = self.explainer.generate_explanation(
            reading=reading,
            fault_type=diagnosis_res.fault_type,
            diagnosis_confidence=diagnosis_res.confidence,
            layer_scores=layer_scores,
            reasons=reasons,
            sensor_health=health_score,
            days_to_failure=days_to_failure,
            primary_signal=diagnosis_res.primary_signal,
            alternatives=diagnosis_res.alternatives,
            layer_details=layer_details
        )

        # ── 9. Self-Healing Imputation ──
        temporal_fallback = {
            "temperature_c": reading.temperature_c,
            "pressure_hpa": reading.pressure_hpa,
            "humidity_pct": reading.humidity_pct
        }
        corrected = self.imputer.correct_reading(
            reading=reading,
            is_anomaly=is_anomaly,
            affected_channel=affected[0] if affected else None,
            spatial_consensus=spatial_consensus,
            temporal_fallback=temporal_fallback
        )

        # ── 10. Meteorological Weather Analysis (Section 14) ──
        weather_analysis = self._generate_weather_analysis(
            reading=reading,
            layer_details=layer_details,
            status=status
        )

        # ── 11. Human-Operator Insights (Section 15) ──
        insights = self._generate_insights(
            reading=reading,
            diagnosis=diagnosis_res,
            status=status,
            severity=severity,
            confidence=confidence,
            layer_scores=layer_scores,
            layer_details=layer_details,
            explanation=explanation
        )

        # ── 12. Data Quality Provenance (Section 4, 16) ──
        data_quality_dict = self._generate_data_quality(
            reading=reading,
            layer_details=layer_details
        )

        # ── 13. Canonical Layer Cards (Section 21) ──
        canonical_layers = self._format_canonical_layers(
            layer_scores=layer_scores,
            layer_details=layer_details,
            veto_fired=veto_fired,
            reason_l1=reason_l1,
            reason_l2=reason_l2,
            reason_l3=reason_l3,
            reason_l4=reason_l4,
            reason_l5=reason_l5,
            health_score=health_score
        )

        # Build Canonical §16 Analysis Object
        canonical_result = {
            "station": {
                "id": stn_id,
                "name": stn_name,
                "latitude": reading.lat,
                "longitude": reading.lon,
            },
            "observation": {
                "timestamp": reading.timestamp.isoformat(),
                "temperature": reading.temperature_c,
                "pressure": reading.pressure_hpa,
                "relative_humidity": reading.humidity_pct,
                "wind_speed": reading.wind_speed_kmh,
                "source": "AWS Station Data"
            },
            "overall": {
                "status": status,
                "score": round(severity, 3),
                "anomaly_score": round(severity, 3),
                "confidence": round(confidence, 3),
                "threshold": 0.45,
                "severity": (
                    "HIGH" if severity >= 0.75 else
                    "WARNING" if severity >= 0.45 else
                    "LOW" if severity > 0.0 else "NONE"
                ),
            },
            "layers": canonical_layers,
            "diagnosis": {
                "primary": diagnosis_res.fault_type.value,
                "confidence": diagnosis_res.confidence.value,
                "confidence_level": diagnosis_res.confidence.value,
                "evidence": diagnosis_res.evidence,
                "alternatives": diagnosis_res.alternatives,
                "affected_channels": affected,
                "operator_action": diagnosis_res.operator_action
            },
            "weather_analysis": weather_analysis,
            "insights": insights,
            "data_quality": data_quality_dict
        }

        # Build AnomalyAlert
        alert = AnomalyAlert(
            station_id=stn_id,
            timestamp=reading.timestamp,
            status=status,
            is_anomaly=is_anomaly,
            severity_score=severity,
            confidence_score=confidence,
            veto_fired=veto_fired,
            root_cause=diagnosis_res.fault_type,
            diagnosis_confidence=diagnosis_res.confidence,
            affected_channels=affected,
            layer_scores=layer_scores,
            layer_details=layer_details,
            reasons=reasons,
            explanation=explanation,
            primary_signal=diagnosis_res.primary_signal,
            alternative_causes=diagnosis_res.alternatives,
            raw_values={
                "temperature_c": reading.temperature_c,
                "pressure_hpa": reading.pressure_hpa,
                "humidity_pct": reading.humidity_pct,
                "wind_speed_kmh": reading.wind_speed_kmh,
            },
            corrected_values=corrected,
            sensor_health_index=health_score,
            estimated_days_to_failure=days_to_failure,
            spatial_neighbor_count=spatial_neighbor_count,
            spatial_neighbor_range_km=detail_l4.get("min_distance_km"),
            temporal_history_points=temporal_history_count,
            data_quality_summary=data_quality_dict,
            operator_action=diagnosis_res.operator_action,
            canonical_result=canonical_result
        )

        self._alerts_cache[stn_id] = alert
        self._canonical_cache[stn_id] = canonical_result
        return alert

    def get_station_alert(self, station_id: str) -> Optional[AnomalyAlert]:
        """Returns cached AnomalyAlert for station."""
        return self._alerts_cache.get(station_id)

    def get_station_canonical(self, station_id: str) -> Optional[Dict[str, Any]]:
        """Returns cached Canonical AnalysisResult for station."""
        return self._canonical_cache.get(station_id)

    # ─────────────────────────────────────────────────────────────────
    # Private Helpers for §14, §15, §16, §21
    # ─────────────────────────────────────────────────────────────────

    def _generate_weather_analysis(
        self,
        reading: AWSReading,
        layer_details: Dict[str, Any],
        status: str
    ) -> Dict[str, Any]:
        """
        Generates genuine meteorological analysis strictly grounded in validated measurements.
        Never outputs generic AI filler. Traceable to actual numbers.
        """
        evidence: List[str] = []
        summary_parts: List[str] = []

        valid_count = reading.valid_channel_count
        if valid_count == 0:
            return {
                "summary": "Insufficient observational data to evaluate current meteorological conditions.",
                "evidence": ["All primary sensor channels (T, P, RH) are missing or offline."]
            }

        # Temperature observation
        if reading.channel_valid("temperature_c") and reading.temperature_c is not None:
            t = reading.temperature_c
            evidence.append(f"Ambient air temperature: {t:.1f}°C")
            if t > 35.0:
                summary_parts.append("Elevated heat conditions")
            elif t < 5.0:
                summary_parts.append("Cold surface temperatures")

        # Pressure observation
        if reading.channel_valid("pressure_hpa") and reading.pressure_hpa is not None:
            p = reading.pressure_hpa
            evidence.append(f"Surface barometric pressure: {p:.1f} hPa")
            if p < 1000.0:
                summary_parts.append("Low-pressure system influence")
            elif p > 1025.0:
                summary_parts.append("High-pressure anticyclonic conditions")

        # Humidity observation
        if reading.channel_valid("humidity_pct") and reading.humidity_pct is not None:
            rh = reading.humidity_pct
            evidence.append(f"Relative humidity: {rh:.1f}%")
            if rh >= 90.0:
                summary_parts.append("Near-saturated atmospheric moisture")
            elif rh <= 20.0:
                summary_parts.append("Arid low-humidity regime")

        # Temporal rate of change evidence
        temporal_detail = layer_details.get("temporal", {})
        if "temp_spike" in temporal_detail:
            ts = temporal_detail["temp_spike"]
            evidence.append(
                f"Rapid temperature shift: {ts['delta_c']:+.1f}°C change in {ts['interval_s']}s "
                f"(previous {ts['previous']:.1f}°C → current {ts['current']:.1f}°C)"
            )
            summary_parts.append("Abrupt thermal transition")

        if "press_spike" in temporal_detail:
            ps = temporal_detail["press_spike"]
            interval_s = ps.get("interval_s", 0)
            delta_hpa = ps.get("delta_hpa", 0.0)
            evidence.append(
                f"Barometric pressure surge: {delta_hpa:+.1f} hPa in {interval_s}s"
            )
            summary_parts.append("Barometric gradient shift")

        # Spatial consistency evidence
        spatial_detail = layer_details.get("spatial", {})
        neighbor_count = spatial_detail.get("neighbor_count", 0)
        if neighbor_count >= 2:
            dist_min = spatial_detail.get("min_distance_km", 0.0)
            dist_max = spatial_detail.get("max_distance_km", 0.0)
            deviations = spatial_detail.get("deviations", {})
            if "temperature_c" in deviations:
                dev = deviations["temperature_c"]
                evidence.append(
                    f"Regional temperature comparison: {dev['dev_c']:+.1f}°C deviation from "
                    f"{dev['neighbors_used']} neighbors within {dist_min:.0f}–{dist_max:.0f} km "
                    f"(target {dev['target_c']:.1f}°C vs regional consensus {dev['consensus_c']:.1f}°C)"
                )
                if abs(dev['dev_c']) > 5.0:
                    summary_parts.append("Localized thermal discrepancy relative to regional mesh")
                else:
                    summary_parts.append("Consistent with regional temperature field")
        else:
            evidence.append(f"Regional cross-validation limited: only {neighbor_count} nearby station(s) within radius.")

        if not summary_parts:
            summary_parts.append("Stable atmospheric conditions within seasonal expectations")

        summary = ". ".join(summary_parts) + "."
        met_context = "Regional mesoscale analysis based on in-situ AWS station observations."
        if neighbor_count >= 2:
            met_context = f"Mesoscale analysis synthesized from local station and {neighbor_count} neighboring observations."
        
        phenomenon = "Nominal atmospheric regime"
        if "Abrupt thermal transition" in summary_parts:
            phenomenon = "Localized frontal boundary passage or microclimate transition"
        elif "Low-pressure system influence" in summary_parts:
            phenomenon = "Cyclonic or depression trough system"
        elif "Elevated heat conditions" in summary_parts:
            phenomenon = "Diurnal heat peak or local thermal plume"
        elif "Near-saturated atmospheric moisture" in summary_parts:
            phenomenon = "Surface saturation, mist, or active precipitation"
            
        weather_confidence = "HIGH" if valid_count >= 2 and neighbor_count >= 2 else ("MEDIUM" if valid_count >= 1 else "LOW")

        return {
            "summary": summary,
            "meteorological_context": met_context,
            "likely_phenomenon": phenomenon,
            "confidence": weather_confidence,
            "evidence": evidence
        }

    def _generate_insights(
        self,
        reading: AWSReading,
        diagnosis: DiagnosisResult,
        status: str,
        severity: float,
        confidence: float,
        layer_scores: Dict[str, float],
        layer_details: Dict[str, Any],
        explanation: str
    ) -> List[Dict[str, Any]]:
        """
        Generates structured, actionable insights answering:
        WHAT? WHY? EVIDENCE? WHAT SHOULD THE OPERATOR DO?
        Categories: monitor, verify observation, compare with neighboring stations, inspect sensor, continue monitoring, insufficient evidence.
        """
        insights = []

        if status == "NORMAL":
            insights.append({
                "what": "Telemetry operates within certified normal boundaries.",
                "why": "All 5 analytical layers confirm physical, temporal, and spatial coherence.",
                "evidence": f"Physics score: {layer_scores['physics']:.2f}, Temporal: {layer_scores['temporal']:.2f}, Spatial: {layer_scores['spatial']:.2f}.",
                "action": "Continue automated routine monitoring."
            })
            return insights

        # If data is insufficient
        if status == "INSUFFICIENT_DATA" or diagnosis.confidence == DiagnosisConfidence.INSUFFICIENT_DATA:
            insights.append({
                "what": "Telemetry baseline insufficient for conclusive fault diagnosis.",
                "why": diagnosis.primary_signal,
                "evidence": "; ".join(diagnosis.evidence) if diagnosis.evidence else "Limited historical or spatial data points.",
                "action": "Collect additional telemetry frames before initiating hardware intervention."
            })
            return insights

        # Anomaly / Warning case
        action_verb = "Inspect" if diagnosis.confidence == DiagnosisConfidence.HIGH else "Monitor & Verify"
        insights.append({
            "what": f"{diagnosis.confidence.value} confidence detection: {diagnosis.fault_type.value}.",
            "why": diagnosis.primary_signal,
            "evidence": "; ".join(diagnosis.evidence) if diagnosis.evidence else explanation,
            "action": diagnosis.operator_action or f"{action_verb} station telemetry before making operational adjustments."
        })

        # Spatial corroboration insight
        spatial_detail = layer_details.get("spatial", {})
        if spatial_detail.get("neighbor_count", 0) >= 2:
            insights.append({
                "what": "Regional spatial peer comparison available.",
                "why": f"Cross-referenced against {spatial_detail['neighbor_count']} stations.",
                "evidence": f"Consensus comparison range: {spatial_detail.get('min_distance_km', 0):.0f}–{spatial_detail.get('max_distance_km', 0):.0f} km.",
                "action": "Cross-check station siting and microclimate exposure."
            })

        return insights

    def _generate_data_quality(
        self,
        reading: AWSReading,
        layer_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Builds the provenance and data quality summary block.
        """
        missing = []
        zero_sub = []
        valid = []
        for ch, q in reading.data_quality.items():
            if q == DataQuality.MISSING:
                missing.append(ch)
            elif q == DataQuality.ZERO_SUBSTITUTED:
                zero_sub.append(ch)
            elif q == DataQuality.VALID:
                valid.append(ch)

        temporal_detail = layer_details.get("temporal", {})
        spatial_detail = layer_details.get("spatial", {})

        history_pts = temporal_detail.get("history_points", 0)
        neighbors = spatial_detail.get("neighbor_count", 0)

        limitations = []
        if zero_sub:
            limitations.append(f"Fields with 0.0 treated as missing (not genuine zero): {', '.join(zero_sub)}")
        if missing:
            limitations.append(f"Missing channels: {', '.join(missing)}")
        if history_pts < 3:
            limitations.append(f"Limited historical sequence ({history_pts} points); temporal rate-of-change check restricted")
        if neighbors < 2:
            limitations.append(f"Sparse regional coverage ({neighbors} neighbors within radius); spatial consensus check limited")

        dq_status = (
            "VALID" if len(valid) == 3 and not limitations else
            "DEGRADED" if len(valid) >= 1 else
            "INSUFFICIENT_DATA"
        )

        return {
            "status": dq_status,
            "valid_fields": valid,
            "missing_fields": missing,
            "zero_substituted_fields": zero_sub,
            "historical_points": history_pts,
            "nearby_stations": neighbors,
            "limitations": limitations
        }

    def _format_canonical_layers(
        self,
        layer_scores: Dict[str, float],
        layer_details: Dict[str, Any],
        veto_fired: bool,
        reason_l1: Optional[str],
        reason_l2: Optional[str],
        reason_l3: Optional[str],
        reason_l4: Optional[str],
        reason_l5: Optional[str],
        health_score: float
    ) -> Dict[str, Any]:
        """
        Formats the 5 layer diagnostic cards according to §21:
        LAYER NAME, STATUS, SCORE, CONFIDENCE / EVIDENCE QUALITY, ONE-LINE REASON.
        """
        d1 = layer_details.get("physics", {})
        d2 = layer_details.get("temporal", {})
        d3 = layer_details.get("multivariate", {})
        d4 = layer_details.get("spatial", {})
        d5 = layer_details.get("drift", {})

        # 1. Physics
        ch_eval1 = d1.get("channels_evaluated", [])
        if not ch_eval1:
            l1_status = "LIMITED"
            l1_conf = "INSUFFICIENT_DATA"
            l1_reason = "No valid channels available for physical limit verification"
        elif veto_fired:
            l1_status = "VETO"
            l1_conf = "HIGH"
            l1_reason = reason_l1 or "Real telemetry violates fundamental thermodynamic constraints"
        elif layer_scores["physics"] >= 0.70:
            l1_status = "WARNING"
            l1_conf = "HIGH"
            l1_reason = reason_l1 or "Physical boundary proximity detected"
        else:
            l1_status = "PASS"
            l1_conf = "HIGH"
            l1_reason = "All observed parameters fall within thermodynamic terrestrial envelopes"

        # 2. Temporal
        h_pts = d2.get("history_points", 0)
        if h_pts < 3 or d2.get("status") == "INSUFFICIENT_DATA":
            l2_status = "INSUFFICIENT_DATA"
            l2_conf = "INSUFFICIENT_DATA"
            l2_reason = f"Insufficient temporal history ({h_pts} samples recorded, 3 required)"
        elif layer_scores["temporal"] >= 0.70:
            l2_status = "ANOMALY"
            l2_conf = "HIGH" if h_pts >= 6 else "MEDIUM"
            l2_reason = reason_l2 or "Step-rate or frozen value anomaly detected"
        elif layer_scores["temporal"] >= 0.40:
            l2_status = "WARNING"
            l2_conf = "MEDIUM"
            l2_reason = reason_l2 or "Elevated rate of change observed"
        else:
            l2_status = "PASS"
            l2_conf = "HIGH"
            l2_reason = "Time-series variance and rate of change within nominal thresholds"

        # 3. Multivariate
        v_cnt = d3.get("valid_channel_count", 0)
        if v_cnt < 2 or d3.get("status") == "INSUFFICIENT_DATA":
            l3_status = "INSUFFICIENT_DATA"
            l3_conf = "INSUFFICIENT_DATA"
            l3_reason = f"Multivariate analysis requires ≥2 valid channels ({v_cnt} available)"
        elif layer_scores["multivariate"] >= 0.75:
            l3_status = "ANOMALY"
            l3_conf = "HIGH" if v_cnt == 3 else "MEDIUM"
            l3_reason = reason_l3 or "Unfeasible joint atmospheric state distribution"
        elif layer_scores["multivariate"] >= 0.50:
            l3_status = "WARNING"
            l3_conf = "MEDIUM"
            l3_reason = reason_l3 or "Moderate joint-channel divergence"
        else:
            l3_status = "PASS"
            l3_conf = "HIGH"
            l3_reason = f"Joint state manifold ({d3.get('test_performed', 'bivariate')}) consistent"

        # 4. Spatial
        n_cnt = d4.get("neighbor_count", 0)
        if n_cnt < 2 or d4.get("status") == "INSUFFICIENT_DATA":
            l4_status = "INSUFFICIENT_DATA"
            l4_conf = "INSUFFICIENT_DATA"
            l4_reason = f"Insufficient neighboring stations within radius ({n_cnt} found, 2 required)"
        elif layer_scores["spatial"] >= 0.70:
            l4_status = "ANOMALY"
            l4_conf = "HIGH" if n_cnt >= 4 else "MEDIUM"
            l4_reason = reason_l4 or "Severe divergence from regional consensus"
        elif layer_scores["spatial"] >= 0.45:
            l4_status = "WARNING"
            l4_conf = "MEDIUM"
            l4_reason = reason_l4 or "Marginal divergence from regional cluster"
        else:
            l4_status = "PASS"
            l4_conf = "HIGH" if n_cnt >= 4 else "MEDIUM"
            l4_reason = f"Consistent with {n_cnt} regional stations"

        # 5. Sensor Health / Drift
        s_cnt = d5.get("samples_tracked", 0)
        if s_cnt < 5:
            l5_status = "INSUFFICIENT_DATA"
            l5_conf = "INSUFFICIENT_DATA"
            l5_reason = f"Drift monitoring initializing ({s_cnt} samples tracked)"
        elif layer_scores["drift"] >= 0.70:
            l5_status = "ANOMALY"
            l5_conf = "HIGH" if s_cnt >= 20 else "MEDIUM"
            l5_reason = reason_l5 or "Progressive sensor calibration drift detected"
        elif layer_scores["drift"] >= 0.40:
            l5_status = "WARNING"
            l5_conf = "MEDIUM"
            l5_reason = reason_l5 or "Minor cumulative calibration bias accumulating"
        else:
            l5_status = "PASS"
            l5_conf = "HIGH"
            l5_reason = f"Sensor health index nominal ({health_score:.0f}%)"

        return {
            "physics": {
                "name": "Physics Validation",
                "status": l1_status,
                "score": layer_scores["physics"],
                "evidence_quality": l1_conf,
                "reason": l1_reason,
                "details": d1,
            },
            "temporal": {
                "name": "Temporal Pattern",
                "status": l2_status,
                "score": layer_scores["temporal"],
                "evidence_quality": l2_conf,
                "reason": l2_reason,
                "details": d2,
            },
            "multivariate": {
                "name": "Multivariate Consistency",
                "status": l3_status,
                "score": layer_scores["multivariate"],
                "evidence_quality": l3_conf,
                "reason": l3_reason,
                "details": d3,
            },
            "spatial": {
                "name": "Spatial Consensus",
                "status": l4_status,
                "score": layer_scores["spatial"],
                "evidence_quality": l4_conf,
                "reason": l4_reason,
                "details": d4,
            },
            "sensor_health": {
                "name": "Sensor Health & Drift",
                "status": l5_status,
                "score": layer_scores["drift"],
                "evidence_quality": l5_conf,
                "reason": l5_reason,
                "details": d5,
            },
        }


# Singleton detector instance
detector = AnomalyDetector()
