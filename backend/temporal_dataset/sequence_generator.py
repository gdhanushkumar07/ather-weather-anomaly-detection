"""
Per-station synthetic temporal sequence generation (Stage 1 — normal data only).

Generates a single coupled multivariate (temperature_c, pressure_hpa,
relative_humidity_pct) sequence per station, anchored on that station's real
snapshot baseline from data/stations.json, using:

  - a diurnal sinusoid for temperature (afternoon-peaked, not solar-noon-peaked)
  - AR(1) slow + fast correlated components for temperature and pressure
    (NOT independent per-step Gaussian noise — see design note below)
  - humidity coupled to the temperature deviation from baseline, plus its
    own smaller AR(1) noise, clipped to [0, 100]

No anomalies are injected in Stage 1. `is_anomaly`/`anomaly_type` columns
are always False/None here; the schema exists so Stage-2/3 anomaly
injection can reuse the same long-form table without a schema change.

DESIGN NOTE ON AR(1) NOISE:
An AR(1) process x[t] = rho * x[t-1] + eps[t] (eps ~ N(0, sigma^2)) has
adjacent-sample correlation Corr(x[t], x[t-1]) = rho. Using rho close to 1
("slow") makes a component drift smoothly over hours; rho in [0.6, 0.8]
("fast") makes a component correlated only over a few consecutive 10-minute
steps. Both are correlated-noise processes, unlike i.i.d. Gaussian noise
(rho = 0), which is exactly what the Stage 1 spec requires ("adjacent
readings should be correlated").
"""
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import numpy as np

from config import CONFIG
from .config import TemporalGeneratorConfig

# Fixed, explicit UTC anchor for all generated timelines. Every generated
# timestamp is timezone-aware UTC — there is no ambiguous "local time"
# stored anywhere; local solar time is used ONLY internally to shape the
# diurnal sinusoid's phase (see _approx_local_solar_hour) and is never
# written to the output.
GENERATION_ANCHOR_UTC = datetime(2025, 1, 6, 0, 0, 0, tzinfo=timezone.utc)  # a Monday, arbitrary but fixed


def _station_rng(global_seed: int, station_id: str) -> np.random.Generator:
    """Per-station RNG derived from (global_seed, station_id) so each
    station's sequence is independently reproducible regardless of
    processing order or how many other stations are generated.

    Uses zlib.crc32 rather than Python's built-in hash() — str hashing is
    randomized per-process (PYTHONHASHSEED) unless disabled, which would
    silently break cross-run/cross-process determinism.
    """
    stable_id_hash = zlib.crc32(station_id.encode("utf-8"))
    seed_seq = np.random.SeedSequence([global_seed, stable_id_hash])
    return np.random.default_rng(seed_seq)


def _approx_local_solar_hour(utc_hour_frac: float, longitude_deg: float) -> float:
    """
    Coarse local-solar-time approximation (15 degrees longitude ~= 1 hour),
    used ONLY to phase-shift the diurnal sinusoid so temperature peaks in
    the station's own afternoon rather than globally at UTC-afternoon.
    This is an approximation for shaping realism, not a real timezone
    conversion, and is documented as such (Stage 1 limitation).
    """
    return (utc_hour_frac + longitude_deg / 15.0) % 24.0


def _ar1_series(n: int, rho: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Generates a zero-mean AR(1) correlated series of length n."""
    innovations = rng.normal(loc=0.0, scale=sigma, size=n)
    series = np.empty(n, dtype=float)
    series[0] = innovations[0]
    for t in range(1, n):
        series[t] = rho * series[t - 1] + innovations[t]
    return series


def _diurnal_amplitude_for_latitude(base_amplitude_c: float, latitude_deg: float, scale: bool) -> float:
    if not scale:
        return base_amplitude_c
    # Mild, bounded scaling: amplitude grows away from the equator, capped
    # at +/-60 deg so polar stations don't get an unrealistically extreme
    # swing from this simple heuristic.
    lat_factor = min(abs(latitude_deg), 60.0) / 60.0
    return base_amplitude_c * (0.7 + 0.6 * lat_factor)


@dataclass
class StationSequenceResult:
    station_id: str
    timestamps: List[datetime]
    temperature_c: np.ndarray
    pressure_hpa: np.ndarray
    relative_humidity_pct: np.ndarray
    clip_counts: Dict[str, int]


def generate_station_sequence(
    station: Dict[str, Any],
    cfg: TemporalGeneratorConfig,
) -> StationSequenceResult:
    station_id = str(station["id"])
    t_base = float(station["temperature"])
    p_base = float(station["pressure"])
    rh_base = float(station["humidity"])
    lat = float(station["latitude"])
    lon = float(station["longitude"])

    n = cfg.total_steps_per_station
    interval_min = cfg.sampling_interval_minutes
    rng = _station_rng(cfg.seed, station_id)

    timestamps = [GENERATION_ANCHOR_UTC + timedelta(minutes=interval_min * i) for i in range(n)]
    utc_hour_frac = np.array([ts.hour + ts.minute / 60.0 for ts in timestamps])
    local_hour = np.array([_approx_local_solar_hour(h, lon) for h in utc_hour_frac])

    # ── Temperature: diurnal + slow AR(1) + fast AR(1) ──────────────────
    amplitude = _diurnal_amplitude_for_latitude(cfg.diurnal_amplitude_c, lat, cfg.scale_amplitude_by_latitude)
    # sin(2*pi*(h - phase)/24) peaks when (h - phase) = 6 (quarter period).
    # Solving for phase so the peak lands at diurnal_peak_local_hour:
    phase_shift = cfg.diurnal_peak_local_hour - 6.0
    diurnal_component = amplitude * np.sin(2.0 * np.pi * (local_hour - phase_shift) / 24.0)

    slow_component_t = _ar1_series(n, cfg.temp_slow_rho, cfg.temp_slow_sigma, rng)
    fast_component_t = _ar1_series(n, cfg.temp_fast_rho, cfg.temp_fast_sigma, rng)

    temperature_c = t_base + diurnal_component + slow_component_t + fast_component_t

    # ── Humidity: coupled to temperature deviation + own AR(1) noise ───
    temp_deviation = temperature_c - t_base
    humidity_noise = _ar1_series(n, cfg.humidity_fast_rho, cfg.humidity_fast_sigma, rng)
    relative_humidity_pct = (
        rh_base
        - cfg.humidity_temp_coupling_pct_per_c * temp_deviation
        + humidity_noise
    )

    # ── Pressure: slow AR(1) drift + small fast AR(1) noise, no diurnal ─
    slow_component_p = _ar1_series(n, cfg.pressure_slow_rho, cfg.pressure_slow_sigma, rng)
    fast_component_p = _ar1_series(n, cfg.pressure_fast_rho, cfg.pressure_fast_sigma, rng)
    pressure_hpa = p_base + slow_component_p + fast_component_p

    # ── Physical bounds enforcement (reuse EXISTING physics config) ────
    phys = CONFIG.physics
    clip_counts = {"temperature_c": 0, "pressure_hpa": 0, "relative_humidity_pct": 0}

    def _clip_and_count(values: np.ndarray, lo: float, hi: float, key: str) -> np.ndarray:
        violations = int(np.sum((values < lo) | (values > hi)))
        clip_counts[key] = violations
        return np.clip(values, lo, hi)

    temperature_c = _clip_and_count(temperature_c, phys.temp_min_c, phys.temp_max_c, "temperature_c")
    pressure_hpa = _clip_and_count(pressure_hpa, phys.pressure_min_hpa, phys.pressure_max_hpa, "pressure_hpa")
    relative_humidity_pct = _clip_and_count(relative_humidity_pct, phys.humidity_min_pct, phys.humidity_max_pct, "relative_humidity_pct")

    return StationSequenceResult(
        station_id=station_id,
        timestamps=timestamps,
        temperature_c=temperature_c,
        pressure_hpa=pressure_hpa,
        relative_humidity_pct=relative_humidity_pct,
        clip_counts=clip_counts,
    )
