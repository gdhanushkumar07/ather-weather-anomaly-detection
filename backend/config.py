"""
Global configuration, physical constants, and default hyper-parameters for ATHER.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

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
    # A persistence ("stuck sensor") verdict also requires the unchanged run
    # to span at least this much wall-clock time. A count-only window
    # silently assumes a 10-minute cadence: at a 1-minute cadence, 12
    # identical 0.1 hPa barometer readings are normal, not a fault
    # (WMO-No. 8 / GAW QC persistence checks are time-based).
    frozen_min_span_minutes: float = float(os.environ.get("ATHER_FROZEN_MIN_SPAN_MIN", "60"))

    # Rolling z-score anomaly threshold
    z_score_threshold: float = 3.5
    # Floor for the MAD in the robust z-score, per channel. During quiet
    # periods the MAD collapses to the sensor's quantisation step (0.1 °C),
    # which made a routine 0.6 °C change score z ≈ 4. A deviation smaller
    # than the instrument's achievable measurement uncertainty (WMO-No. 8,
    # Annex 1.A: T 0.2 K, P 0.15 hPa, RH ~1 %) cannot be significant.
    zscore_mad_floor: Dict[str, float] = field(default_factory=lambda: {
        "temperature_c": 0.2, "pressure_hpa": 0.15, "humidity_pct": 1.0,
    })
    rolling_window_samples: int = 72  # 12 hours of 10-minute readings

@dataclass
class SpatialThresholds:
    neighbor_distance_km_max: float = 250.0
    spatial_z_threshold: float = 3.0
    min_neighbors_required: int = 2

@dataclass
class MultivariateThresholds:
    """
    Layer 3: Multivariate Intelligence (ECOD + Isolation Forest) configuration.

    Models are station/region specific (never one global model across
    different climates) — see backend/multivariate/README.md for the full
    design, dataset provenance and the validation that chose these defaults.
    All paths are relative to the backend/ directory.
    """
    # ── Models ─────────────────────────────────────────────────────────
    ecod_enabled: bool = True
    isolation_forest_enabled: bool = True
    if_n_estimators: int = 200
    if_max_samples: Any = "auto"   # "auto", or an int / float per sklearn's IsolationForest
    if_random_state: int = 42
    fit_max_rows: int = 6000       # deterministic stride-subsample of the fit set (bounds ECOD latency)

    # ── Decision (split-conformal, per model) ───────────────────────────
    # Each model's raw score is converted to a conformal p-value against a
    # HELD-OUT calibration set of trusted normal observations (every k-th
    # calendar day of the training window, k = 1/calibration_fraction — never
    # the rows the model was fit on; see training.split_fit_calibration).
    # A model flags when p <= alpha, i.e. alpha is that
    # model's target false-alarm rate on normal data.
    #   both models flag  -> ANOMALY    (high confidence, layer3_anomaly=True)
    #   exactly one flags -> SUSPICIOUS (low confidence)
    #   neither flags     -> NORMAL
    alpha: float = 0.01
    calibration_fraction: float = 0.25

    # ── Features ───────────────────────────────────────────────────────
    # Chosen on the 2022 VALIDATION year only (backend/multivariate/README.md, variant study V1-V5):
    # "diurnal_anomaly" + the learned RH|T residual had the best F1 in both decision tiers and the
    # lowest normal-data alarm rate for the any-flag tier. use_diurnal_features only matters for "raw".
    feature_representation: str = "diurnal_anomaly"   # "raw" | "diurnal_anomaly" (see multivariate/models.py)
    use_rh_temperature_residual: bool = True          # learned RH | (T, solar hour) residual
    # learned P | (T, solar hour) residual as a MODEL column. Enabled by project decision: it makes
    # pressure-context and joint T/RH/P anomalies detectable, at a measured cost on the 2022
    # validation year (normal any-flag rate 1.32% -> 1.56%, multivariate F1 .554 -> .503).
    # Set False to trade that sensitivity back for fewer false alarms (see models.RELATIONSHIPS).
    use_pressure_temperature_residual: bool = True
    use_diurnal_features: bool = True                 # "raw" only: solar-hour sin/cos as model columns

    # ONE seasonal context window, used identically by the live regional
    # reference, by offline validation, and by the injector's plausibility
    # bands: models for a date see only +-season_window_days of that calendar day.
    season_window_days: int = 30
    max_delta_gap_hours: float = 3.0    # deltas across a longer gap are not comparable -> static feature set

    # ── Station-specific online learning ───────────────────────────────
    min_train_samples: int = 400    # own-model minimum when NO regional reference covers the station
    # When a regional reference DOES cover the station, its own model replaces the reference only
    # once it is comparably strong: ECOD's per-feature tail is capped at 1/(n_fit+1), so a model fit
    # on 300 rows cannot express how extreme a value is the way the ~6000-row reference can.
    station_model_takeover_samples: int = 1440   # ~60 days hourly
    retrain_interval: int = 24      # refit after this many NEW trusted observations
    buffer_max_len: int = 2160      # bounded trusted-history window (~90 days hourly)

    # ── Regional historical reference (cold start for live stations) ────
    reference_enabled: bool = True
    reference_data_path: str = "../data/historical/open_meteo_india_hourly.csv"
    reference_cache_dir: str = "models/multivariate/reference"
    reference_max_distance_km: float = 75.0
    reference_max_cached_models: int = 96

    # ── Physical joint-state rule (kept alongside the learned models) ───
    # T > 32C with RH > 95% implies a dew point above ~31C. That never
    # occurs in 2.1M hourly rows of the 2015-2024 Indian reference data
    # (max dew point there: 29.9C), so this rule does not fire on normal data.
    clausius_clapeyron_temp_c: float = 32.0
    clausius_clapeyron_rh_pct: float = 95.0
    clausius_clapeyron_score: float = 0.85

@dataclass
class DriftThresholds:
    cusum_threshold: float = 5.0
    cusum_slack: float = 0.5
    drift_critical_days: float = 7.0  # Alert if sensor will exceed tolerance within 7 days
    temp_tolerance_c: float = 1.0     # WMO AWS standard accuracy
    humidity_tolerance_pct: float = 3.0
    pressure_tolerance_hpa: float = 0.5

@dataclass
class PINNThresholds:
    enabled: bool = True
    lambda_physics: float = 0.3  # weight of physics loss vs data loss during training

    # Kept in sync with PhysicsThresholds so the PINN's training-time physics
    # loss and its inference-time consistency check agree with the rule layer.
    hypsometric_tolerance_pct: float = 8.0
    dew_point_margin_c: float = 0.5

    # Consistency-check tolerances (inference time). This check only runs on
    # readings that already passed every hard veto/threshold in
    # PhysicsValidationLayer, so these are deliberately generous — it is a
    # secondary, corroborating signal, not a primary detector.
    temp_consistency_tolerance_c: float = 3.5
    pressure_consistency_tolerance_pct: float = 6.0
    humidity_consistency_tolerance_pct: float = 12.0

    # Soft score ramps from 0 at score_ramp_start_z (multiples of tolerance)
    # up to max_score_contribution at score_ramp_saturate_z.
    score_ramp_start_z: float = 2.0
    score_ramp_saturate_z: float = 5.0
    max_score_contribution: float = 0.55

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
    multivariate: MultivariateThresholds = field(default_factory=MultivariateThresholds)
    spatial: SpatialThresholds = field(default_factory=SpatialThresholds)
    drift: DriftThresholds = field(default_factory=DriftThresholds)
    fusion: FusionThresholds = field(default_factory=FusionThresholds)
    pinn: PINNThresholds = field(default_factory=PINNThresholds)
    lstm_temporal: LSTMTemporalConfig = field(default_factory=LSTMTemporalConfig)

    # Default AWS Station metadata
    default_station_id: str = "ATHER_AWS_01"
    default_lat: float = 17.385
    default_lon: float = 78.4867
    default_elevation_m: float = 500.0

# Singleton global instance
CONFIG = AtherConfig()
