"""
Data Quality Controller: Stage-0 sanity checks, missing data handling, and range validation.
"""
from typing import Dict, Optional, Tuple
import numpy as np

from ather.config import CONFIG
from ather.data.schema import AWSReading

class QualityController:
    """
    Initial fast ingestion quality gate for incoming telemetry.
    Rejects malformed packets and flags gross physical boundary failures.
    """
    def __init__(self, config=CONFIG.physics):
        self.cfg = config

    def validate_reading(self, reading: AWSReading) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_valid, error_reason).
        """
        # 1. Missing / NaN values
        if np.isnan(reading.temperature_c):
            return False, "Missing temperature reading (NaN)"
        if np.isnan(reading.pressure_hpa):
            return False, "Missing pressure reading (NaN)"
        if np.isnan(reading.humidity_pct):
            return False, "Missing humidity reading (NaN)"

        # 2. Hard physical operating boundaries
        if not (self.cfg.temp_min_c <= reading.temperature_c <= self.cfg.temp_max_c):
            return False, f"Temperature {reading.temperature_c}°C outside sensor bounds [{self.cfg.temp_min_c}, {self.cfg.temp_max_c}]"

        if not (self.cfg.pressure_min_hpa <= reading.pressure_hpa <= self.cfg.pressure_max_hpa):
            return False, f"Pressure {reading.pressure_hpa} hPa outside sensor bounds [{self.cfg.pressure_min_hpa}, {self.cfg.pressure_max_hpa}]"

        if not (self.cfg.humidity_min_pct <= reading.humidity_pct <= self.cfg.humidity_max_pct):
            return False, f"Relative humidity {reading.humidity_pct}% outside valid range [0, 100]%"

        return True, None
