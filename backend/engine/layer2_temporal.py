"""
Layer 2: Temporal Pattern Analysis Engine (v2 + Stage 4 LSTM evidence).

CORRECTNESS RULES:
  - Only evaluates channels with DataQuality == VALID.
  - Returns INSUFFICIENT_DATA status when < 3 historical readings exist.
  - Reports historical_points per channel so the frontend can show data coverage.
  - Step-rate spikes require a VALID previous reading too.
  - Never declares a spike or freeze on a single data point.

STAGE 4 ADDITION:
  - An optional LSTM next-step-prediction residual is combined with the
    ORIGINAL rule-based evidence above as an ADDITIONAL signal — it never
    replaces or disables any of the rule-based checks. See
    engine/lstm_temporal.py for the LSTM wrapper and config.LSTMTemporalConfig
    for its settings. If the LSTM artifacts are unavailable or fail to
    load/run, this layer transparently falls back to rule-based-only
    behavior (identical to pre-Stage-4 behavior).
"""
from collections import deque
from typing import Dict, Optional, Tuple, Any
import numpy as np

from config import CONFIG, TemporalThresholds, LSTMTemporalConfig
from schema import AWSReading, DataQuality
from .lstm_temporal import LSTMTemporalEvidence, LSTMStepResult

_MIN_HISTORY_FOR_TEMPORAL = 3   # Minimum readings required for any temporal conclusion
_MIN_HISTORY_FOR_ZSCORE   = 24  # Minimum readings required for rolling Z-score

_LSTM_CHANNELS = ("temperature_c", "pressure_hpa", "humidity_pct")


class StationTemporalBuffer:
    def __init__(self, max_len: int = 72, lstm_sequence_length: int = 144, lstm_residual_window: int = 6):
        # Store only VALID readings per channel
        self.history_temp:  deque = deque(maxlen=max_len)
        self.history_press: deque = deque(maxlen=max_len)
        self.history_rh:    deque = deque(maxlen=max_len)
        self.last_reading: Optional[AWSReading] = None
        self.readings_total: int = 0

        # ── Stage 4: LSTM-specific buffers (additive, do not affect the
        # rule-based deques above) ──────────────────────────────────────
        # Only ever appended when ALL THREE channels are VALID together on
        # the SAME reading, so every entry is a complete, aligned
        # (timestamp, T, P, RH) tuple — never partially missing, never fed
        # to the LSTM with a NaN.
        self.history_complete: deque = deque(maxlen=lstm_sequence_length)
        # Rolling recent LSTM channel scores, for the "recent peak" logic
        # (spec section 11) — lets a temporal deviation the LSTM caught a
        # few steps ago keep contributing evidence even if the LSTM has
        # since adapted to a frozen/stale value and its CURRENT residual
        # has fallen.
        self.recent_lstm_channel_scores: Dict[str, deque] = {
            ch: deque(maxlen=lstm_residual_window) for ch in _LSTM_CHANNELS
        }


class TemporalPatternLayer:
    """
    Evaluates temporal dynamics: step-rate spikes, frozen sensors, rolling
    Z-score (all original, unchanged rule-based checks), PLUS an optional
    Stage 4 LSTM next-step-prediction residual as additional evidence.
    """
    def __init__(self, config: TemporalThresholds = CONFIG.temporal,
                 lstm_config: LSTMTemporalConfig = CONFIG.lstm_temporal):
        self.cfg = config
        self.buffers: Dict[str, StationTemporalBuffer] = {}
        # Loaded ONCE here (not per station, not per reading). Degrades
        # gracefully to rule-based-only behavior if artifacts are missing
        # or fail to load — see LSTMTemporalEvidence.__init__.
        self.lstm = LSTMTemporalEvidence(lstm_config)

    def _get_buffer(self, station_id: str) -> StationTemporalBuffer:
        if station_id not in self.buffers:
            self.buffers[station_id] = StationTemporalBuffer(
                max_len=self.cfg.rolling_window_samples,
                lstm_sequence_length=self.lstm.cfg.sequence_length,
                lstm_residual_window=self.lstm.cfg.residual_window,
            )
        return self.buffers[station_id]

    def evaluate(self, reading: AWSReading) -> Tuple[float, Dict[str, float], Optional[str], Dict[str, Any]]:
        """
        Evaluates temporal consistency.
        Returns:
            anomaly_score:   float [0.0, 1.0]
            channel_scores:  Dict[str, float]
            detected_reason: Optional[str]
            detail:          Dict with traceability (historical_points, method, etc.)
        """
        buf = self._get_buffer(reading.station_id)
        buf.readings_total += 1

        scores:           Dict[str, float] = {"temperature_c": 0.0, "pressure_hpa": 0.0, "humidity_pct": 0.0}
        detected_reasons: list = []
        detail:           Dict[str, Any]   = {}

        def ch_valid(ch: str) -> bool:
            return reading.data_quality.get(ch) == DataQuality.VALID

        # Stage 6: check staleness/ordering of the LSTM history BEFORE it is
        # used for prediction — not just before deciding whether to append
        # to it. Originally this check only ran later (at append time), so
        # the very reading that ARRIVED after a big gap (or out of order)
        # still got an LSTM prediction using the now-stale/misordered
        # pre-gap history, one step later than intended. Moving the same
        # check here means a reading arriving long after (or not after) the
        # buffer's last entry never uses that stale/misordered history —
        # it correctly reports insufficient_valid_history instead, and
        # rewarming starts cleanly from this reading onward. This is the
        # SAME reset condition as before (see the append step below), just
        # evaluated at the right time; no new policy was introduced.
        if buf.history_complete and reading.timestamp is not None:
            gap_minutes = (reading.timestamp - buf.history_complete[-1][0]).total_seconds() / 60.0
            if gap_minutes > self.lstm.cfg.max_gap_minutes or gap_minutes <= 0:
                buf.history_complete.clear()

        # ── Stage 4: LSTM next-step prediction (uses the history as it
        # stood BEFORE this reading — never includes the reading being
        # predicted in its own 144-step input, per spec section 7). The
        # result is only MERGED into scores/reasons/detail further below,
        # after all the ORIGINAL rule-based checks have run unchanged.
        history_before_this_reading = list(buf.history_complete)
        lstm_result: LSTMStepResult = self.lstm.evaluate(
            history_before_this_reading,
            reading.temperature_c if ch_valid("temperature_c") else None,
            reading.pressure_hpa if ch_valid("pressure_hpa") else None,
            reading.humidity_pct if ch_valid("humidity_pct") else None,
        )
        if lstm_result.available:
            buf.recent_lstm_channel_scores["temperature_c"].append(lstm_result.temperature_score)
            buf.recent_lstm_channel_scores["pressure_hpa"].append(lstm_result.pressure_score)
            buf.recent_lstm_channel_scores["humidity_pct"].append(lstm_result.humidity_score)

        # ── 1. Step-Rate / Spike Check ─────────────────────────────────────
        if buf.last_reading is not None:
            prev = buf.last_reading
            dt_seconds = 600.0
            if reading.timestamp and prev.timestamp:
                try:
                    # Stage 6: abs() — an out-of-order/backfilled/rollback
                    # reading (timestamp earlier than the cached "previous")
                    # must not be clamped down to a 1-second interval. That
                    # collapsed interval_factor to its floor (0.5), making
                    # the abrupt-change threshold artificially tight and
                    # capable of flagging a perfectly normal value change as
                    # a false spike (confirmed: a plausible +2C/30min change
                    # scored 0.91 and produced a false "Abrupt temperature
                    # change" reason before this fix). Using the MAGNITUDE
                    # of the time gap keeps the threshold scaled to how much
                    # real time actually separates the two readings either
                    # direction, without asserting anything about order.
                    dt_seconds = max(1.0, abs((reading.timestamp - prev.timestamp).total_seconds()))
                except Exception:
                    dt_seconds = 600.0

            interval_factor = max(0.5, min(3.0, dt_seconds / 600.0))

            # Temperature spike — only if BOTH current and previous are VALID
            if (ch_valid("temperature_c") and reading.temperature_c is not None
                    and prev.channel_valid("temperature_c") and prev.temperature_c is not None):
                d_temp  = abs(reading.temperature_c - prev.temperature_c)
                max_dt  = self.cfg.max_temp_delta_c * interval_factor
                if d_temp > max_dt:
                    score = min(1.0, d_temp / (max_dt * 1.8))
                    scores["temperature_c"] = max(scores["temperature_c"], score)
                    detected_reasons.append(
                        f"Abrupt temperature change: {d_temp:.1f}°C in {int(dt_seconds)}s "
                        f"(max expected {max_dt:.1f}°C)"
                    )
                    detail["temp_spike"] = {
                        "current": reading.temperature_c,
                        "previous": prev.temperature_c,
                        "delta_c": round(d_temp, 2),
                        "interval_s": int(dt_seconds),
                        "max_allowed_c": round(max_dt, 2),
                        "score": round(score, 3),
                    }

            # Pressure spike
            if (ch_valid("pressure_hpa") and reading.pressure_hpa is not None
                    and prev.channel_valid("pressure_hpa") and prev.pressure_hpa is not None):
                d_press = abs(reading.pressure_hpa - prev.pressure_hpa)
                max_dp  = self.cfg.max_pressure_delta_hpa * interval_factor
                if d_press > max_dp:
                    score = min(1.0, d_press / (max_dp * 1.8))
                    scores["pressure_hpa"] = max(scores["pressure_hpa"], score)
                    detected_reasons.append(
                        f"Abrupt pressure change: {d_press:.1f} hPa in {int(dt_seconds)}s"
                    )
                    detail["press_spike"] = {
                        "current": reading.pressure_hpa, "previous": prev.pressure_hpa,
                        "delta_hpa": round(d_press, 2), "interval_s": int(dt_seconds),
                        "score": round(score, 3)
                    }

            # Humidity spike
            if (ch_valid("humidity_pct") and reading.humidity_pct is not None
                    and prev.channel_valid("humidity_pct") and prev.humidity_pct is not None):
                d_rh   = abs(reading.humidity_pct - prev.humidity_pct)
                max_drh = self.cfg.max_humidity_delta_pct * interval_factor
                if d_rh > max_drh:
                    score = min(1.0, d_rh / (max_drh * 1.8))
                    scores["humidity_pct"] = max(scores["humidity_pct"], score)
                    detected_reasons.append(
                        f"Abrupt humidity change: {d_rh:.1f}% in {int(dt_seconds)}s"
                    )

        # ── Update rolling histories (VALID readings only) ──────────────────
        if ch_valid("temperature_c") and reading.temperature_c is not None:
            buf.history_temp.append(reading.temperature_c)
        if ch_valid("pressure_hpa") and reading.pressure_hpa is not None:
            buf.history_press.append(reading.pressure_hpa)
        if ch_valid("humidity_pct") and reading.humidity_pct is not None:
            buf.history_rh.append(reading.humidity_pct)

        # Stage 4: append to the LSTM's joint-valid history ONLY when all
        # three channels are VALID on this SAME reading, and only AFTER
        # lstm_result above was already computed from the prior state —
        # this reading never appears inside its own prediction's input.
        # (Stage 6: the gap/ordering check that used to live here now runs
        # BEFORE the LSTM call above, so by this point the buffer is
        # already correctly reset if this reading broke contiguity —
        # appending here is unconditional on that account.)
        if (ch_valid("temperature_c") and ch_valid("pressure_hpa") and ch_valid("humidity_pct")
                and reading.temperature_c is not None and reading.pressure_hpa is not None
                and reading.humidity_pct is not None):
            buf.history_complete.append((reading.timestamp, reading.temperature_c, reading.pressure_hpa, reading.humidity_pct))

        buf.last_reading = reading

        # Track history counts for data quality reporting
        detail["historical_points"] = {
            "temperature_c": len(buf.history_temp),
            "pressure_hpa":  len(buf.history_press),
            "humidity_pct":  len(buf.history_rh),
        }

        max_history = max(
            len(buf.history_temp),
            len(buf.history_press),
            len(buf.history_rh)
        )

        # Check if we have enough history for rolling statistics,
        # but allow acute 2-point step-rate spikes to be reported
        spike_detected = any(s > 0.5 for s in scores.values())

        if max_history < _MIN_HISTORY_FOR_TEMPORAL and not spike_detected:
            detail["status"] = "INSUFFICIENT_DATA"
            detail["note"] = f"Only {max_history} valid reading(s) available. Temporal analysis requires {_MIN_HISTORY_FOR_TEMPORAL}+."
            return 0.0, scores, None, detail

        detail["status"] = "EVALUATED"

        # ── 2. Frozen / Stuck Sensor Check ─────────────────────────────────
        win_t = self.cfg.frozen_window_size

        if len(buf.history_temp) >= win_t:
            recent_t = list(buf.history_temp)[-win_t:]
            if (max(recent_t) - min(recent_t)) < self.cfg.frozen_variance_threshold:
                scores["temperature_c"] = max(scores["temperature_c"], 0.95)
                detected_reasons.append(
                    f"Frozen temperature sensor: constant {recent_t[0]:.2f}°C across {win_t} consecutive readings"
                )
                detail["frozen_temp"] = {
                    "stuck_value": recent_t[0],
                    "window_size": win_t,
                    "variance": round(max(recent_t) - min(recent_t), 6),
                    "score": 0.95
                }

        if len(buf.history_press) >= win_t:
            recent_p = list(buf.history_press)[-win_t:]
            if (max(recent_p) - min(recent_p)) < self.cfg.frozen_variance_threshold:
                scores["pressure_hpa"] = max(scores["pressure_hpa"], 0.95)
                detected_reasons.append(
                    f"Frozen pressure sensor: constant {recent_p[0]:.2f} hPa across {win_t} readings"
                )

        if len(buf.history_rh) >= win_t:
            recent_rh = list(buf.history_rh)[-win_t:]
            if ((max(recent_rh) - min(recent_rh)) < self.cfg.frozen_variance_threshold
                    and recent_rh[0] < 99.5):
                scores["humidity_pct"] = max(scores["humidity_pct"], 0.95)
                detected_reasons.append(
                    f"Frozen humidity sensor: constant {recent_rh[0]:.2f}% across {win_t} readings"
                )

        # ── 3. Rolling Statistical Z-Score Check ───────────────────────────
        for ch_name, hist, val in [
            ("temperature_c", buf.history_temp,  reading.temperature_c),
            ("pressure_hpa",  buf.history_press, reading.pressure_hpa),
            ("humidity_pct",  buf.history_rh,    reading.humidity_pct),
        ]:
            if (ch_valid(ch_name) and val is not None
                    and len(hist) >= _MIN_HISTORY_FOR_ZSCORE):
                arr = np.array(hist)
                med = np.median(arr)
                mad = np.median(np.abs(arr - med))
                if mad > 1e-3:
                    mod_z = 0.6745 * abs(val - med) / mad
                    if mod_z > self.cfg.z_score_threshold:
                        z_score = min(1.0, (mod_z - self.cfg.z_score_threshold) / 3.0 + 0.6)
                        scores[ch_name] = max(scores[ch_name], z_score)
                        detected_reasons.append(
                            f"{ch_name} statistical outlier: current={val:.2f}, "
                            f"rolling median={med:.2f}, modified Z={mod_z:.1f} "
                            f"(threshold {self.cfg.z_score_threshold})"
                        )
                        detail[f"zscore_{ch_name}"] = {
                            "current": val, "median": round(med, 3),
                            "mad": round(mad, 3), "modified_z": round(mod_z, 2),
                            "sample_count": len(hist), "score": round(z_score, 3)
                        }

        # ── Stage 4: merge LSTM evidence (ADDS to, never replaces, the
        # rule-based scores computed above) ─────────────────────────────
        pre_lstm_scores = dict(scores)  # snapshot: did a rule already flag each channel this cycle?

        channel_labels = {"temperature_c": ("temperature", "°C"), "pressure_hpa": ("pressure", "hPa"), "humidity_pct": ("humidity", "%")}
        recent_peak_by_channel: Dict[str, float] = {}
        for ch in _LSTM_CHANNELS:
            recent_scores = buf.recent_lstm_channel_scores[ch]
            recent_peak_by_channel[ch] = max(recent_scores) if recent_scores else 0.0
            # Combine via max() — the SAME aggregation idiom every rule-based
            # check above already uses to combine evidence within a channel.
            # This can only ever RAISE a channel's score, never lower a
            # strong existing rule-based signal (spec section 13).
            scores[ch] = max(scores[ch], recent_peak_by_channel[ch])

        for ch in _LSTM_CHANNELS:
            if recent_peak_by_channel[ch] <= self.lstm.cfg.reason_report_threshold:
                continue
            label, unit = channel_labels[ch]
            rule_already_flagged = pre_lstm_scores[ch] > self.lstm.cfg.reason_report_threshold
            if rule_already_flagged:
                detected_reasons.append(f"{label.capitalize()} anomaly with elevated temporal prediction residual")
            elif lstm_result.available and ch == "temperature_c" and lstm_result.temperature_score == recent_peak_by_channel[ch]:
                sign = "+" if lstm_result.temperature_residual >= 0 else ""
                detected_reasons.append(
                    f"Temporal prediction residual: {label} deviates from expected value "
                    f"(expected {lstm_result.predicted_temperature_c:.1f}{unit}, actual {reading.temperature_c:.1f}{unit}, "
                    f"residual {sign}{lstm_result.temperature_residual:.1f}{unit})"
                )
            elif lstm_result.available and ch == "pressure_hpa" and lstm_result.pressure_score == recent_peak_by_channel[ch]:
                sign = "+" if lstm_result.pressure_residual >= 0 else ""
                detected_reasons.append(
                    f"Temporal prediction residual: {label} deviates from expected value "
                    f"(expected {lstm_result.predicted_pressure_hpa:.1f}{unit}, actual {reading.pressure_hpa:.1f}{unit}, "
                    f"residual {sign}{lstm_result.pressure_residual:.1f}{unit})"
                )
            elif lstm_result.available and ch == "humidity_pct" and lstm_result.humidity_score == recent_peak_by_channel[ch]:
                sign = "+" if lstm_result.humidity_residual >= 0 else ""
                detected_reasons.append(
                    f"Temporal prediction residual: {label} deviates from expected value "
                    f"(expected {lstm_result.predicted_humidity_pct:.1f}{unit}, actual {reading.humidity_pct:.1f}{unit}, "
                    f"residual {sign}{lstm_result.humidity_residual:.1f}{unit})"
                )
            else:
                # The current step's own LSTM residual has already fallen
                # (e.g. frozen/stale adaptation) but a recent peak within
                # the rolling window still carries evidence forward.
                detected_reasons.append(
                    f"Temporal prediction residual: recent elevated {label} deviation within the last "
                    f"{self.lstm.cfg.residual_window} readings"
                )

        detail["lstm"] = {
            "lstm_available": lstm_result.available,
            "lstm_skip_reason": lstm_result.skip_reason,
            "lstm_predicted_temperature_c": lstm_result.predicted_temperature_c,
            "lstm_predicted_pressure_hpa": lstm_result.predicted_pressure_hpa,
            "lstm_predicted_humidity_pct": lstm_result.predicted_humidity_pct,
            "temperature_residual": lstm_result.temperature_residual,
            "pressure_residual": lstm_result.pressure_residual,
            "humidity_residual": lstm_result.humidity_residual,
            "temperature_abs_residual": lstm_result.temperature_abs_residual,
            "pressure_abs_residual": lstm_result.pressure_abs_residual,
            "humidity_abs_residual": lstm_result.humidity_abs_residual,
            "temperature_lstm_score": round(lstm_result.temperature_score, 4),
            "pressure_lstm_score": round(lstm_result.pressure_score, 4),
            "humidity_lstm_score": round(lstm_result.humidity_score, 4),
            "temperature_lstm_raw_score": lstm_result.temperature_raw_score,
            "pressure_lstm_raw_score": lstm_result.pressure_raw_score,
            "humidity_lstm_raw_score": lstm_result.humidity_raw_score,
            "lstm_residual_score": round(lstm_result.lstm_residual_score, 4),
            "recent_lstm_peak": round(max(recent_peak_by_channel.values()), 4),
            "recent_lstm_peak_by_channel": {ch: round(v, 4) for ch, v in recent_peak_by_channel.items()},
            "note": "lstm_residual_score is an INITIAL Stage 4 calibration signal, not the final ATHER temporal score.",
        }

        overall_score = max(scores.values())
        reason_str    = "; ".join(detected_reasons) if detected_reasons else None
        return overall_score, scores, reason_str, detail
