"""
Layer 5: Sensor Drift & Health Tracking Engine (v3).

CORRECTNESS RULES:
  - Updates CUSUM only from VALID channel readings.
  - Returns samples_tracked per channel so the UI can show data coverage.
  - 5-tier drift classification:
      NORMAL, SUSPICIOUS, POSSIBLE_DRIFT, LIKELY_DRIFT, HIGH_RISK
  - Does NOT declare sensor failure from a single anomalous reading.

v3 — WHAT IS TRACKED (the reason this layer changed):
  Drift is a change in the SENSOR, not in the weather. Tracking the raw value
  against its own moving average (v2) cannot tell the two apart: the normal
  diurnal cycle (RH falling ~8 %/h every morning) accumulates in CUSUM exactly
  like calibration drift, and any continuously reporting station was flagged
  daily. v3 tracks, per channel, the best weather-independent residual
  available:

    SPATIAL     value − L4 neighbour consensus   (weather is common-mode)
    BACKGROUND  value − NWP background           (observation-minus-background)
    RAW         value − own moving average       (v2 behaviour; no reference —
                                                  kept for isolated stations
                                                  and legacy callers, with
                                                  LOW evidence quality)

  The CUSUM baseline (EMA) learns the station's stable microclimate offset;
  a drift is the residual moving away from it.

  CUSUM increments and the EMA are weighted by elapsed time relative to the
  engine's 10-minute reference cadence, so a 1-minute and a 10-minute station
  accumulate the same evidence per hour. With 10-minute (or unknown) spacing
  this is identical to v2.

  Trend significance uses the Mann-Kendall test (Kendall's tau of residual
  vs. time); a tolerance-breach projection is only reported for a
  statistically significant monotonic trend with CUSUM evidence behind it.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import kendalltau

from config import CONFIG, DriftThresholds
from schema import AWSReading, DataQuality

REFERENCE_CADENCE_S = 600.0     # the cadence v2's per-sample constants assumed
MK_MIN_SAMPLES = 12
MK_P_THRESHOLD = 0.01


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
        self.recent_times:     list = []   # seconds since first sample
        self.accumulated_drift_rate = 0.0  # residual units per 10-min step (v2 unit)
        self.drift_rate_per_day: Optional[float] = None
        self.mk_tau: Optional[float] = None
        self.mk_p:   Optional[float] = None
        self._t0: Optional[datetime] = None
        self._last_ts: Optional[datetime] = None
        self._elapsed_s = 0.0

    def _weight(self, ts: Optional[datetime]) -> float:
        """Elapsed time since the previous sample in units of the 10-minute
        reference cadence. Unknown or sub-5 s spacing (synthetic callers that
        never set timestamps) keeps v2's one-step-per-sample behaviour."""
        if ts is None or self._last_ts is None:
            return 1.0
        try:
            dt = (ts - self._last_ts).total_seconds()
        except Exception:
            return 1.0
        if dt < 5.0:
            return 1.0
        return min(6.0, dt / REFERENCE_CADENCE_S)

    def update(self, value: float, ts: Optional[datetime] = None) -> Tuple[float, float]:
        """
        Updates CUSUM with a new VALID value (a raw reading in RAW mode, a
        residual against a reference otherwise).
        Returns (cusum_score [0, 1], estimated_bias).
        """
        w = self._weight(ts)
        if ts is not None:
            if self._t0 is None:
                self._t0 = ts
            self._last_ts = ts
        self._elapsed_s += w * REFERENCE_CADENCE_S
        self.sample_count += 1
        if self.ema_mean is None:
            self.ema_mean = value

        residual      = value - self.ema_mean
        beta_w        = self.beta ** w
        self.ema_mean = beta_w * self.ema_mean + (1.0 - beta_w) * value

        self.recent_residuals.append(residual)
        self.recent_times.append(self._elapsed_s)
        if len(self.recent_residuals) > 144:
            self.recent_residuals.pop(0)
            self.recent_times.pop(0)

        leak = 0.98 ** w
        self.s_pos = max(0.0, self.s_pos + (residual - self.slack) * w) * leak
        self.s_neg = max(0.0, self.s_neg + (-residual - self.slack) * w) * leak

        if len(self.recent_residuals) >= MK_MIN_SAMPLES:
            t = np.array(self.recent_times)
            r = np.array(self.recent_residuals)
            try:
                slope_per_s, _ = np.polyfit(t, r, 1)
                self.accumulated_drift_rate = float(slope_per_s * REFERENCE_CADENCE_S)
                self.drift_rate_per_day = float(slope_per_s * 86400.0)
            except Exception:
                pass
            # Mann-Kendall only matters once CUSUM sees drift (it gates the
            # breach projection and the evidence text) — skip it otherwise.
            if max(self.s_pos, self.s_neg) >= self.threshold * 0.6:
                try:
                    tau, p = kendalltau(t, r)
                    self.mk_tau = None if np.isnan(tau) else float(tau)
                    self.mk_p = None if np.isnan(p) else float(p)
                except Exception:
                    self.mk_tau, self.mk_p = None, None
            else:
                self.mk_tau, self.mk_p = None, None

        max_s        = max(self.s_pos, self.s_neg)
        score        = min(1.0, max_s / (self.threshold * 2.0))
        current_bias = float(np.mean(self.recent_residuals[-12:])) if self.recent_residuals else 0.0
        return score, current_bias

    @property
    def trend_significant(self) -> bool:
        return self.mk_p is not None and self.mk_p < MK_P_THRESHOLD

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


_CHANNEL_PARAMS = {
    # channel: (slack multiplier, threshold multiplier)
    "temperature_c": (2.0, 2.0),
    "pressure_hpa":  (2.5, 2.5),
    "humidity_pct":  (5.0, 4.0),
}


class StationDriftTracker:
    def __init__(self, cfg: DriftThresholds = CONFIG.drift):
        self.cfg = cfg
        # One CUSUM state per (channel, reference mode): switching reference
        # (e.g. neighbours become available) must not mix residual types.
        self.states: Dict[Tuple[str, str], ChannelDriftState] = {}
        self.anomaly_count = 0
        self.total_readings = 0

    def state(self, channel: str, mode: str) -> ChannelDriftState:
        key = (channel, mode)
        if key not in self.states:
            ks, kt = _CHANNEL_PARAMS[channel]
            self.states[key] = ChannelDriftState(
                slack=self.cfg.cusum_slack * ks, threshold=self.cfg.cusum_threshold * kt
            )
        return self.states[key]

    @property
    def channel_states(self) -> Dict[str, ChannelDriftState]:
        """v2 compatibility: the RAW-mode states keyed by channel."""
        return {ch: self.state(ch, "RAW") for ch in _CHANNEL_PARAMS}


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
        recent_is_anomaly: bool = False,
        spatial_consensus: Optional[Dict[str, Optional[float]]] = None,
        background:        Optional[Dict[str, Optional[float]]] = None,
    ) -> Tuple[float, float, Optional[float], Optional[str], Dict[str, Any]]:
        """
        Evaluates drift and health status using only VALID channels.
        spatial_consensus: L4's IDW neighbour consensus per channel (preferred reference).
        background:        an NWP background per channel, used when no consensus exists.
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

        channel_scores:          List[float] = []
        days_to_failure_estimates: List[float] = []
        detail: Dict[str, Any] = {"channel_drift": {}}
        spatial_consensus = spatial_consensus or {}
        background = background or {}

        tolerances = {
            "temperature_c": (self.cfg.temp_tolerance_c, 0.05),
            "humidity_pct":  (self.cfg.humidity_tolerance_pct, 0.15),
            "pressure_hpa":  (self.cfg.pressure_tolerance_hpa, None),  # v2 never projected pressure
        }

        for ch, value in (
            ("temperature_c", reading.temperature_c),
            ("pressure_hpa",  reading.pressure_hpa),
            ("humidity_pct",  reading.humidity_pct),
        ):
            if reading.data_quality.get(ch) != DataQuality.VALID or value is None:
                continue
            ref_val = spatial_consensus.get(ch) if spatial_consensus.get(ch) is not None else background.get(ch)
            if ch == "humidity_pct" and ref_val is not None and max(value, float(ref_val)) >= 95.0:
                # Near saturation RH is compressed and non-linear: a station and
                # its neighbours can differ by several % purely from a regime
                # change (dry -> saturated). Not a sensor change — skip.
                detail["channel_drift"][ch] = {"reference_mode": "SUSPENDED_SATURATION",
                                               "drift_tier": "NORMAL", "cusum_score": 0.0,
                                               "estimated_bias": 0.0, "drift_rate_per_day": 0.0,
                                               "samples_tracked": tracker.state(ch, "SPATIAL").sample_count,
                                               "mann_kendall": {"tau": None, "p_value": None, "significant": False},
                                               "days_to_failure": None}
                continue
            if spatial_consensus.get(ch) is not None:
                mode, tracked = "SPATIAL", value - float(spatial_consensus[ch])
            elif background.get(ch) is not None:
                mode, tracked = "BACKGROUND", value - float(background[ch])
            else:
                mode, tracked = "RAW", value

            state = tracker.state(ch, mode)
            score, bias = state.update(tracked, reading.timestamp)
            channel_scores.append(score)

            tol, min_rate = tolerances[ch]
            rate_per_day = (
                abs(state.drift_rate_per_day) if state.drift_rate_per_day is not None
                else abs(state.accumulated_drift_rate) * 144.0
            )
            dtf = None
            if min_rate is not None and rate_per_day > min_rate:
                # With a reference, only project a breach for a statistically
                # significant trend that CUSUM also sees. RAW mode keeps v2's rule.
                evidence_ok = mode == "RAW" or (
                    state.trend_significant and state.drift_tier in ("POSSIBLE_DRIFT", "LIKELY_DRIFT", "HIGH_RISK")
                )
                if evidence_ok:
                    remaining = max(0.0, tol - abs(bias))
                    dtf = remaining / rate_per_day
                    days_to_failure_estimates.append(dtf)

            ch_detail = {
                "reference_mode":  mode,
                "drift_tier":      state.drift_tier,
                "cusum_score":     round(score, 3),
                "estimated_bias":  round(bias, 3),
                "drift_rate_per_day": round(rate_per_day, 4),
                "samples_tracked": state.sample_count,
                "mann_kendall": {
                    "tau": round(state.mk_tau, 3) if state.mk_tau is not None else None,
                    "p_value": round(state.mk_p, 4) if state.mk_p is not None else None,
                    "significant": state.trend_significant,
                },
            }
            if min_rate is not None:
                ch_detail["days_to_failure"] = round(dtf, 1) if dtf is not None else None
            detail["channel_drift"][ch] = ch_detail

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
                ref = {"SPATIAL": " vs neighbour consensus", "BACKGROUND": " vs NWP background"}.get(
                    ch_detail["reference_mode"], "")
                mk = ch_detail["mann_kendall"]
                mk_txt = f", Mann-Kendall tau {mk['tau']:+.2f} (p={mk['p_value']:.3f})" if mk["tau"] is not None and mk["significant"] else ""
                reasons.append(
                    f"{ch} CUSUM drift ({tier}): estimated bias {ch_detail['estimated_bias']:+.2f}{ref}, "
                    f"{ch_detail['samples_tracked']} samples tracked{mk_txt}"
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
