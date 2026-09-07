"""
Layer 2: Temporal Pattern Analysis Engine.
Implements high-throughput time-series checks:
1. Rate-of-Change step spikes (Delta x / Delta t)
2. Frozen / Stuck-at-constant sensor detection (sliding variance)
3. Rolling dynamic Z-score / MAD statistical deviation
Maintains rolling per-station state for streaming inference (< 1ms execution).
"""
from collections import deque
from typing import Dict, Optional, Tuple
import numpy as np

from ather.config import CONFIG, TemporalThresholds
from ather.data.schema import AWSReading

class StationTemporalBuffer:
    def __init__(self, max_len: int = 72):
        self.history_temp = deque(maxlen=max_len)
        self.history_press = deque(maxlen=max_len)
        self.history_rh = deque(maxlen=max_len)
        self.last_reading: Optional[AWSReading] = None

class TemporalPatternLayer:
    """
    Evaluates temporal dynamics, local continuity, and step-rate variations.
    """
    def __init__(self, config: TemporalThresholds = CONFIG.temporal):
        self.cfg = config
        self.buffers: Dict[str, StationTemporalBuffer] = {}

    def _get_buffer(self, station_id: str) -> StationTemporalBuffer:
        if station_id not in self.buffers:
            self.buffers[station_id] = StationTemporalBuffer(max_len=self.cfg.rolling_window_samples)
        return self.buffers[station_id]

    def evaluate(self, reading: AWSReading) -> Tuple[float, Dict[str, float], Optional[str]]:
        """
        Evaluates temporal consistency of current reading against historical buffer.
        Returns:
            anomaly_score: float [0.0, 1.0]
            channel_scores: Dict[str, float]
            detected_flag: Optional[str]
        """
        buf = self._get_buffer(reading.station_id)
        scores = {"temperature_c": 0.0, "pressure_hpa": 0.0, "humidity_pct": 0.0}
        detected_reasons = []

        # 1. Step-Rate / Spike Check against immediate predecessor
        if buf.last_reading is not None:
            dt_seconds = (reading.timestamp - buf.last_reading.timestamp).total_seconds()
            # Standardize step interval (nominal 600s = 10min)
            interval_factor = max(0.5, min(3.0, dt_seconds / 600.0)) if dt_seconds > 0 else 1.0

            d_temp = abs(reading.temperature_c - buf.last_reading.temperature_c)
            d_press = abs(reading.pressure_hpa - buf.last_reading.pressure_hpa)
            d_rh = abs(reading.humidity_pct - buf.last_reading.humidity_pct)

            max_dt = self.cfg.max_temp_delta_c * interval_factor
            max_dp = self.cfg.max_pressure_delta_hpa * interval_factor
            max_drh = self.cfg.max_humidity_delta_pct * interval_factor

            if d_temp > max_dt:
                score = min(1.0, d_temp / (max_dt * 1.8))
                scores["temperature_c"] = max(scores["temperature_c"], score)
                detected_reasons.append(f"Abrupt Temp Spike (+/-{d_temp:.1f}°C in {int(dt_seconds)}s)")

            if d_press > max_dp:
                score = min(1.0, d_press / (max_dp * 1.8))
                scores["pressure_hpa"] = max(scores["pressure_hpa"], score)
                detected_reasons.append(f"Abrupt Pressure Spike (+/-{d_press:.1f}hPa)")

            if d_rh > max_drh:
                score = min(1.0, d_rh / (max_drh * 1.8))
                scores["humidity_pct"] = max(scores["humidity_pct"], score)
                detected_reasons.append(f"Abrupt Humidity Spike (+/-{d_rh:.1f}%)")

        # Update rolling histories
        buf.history_temp.append(reading.temperature_c)
        buf.history_press.append(reading.pressure_hpa)
        buf.history_rh.append(reading.humidity_pct)
        buf.last_reading = reading

        # 2. Frozen / Stuck Sensor Check (Strict identical repeated values)
        # In meteorology, sensor lockup produces 0.000 variation across sustained hours
        win_t = 12   # 2 hours for temperature
        win_p = 12   # 2 hours for pressure
        win_rh = 12  # 2 hours for humidity

        if len(buf.history_temp) >= win_t:
            recent_t = list(buf.history_temp)[-win_t:]
            if (max(recent_t) - min(recent_t)) < 1e-6:
                scores["temperature_c"] = max(scores["temperature_c"], 0.95)
                detected_reasons.append(f"Frozen Temperature Sensor (Stuck at {recent_t[0]:.2f}°C for {win_t} intervals)")

        if len(buf.history_press) >= win_p:
            recent_p = list(buf.history_press)[-win_p:]
            if (max(recent_p) - min(recent_p)) < 1e-6:
                scores["pressure_hpa"] = max(scores["pressure_hpa"], 0.95)
                detected_reasons.append(f"Frozen Pressure Sensor (Stuck at {recent_p[0]:.2f}hPa for {win_p} intervals)")

        if len(buf.history_rh) >= win_rh:
            recent_rh = list(buf.history_rh)[-win_rh:]
            if (max(recent_rh) - min(recent_rh)) < 1e-6 and recent_rh[0] < 99.5:
                scores["humidity_pct"] = max(scores["humidity_pct"], 0.95)
                detected_reasons.append(f"Frozen Humidity Sensor (Stuck at {recent_rh[0]:.2f}% for {win_rh} intervals)")

        # 3. Rolling Statistical Z-Score Check (Full 24h Diurnal Cycle = 144 samples)
        if len(buf.history_temp) >= 144:
            for ch_name, hist, val in [
                ("temperature_c", buf.history_temp, reading.temperature_c),
                ("pressure_hpa", buf.history_press, reading.pressure_hpa),
                ("humidity_pct", buf.history_rh, reading.humidity_pct),
            ]:
                arr = np.array(hist)
                med = np.median(arr)
                mad = np.median(np.abs(arr - med))
                if mad > 1e-3:
                    mod_z = 0.6745 * abs(val - med) / mad
                    if mod_z > 4.5:  # Extreme statistical outlier beyond diurnal range
                        z_score = min(1.0, (mod_z - 4.5) / 3.0 + 0.6)
                        scores[ch_name] = max(scores[ch_name], z_score)
                        detected_reasons.append(f"{ch_name} statistical outlier (Modified Z={mod_z:.1f})")

        overall_score = max(scores.values())
        reason_str = "; ".join(detected_reasons) if detected_reasons else None
        return overall_score, scores, reason_str
