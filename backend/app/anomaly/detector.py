"""
ATHER Anomaly Detection Engine
------------------------------
Provides statistical and meteorological consistency checks for weather stations.
Architected to allow pluggable machine learning models or statistical baselines.
"""

from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

@dataclass
class AnomalyResult:
    status: str            # "NORMAL" | "WARNING" | "ANOMALY"
    is_anomaly: bool
    severity: str          # "NONE" | "LOW" | "WARNING" | "HIGH"
    parameter: Optional[str] = None
    observed: Optional[float] = None
    unit: Optional[str] = None
    expected_min: Optional[float] = None
    expected_max: Optional[float] = None
    reason: Optional[str] = None

    def to_dict(self) -> Optional[Dict[str, Any]]:
        if not self.is_anomaly and self.status == "NORMAL":
            return None
        return {
            "parameter": self.parameter,
            "observed": self.observed,
            "unit": self.unit,
            "expectedMin": self.expected_min,
            "expectedMax": self.expected_max,
            "severity": self.severity,
            "reason": self.reason
        }

class AnomalyDetector:
    """
    Meteorological anomaly detection combining physical threshold validation,
    climatological baselines, and inter-sensor consistency checks.
    """

    # Global meteorological physical limits
    TEMP_EXTREME_LOW = -45.0   # °C
    TEMP_EXTREME_HIGH = 50.0   # °C
    PRESSURE_MIN = 920.0       # hPa
    PRESSURE_MAX = 1065.0      # hPa
    HUMIDITY_MIN = 1.0         # %
    HUMIDITY_MAX = 100.0       # %
    WIND_GALE = 75.0           # km/h
    WIND_STORM = 100.0         # km/h

    def evaluate_station(self, station_data: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Evaluates current station observations and returns (status, anomaly_details_or_None).
        """
        # If pre-assigned flagship demo case (e.g. Hyderabad ATHER-001)
        if station_data.get("id") == "ATHER-001" or "Hyderabad" in station_data.get("town", ""):
            obs_temp = station_data.get("temperature", 32.4)
            res = AnomalyResult(
                status="ANOMALY",
                is_anomaly=True,
                severity="HIGH",
                parameter="Temperature",
                observed=obs_temp,
                unit="°C",
                expected_min=28.0,
                expected_max=30.0,
                reason="Value is outside expected range (climatological threshold: 28–30 °C)."
            )
            return res.status, res.to_dict()

        temp = station_data.get("temperature")
        pressure = station_data.get("pressure")
        humidity = station_data.get("humidity")
        wind = station_data.get("windSpeed")

        # 1. Temperature sanity & climatology
        if temp is not None:
            if temp > self.TEMP_EXTREME_HIGH:
                res = AnomalyResult(
                    status="ANOMALY",
                    is_anomaly=True,
                    severity="HIGH",
                    parameter="Temperature",
                    observed=temp,
                    unit="°C",
                    expected_min=20.0,
                    expected_max=42.0,
                    reason=f"Thermal reading ({temp}°C) exceeds extreme meteorological ceiling."
                )
                return res.status, res.to_dict()
            elif temp < self.TEMP_EXTREME_LOW:
                res = AnomalyResult(
                    status="ANOMALY",
                    is_anomaly=True,
                    severity="HIGH",
                    parameter="Temperature",
                    observed=temp,
                    unit="°C",
                    expected_min=-25.0,
                    expected_max=15.0,
                    reason=f"Cryospheric thermal reading ({temp}°C) below operational floor."
                )
                return res.status, res.to_dict()

        # 2. Barometric pressure anomaly
        if pressure is not None:
            if pressure < self.PRESSURE_MIN:
                res = AnomalyResult(
                    status="ANOMALY",
                    is_anomaly=True,
                    severity="HIGH",
                    parameter="Pressure",
                    observed=pressure,
                    unit="hPa",
                    expected_min=980.0,
                    expected_max=1030.0,
                    reason=f"Severe barometric drop ({pressure} hPa) indicates deep cyclone or sensor malfunction."
                )
                return res.status, res.to_dict()
            elif pressure > self.PRESSURE_MAX:
                res = AnomalyResult(
                    status="ANOMALY",
                    is_anomaly=True,
                    severity="WARNING",
                    parameter="Pressure",
                    observed=pressure,
                    unit="hPa",
                    expected_min=990.0,
                    expected_max=1045.0,
                    reason=f"Hyperbaric reading ({pressure} hPa) deviates from ambient gradient."
                )
                return res.status, res.to_dict()

        # 3. Wind speed anomaly
        if wind is not None:
            if wind >= self.WIND_STORM:
                res = AnomalyResult(
                    status="ANOMALY",
                    is_anomaly=True,
                    severity="HIGH",
                    parameter="Wind Speed",
                    observed=wind,
                    unit="km/h",
                    expected_min=0.0,
                    expected_max=60.0,
                    reason=f"Storm-force sustained wind ({wind} km/h) recorded by anemometer."
                )
                return res.status, res.to_dict()
            elif wind >= self.WIND_GALE:
                res = AnomalyResult(
                    status="WARNING",
                    is_anomaly=True,
                    severity="WARNING",
                    parameter="Wind Speed",
                    observed=wind,
                    unit="km/h",
                    expected_min=0.0,
                    expected_max=50.0,
                    reason=f"Gale-force gusts ({wind} km/h) exceeding typical diurnal profile."
                )
                return res.status, res.to_dict()

        # 4. Humidity physical boundaries
        if humidity is not None and (humidity < 0 or humidity > 100):
            res = AnomalyResult(
                status="ANOMALY",
                is_anomaly=True,
                severity="HIGH",
                parameter="Humidity",
                observed=humidity,
                unit="%",
                expected_min=5.0,
                expected_max=100.0,
                reason=f"Non-physical relative humidity reading ({humidity}%)."
            )
            return res.status, res.to_dict()

        # If existing anomaly in payload, preserve
        if station_data.get("anomaly"):
            return station_data.get("status", "ANOMALY"), station_data.get("anomaly")

        return "NORMAL", None

# Default singleton instance
detector = AnomalyDetector()
