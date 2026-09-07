"""
Pydantic data contracts and models for AWS sensor readings and anomaly outputs.
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class SensorChannel(str, Enum):
    TEMPERATURE = "temperature_c"
    PRESSURE = "pressure_hpa"
    HUMIDITY = "humidity_pct"

class StationMetadata(BaseModel):
    station_id: str
    name: str = "AWS Station"
    lat: float
    lon: float
    elevation_m: float = 0.0

class AWSReading(BaseModel):
    station_id: str
    timestamp: datetime
    temperature_c: float = Field(..., description="Ambient air temperature in Celsius")
    pressure_hpa: float = Field(..., description="Barometric surface pressure in hPa/mbar")
    humidity_pct: float = Field(..., description="Relative humidity in percentage [0, 100]")
    dew_point_c: Optional[float] = Field(None, description="Dew point temperature in Celsius if available")
    lat: float = 50.93
    lon: float = 11.58
    elevation_m: float = 207.0

    def to_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "timestamp": self.timestamp.isoformat(),
            "temperature_c": self.temperature_c,
            "pressure_hpa": self.pressure_hpa,
            "humidity_pct": self.humidity_pct,
            "dew_point_c": self.dew_point_c,
            "lat": self.lat,
            "lon": self.lon,
            "elevation_m": self.elevation_m
        }

class FaultType(str, Enum):
    NORMAL = "NORMAL"
    SENSOR_SPIKE = "SENSOR_SPIKE"
    FROZEN_SENSOR = "FROZEN_SENSOR"
    CALIBRATION_DRIFT = "CALIBRATION_DRIFT"
    NOISE_BURST = "NOISE_BURST"
    SINGLE_CHANNEL_FAULT = "SINGLE_CHANNEL_FAULT"
    GENUINE_EXTREME_WEATHER = "GENUINE_EXTREME_WEATHER"
    COMMUNICATION_OUTAGE = "COMMUNICATION_OUTAGE"

class AnomalyAlert(BaseModel):
    station_id: str
    timestamp: datetime
    is_anomaly: bool
    severity_score: float = Field(..., ge=0.0, le=1.0, description="Calibrated anomaly severity [0, 1]")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Statistical confidence [0, 1]")
    veto_fired: bool = Field(False, description="True if thermodynamic physics rule triggered instant veto")
    root_cause: FaultType = FaultType.NORMAL
    affected_channels: List[str] = Field(default_factory=list)
    layer_scores: Dict[str, float] = Field(default_factory=dict, description="Anomaly score per detection layer [0, 1]")
    explanation: str = Field("", description="SHAP/Physics-grounded diagnostic text for AWS technician")
    raw_values: Dict[str, float]
    corrected_values: Dict[str, float]
    sensor_health_index: float = Field(100.0, ge=0.0, le=100.0, description="Overall station sensor health [0, 100]")
    estimated_days_to_failure: Optional[float] = None
