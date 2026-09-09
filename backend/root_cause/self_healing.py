"""
Self-Healing and Sensor Value Imputation Engine.
Generates estimated/corrected values when sensors fail, preserving data continuity.
Always maintains the raw original telemetry alongside the imputed value.
Methods:
1. Spatial Neighbor Inverse Distance Weighting (IDW)
2. Physical Thermodynamic Inversion (Magnus-Tetens)
3. Temporal Autoregressive Exponential Smoothing
"""
from typing import Dict, List, Optional
import numpy as np

from schema import AWSReading

class SelfHealingImputer:
    """
    Synthesizes physically coherent replacement values for faulty sensor channels.
    """
    def __init__(self):
        # Magnus constants for psychrometric inversion
        self.a = 17.625
        self.b = 243.04

    def impute_from_physics(self, reading: AWSReading, faulty_channel: str) -> Optional[float]:
        """
        Uses thermodynamic relations between (T, RH, Tdew) to estimate the missing channel.
        """
        t = reading.temperature_c
        rh = reading.humidity_pct
        tdew = reading.dew_point_c

        if faulty_channel == "humidity_pct" and tdew is not None and t is not None:
            try:
                gamma_dew = (self.a * tdew) / (self.b + tdew)
                gamma_t = (self.a * t) / (self.b + t)
                est_rh = 100.0 * np.exp(gamma_dew - gamma_t)
                return float(np.clip(est_rh, 0.0, 100.0))
            except Exception:
                pass

        elif faulty_channel == "temperature_c" and tdew is not None and rh is not None and rh > 5.0:
            try:
                gamma_dew = (self.a * tdew) / (self.b + tdew)
                alpha = gamma_dew - np.log(rh / 100.0)
                est_t = (self.b * alpha) / (self.a - alpha)
                return float(est_t)
            except Exception:
                pass

        return None

    def correct_reading(
        self,
        reading: AWSReading,
        is_anomaly: bool,
        affected_channel: Optional[str] = None,
        spatial_consensus: Optional[Dict[str, Optional[float]]] = None,
        temporal_fallback: Optional[Dict[str, Optional[float]]] = None
    ) -> Dict[str, Optional[float]]:
        """
        Returns a dict of corrected values for [temperature_c, pressure_hpa, humidity_pct].
        If reading is normal, returns raw values.
        """
        corrected: Dict[str, Optional[float]] = {
            "temperature_c": reading.temperature_c,
            "pressure_hpa": reading.pressure_hpa,
            "humidity_pct": reading.humidity_pct
        }

        if not is_anomaly:
            return corrected

        channels_to_fix = [affected_channel] if (affected_channel and affected_channel in corrected) else list(corrected.keys())

        for ch in channels_to_fix:
            imputed_val = None

            # Priority 1: Spatial neighbor consensus
            if spatial_consensus is not None and spatial_consensus.get(ch) is not None:
                imputed_val = spatial_consensus[ch]

            # Priority 2: Thermodynamic cross-channel inversion
            if imputed_val is None:
                imputed_val = self.impute_from_physics(reading, ch)

            # Priority 3: Temporal historical fallback
            if imputed_val is None and temporal_fallback is not None and temporal_fallback.get(ch) is not None:
                imputed_val = temporal_fallback[ch]

            if imputed_val is not None:
                corrected[ch] = round(float(imputed_val), 2)

        return corrected
