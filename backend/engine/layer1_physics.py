"""
Layer 1: Physics Intelligence Engine.

CORRECTNESS RULES (v2):
  - NEVER flag a missing or zero-substituted value as a physics veto.
  - VETO only fires when the channel DataQuality is VALID and the value is physically impossible.
  - OUT_OF_RANGE values (e.g. humidity = 105%) ARE flagged — they are real but impossible.
  - Returns structured LayerResult with evidence traceability.

Two complementary sub-systems, both living in this one module:

  A. Physics-based rules (MetPy + closed-form atmospheric equations), with
     VETO authority — fire on unambiguous, deterministic violations:
       1. Hard bounds:  temperature, pressure, humidity, wind
       2. Dew point thermodynamic impossibility (T_dew > T_amb)
       3. Wet-bulb survivability limit (T_wb > 35°C)
       4. Hypsometric barometric altitude consistency

  B. Physics-Informed Neural Network (PINN) — a small denoising autoencoder
     over (temperature, pressure, humidity, altitude), trained offline
     (see train_pinn.py) with Total Loss = Data Loss + lambda * Physics Loss,
     where the physics loss penalizes the network's OWN reconstruction for
     breaking the same laws the rules above enforce (dew point <=
     temperature, hypsometric pressure-altitude consistency, RH in [0,100]).
     It only runs on readings that already passed every check in (A), and
     contributes:
       - expected_value / physics_residual per channel (comparing the
         observation to the network's reconstruction) — usable directly for
         self-healing imputation even when no anomaly is flagged.
       - a smooth, capped physics_score contribution for combinations that
         are individually in-range but jointly atypical (a graded signal
         under the hard-veto thresholds, rather than a binary cutoff).

Output (per evaluate() call, in `detail`): physics_score, physics_reason,
expected_value, physics_residual — alongside the existing
channels_evaluated/evidence fields the rest of the engine already relies on.
"""
import json
import os
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

try:
    import metpy.calc as mpcalc
    from metpy.units import units as metpy_units
    METPY_AVAILABLE = True
except ImportError:
    METPY_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from config import CONFIG, PhysicsThresholds, PINNThresholds
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
    evidence: Optional[Dict[str, Any]] = None,
    expected_value: Optional[Dict[str, float]] = None,
    physics_residual: Optional[Dict[str, float]] = None,
) -> Tuple[float, bool, Optional[str], Dict[str, Any]]:
    """
    Returns the standardized Layer 1 result tuple. `detail` always carries the
    physics_score/physics_reason/expected_value/physics_residual keys called
    for by the Layer 1 spec, in addition to the existing channels_evaluated/
    evidence fields other code already relies on.
    """
    return score, veto, reason, {
        "channels_evaluated": channels_evaluated,
        "evidence": evidence or {},
        "physics_score": round(float(score), 3),
        "physics_reason": reason,
        "expected_value": expected_value or {},
        "physics_residual": physics_residual or {},
    }


# ═════════════════════════════════════════════════════════════════════════
# B. Physics-Informed Neural Network
#
# Kept inside this module (rather than a separate package) so the whole
# Layer 1 story — rules + MetPy + PINN — lives in one file. train_pinn.py
# imports PhysicsInformedNet/magnus_dewpoint_torch/hypsometric_pressure_torch
# from here to train offline; nothing at runtime needs to know it exists.
# ═════════════════════════════════════════════════════════════════════════

PINN_CHANNELS: List[str] = ["temperature_c", "pressure_hpa", "humidity_pct"]
PINN_ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "pinn_artifacts")
PINN_WEIGHTS_PATH = os.path.join(PINN_ARTIFACTS_DIR, "pinn_weights.pt")
PINN_NORM_STATS_PATH = os.path.join(PINN_ARTIFACTS_DIR, "norm_stats.json")

# Same Magnus-Tetens constants as _fallback_dewpoint() above, so the PINN's
# physics loss enforces exactly the same dew-point law the rules check.
_MAGNUS_A = 17.27
_MAGNUS_B = 237.7


if TORCH_AVAILABLE:
    class PhysicsInformedNet(nn.Module):
        """
        Input (7): [T_norm, P_norm, RH_norm, alt_norm, mask_T, mask_P, mask_RH]
        Output (3): [T_hat_norm, P_hat_norm, RH_hat_norm]

        The 4-unit bottleneck is deliberately undercomplete relative to the
        7-dim input so the network cannot trivially copy its input through —
        it must prioritize physically-plausible, densely-populated regions of
        training data, which is what gives reconstruction error meaning as a
        joint-plausibility signal.
        """
        def __init__(self, hidden: int = 16, bottleneck: int = 4):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(7, hidden), nn.Tanh(),
                nn.Linear(hidden, bottleneck), nn.Tanh(),
            )
            self.decoder = nn.Sequential(
                nn.Linear(bottleneck, hidden), nn.Tanh(),
                nn.Linear(hidden, 3),
            )

        def forward(self, x):
            return self.decoder(self.encoder(x))

    def magnus_dewpoint_torch(temp_c: "torch.Tensor", rh_pct: "torch.Tensor") -> "torch.Tensor":
        """Differentiable Magnus-Tetens dew point, same constants as _fallback_dewpoint()."""
        safe_rh = torch.clamp(rh_pct, min=0.5, max=100.0)
        alpha = (_MAGNUS_A * temp_c) / (_MAGNUS_B + temp_c) + torch.log(safe_rh / 100.0)
        # Guard the denominator away from zero to keep training numerically stable
        # for wildly out-of-distribution intermediate predictions.
        denom = torch.clamp(_MAGNUS_A - alpha, min=1e-3)
        return (_MAGNUS_B * alpha) / denom

    def hypsometric_pressure_torch(temp_c: "torch.Tensor", altitude_m: "torch.Tensor",
                                    sea_level_hpa: float, lapse_rate: float,
                                    sea_level_k: float, gravity: float, gas_const: float) -> "torch.Tensor":
        """Differentiable standard-atmosphere barometric formula, same constants as section 6 above."""
        exponent = gravity / (gas_const * lapse_rate)
        base = torch.clamp(1.0 - (lapse_rate * altitude_m) / sea_level_k, min=1e-3)
        return sea_level_hpa * torch.pow(base, exponent)
else:
    PhysicsInformedNet = None  # torch unavailable — PINNPhysicsEngine below stays in fallback mode


class PINNPhysicsEngine:
    """
    Inference-time wrapper: loads pretrained weights + normalization stats
    once, then serves reconstruction / consistency-scoring calls used by
    PhysicsValidationLayer.evaluate(). Never raises — every public method
    degrades to a "no opinion" return (None / 0.0 score) if torch or the
    trained artifacts are unavailable (same degrade-gracefully pattern as
    METPY_AVAILABLE above).
    """

    def __init__(self, weights_path: str = PINN_WEIGHTS_PATH, norm_path: str = PINN_NORM_STATS_PATH):
        self.available = False
        self.model = None
        self.norm: Optional[Dict[str, Dict[str, float]]] = None

        if not TORCH_AVAILABLE:
            return
        if not (os.path.isfile(weights_path) and os.path.isfile(norm_path)):
            return
        try:
            with open(norm_path, "r") as f:
                self.norm = json.load(f)
            model = PhysicsInformedNet()
            state = torch.load(weights_path, map_location="cpu")
            model.load_state_dict(state)
            model.eval()
            self.model = model
            self.available = True
        except Exception:
            self.available = False
            self.model = None
            self.norm = None

    def _normalize(self, channel: str, value: float) -> float:
        stats = self.norm[channel]
        return (value - stats["mean"]) / max(1e-6, stats["std"])

    def _denormalize(self, channel: str, value: float) -> float:
        stats = self.norm[channel]
        return value * stats["std"] + stats["mean"]

    def _forward(
        self,
        temperature_c: Optional[float],
        pressure_hpa: Optional[float],
        humidity_pct: Optional[float],
        elevation_m: float,
    ) -> Optional[Dict[str, float]]:
        if not self.available:
            return None
        try:
            raw = {"temperature_c": temperature_c, "pressure_hpa": pressure_hpa, "humidity_pct": humidity_pct}
            feats, masks = [], []
            for ch in PINN_CHANNELS:
                v = raw[ch]
                if v is None:
                    feats.append(0.0)
                    masks.append(0.0)
                else:
                    feats.append(self._normalize(ch, float(v)))
                    masks.append(1.0)
            alt_norm = self._normalize("elevation_m", float(elevation_m) if elevation_m is not None else 0.0)

            x = torch.tensor([feats + [alt_norm] + masks], dtype=torch.float32)
            with torch.no_grad():
                out = self.model(x)[0].tolist()
            return {
                "temperature_c": self._denormalize("temperature_c", out[0]),
                "pressure_hpa": self._denormalize("pressure_hpa", out[1]),
                "humidity_pct": self._denormalize("humidity_pct", out[2]),
            }
        except Exception:
            return None

    def reconstruct_all(
        self, temperature_c: Optional[float], pressure_hpa: Optional[float],
        humidity_pct: Optional[float], elevation_m: float,
    ) -> Optional[Dict[str, float]]:
        """Reconstructs (T, P, RH) using every channel that is actually present."""
        return self._forward(temperature_c, pressure_hpa, humidity_pct, elevation_m)

    def leave_one_out_expected(
        self, temperature_c: Optional[float], pressure_hpa: Optional[float],
        humidity_pct: Optional[float], elevation_m: float, channel: str,
    ) -> Optional[float]:
        """
        Estimates `channel` using ONLY the other channels + altitude (masks
        `channel` out even if a value is supplied) — the self-healing
        "expected value if this sensor were faulty/missing" estimate.
        """
        if channel not in PINN_CHANNELS:
            return None
        raw = {"temperature_c": temperature_c, "pressure_hpa": pressure_hpa, "humidity_pct": humidity_pct}
        raw[channel] = None
        result = self._forward(raw["temperature_c"], raw["pressure_hpa"], raw["humidity_pct"], elevation_m)
        return result[channel] if result else None

    def evaluate_consistency(
        self,
        temperature_c: Optional[float],
        pressure_hpa: Optional[float],
        humidity_pct: Optional[float],
        elevation_m: float,
        valid_channels: List[str],
        cfg: PINNThresholds,
    ) -> Tuple[float, Optional[str], Dict[str, float], Dict[str, float]]:
        """
        Compares each VALID channel's observed value to the autoencoder's
        full reconstruction (all currently-valid channels visible). Returns
        a conservative, capped soft score — this check runs only on readings
        that already passed every hard veto/threshold in
        PhysicsValidationLayer, so it is deliberately a secondary,
        corroborating signal rather than a primary detector.

        Returns: (score, reason, expected_value_by_channel, residual_by_channel)
        """
        empty: Dict[str, float] = {}
        if not self.available or len(valid_channels) < 2:
            return 0.0, None, empty, empty

        recon = self.reconstruct_all(temperature_c, pressure_hpa, humidity_pct, elevation_m)
        if recon is None:
            return 0.0, None, empty, empty

        raw = {"temperature_c": temperature_c, "pressure_hpa": pressure_hpa, "humidity_pct": humidity_pct}
        tolerance_abs = {
            "temperature_c": cfg.temp_consistency_tolerance_c,
            "humidity_pct": cfg.humidity_consistency_tolerance_pct,
        }

        expected: Dict[str, float] = {}
        residual: Dict[str, float] = {}
        worst_z, worst_channel = 0.0, None

        for ch in valid_channels:
            observed = raw.get(ch)
            if observed is None:
                continue
            exp_val = recon[ch]
            expected[ch] = round(float(exp_val), 3)
            resid = float(observed) - exp_val
            residual[ch] = round(resid, 3)

            if ch == "pressure_hpa":
                # Relative tolerance — matches the rule layer's percentage-based
                # hypsometric check rather than a flat hPa band.
                tol = max(1e-3, abs(exp_val)) * (cfg.pressure_consistency_tolerance_pct / 100.0)
            else:
                tol = tolerance_abs[ch]

            z = abs(resid) / max(1e-6, tol)
            if z > worst_z:
                worst_z, worst_channel = z, ch

        if worst_channel is None:
            return 0.0, None, expected, residual

        ramp_span = max(1e-6, cfg.score_ramp_saturate_z - cfg.score_ramp_start_z)
        score = float(np.clip((worst_z - cfg.score_ramp_start_z) / ramp_span, 0.0, 1.0)) * cfg.max_score_contribution

        reason = None
        if score > 0.0:
            reason = (
                f"PINN joint-consistency check: {worst_channel} observed "
                f"{raw[worst_channel]:.2f} deviates {residual[worst_channel]:+.2f} from the "
                f"autoencoder's physics-regularized reconstruction {expected[worst_channel]:.2f} "
                f"given the other channels and altitude"
            )
        return score, reason, expected, residual


# Process-wide singleton — weights are loaded once, not per-reading.
_pinn_engine_singleton: Optional[PINNPhysicsEngine] = None


def get_pinn_engine() -> PINNPhysicsEngine:
    global _pinn_engine_singleton
    if _pinn_engine_singleton is None:
        _pinn_engine_singleton = PINNPhysicsEngine()
    return _pinn_engine_singleton


# ═════════════════════════════════════════════════════════════════════════
# A. Physics Validation Layer (rules + MetPy) + B. PINN integration
# ═════════════════════════════════════════════════════════════════════════

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
    def __init__(self, config: PhysicsThresholds = CONFIG.physics, pinn_config: PINNThresholds = CONFIG.pinn):
        self.cfg = config
        self.pinn_cfg = pinn_config
        self.pinn = get_pinn_engine()

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

        # ── 7. PINN Joint-Consistency Check (soft, secondary signal) ────────
        # Only reached once every hard veto/threshold above has already
        # passed. Supplies expected_value/physics_residual (self-healing
        # input) unconditionally, and contributes a capped soft score only
        # for combinations that drift far enough from the autoencoder's
        # physics-regularized reconstruction to be worth flagging.
        expected_value: Dict[str, float] = {}
        physics_residual: Dict[str, float] = {}
        if self.pinn_cfg.enabled and self.pinn.available:
            valid_channels = [
                ch for ch, val in (
                    ("temperature_c", temp_c), ("pressure_hpa", press_hpa), ("humidity_pct", rh_pct)
                ) if channel_evaluable(ch) and val is not None
            ]
            try:
                pinn_score, pinn_reason, expected_value, physics_residual = self.pinn.evaluate_consistency(
                    temp_c, press_hpa, rh_pct, elev_m, valid_channels, self.pinn_cfg
                )
                if pinn_score > 0.0:
                    scores_and_reasons.append((pinn_score, pinn_reason))
            except Exception:
                pass

        # ── Aggregate soft violations ──────────────────────────────────────
        if scores_and_reasons:
            max_score  = max(s for s, _ in scores_and_reasons)
            max_reason = max(scores_and_reasons, key=lambda x: x[0])[1]
            return _make_result(
                max_score, False, max_reason, channels_evaluated,
                {"soft_violations": [r for _, r in scores_and_reasons]},
                expected_value=expected_value,
                physics_residual=physics_residual,
            )

        # All checks passed or skipped due to missing data
        skipped = [
            ch for ch in ("temperature_c", "pressure_hpa", "humidity_pct")
            if reading.data_quality.get(ch) not in (DataQuality.VALID, DataQuality.OUT_OF_RANGE)
        ]
        skipped_note = f" Skipped channels (missing data): {skipped}" if skipped else ""
        return _make_result(0.0, False, None, channels_evaluated,
                            {"note": f"All physics checks passed.{skipped_note}"},
                            expected_value=expected_value,
                            physics_residual=physics_residual)
