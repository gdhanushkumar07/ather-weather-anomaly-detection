"""
Layer 5: Sensor Drift & Health Tracking Engine.
Implements:
1. Two-sided Cumulative Sum (CUSUM) test for slow systematic calibration bias.
2. Continuous Sensor Health Index (0 - 100%).
3. Predictive Maintenance: "Days Until Out of Tolerance" based on linear drift velocity.
"""
from typing import Dict, Optional, Tuple
import numpy as np

from ather.config import CONFIG, DriftThresholds
from ather.data.schema import AWSReading

class ChannelDriftState:
    def __init__(self, slack: float, threshold: float, beta: float = 0.97):
        self.slack = slack
        self.threshold = threshold
        self.beta = beta
        self.ema_mean: Optional[float] = None
        self.s_pos = 0.0  # Upper CUSUM
        self.s_neg = 0.0  # Lower CUSUM
        self.sample_count = 0
        self.recent_residuals = []
        self.accumulated_drift_rate = 0.0 # units per sample

    def update(self, value: float) -> Tuple[float, float]:
        """
        Updates CUSUM accumulator with new value using adaptive EMA baseline.
        Returns (cusum_score [0, 1], current_estimated_bias).
        """
        self.sample_count += 1
        if self.ema_mean is None:
            self.ema_mean = value

        residual = value - self.ema_mean
        # Slowly adapt EMA baseline to natural seasonal / diurnal shifts
        self.ema_mean = self.beta * self.ema_mean + (1.0 - self.beta) * value

        self.recent_residuals.append(residual)
        if len(self.recent_residuals) > 144:  # Retain 24 hours of 10-minute samples
            self.recent_residuals.pop(0)

        # CUSUM equations
        self.s_pos = max(0.0, self.s_pos + residual - self.slack)
        self.s_neg = max(0.0, self.s_neg - residual - self.slack)

        # Subtle natural decay of CUSUM accumulator
        self.s_pos *= 0.98
        self.s_neg *= 0.98

        # Estimate drift rate via linear slope over recent window
        if len(self.recent_residuals) >= 24:
            x = np.arange(len(self.recent_residuals))
            slope, _ = np.polyfit(x, self.recent_residuals, 1)
            self.accumulated_drift_rate = float(slope)

        max_s = max(self.s_pos, self.s_neg)
        score = min(1.0, max_s / (self.threshold * 2.0))
        current_bias = float(np.mean(self.recent_residuals[-12:])) if self.recent_residuals else 0.0
        return score, current_bias

class StationDriftTracker:
    def __init__(self, cfg: DriftThresholds = CONFIG.drift):
        self.cfg = cfg
        self.channel_states: Dict[str, ChannelDriftState] = {
            "temperature_c": ChannelDriftState(slack=2.5, threshold=12.0),
            "pressure_hpa": ChannelDriftState(slack=3.0, threshold=12.0),
            "humidity_pct": ChannelDriftState(slack=8.0, threshold=15.0)
        }
        self.anomaly_count = 0
        self.total_readings = 0

class SensorDriftHealthLayer:
    """
    Evaluates progressive sensor calibration degradation and station operational health.
    """
    def __init__(self, config: DriftThresholds = CONFIG.drift):
        self.cfg = config
        self.trackers: Dict[str, StationDriftTracker] = {}

    def _get_tracker(self, station_id: str) -> StationDriftTracker:
        if station_id not in self.trackers:
            self.trackers[station_id] = StationDriftTracker(self.cfg)
        return self.trackers[station_id]

    def evaluate(
        self,
        reading: AWSReading,
        recent_is_anomaly: bool = False
    ) -> Tuple[float, float, Optional[float], Optional[str]]:
        """
        Evaluates drift and health status.
        Returns:
            drift_score: float [0.0, 1.0]
            sensor_health_index: float [0.0, 100.0]
            estimated_days_to_failure: Optional[float]
            diagnostic_reason: Optional[str]
        """
        tracker = self._get_tracker(reading.station_id)
        tracker.total_readings += 1
        if recent_is_anomaly:
            tracker.anomaly_count += 1

        t_score, t_bias = tracker.channel_states["temperature_c"].update(reading.temperature_c)
        p_score, p_bias = tracker.channel_states["pressure_hpa"].update(reading.pressure_hpa)
        rh_score, rh_bias = tracker.channel_states["humidity_pct"].update(reading.humidity_pct)

        max_drift_score = max(t_score, p_score, rh_score)

        # Predictive Maintenance Days-to-Failure Calculation
        days_to_failure_estimates = []

        # Temperature: 144 samples per day at 10-min resolution
        t_rate_per_day = abs(tracker.channel_states["temperature_c"].accumulated_drift_rate) * 144.0
        if t_rate_per_day > 0.05:
            remaining_margin = max(0.0, self.cfg.temp_tolerance_c - abs(t_bias))
            days_t = remaining_margin / t_rate_per_day
            days_to_failure_estimates.append(days_t)

        rh_rate_per_day = abs(tracker.channel_states["humidity_pct"].accumulated_drift_rate) * 144.0
        if rh_rate_per_day > 0.15:
            remaining_margin_rh = max(0.0, self.cfg.humidity_tolerance_pct - abs(rh_bias))
            days_rh = remaining_margin_rh / rh_rate_per_day
            days_to_failure_estimates.append(days_rh)

        min_days_to_failure = min(days_to_failure_estimates) if days_to_failure_estimates else None

        # Composite Health Score (0 - 100)
        # Deduct penalties for drift, anomaly frequency, and bias
        drift_penalty = max_drift_score * 35.0
        error_rate = (tracker.anomaly_count / max(1, tracker.total_readings))
        error_penalty = min(40.0, error_rate * 100.0 * 2.0)

        health_score = max(5.0, min(100.0, 100.0 - drift_penalty - error_penalty))

        reasons = []
        if max_drift_score > 0.6:
            reasons.append(f"Cumulative sensor calibration drift detected (CUSUM score: {max_drift_score:.2f})")
        if min_days_to_failure is not None and min_days_to_failure < self.cfg.drift_critical_days:
            reasons.append(f"PREDICTIVE ALERT: Projected out-of-tolerance failure in {min_days_to_failure:.1f} days")

        reason_str = "; ".join(reasons) if reasons else None
        return max_drift_score, health_score, min_days_to_failure, reason_str
