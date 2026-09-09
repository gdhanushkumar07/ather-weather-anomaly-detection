"""
Layer 2: Temporal Pattern Analysis Engine (v2).

CORRECTNESS RULES:
  - Only evaluates channels with DataQuality == VALID.
  - Returns INSUFFICIENT_DATA status when < 3 historical readings exist.
  - Reports historical_points per channel so the frontend can show data coverage.
  - Step-rate spikes require a VALID previous reading too.
  - Never declares a spike or freeze on a single data point.
"""
from collections import deque
from typing import Dict, Optional, Tuple, Any
import numpy as np

from config import CONFIG, TemporalThresholds
from schema import AWSReading, DataQuality

_MIN_HISTORY_FOR_TEMPORAL = 3   # Minimum readings required for any temporal conclusion
_MIN_HISTORY_FOR_ZSCORE   = 24  # Minimum readings required for rolling Z-score


class StationTemporalBuffer:
    def __init__(self, max_len: int = 72):
        # Store only VALID readings per channel
        self.history_temp:  deque = deque(maxlen=max_len)
        self.history_press: deque = deque(maxlen=max_len)
        self.history_rh:    deque = deque(maxlen=max_len)
        self.last_reading: Optional[AWSReading] = None
        self.readings_total: int = 0


class TemporalPatternLayer:
    """
    Evaluates temporal dynamics: step-rate spikes, frozen sensors, and rolling Z-score.
    """
    def __init__(self, config: TemporalThresholds = CONFIG.temporal):
        self.cfg = config
        self.buffers: Dict[str, StationTemporalBuffer] = {}

    def _get_buffer(self, station_id: str) -> StationTemporalBuffer:
        if station_id not in self.buffers:
            self.buffers[station_id] = StationTemporalBuffer(max_len=self.cfg.rolling_window_samples)
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

        # ── 1. Step-Rate / Spike Check ─────────────────────────────────────
        if buf.last_reading is not None:
            prev = buf.last_reading
            dt_seconds = 600.0
            if reading.timestamp and prev.timestamp:
                try:
                    dt_seconds = max(1.0, (reading.timestamp - prev.timestamp).total_seconds())
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

        overall_score = max(scores.values())
        reason_str    = "; ".join(detected_reasons) if detected_reasons else None
        return overall_score, scores, reason_str, detail
