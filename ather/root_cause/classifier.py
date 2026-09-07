"""
Root-Cause Classifier for AWS Anomaly Diagnosis.
Categorizes detected anomalies into actionable engineering fault classes:
- SENSOR_SPIKE
- FROZEN_SENSOR
- CALIBRATION_DRIFT
- NOISE_BURST
- SINGLE_CHANNEL_FAULT
- GENUINE_EXTREME_WEATHER (differentiates natural meteorological events from hardware failure)
"""
from typing import Dict, List, Optional
import numpy as np

from ather.data.schema import FaultType

class RootCauseClassifier:
    """
    Diagnoses the underlying physical or mechanical root-cause of an anomaly.
    """
    def __init__(self):
        pass

    def classify(
        self,
        is_anomaly: bool,
        layer_scores: Dict[str, float],
        veto_fired: bool,
        channel_scores: Dict[str, float],
        spatial_score: float,
        reasons: List[str]
    ) -> FaultType:
        """
        Determines the specific FaultType based on multi-layer evidence signatures.
        """
        if not is_anomaly:
            return FaultType.NORMAL

        # 1. Physical VETO -> Severe Single Channel or Instrument Disconnect
        if veto_fired:
            # Check which channel is physically impossible
            for ch, score in channel_scores.items():
                if score > 0.8:
                    return FaultType.SINGLE_CHANNEL_FAULT
            return FaultType.SINGLE_CHANNEL_FAULT

        # 2. Frozen / Stuck Sensor
        temporal_score = layer_scores.get("temporal", 0.0)
        reasons_text = " ".join(reasons).lower()
        if "frozen" in reasons_text or "identical" in reasons_text:
            return FaultType.FROZEN_SENSOR

        # 3. Sudden Sensor Spike (abrupt step change)
        if "spike" in reasons_text:
            return FaultType.SENSOR_SPIKE

        # 4. Genuine Extreme Weather Distinction
        # An extreme weather event (e.g. squall line, gust front):
        # - High temporal rate-of-change
        # - NEIGHBORS AGREE (spatial_score is low < 0.35)
        # - Thermodynamic laws are valid (veto_fired is False)
        if temporal_score > 0.6 and spatial_score < 0.35 and not veto_fired:
            return FaultType.GENUINE_EXTREME_WEATHER

        # 5. Calibration Drift (slow cumulative deviation without abrupt spike)
        drift_score = layer_scores.get("drift", 0.0)
        if drift_score > 0.65 and "drift" in reasons_text:
            return FaultType.CALIBRATION_DRIFT

        # 6. High-Frequency Noise
        if "noise" in reasons_text or "statistical outlier" in reasons_text:
            return FaultType.NOISE_BURST

        # 7. Spatial Disagreement without Extreme Weather
        if spatial_score > 0.7:
            return FaultType.SINGLE_CHANNEL_FAULT

        return FaultType.SENSOR_SPIKE
