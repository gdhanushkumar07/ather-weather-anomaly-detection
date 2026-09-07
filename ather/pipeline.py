"""
ATHER Master Pipeline Coordinator.
Orchestrates the 5 detection layers, conformal evidence fusion, root-cause diagnosis,
explanation generation, and self-healing value imputation into a unified inference flow.
"""
from datetime import datetime
import time
from typing import Dict, List, Optional, Tuple
import pandas as pd

from ather.config import CONFIG, AtherConfig
from ather.data.schema import AWSReading, AnomalyAlert, FaultType
from ather.engine.layer1_physics import PhysicsValidationLayer
from ather.engine.layer2_temporal import TemporalPatternLayer
from ather.engine.layer3_multivariate import MultivariateConsistencyLayer
from ather.engine.layer4_spatial import SpatialNeighborLayer
from ather.engine.layer5_drift import SensorDriftHealthLayer
from ather.fusion.conformal_fusion import ConformalEvidenceFusion
from ather.root_cause.classifier import RootCauseClassifier
from ather.root_cause.explainability import ExplanationGenerator
from ather.root_cause.self_healing import SelfHealingImputer

class AtherPipeline:
    """
    End-to-end anomaly detection pipeline for Automatic Weather Stations.
    """
    def __init__(self, config: AtherConfig = CONFIG):
        self.cfg = config

        # Initialize the 5 core detection layers
        self.layer1_physics = PhysicsValidationLayer(self.cfg.physics)
        self.layer2_temporal = TemporalPatternLayer(self.cfg.temporal)
        self.layer3_multivariate = MultivariateConsistencyLayer()
        self.layer4_spatial = SpatialNeighborLayer(self.cfg.spatial)
        self.layer5_drift = SensorDriftHealthLayer(self.cfg.drift)

        # Decision, classification, and explanation components
        self.fusion = ConformalEvidenceFusion(self.cfg.fusion)
        self.classifier = RootCauseClassifier()
        self.explainer = ExplanationGenerator()
        self.imputer = SelfHealingImputer()

    def train_and_calibrate(self, clean_df: pd.DataFrame, calibration_samples: int = 5000):
        """
        Fits multivariate manifolds and calibrates conformal false alarm bounds on clean series.
        """
        # 1. Fit multivariate layer
        n = len(clean_df)
        split_fit = int(n * 0.7)
        fit_df = clean_df.iloc[:split_fit]
        self.layer3_multivariate.fit(fit_df)

        # 2. Collect baseline non-conformity scores on clean validation slice
        calib_slice = clean_df.iloc[split_fit:split_fit + calibration_samples]
        if len(calib_slice) < 50:
            calib_slice = clean_df.iloc[split_fit:]
        clean_scores_list = []

        for _, row in calib_slice.iterrows():
            reading = AWSReading(
                station_id=self.cfg.default_station_id,
                timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                temperature_c=float(row["temperature_c"]),
                pressure_hpa=float(row["pressure_hpa"]),
                humidity_pct=float(row["humidity_pct"]),
                dew_point_c=float(row["dew_point_c"]) if "dew_point_c" in row and pd.notna(row["dew_point_c"]) else None,
                lat=self.cfg.default_lat,
                lon=self.cfg.default_lon,
                elevation_m=self.cfg.default_elevation_m
            )
            # Evaluate layers
            s1, _, _ = self.layer1_physics.evaluate(reading)
            s2, _, _ = self.layer2_temporal.evaluate(reading)
            s3, _ = self.layer3_multivariate.evaluate(reading)
            s5, _, _, _ = self.layer5_drift.evaluate(reading, recent_is_anomaly=False)

            clean_scores_list.append({
                "physics": s1,
                "temporal": s2,
                "multivariate": s3,
                "spatial": 0.0,
                "drift": s5
            })

        # 3. Calibrate conformal fusion threshold
        self.fusion.calibrate(clean_scores_list, alpha=self.cfg.fusion.target_false_alarm_rate)

        # 4. Clear calibration residue from temporal and drift state
        self.layer2_temporal.buffers.clear()
        self.layer5_drift.trackers.clear()

    def process_reading(
        self,
        reading: AWSReading,
        neighbor_readings: Optional[List[AWSReading]] = None,
        fast_path_only: bool = False
    ) -> AnomalyAlert:
        """
        Processes a single incoming AWS telemetry reading through the detection pipeline.
        Supports fast-path mode (< 1ms execution) or full 5-layer ensemble.
        """
        reasons: List[str] = []
        layer_scores: Dict[str, float] = {}

        # -------------------------------------------------------------
        # FAST-PATH LAYER 1: Physics Validation (Deterministic VETO)
        # -------------------------------------------------------------
        score_phys, is_veto, reason_phys = self.layer1_physics.evaluate(reading)
        layer_scores["physics"] = score_phys
        if reason_phys:
            reasons.append(reason_phys)

        # -------------------------------------------------------------
        # FAST-PATH LAYER 2: Temporal Dynamics & Step Rate
        # -------------------------------------------------------------
        score_temp, channel_temp_scores, reason_temp = self.layer2_temporal.evaluate(reading)
        layer_scores["temporal"] = score_temp
        if reason_temp:
            reasons.append(reason_temp)

        # If fast-path only and veto or high temporal spike, can exit early
        if fast_path_only and is_veto:
            layer_scores["multivariate"] = 0.0
            layer_scores["spatial"] = 0.0
            layer_scores["drift"] = 0.0
            is_anomaly = True
            severity = 1.0
            confidence = 1.0
            p_val = 0.0
            fault_type = FaultType.SINGLE_CHANNEL_FAULT
            health = 50.0
            days_to_fail = 0.0
            explanation = self.explainer.generate_explanation(
                reading, fault_type, layer_scores, reasons, health, days_to_fail
            )
            raw_vals = {"temperature_c": reading.temperature_c, "pressure_hpa": reading.pressure_hpa, "humidity_pct": reading.humidity_pct}
            corrected_vals = self.imputer.correct_reading(reading, is_anomaly=True)
            return AnomalyAlert(
                station_id=reading.station_id,
                timestamp=reading.timestamp,
                is_anomaly=is_anomaly,
                severity_score=severity,
                confidence_score=confidence,
                veto_fired=True,
                root_cause=fault_type,
                affected_channels=["temperature_c" if score_phys > 0 else "humidity_pct"],
                layer_scores=layer_scores,
                explanation=explanation,
                raw_values=raw_vals,
                corrected_values=corrected_vals,
                sensor_health_index=health,
                estimated_days_to_failure=days_to_fail
            )

        # -------------------------------------------------------------
        # FULL-PATH LAYER 3: Multivariate Consistency
        # -------------------------------------------------------------
        score_mv, reason_mv = self.layer3_multivariate.evaluate(reading)
        layer_scores["multivariate"] = score_mv
        if reason_mv:
            reasons.append(reason_mv)

        # -------------------------------------------------------------
        # FULL-PATH LAYER 4: Spatial / Neighbor Analysis
        # -------------------------------------------------------------
        spatial_consensus = None
        if neighbor_readings:
            score_sp, spatial_consensus, reason_sp = self.layer4_spatial.evaluate(reading, neighbor_readings)
            layer_scores["spatial"] = score_sp
            if reason_sp:
                reasons.append(reason_sp)
        else:
            layer_scores["spatial"] = 0.0

        # -------------------------------------------------------------
        # FULL-PATH LAYER 5: Sensor Drift & Health Tracking
        # -------------------------------------------------------------
        prelim_anomaly = (is_veto or score_temp > 0.6 or score_mv > 0.7)
        score_drift, health_score, days_to_fail, reason_drift = self.layer5_drift.evaluate(
            reading, recent_is_anomaly=prelim_anomaly
        )
        layer_scores["drift"] = score_drift
        if reason_drift:
            reasons.append(reason_drift)

        # -------------------------------------------------------------
        # EVIDENCE FUSION & CONFORMAL DECISION
        # -------------------------------------------------------------
        is_anomaly, severity, confidence, p_val = self.fusion.fuse(layer_scores, veto_fired=is_veto)

        # -------------------------------------------------------------
        # ROOT-CAUSE CLASSIFICATION
        # -------------------------------------------------------------
        fault_type = self.classifier.classify(
            is_anomaly=is_anomaly,
            layer_scores=layer_scores,
            veto_fired=is_veto,
            channel_scores=channel_temp_scores,
            spatial_score=layer_scores.get("spatial", 0.0),
            reasons=reasons
        )

        # Identify affected channel
        affected_channels = [ch for ch, s in channel_temp_scores.items() if s > 0.5]

        # -------------------------------------------------------------
        # EXPLAINABLE AI (XAI) DIAGNOSTIC GENERATION
        # -------------------------------------------------------------
        explanation = self.explainer.generate_explanation(
            reading=reading,
            fault_type=fault_type,
            layer_scores=layer_scores,
            reasons=reasons,
            sensor_health=health_score,
            days_to_failure=days_to_fail
        )

        # -------------------------------------------------------------
        # SELF-HEALING VALUE IMPUTATION
        # -------------------------------------------------------------
        raw_vals = {
            "temperature_c": reading.temperature_c,
            "pressure_hpa": reading.pressure_hpa,
            "humidity_pct": reading.humidity_pct
        }
        corrected_vals = self.imputer.correct_reading(
            reading=reading,
            is_anomaly=is_anomaly,
            affected_channel=affected_channels[0] if affected_channels else None,
            spatial_consensus=spatial_consensus
        )

        return AnomalyAlert(
            station_id=reading.station_id,
            timestamp=reading.timestamp,
            is_anomaly=is_anomaly,
            severity_score=severity,
            confidence_score=confidence,
            veto_fired=is_veto,
            root_cause=fault_type,
            affected_channels=affected_channels,
            layer_scores=layer_scores,
            explanation=explanation,
            raw_values=raw_vals,
            corrected_values=corrected_vals,
            sensor_health_index=health_score,
            estimated_days_to_failure=days_to_fail
        )
