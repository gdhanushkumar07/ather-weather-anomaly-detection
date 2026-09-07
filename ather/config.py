"""
Global configuration, physical constants, and default hyper-parameters for ATHER.
"""
from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass
class PhysicsThresholds:
    # Sensor physical operating bounds
    temp_min_c: float = -60.0
    temp_max_c: float = 60.0
    pressure_min_hpa: float = 300.0
    pressure_max_hpa: float = 1085.0
    humidity_min_pct: float = 0.0
    humidity_max_pct: float = 100.0

    # Thermodynamic constraints
    max_wet_bulb_c: float = 35.0  # Theoretical survivability limit
    dew_point_margin_c: float = 0.5  # T_dew <= T + margin

    # Standard atmospheric model parameters (for barometric altitude check)
    sea_level_pressure_hpa: float = 1013.25
    temp_lapse_rate: float = 0.0065  # K/m
    sea_level_temp_k: float = 288.15
    gravity: float = 9.80665
    gas_constant: float = 287.05
    max_pressure_altitude_error_pct: float = 6.0  # % allowable deviation from hypsometric expectation

@dataclass
class TemporalThresholds:
    # Maximum plausible step change across a 10-minute reporting interval
    max_temp_delta_c: float = 2.8
    max_pressure_delta_hpa: float = 1.8
    max_humidity_delta_pct: float = 12.0

    # Frozen / stuck sensor parameters
    frozen_window_size: int = 12  # 12 consecutive 10-min readings = 2 hours
    frozen_variance_threshold: float = 1e-6

    # Rolling z-score anomaly threshold
    z_score_threshold: float = 3.5
    rolling_window_samples: int = 72  # 12 hours of 10-minute readings

@dataclass
class SpatialThresholds:
    neighbor_distance_km_max: float = 150.0
    spatial_z_threshold: float = 3.0
    min_neighbors_required: int = 2

@dataclass
class DriftThresholds:
    cusum_threshold: float = 5.0
    cusum_slack: float = 0.5
    drift_critical_days: float = 7.0  # Alert if sensor will exceed tolerance within 7 days
    temp_tolerance_c: float = 1.0     # WMO AWS standard accuracy
    humidity_tolerance_pct: float = 3.0
    pressure_tolerance_hpa: float = 0.5

@dataclass
class FusionThresholds:
    target_false_alarm_rate: float = 0.001  # MAPIE conformal significance level alpha
    physics_veto_weight: float = 1.0
    ensemble_anomaly_threshold: float = 0.55

@dataclass
class AtherConfig:
    physics: PhysicsThresholds = field(default_factory=PhysicsThresholds)
    temporal: TemporalThresholds = field(default_factory=TemporalThresholds)
    spatial: SpatialThresholds = field(default_factory=SpatialThresholds)
    drift: DriftThresholds = field(default_factory=DriftThresholds)
    fusion: FusionThresholds = field(default_factory=FusionThresholds)

    # Default AWS Station metadata (Jena station)
    default_station_id: str = "AWS_JENA_01"
    default_lat: float = 50.93
    default_lon: float = 11.58
    default_elevation_m: float = 207.0

# Singleton global instance
CONFIG = AtherConfig()
