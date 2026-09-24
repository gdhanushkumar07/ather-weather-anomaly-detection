"""
Global configuration, physical constants, and default hyper-parameters for ATHER.
"""
from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass
class PhysicsThresholds:
    # Sensor physical operating bounds
    temp_min_c: float = -45.0
    temp_max_c: float = 50.0
    pressure_min_hpa: float = 920.0
    pressure_max_hpa: float = 1065.0
    humidity_min_pct: float = 0.0
    humidity_max_pct: float = 100.0
    wind_gale_kmh: float = 75.0
    wind_storm_kmh: float = 100.0

    # Thermodynamic constraints
    max_wet_bulb_c: float = 35.0  # Theoretical survivability limit
    dew_point_margin_c: float = 0.5  # T_dew <= T + margin

    # Standard atmospheric model parameters (for barometric altitude check)
    sea_level_pressure_hpa: float = 1013.25
    temp_lapse_rate: float = 0.0065  # K/m
    sea_level_temp_k: float = 288.15
    gravity: float = 9.80665
    gas_constant: float = 287.05
    max_pressure_altitude_error_pct: float = 8.0  # % allowable deviation from hypsometric expectation

@dataclass
class TemporalThresholds:
    # Maximum plausible step change across a 10-minute reporting interval
    max_temp_delta_c: float = 3.5
    max_pressure_delta_hpa: float = 2.5
    max_humidity_delta_pct: float = 15.0

    # Frozen / stuck sensor parameters
    frozen_window_size: int = 12  # 12 consecutive readings (~2 hours)
    frozen_variance_threshold: float = 1e-6

    # Rolling z-score anomaly threshold
    z_score_threshold: float = 3.5
    rolling_window_samples: int = 72  # 12 hours of 10-minute readings

@dataclass
class SpatialThresholds:
    neighbor_distance_km_max: float = 250.0
    spatial_z_threshold: float = 3.0
    min_neighbors_required: int = 2
    # S1 — Spatial Neighborhood Foundation (engine/spatial_neighbors.py):
    # the maximum number of nearest-in-radius stations kept after distance
    # sorting. Default 8 matches the previous hardcoded
    # `max_neighbors=8` in AnomalyDetector.get_neighbors_for_reading(), so
    # existing production/test behavior is unchanged at this default (no
    # currently exercised scenario has more than 5 neighbors within
    # radius). Distinct from min_neighbors_required, which is the FLOOR
    # below which Spatial refuses to draw a conclusion; this is the CEILING
    # on how many of the nearest candidates are used once there are enough.
    spatial_k_neighbors: int = 8

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
class LSTMTemporalConfig:
    """
    Stage 4: configuration for the optional LSTM temporal-prediction
    evidence source inside TemporalPatternLayer (engine/layer2_temporal.py).
    This ADDS evidence alongside the existing rule-based temporal checks —
    it never replaces them (see engine/lstm_temporal.py).

    All paths are relative to the backend/ directory.
    """
    enabled: bool = True  # if artifacts fail to load, the layer disables itself regardless of this flag
    model_dir: str = "models/temporal_lstm"
    calibration_path: str = "models/temporal_lstm/stage3_results/calibration_stats.json"
    sequence_length: int = 144            # must match the trained Stage 2 model's window length
    residual_window: int = 6              # rolling recent-peak window, ~60 min at 10-min cadence
    reason_report_threshold: float = 0.5  # min channel score to mention LSTM evidence in the reason string
    max_gap_minutes: float = 15.0         # a joint-valid reading arriving after a bigger gap than this
                                           # resets the LSTM history buffer — Stage 2 trained on strictly
                                           # contiguous 10-min steps, so a stretched/discontiguous sequence
                                           # must not be silently fed to the model as if it were 24h of history
    combined_score_calibration_factor: float = 1.44
    # STAGE 5 CALIBRATION (measured, not guessed): each channel's raw
    # residual is normalized by its OWN Stage 3 per-channel P99 (a ~1%
    # exceedance target for THAT channel alone). But the final evidence
    # combines 3 channels via max() AND a 6-step rolling max — combining
    # several ~1%-tail signals via max() inflates the exceedance rate far
    # past 1% (measured on 75 real Stage 1 normal-validation stations,
    # 64,800 observations: without this factor, the combined recent-peak
    # score exceeded 0.70 on 16.3% of genuinely NORMAL readings — enough to
    # trip fusion's acute_temporal>=0.70 override on roughly 1 in 6 normal
    # readings). This factor is the measured P99 of the raw (pre-clip)
    # channel-max + 6-step-rolling-max score on that same normal traffic,
    # so post-correction ~99% of normal traffic's combined evidence again
    # falls at or below 1.0 — restoring the ORIGINAL single-channel P99
    # design's intended rarity to the actual combined quantity fusion sees.
    # Provenance: backend/stage5_results/normal_calibration_summary.json
    # (calibration_factor_derivation). Setting this to 1.0 reproduces exact
    # pre-Stage-5 (Stage 4) behavior.

@dataclass
class AtherConfig:
    physics: PhysicsThresholds = field(default_factory=PhysicsThresholds)
    temporal: TemporalThresholds = field(default_factory=TemporalThresholds)
    spatial: SpatialThresholds = field(default_factory=SpatialThresholds)
    drift: DriftThresholds = field(default_factory=DriftThresholds)
    fusion: FusionThresholds = field(default_factory=FusionThresholds)
    lstm_temporal: LSTMTemporalConfig = field(default_factory=LSTMTemporalConfig)

    # Default AWS Station metadata
    default_station_id: str = "ATHER_AWS_01"
    default_lat: float = 17.385
    default_lon: float = 78.4867
    default_elevation_m: float = 500.0

# Singleton global instance
CONFIG = AtherConfig()
