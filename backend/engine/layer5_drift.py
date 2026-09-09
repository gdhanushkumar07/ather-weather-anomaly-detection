"""
Layer 5: Sensor Drift & Health Tracking Engine (v2).

CORRECTNESS RULES (v2):
  - Updates CUSUM only from VALID channel readings.
  - Returns samples_tracked per channel so the UI can show data coverage.
  - Uses a 5-tier drift classification:
      NORMAL, SUSPICIOUS, POSSIBLE_DRIFT, LIKELY_DRIFT, HIGH_RISK
  - Does NOT declare sensor failure from a single anomalous reading.
    Drift conclusions require > 12 samples for the CUSUM to be meaningful.
"""
from typing import Dict, Optional, Tuple, Any
import numpy as np

from config import CONFIG, DriftThresholds
from schema import AWSReading, DataQuality


class ChannelDriftState:
    def __init__(self, slack: float, threshold: float, beta: float = 0.97):
        self.slack             = slack
        self.threshold         = threshold
        self.beta              = beta
        self.ema_mean:         Optional[float] = None
        self.s_pos             = 0.0   # Upper CUSUM accumulator
        self.s_neg             = 0.0   # Lower CUSUM accumulator
        self.sample_count      = 0
        self.recent_residuals: list = []
        self.accumulated_drift_rate = 0.0

    def update(self, value: float) -> Tuple[float, float]:
        """
        Updates CUSUM with new VALID reading.
        Returns (cusum_score [0, 1], estimated_bias).
        """
        self.sample_count += 1
        if self.ema_mean is None:
            self.ema_mean = value

        residual        = value - self.ema_mean
        self.ema_mean   = self.beta * self.ema_mean + (1.0 - self.beta) * value

        self.recent_residuals.append(residual)
        if len(self.recent_residuals) > 144:
            self.recent_residuals.pop(0)

        self.s_pos = max(0.0, self.s_pos + residual - self.slack) * 0.98
        self.s_neg = max(0.0, self.s_neg - residual - self.slack) * 0.98

        if len(self.recent_residuals) >= 12:
            x, slope = np.arange(len(self.recent_residuals)), 0.0
            try:
                slope, _ = np.polyfit(x, self.recent_residuals, 1)
            except Exception:
                pass
            self.accumulated_drift_rate = float(slope)

        max_s        = max(self.s_pos, self.s_neg)
        score        = min(1.0, max_s / (self.threshold * 2.0))
        current_bias = float(np.mean(self.recent_residuals[-12:])) if self.recent_residuals else 0.0
        return score, current_bias

    @property
    def drift_tier(self) -> str:
        """Maps current CUSUM state to a human-readable drift tier."""
        if self.sample_count < 6:
            return "INSUFFICIENT_DATA"
        max_s     = max(self.s_pos, self.s_neg)
        threshold = self.threshold
        if max_s < threshold * 0.3:
            return "NORMAL"
        if max_s < threshold * 0.6:
            return "SUSPICIOUS"
        if max_s < threshold:
            return "POSSIBLE_DRIFT"
        if max_s < threshold * 1.5:
            return "LIKELY_DRIFT"
        return "HIGH_RISK"


class StationDriftTracker:
    def __init__(self, cfg: DriftThresholds = CONFIG.drift):
        self.cfg           = cfg
        self.channel_states: Dict[str, ChannelDriftState] = {
            "temperature_c": ChannelDriftState(
                slack=self.cfg.cusum_slack * 2.0, threshold=self.cfg.cusum_threshold * 2.0
            ),
            "pressure_hpa": ChannelDriftState(
                slack=self.cfg.cusum_slack * 2.5, threshold=self.cfg.cusum_threshold * 2.5
            ),
            "humidity_pct": ChannelDriftState(
                slack=self.cfg.cusum_slack * 5.0, threshold=self.cfg.cusum_threshold * 4.0
            ),
        }
        self.anomaly_count = 0
        self.total_readings = 0


class SensorDriftHealthLayer:
    """
    Evaluates progressive sensor calibration degradation.
    """
    def __init__(self, config: DriftThresholds = CONFIG.drift):
        self.cfg      = config
        self.trackers: Dict[str, StationDriftTracker] = {}

    def _get_tracker(self, station_id: str) -> StationDriftTracker:
        if station_id not in self.trackers:
            self.trackers[station_id] = StationDriftTracker(self.cfg)
        return self.trackers[station_id]

    def evaluate(
        self,
        reading:           AWSReading,
        recent_is_anomaly: bool = False
    ) -> Tuple[float, float, Optional[float], Optional[str], Dict[str, Any]]:
        """
        Evaluates drift and health status using only VALID channels.
        Returns:
            drift_score:              float [0.0, 1.0]
            sensor_health_index:      float [0.0, 100.0]
            estimated_days_to_failure: Optional[float]
            diagnostic_reason:        Optional[str]
            detail:                   Dict with samples_tracked, drift_tiers per channel
        """
        tracker = self._get_tracker(reading.station_id)
        tracker.total_readings += 1
        if recent_is_anomaly:
            tracker.anomaly_count += 1

        channel_scores:          list = []
        days_to_failure_estimates: list = []
        detail: Dict[str, Any] = {"channel_drift": {}}

        def ch_valid(ch: str) -> bool:
            return reading.data_quality.get(ch) == DataQuality.VALID

        # ── Temperature drift ──────────────────────────────────────────────
        if ch_valid("temperature_c") and reading.temperature_c is not None:
            state      = tracker.channel_states["temperature_c"]
            t_score, t_bias = state.update(reading.temperature_c)
            channel_scores.append(t_score)

            t_rate_per_day = abs(state.accumulated_drift_rate) * 144.0
            dtf_t = None
            if t_rate_per_day > 0.05:
                remaining = max(0.0, self.cfg.temp_tolerance_c - abs(t_bias))
                dtf_t = remaining / t_rate_per_day
                days_to_failure_estimates.append(dtf_t)

            detail["channel_drift"]["temperature_c"] = {
                "drift_tier":     state.drift_tier,
                "cusum_score":    round(t_score, 3),
                "estimated_bias": round(t_bias, 3),
                "drift_rate_per_day": round(t_rate_per_day, 4),
                "samples_tracked": state.sample_count,
                "days_to_failure": round(dtf_t, 1) if dtf_t is not None else None,
            }

        # ── Pressure drift ─────────────────────────────────────────────────
        if ch_valid("pressure_hpa") and reading.pressure_hpa is not None:
            state      = tracker.channel_states["pressure_hpa"]
            p_score, p_bias = state.update(reading.pressure_hpa)
            channel_scores.append(p_score)

            detail["channel_drift"]["pressure_hpa"] = {
                "drift_tier":     state.drift_tier,
                "cusum_score":    round(p_score, 3),
                "estimated_bias": round(p_bias, 3),
                "samples_tracked": state.sample_count,
            }

        # ── Humidity drift ─────────────────────────────────────────────────
        if ch_valid("humidity_pct") and reading.humidity_pct is not None:
            state         = tracker.channel_states["humidity_pct"]
            rh_score, rh_bias = state.update(reading.humidity_pct)
            channel_scores.append(rh_score)

            rh_rate_per_day = abs(state.accumulated_drift_rate) * 144.0
            dtf_rh = None
            if rh_rate_per_day > 0.15:
                remaining = max(0.0, self.cfg.humidity_tolerance_pct - abs(rh_bias))
                dtf_rh = remaining / rh_rate_per_day
                days_to_failure_estimates.append(dtf_rh)

            detail["channel_drift"]["humidity_pct"] = {
                "drift_tier":     state.drift_tier,
                "cusum_score":    round(rh_score, 3),
                "estimated_bias": round(rh_bias, 3),
                "samples_tracked": state.sample_count,
                "days_to_failure": round(dtf_rh, 1) if dtf_rh is not None else None,
            }

        # ── Composite health score ──────────────────────────────────────────
        max_drift_score      = max(channel_scores) if channel_scores else 0.0
        min_days_to_failure  = min(days_to_failure_estimates) if days_to_failure_estimates else None

        drift_penalty  = max_drift_score * 35.0
        error_rate     = tracker.anomaly_count / max(1, tracker.total_readings)
        error_penalty  = min(40.0, error_rate * 100.0 * 2.0)
        health_score   = max(5.0, min(100.0, 100.0 - drift_penalty - error_penalty))

        # ── Reason based on tier ───────────────────────────────────────────
        reasons: list = []
        worst_tier    = "NORMAL"
        for ch, ch_detail in detail["channel_drift"].items():
            tier = ch_detail.get("drift_tier", "NORMAL")
            if tier in ("LIKELY_DRIFT", "HIGH_RISK"):
                reasons.append(
                    f"{ch} CUSUM drift ({tier}): estimated bias {ch_detail['estimated_bias']:+.2f}, "
                    f"{ch_detail['samples_tracked']} samples tracked"
                )
                worst_tier = tier
            elif tier in ("POSSIBLE_DRIFT", "SUSPICIOUS") and not reasons:
                worst_tier = tier

        if min_days_to_failure is not None and min_days_to_failure < self.cfg.drift_critical_days:
            reasons.append(
                f"Projected tolerance breach in {min_days_to_failure:.1f} days"
            )

        detail["health_score"]      = round(health_score, 1)
        detail["max_drift_score"]   = round(max_drift_score, 3)
        detail["worst_drift_tier"]  = worst_tier
        detail["samples_in_radius"] = tracker.total_readings

        reason_str = "; ".join(reasons) if reasons else None
        return max_drift_score, health_score, min_days_to_failure, reason_str, detail
