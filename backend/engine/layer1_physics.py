"""
Layer 1: Physics Validation Engine.

CORRECTNESS RULES (v2):
  - NEVER flag a missing or zero-substituted value as a physics veto.
  - VETO only fires when the channel DataQuality is VALID and the value is physically impossible.
  - OUT_OF_RANGE values (e.g. humidity = 105%) ARE flagged — they are real but impossible.
  - Returns structured LayerResult with evidence traceability.

Physics checks performed (on VALID channels only):
  1. Hard bounds:  temperature, pressure, humidity, wind
  2. Dew point thermodynamic impossibility (T_dew > T_amb)
  3. Wet-bulb survivability limit (T_wb > 35°C)
  4. Hypsometric barometric altitude consistency
"""
from typing import Dict, Optional, Tuple, Any
import numpy as np

try:
    import metpy.calc as mpcalc
    from metpy.units import units as metpy_units
    METPY_AVAILABLE = True
except ImportError:
    METPY_AVAILABLE = False

from config import CONFIG, PhysicsThresholds
from schema import AWSReading, DataQuality


def _fallback_dewpoint(temp_c: float, rh_pct: float) -> float:
    """Magnus-Tetens formula for dewpoint (fallback when MetPy unavailable)."""
    a = 17.27
    b = 237.7
    rh = max(0.01, min(100.0, rh_pct))
    alpha = ((a * temp_c) / (b + temp_c)) + np.log(rh / 100.0)
    return float((b * alpha) / (a - alpha))


def _make_result(
    score: float,
    veto: bool,
    reason: Optional[str],
    channels_evaluated: list,
    evidence: Optional[Dict[str, Any]] = None
) -> Tuple[float, bool, Optional[str], Dict[str, Any]]:
    """Returns the standardized Layer 1 result tuple."""
    return score, veto, reason, {
        "channels_evaluated": channels_evaluated,
        "evidence": evidence or {},
    }


class PhysicsValidationLayer:
    """
    Thermodynamic and psychrometric validator with VETO authority.

    VETO is only fired when:
      - The channel DataQuality is VALID or OUT_OF_RANGE (a real value was received)
      - AND that real value violates a physical law
    VETO is NOT fired when:
      - The channel is MISSING (None)
      - The channel is ZERO_SUBSTITUTED (0.0 treated as missing)
      - The channel is INVALID
    """
    def __init__(self, config: PhysicsThresholds = CONFIG.physics):
        self.cfg = config

    def evaluate(self, reading: AWSReading) -> Tuple[float, bool, Optional[str], Dict[str, Any]]:
        """
        Evaluates physical consistency of a single reading.
        Returns:
            anomaly_score:    float [0.0, 1.0]
            is_veto:          bool (True if a REAL physically impossible value detected)
            violation_reason: Optional[str]
            detail:           Dict with evidence traceability
        """
        channels_evaluated = []
        scores_and_reasons = []

        # ── Helper: check if channel should be evaluated ──────────────────
        def channel_evaluable(channel_name: str) -> bool:
            q = reading.data_quality.get(channel_name, DataQuality.MISSING)
            # VALID and OUT_OF_RANGE are real values — evaluate them
            # MISSING, ZERO_SUBSTITUTED, INVALID — skip physics check
            return q in (DataQuality.VALID, DataQuality.OUT_OF_RANGE)

        temp_c    = reading.temperature_c
        press_hpa = reading.pressure_hpa
        rh_pct    = reading.humidity_pct
        elev_m    = reading.elevation_m if reading.elevation_m is not None else 0.0

        # ── 1. Humidity hard bounds ────────────────────────────────────────
        if channel_evaluable("humidity_pct") and rh_pct is not None:
            channels_evaluated.append("humidity_pct")
            if rh_pct < self.cfg.humidity_min_pct or rh_pct > self.cfg.humidity_max_pct:
                return _make_result(
                    1.0, True,
                    f"Impossible humidity: {rh_pct:.1f}% is outside the physically possible range [0, 100]%",
                    channels_evaluated,
                    {"channel": "humidity_pct", "value": rh_pct, "valid_range": [0.0, 100.0], "method": "hard_bounds"}
                )

        # ── 2. Temperature hard bounds ─────────────────────────────────────
        if channel_evaluable("temperature_c") and temp_c is not None:
            channels_evaluated.append("temperature_c")
            if temp_c < self.cfg.temp_min_c or temp_c > self.cfg.temp_max_c:
                return _make_result(
                    1.0, True,
                    f"Temperature {temp_c:.1f}°C violates terrestrial physical boundaries "
                    f"[{self.cfg.temp_min_c}, {self.cfg.temp_max_c}]°C",
                    channels_evaluated,
                    {"channel": "temperature_c", "value": temp_c,
                     "valid_range": [self.cfg.temp_min_c, self.cfg.temp_max_c], "method": "hard_bounds"}
                )

        # ── 3. Pressure hard bounds ────────────────────────────────────────
        if channel_evaluable("pressure_hpa") and press_hpa is not None:
            channels_evaluated.append("pressure_hpa")
            if press_hpa < self.cfg.pressure_min_hpa or press_hpa > self.cfg.pressure_max_hpa:
                return _make_result(
                    1.0, True,
                    f"Barometric pressure {press_hpa:.1f} hPa outside physical bounds "
                    f"[{self.cfg.pressure_min_hpa}, {self.cfg.pressure_max_hpa}] hPa",
                    channels_evaluated,
                    {"channel": "pressure_hpa", "value": press_hpa,
                     "valid_range": [self.cfg.pressure_min_hpa, self.cfg.pressure_max_hpa], "method": "hard_bounds"}
                )

        # ── 4. Wind speed bounds ───────────────────────────────────────────
        wind_kmh = reading.wind_speed_kmh
        if wind_kmh is not None:
            if wind_kmh >= self.cfg.wind_storm_kmh:
                return _make_result(
                    1.0, True,
                    f"Storm-force wind ({wind_kmh:.1f} km/h) exceeds operational sensor ceiling",
                    channels_evaluated + ["wind_speed_kmh"],
                    {"channel": "wind_speed_kmh", "value": wind_kmh, "threshold": self.cfg.wind_storm_kmh}
                )
            elif wind_kmh >= self.cfg.wind_gale_kmh:
                scores_and_reasons.append((0.70, f"Gale-force wind gust ({wind_kmh:.1f} km/h) recorded"))

        # ── 5. Thermodynamic Dew Point & Wet Bulb (requires T + RH, both VALID) ──
        if (channel_evaluable("temperature_c") and channel_evaluable("humidity_pct")
                and temp_c is not None and rh_pct is not None):
            try:
                safe_rh = max(0.5, min(100.0, rh_pct))
                calc_dewpoint = None

                if METPY_AVAILABLE:
                    try:
                        calc_dewpoint = mpcalc.dewpoint_from_relative_humidity(
                            temp_c * metpy_units.degC, safe_rh * metpy_units.percent
                        ).to('degC').magnitude
                    except Exception:
                        calc_dewpoint = _fallback_dewpoint(temp_c, safe_rh)
                else:
                    calc_dewpoint = _fallback_dewpoint(temp_c, safe_rh)

                measured_dew = reading.dew_point_c if reading.dew_point_c is not None else calc_dewpoint
                if measured_dew is not None and measured_dew > (temp_c + self.cfg.dew_point_margin_c):
                    return _make_result(
                        1.0, True,
                        f"Thermodynamic Violation: Dew point ({measured_dew:.2f}°C) exceeds ambient "
                        f"temperature ({temp_c:.2f}°C) — physically impossible",
                        channels_evaluated,
                        {"dew_point_c": measured_dew, "temperature_c": temp_c,
                         "margin_allowed": self.cfg.dew_point_margin_c, "method": "psychrometric"}
                    )

                # Wet bulb survivability check
                if press_hpa is not None and channel_evaluable("pressure_hpa") and METPY_AVAILABLE and calc_dewpoint is not None:
                    try:
                        wet_bulb = mpcalc.wet_bulb_temperature(
                            press_hpa * metpy_units.hPa,
                            temp_c    * metpy_units.degC,
                            calc_dewpoint * metpy_units.degC
                        ).to('degC').magnitude
                        if wet_bulb > self.cfg.max_wet_bulb_c:
                            return _make_result(
                                1.0, True,
                                f"Wet-bulb temperature ({wet_bulb:.1f}°C) exceeds survivability limit ({self.cfg.max_wet_bulb_c}°C)",
                                channels_evaluated,
                                {"wet_bulb_c": wet_bulb, "limit": self.cfg.max_wet_bulb_c, "method": "wet_bulb_metpy"}
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        # ── 6. Barometric Altitude Consistency ─────────────────────────────
        if (channel_evaluable("pressure_hpa") and press_hpa is not None
                and elev_m is not None and elev_m > 50):
            try:
                h    = elev_m
                t0   = self.cfg.sea_level_temp_k
                l    = self.cfg.temp_lapse_rate
                g    = self.cfg.gravity
                r    = self.cfg.gas_constant
                exp  = g / (r * l)
                expected = self.cfg.sea_level_pressure_hpa * ((1.0 - (l * h) / t0) ** exp)
                pct_dev  = abs(press_hpa - expected) / expected * 100.0

                if pct_dev > self.cfg.max_pressure_altitude_error_pct:
                    scores_and_reasons.append((
                        0.85,
                        f"Barometric Discrepancy: {press_hpa:.1f} hPa deviates {pct_dev:.1f}% "
                        f"from hypsometric expectation ({expected:.1f} hPa) at elevation {h:.0f} m"
                    ))
            except Exception:
                pass

        # ── Aggregate soft violations ──────────────────────────────────────
        if scores_and_reasons:
            max_score  = max(s for s, _ in scores_and_reasons)
            max_reason = max(scores_and_reasons, key=lambda x: x[0])[1]
            return _make_result(
                max_score, False, max_reason, channels_evaluated,
                {"soft_violations": [r for _, r in scores_and_reasons]}
            )

        # All checks passed or skipped due to missing data
        skipped = [
            ch for ch in ("temperature_c", "pressure_hpa", "humidity_pct")
            if reading.data_quality.get(ch) not in (DataQuality.VALID, DataQuality.OUT_OF_RANGE)
        ]
        skipped_note = f" Skipped channels (missing data): {skipped}" if skipped else ""
        return _make_result(0.0, False, None, channels_evaluated,
                            {"note": f"All physics checks passed.{skipped_note}"})
