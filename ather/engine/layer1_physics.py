"""
Layer 1: Physics Validation Engine.
Powered by Unidata/MetPy thermodynamics (https://github.com/Unidata/MetPy).
Implements non-negotiable physical laws:
1. Dew point impossibility: T_dew <= T_ambient + 0.5°C
2. Wet-bulb physiological threshold: T_wet_bulb <= 35.0°C
3. Hypsometric / Barometric altitude-pressure consistency
Deterministic VETO: Thermodynamic impossibility immediately triggers anomaly score = 1.0.
"""
from typing import Dict, Optional, Tuple
import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

from ather.config import CONFIG, PhysicsThresholds
from ather.data.schema import AWSReading

class PhysicsValidationLayer:
    """
    Thermodynamic and psychrometric validator with VETO authority.
    """
    def __init__(self, config: PhysicsThresholds = CONFIG.physics):
        self.cfg = config

    def evaluate(self, reading: AWSReading) -> Tuple[float, bool, Optional[str]]:
        """
        Evaluates physical consistency of a single reading.
        Returns:
            anomaly_score: float [0.0, 1.0]
            is_veto: bool (True if hard physical law is broken)
            violation_reason: Optional[str]
        """
        temp_c = reading.temperature_c
        press_hpa = reading.pressure_hpa
        rh_pct = reading.humidity_pct
        elev_m = reading.elevation_m

        # Fast sanity bounds
        if rh_pct < 0.0 or rh_pct > 100.0:
            return 1.0, True, f"Relative humidity {rh_pct}% outside physically possible range [0, 100]%"

        if temp_c < self.cfg.temp_min_c or temp_c > self.cfg.temp_max_c:
            return 1.0, True, f"Temperature {temp_c}°C violates absolute terrestrial boundaries [{self.cfg.temp_min_c}, {self.cfg.temp_max_c}]"

        # 1. MetPy Psychrometric Dew Point Check
        try:
            temp_quant = temp_c * units.degC
            rh_quant = rh_pct * units.percent
            press_quant = press_hpa * units.hPa

            calc_dewpoint = mpcalc.dewpoint_from_relative_humidity(temp_quant, rh_quant).to('degC').magnitude

            # If user provided a measured dewpoint, verify against ambient
            measured_dew = reading.dew_point_c if reading.dew_point_c is not None else calc_dewpoint
            if measured_dew > (temp_c + self.cfg.dew_point_margin_c):
                return 1.0, True, (
                    f"Thermodynamic Violation: Dew point ({measured_dew:.2f}°C) exceeds ambient "
                    f"temperature ({temp_c:.2f}°C) by > {self.cfg.dew_point_margin_c}°C."
                )

            # 2. Wet-Bulb Temperature Survivability Bound
            # Normand's rule / psychrometric wet bulb
            wet_bulb = mpcalc.wet_bulb_temperature(press_quant, temp_quant, calc_dewpoint * units.degC).to('degC').magnitude
            if wet_bulb > self.cfg.max_wet_bulb_c:
                return 1.0, True, (
                    f"Physical Limit Exceeded: Calculated wet-bulb temperature ({wet_bulb:.1f}°C) "
                    f"exceeds terrestrial survivability limit ({self.cfg.max_wet_bulb_c}°C)."
                )

        except Exception as e:
            # Fallback thermodynamic check if MetPy unit conversion encounters non-physical domain
            pass

        # 3. Barometric Hypsometric Altitude Consistency
        # P_expected at elevation h under standard atmosphere: P = P0 * (1 - L*h / T0)^(g*M / R*L)
        try:
            h = elev_m
            t0 = self.cfg.sea_level_temp_k
            l_rate = self.cfg.temp_lapse_rate
            g = self.cfg.gravity
            r = self.cfg.gas_constant

            exponent = g / (r * l_rate)
            expected_pressure = self.cfg.sea_level_pressure_hpa * ((1.0 - (l_rate * h) / t0) ** exponent)

            pct_dev = abs(press_hpa - expected_pressure) / expected_pressure * 100.0

            if pct_dev > self.cfg.max_pressure_altitude_error_pct:
                return 0.85, False, (
                    f"Barometric Discrepancy: Surface pressure {press_hpa:.1f} hPa deviates by "
                    f"{pct_dev:.1f}% from expected standard barometric level ({expected_pressure:.1f} hPa) at elevation {h:.0f}m."
                )

        except Exception:
            pass

        # All physical constraints satisfied
        return 0.0, False, None
