"""
Layer 5: Sensor Drift & Health Tracking Engine (v3 - Phase 3 validation).

WHAT THIS LAYER CAN AND CANNOT CLAIM
  It runs a CUSUM per channel on each sensor's residual against that sensor's
  OWN recent baseline (an exponential moving average). It therefore detects a
  SUSTAINED CHANGE IN THE SENSOR'S BEHAVIOR relative to its recent past, and
  reports it as sensor-health EVIDENCE that can support a maintenance
  investigation. It does NOT:
    - predict failure or a failure date (any tolerance projection is a rough
      linear extrapolation of the recent drift rate, gated behind sustained
      evidence, and is indicative only);
    - detect instantaneous anomalies (Physics / Temporal own those) or frozen
      sensors (Temporal's frozen-window check owns that: a constant series has
      zero residual and no CUSUM signal, by design);
    - separate natural weather variability from drift: the baseline is the
      sensor's own history, so a large, sustained natural swing (e.g. a strong
      diurnal cycle) can accumulate CUSUM evidence. `detail["reference"]`
      states this explicitly ("OWN_RECENT_BASELINE"). Independent-reference
      drift detection (e.g. against neighbor consensus) is NOT implemented.

CORRECTNESS RULES
  - Updates CUSUM only from VALID channel readings; a missing channel never
    becomes a sample and never advances that channel's state.
  - Bounded influence: each residual is clipped to +/- clip_factor*slack before
    it enters the CUSUM or the baseline, so ONE extreme value cannot by itself
    create drift evidence - persistence is required.
  - Warm-up: no drift score or tier until `min_samples_for_drift` valid
    samples (tier INSUFFICIENT_DATA before that).
  - Time: uses the OBSERVATION time when known (else the processing time, the
    same convention as Temporal). A duplicate timestamp or an out-of-order
    reading is NOT a new sample and does not advance any state; a gap longer
    than `reset_gap_minutes` reinitializes the stale baseline.
  - State is per station and per channel; nothing is shared.
  - NWP model references are not sensors: no state is created or updated.
  - Uses a 5-tier classification: NORMAL, SUSPICIOUS, POSSIBLE_DRIFT,
    LIKELY_DRIFT, HIGH_RISK (thresholds are multiples of the channel CUSUM
    threshold h; score = S / (2h) clipped to [0, 1]).
"""
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any, List

import numpy as np

from config import CONFIG, DriftThresholds
from schema import AWSReading, DataQuality

NWP_SOURCE = "NWP_MODEL_REFERENCE"

# (slack multiplier, threshold multiplier) applied to DriftThresholds'
# cusum_slack / cusum_threshold for each channel, reflecting each channel's
# typical natural variability (humidity is noisier than temperature, etc.).
CHANNEL_CUSUM_SCALE: Dict[str, Tuple[float, float]] = {
    "temperature_c": (2.0, 2.0),
    "pressure_hpa":  (2.5, 2.5),
    "humidity_pct":  (5.0, 4.0),
}

# Minimum per-day drift rate (channel units/day) worth reporting a tolerance
# projection for; below these the "trend" is indistinguishable from noise.
_MIN_RATE_PER_DAY = {"temperature_c": 0.05, "humidity_pct": 0.15}

_TIER_ORDER = ["INSUFFICIENT_DATA", "NORMAL", "SUSPICIOUS", "POSSIBLE_DRIFT", "LIKELY_DRIFT", "HIGH_RISK"]


def _effective_timestamp(reading: AWSReading) -> Optional[datetime]:
    """Observation time when known, else the processing timestamp (same
    convention as engine/layer2_temporal.py). tz-naive values are UTC."""
    ts = reading.observation_timestamp or reading.timestamp
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


class ChannelDriftState:
    """CUSUM state for ONE channel of ONE station."""

    def __init__(self, slack: float, threshold: float, beta: float = 0.97, leak: float = 0.98,
                 clip_factor: float = 3.0, min_samples: int = 12):
        self.slack       = slack
        self.threshold   = threshold
        self.beta        = beta
        self.leak        = leak
        self.clip_factor = clip_factor
        self.min_samples = min_samples
        self.reset()

    def reset(self) -> None:
        """Reinitialize to a pristine, uninformed state (new baseline)."""
        self.ema_mean:  Optional[float] = None
        self.s_pos             = 0.0   # Upper CUSUM accumulator
        self.s_neg             = 0.0   # Lower CUSUM accumulator
        self.sample_count      = 0
        self.recent_residuals: List[float] = []
        self.accumulated_drift_rate = 0.0        # slope of recent residuals, per SAMPLE
        self.last_ts: Optional[datetime] = None
        self.mean_interval_minutes: Optional[float] = None
        self.score = 0.0
        self.bias  = 0.0

    def update(self, value: float, ts: Optional[datetime] = None) -> Tuple[float, float]:
        """
        Updates CUSUM with one new VALID, in-order sample.
        Returns (cusum_score [0, 1], recent mean residual vs own baseline).
        """
        if ts is not None and self.last_ts is not None:
            dt_min = (ts - self.last_ts).total_seconds() / 60.0
            self.mean_interval_minutes = dt_min if self.mean_interval_minutes is None \
                else 0.9 * self.mean_interval_minutes + 0.1 * dt_min
        if ts is not None:
            self.last_ts = ts

        self.sample_count += 1
        if self.ema_mean is None:
            self.ema_mean = value

        # Bounded-influence residual: one outlier adds at most (clip - slack).
        clip     = self.clip_factor * self.slack
        residual = float(max(-clip, min(clip, value - self.ema_mean)))
        self.ema_mean = self.ema_mean + (1.0 - self.beta) * residual   # == beta*ema + (1-beta)*value when unclipped

        self.recent_residuals.append(residual)
        if len(self.recent_residuals) > 144:
            self.recent_residuals.pop(0)

        self.s_pos = max(0.0, self.s_pos + residual - self.slack) * self.leak
        self.s_neg = max(0.0, self.s_neg - residual - self.slack) * self.leak

        if len(self.recent_residuals) >= 12:
            slope = 0.0
            try:
                slope, _ = np.polyfit(np.arange(len(self.recent_residuals)), self.recent_residuals, 1)
            except Exception:
                pass
            self.accumulated_drift_rate = float(slope)

        max_s = max(self.s_pos, self.s_neg)
        raw_score = min(1.0, max_s / (self.threshold * 2.0))
        # warm-up gate: no drift conclusion from a handful of samples
        self.score = raw_score if self.sample_count >= self.min_samples else 0.0
        self.bias  = float(np.mean(self.recent_residuals[-12:])) if self.recent_residuals else 0.0
        return self.score, self.bias

    @property
    def drift_tier(self) -> str:
        """Maps current CUSUM state to a human-readable drift tier."""
        if self.sample_count < self.min_samples:
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

    def rate_per_day(self, cfg: DriftThresholds) -> Optional[float]:
        """|drift rate| in channel units/day, from the OBSERVED sampling
        interval (never an assumed 10-minute cadence). None when the cadence
        is unknown or implausible (e.g. a burst processed seconds apart)."""
        m = self.mean_interval_minutes
        if m is None or not (cfg.plausible_cadence_min_minutes <= m <= cfg.plausible_cadence_max_minutes):
            return None
        return abs(self.accumulated_drift_rate) * (1440.0 / m)


class StationDriftTracker:
    """All Sensor Health state for ONE station."""

    def __init__(self, cfg: DriftThresholds = CONFIG.drift):
        self.cfg = cfg
        self.channel_states: Dict[str, ChannelDriftState] = {
            ch: ChannelDriftState(
                slack=cfg.cusum_slack * s_scale, threshold=cfg.cusum_threshold * t_scale,
                beta=cfg.ema_beta, leak=cfg.cusum_leak,
                clip_factor=cfg.cusum_residual_clip_factor, min_samples=cfg.min_samples_for_drift,
            )
            for ch, (s_scale, t_scale) in CHANNEL_CUSUM_SCALE.items()
        }
        self.anomaly_count = 0
        self.total_readings = 0
        self.last_ts: Optional[datetime] = None

    def reset_all(self) -> None:
        for st in self.channel_states.values():
            st.reset()
        self.anomaly_count = 0
        self.total_readings = 0
        self.last_ts = None


class SensorDriftHealthLayer:
    """
    Evaluates sustained change in a physical sensor's behavior (possible
    calibration drift) as sensor-health evidence. See the module docstring for
    exactly what this does and does not claim.
    """
    def __init__(self, config: DriftThresholds = CONFIG.drift):
        self.cfg      = config
        self.trackers: Dict[str, StationDriftTracker] = {}

    def _get_tracker(self, station_id: str) -> StationDriftTracker:
        if station_id not in self.trackers:
            self.trackers[station_id] = StationDriftTracker(self.cfg)
        return self.trackers[station_id]

    @staticmethod
    def _not_applicable_detail() -> Dict[str, Any]:
        return {
            "status": "NOT_APPLICABLE_NON_PHYSICAL_SOURCE",
            "channel_drift": {}, "samples_tracked": 0, "samples_in_radius": 0,
            "health_score": 100.0, "max_drift_score": 0.0, "worst_drift_tier": "NORMAL",
            "observation_status": "NOT_APPLICABLE", "channel_resets": [],
            "reference": "OWN_RECENT_BASELINE",
            "note": "Not a physical sensor (NWP model reference): sensor drift/health is not assessed and no state is kept.",
        }

    def evaluate(
        self,
        reading:           AWSReading,
        recent_is_anomaly: bool = False
    ) -> Tuple[float, float, Optional[float], Optional[str], Dict[str, Any]]:
        """
        Evaluates sustained change in the sensor's own behavior using only
        VALID channels.
        Returns:
            drift_score:              float [0.0, 1.0]
            sensor_health_index:      float [0.0, 100.0]
            estimated_days_to_failure: Optional[float]  -- rough, indicative
                                       extrapolation only; None unless drift is
                                       sustained (LIKELY_DRIFT or worse)
            diagnostic_reason:        Optional[str]
            detail:                   Dict with samples_tracked, drift_tiers per channel
        """
        if reading.source == NWP_SOURCE:
            return 0.0, 100.0, None, None, self._not_applicable_detail()

        tracker = self._get_tracker(reading.station_id)
        cfg     = self.cfg
        ts      = _effective_timestamp(reading)

        def ch_valid(ch: str) -> bool:
            return reading.data_quality.get(ch) == DataQuality.VALID

        values = {
            "temperature_c": reading.temperature_c,
            "pressure_hpa":  reading.pressure_hpa,
            "humidity_pct":  reading.humidity_pct,
        }
        valid_channels = [ch for ch, v in values.items() if ch_valid(ch) and v is not None]

        # ── observation ordering: a duplicate / out-of-order reading is not a new sample ──
        obs_status = "ACCEPTED"
        if ts is not None and tracker.last_ts is not None:
            if ts == tracker.last_ts:
                obs_status = "DUPLICATE"
            elif ts < tracker.last_ts:
                obs_status = "OUT_OF_ORDER"

        resets: List[str] = []
        if obs_status == "ACCEPTED" and valid_channels:
            if ts is not None and tracker.last_ts is not None \
                    and (ts - tracker.last_ts).total_seconds() / 60.0 > cfg.reset_gap_minutes:
                tracker.reset_all()                # stale baseline: start over
                resets.append("station")

            tracker.total_readings += 1
            if recent_is_anomaly:
                tracker.anomaly_count += 1

            for ch in valid_channels:
                state = tracker.channel_states[ch]
                if ts is not None and state.last_ts is not None \
                        and (ts - state.last_ts).total_seconds() / 60.0 > cfg.reset_gap_minutes:
                    state.reset()                  # this channel was absent for too long
                    resets.append(ch)
                state.update(float(values[ch]), ts)

            if ts is not None:
                tracker.last_ts = ts

        # ── per-channel evidence from the CURRENT state (updated, or unchanged for a skipped reading) ──
        detail: Dict[str, Any] = {"channel_drift": {}}
        channel_scores:            List[float] = []
        days_to_failure_estimates: List[float] = []

        tolerance = {"temperature_c": cfg.temp_tolerance_c, "humidity_pct": cfg.humidity_tolerance_pct}

        for ch in valid_channels:
            state = tracker.channel_states[ch]
            if state.sample_count == 0:
                continue                           # nothing ever tracked for this channel
            tier = state.drift_tier
            channel_scores.append(state.score)
            entry: Dict[str, Any] = {
                "drift_tier":      tier,
                "cusum_score":     round(state.score, 3),
                "estimated_bias":  round(state.bias, 3),   # mean recent residual vs the sensor's OWN baseline
                "samples_tracked": state.sample_count,
            }
            if ch in tolerance:
                rate = state.rate_per_day(cfg)
                entry["drift_rate_per_day"] = round(rate, 4) if rate is not None else None
                dtf = None
                # Only with SUSTAINED evidence, a known plausible cadence and a
                # non-trivial rate: a rough extrapolation, not a prediction.
                if (tier in ("LIKELY_DRIFT", "HIGH_RISK") and rate is not None
                        and rate > _MIN_RATE_PER_DAY[ch]):
                    remaining = max(0.0, tolerance[ch] - abs(state.bias))
                    dtf = remaining / rate
                    days_to_failure_estimates.append(dtf)
                entry["days_to_failure"] = round(dtf, 1) if dtf is not None else None
            detail["channel_drift"][ch] = entry

        # ── Composite health score ──────────────────────────────────────────
        max_drift_score      = max(channel_scores) if channel_scores else 0.0
        min_days_to_failure  = min(days_to_failure_estimates) if days_to_failure_estimates else None

        drift_penalty  = max_drift_score * 35.0
        # small-sample guard: one flagged reading among the first few must not
        # look like a 100% error rate
        error_rate     = tracker.anomaly_count / max(cfg.health_error_rate_min_samples, tracker.total_readings, 1)
        error_penalty  = min(40.0, error_rate * 100.0 * 2.0)
        health_score   = max(5.0, min(100.0, 100.0 - drift_penalty - error_penalty))

        # ── Reason based on tier ───────────────────────────────────────────
        reasons: List[str] = []
        worst_tier = "NORMAL"
        for ch, ch_detail in detail["channel_drift"].items():
            tier = ch_detail.get("drift_tier", "NORMAL")
            if tier in ("LIKELY_DRIFT", "HIGH_RISK"):
                reasons.append(
                    f"{ch} CUSUM drift ({tier}): sustained deviation from the sensor's own recent baseline "
                    f"({ch_detail['estimated_bias']:+.2f}), {ch_detail['samples_tracked']} samples tracked"
                )
                worst_tier = tier
            elif tier in ("POSSIBLE_DRIFT", "SUSPICIOUS") and not reasons:
                worst_tier = tier

        if min_days_to_failure is not None and min_days_to_failure < cfg.drift_critical_days:
            if min_days_to_failure <= 0.0:
                reasons.append(
                    "The sustained deviation already exceeds the channel's nominal tolerance "
                    "(indicative only, not a failure prediction)"
                )
            else:
                reasons.append(
                    f"Rough drift-rate extrapolation: tolerance could be exceeded in about "
                    f"{min_days_to_failure:.1f} days (indicative only, not a failure prediction)"
                )

        max_samples = max((c["samples_tracked"] for c in detail["channel_drift"].values()), default=0)
        detail["status"] = "EVALUATED" if max_samples >= cfg.min_samples_for_drift else "INSUFFICIENT_DATA"
        # Output contract: the detector reads a top-level scalar `samples_tracked`
        # for fusion's sensor-health coverage; it was previously only exposed
        # per channel, so that lookup always fell back to 0.
        detail["samples_tracked"]      = max_samples
        detail["min_samples_required"] = cfg.min_samples_for_drift
        detail["health_score"]         = round(health_score, 1)
        detail["max_drift_score"]      = round(max_drift_score, 3)
        detail["worst_drift_tier"]     = worst_tier
        detail["samples_in_radius"]    = tracker.total_readings   # legacy name: valid readings processed for this station
        detail["observation_status"]   = obs_status
        detail["channel_resets"]       = resets
        detail["reference"]            = "OWN_RECENT_BASELINE"
        detail["note"] = (
            "CUSUM against the sensor's own recent baseline: detects sustained change in sensor behavior. "
            "It cannot separate natural weather variability from drift and is not a failure prediction."
        )

        reason_str = "; ".join(reasons) if reasons else None
        return max_drift_score, health_score, min_days_to_failure, reason_str, detail
