"""
Multivariate feature space: pressure-convention normalization + robust,
city-conditioned T/P/RH features.

This module is the SINGLE definition of the feature vector. Both the offline
training pipeline (backend/multivariate_training/) and the runtime layer
(engine/layer3_multivariate.py) import it, so the model can never be trained on
one representation and queried with another.

WHY THIS EXISTS -- the pressure-convention mismatch
---------------------------------------------------
The historical reference dataset stores SURFACE (station) pressure: it reads
~648 hPa at high-altitude cities and 912 hPa at Bengaluru. The runtime feeds
SEA-LEVEL-REDUCED pressure (Open-Meteo `pressure_msl`, ~1010 hPa everywhere).
Comparing them directly differs by 0-100 hPa depending on the city's elevation,
i.e. tens of robust standard deviations, which would flag every normal station
as an extreme outlier purely because of a unit/convention difference.

The reference distribution is therefore converted to an approximate
SEA-LEVEL-EQUIVALENT pressure before any statistics or model see it.

PRESSURE CONVERSION (documented assumptions)
--------------------------------------------
Atmosphere model: constant lapse rate L = 0.0065 K/m, dry air.

    P_msl = P_sfc * (1 + L*h / T_sfc_K) ** (g / (R_d * L))

with g = 9.80665 m/s^2, R_d = 287.05 J/(kg K), L = 0.0065 K/m. The exponent
g/(R_d*L) = 5.2559. T_sfc_K is the observation's own surface temperature.

CLIMATOLOGICAL ELEVATION PROXY
------------------------------
The dataset carries no station elevation, and none is available at runtime, so
elevation is NOT assumed. Instead the SAME relation is inverted at each city's
robust historical medians, with the ICAO standard sea-level pressure
P_ref = 1013.25 hPa as the sea-level reference:

    h_proxy = (T_med_K / L) * ((P_ref / P_sfc_med) ** (R_d*L/g) - 1)     [m, floored at 0]

This is a NORMALIZATION PROXY named `climatological_elevation_proxy`. It is NOT
an authoritative geographic elevation and must never be presented as one.

KNOWN, UNTUNED RESIDUAL
-----------------------
Because P_ref is the standard atmosphere, the converted pressure is centred
near 1013 hPa, whereas India's true climatological mean sea-level pressure is a
few hPa lower. This appears as a small, uniform negative offset in the runtime
pressure feature. It is measured and reported, not tuned away.

FEATURE VECTOR (exact runtime == training definition)
-----------------------------------------------------
    [z_temperature, z_pressure_msl_equivalent, z_humidity]

    z = (x - median) / scale,   scale = max(1.4826 * MAD, floor)

with per-channel floors so a degenerate (near-constant) city can never divide
by ~0.
"""
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Physical constants (SI) ───────────────────────────────────────────────
GRAVITY_M_S2 = 9.80665
R_DRY_AIR = 287.05                 # J/(kg K)
LAPSE_RATE_K_PER_M = 0.0065        # standard tropospheric lapse rate
P_REF_HPA = 1013.25                # ICAO standard sea-level pressure
BAROMETRIC_EXPONENT = GRAVITY_M_S2 / (R_DRY_AIR * LAPSE_RATE_K_PER_M)   # ~5.2559
KELVIN = 273.15

# ── Conventions ───────────────────────────────────────────────────────────
PRESSURE_MSL = "MSL"
PRESSURE_SURFACE = "SURFACE"
PRESSURE_UNKNOWN = "UNKNOWN"
DATASET_PRESSURE_CONVENTION = PRESSURE_SURFACE
RUNTIME_PRESSURE_CONVENTION = PRESSURE_MSL
PRESSURE_NORMALIZATION_METHOD = "SURFACE_TO_MSL_EQUIVALENT_CONSTANT_LAPSE_HYPSOMETRIC"
ELEVATION_PROXY_METHOD = (
    "climatological_elevation_proxy: constant-lapse hypsometric inversion at the city's "
    "robust median surface pressure and median temperature, P_ref=1013.25 hPa (ICAO)"
)

# ── Robust scaling ────────────────────────────────────────────────────────
MAD_TO_SIGMA = 1.4826              # makes MAD comparable to a Gaussian sigma
# Minimum scale per channel: used when a city's MAD is ~0 (near-constant series).
SCALE_FLOOR = {"temperature_c": 0.5, "pressure_hpa": 0.5, "humidity_pct": 1.0}

FEATURE_NAMES = ("z_temperature", "z_pressure_msl_equivalent", "z_humidity")

# ── City matching ─────────────────────────────────────────────────────────
# Runtime stations carry lat/lon but no city field. The nearest reference city
# within this radius supplies the baseline; otherwise GLOBAL_FALLBACK. 75 km is
# the measured MEDIAN spacing between neighbouring cities in the reference
# dataset (75 km, 175 cities), so a match never reaches past roughly one city
# spacing.
MAX_CITY_MATCH_KM = 75.0

SCOPE_CITY = "CITY"
SCOPE_GLOBAL = "GLOBAL_FALLBACK"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


# ── Pressure conversion ───────────────────────────────────────────────────
def climatological_elevation_proxy(p_surface_median_hpa: float, t_median_c: float) -> float:
    """Elevation PROXY (metres, floored at 0) from a city's median surface
    pressure and median temperature. See the module docstring: this is a
    normalization proxy, not an authoritative station elevation."""
    t_k = t_median_c + KELVIN
    ratio = (P_REF_HPA / p_surface_median_hpa) ** (1.0 / BAROMETRIC_EXPONENT)
    h = (t_k / LAPSE_RATE_K_PER_M) * (ratio - 1.0)
    return float(max(0.0, h))


def surface_to_msl_equivalent(p_surface_hpa, t_c, elevation_m):
    """Sea-level-equivalent pressure from SURFACE pressure.

    Works on scalars or numpy arrays. `elevation_m` is either the city's
    `climatological_elevation_proxy` (offline reference conversion) or an
    AUTHORITATIVE station elevation supplied with a runtime reading -- it is
    never invented at runtime.
    """
    t_k = np.asarray(t_c, dtype=float) + KELVIN
    factor = (1.0 + LAPSE_RATE_K_PER_M * np.asarray(elevation_m, dtype=float) / t_k) ** BAROMETRIC_EXPONENT
    out = np.asarray(p_surface_hpa, dtype=float) * factor
    return float(out) if out.ndim == 0 else out


# ── Robust z-score ────────────────────────────────────────────────────────
def robust_scale(mad: float, channel: str) -> float:
    return float(max(MAD_TO_SIGMA * float(mad), SCALE_FLOOR[channel]))


def robust_z(x, median: float, mad: float, channel: str):
    return (np.asarray(x, dtype=float) - float(median)) / robust_scale(mad, channel)


# ── Baselines ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Baseline:
    """Robust reference statistics for one scope (a city, or the global pool)."""
    scope: str
    name: Optional[str]
    temperature_median: float
    temperature_mad: float
    humidity_median: float
    humidity_mad: float
    pressure_msl_equivalent_median: float
    pressure_msl_equivalent_mad: float
    pressure_surface_median: float
    pressure_surface_mad: float
    climatological_elevation_proxy: Optional[float]
    lat: Optional[float] = None
    lon: Optional[float] = None
    n_reference_rows: int = 0

    @staticmethod
    def from_dict(scope: str, name: Optional[str], d: Dict[str, Any]) -> "Baseline":
        return Baseline(
            scope=scope, name=name,
            temperature_median=d["temperature_median"], temperature_mad=d["temperature_mad"],
            humidity_median=d["humidity_median"], humidity_mad=d["humidity_mad"],
            pressure_msl_equivalent_median=d["pressure_msl_equivalent_median"],
            pressure_msl_equivalent_mad=d["pressure_msl_equivalent_mad"],
            pressure_surface_median=d["pressure_surface_median"],
            pressure_surface_mad=d["pressure_surface_mad"],
            climatological_elevation_proxy=d.get("climatological_elevation_proxy"),
            lat=d.get("lat"), lon=d.get("lon"), n_reference_rows=int(d.get("n_reference_rows", 0)),
        )


def feature_vector(t_c, p_msl_equivalent_hpa, rh_pct, baseline: Baseline) -> np.ndarray:
    """[z_temperature, z_pressure_msl_equivalent, z_humidity].

    `p_msl_equivalent_hpa` MUST already be sea-level(-equivalent) pressure.
    Accepts scalars or equal-length arrays (returns shape (3,) or (n, 3)).
    """
    zt = robust_z(t_c, baseline.temperature_median, baseline.temperature_mad, "temperature_c")
    zp = robust_z(p_msl_equivalent_hpa, baseline.pressure_msl_equivalent_median,
                  baseline.pressure_msl_equivalent_mad, "pressure_hpa")
    zh = robust_z(rh_pct, baseline.humidity_median, baseline.humidity_mad, "humidity_pct")
    return np.stack([zt, zp, zh], axis=-1)


class BaselineSet:
    """City baselines plus the documented global fallback."""

    def __init__(self, cities: Dict[str, Baseline], global_baseline: Baseline,
                 max_match_km: float = MAX_CITY_MATCH_KM):
        self.cities = cities
        self.global_baseline = global_baseline
        self.max_match_km = float(max_match_km)
        self._names: List[str] = sorted(cities)
        self._lat = np.array([cities[n].lat for n in self._names], dtype=float)
        self._lon = np.array([cities[n].lon for n in self._names], dtype=float)

    @staticmethod
    def from_artifact(doc: Dict[str, Any]) -> "BaselineSet":
        cities = {n: Baseline.from_dict(SCOPE_CITY, n, d) for n, d in doc["cities"].items()}
        g = Baseline.from_dict(SCOPE_GLOBAL, None, doc["global_fallback"])
        return BaselineSet(cities, g, doc.get("city_match", {}).get("max_km", MAX_CITY_MATCH_KM))

    def resolve(self, lat: Optional[float], lon: Optional[float]) -> Tuple[Baseline, Optional[float]]:
        """Nearest city within `max_match_km`, else the GLOBAL fallback.

        Returns (baseline, distance_km_to_matched_city_or_None). A reading with
        no usable coordinate (missing, or the 0/0 default) never matches a city.
        """
        if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
            return self.global_baseline, None
        # vectorised haversine to every city
        p1 = math.radians(lat)
        p2 = np.radians(self._lat)
        dphi = p2 - p1
        dl = np.radians(self._lon - lon)
        a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
        d = 2 * 6371.0088 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
        i = int(np.argmin(d))
        if float(d[i]) <= self.max_match_km:
            return self.cities[self._names[i]], round(float(d[i]), 1)
        return self.global_baseline, None


# ── Detector evidence ─────────────────────────────────────────────────────
def evidence_from_raw(raw, center: float, threshold: float, extreme: float):
    """Map a raw detector score to evidence in [0, 1].

    Piecewise-linear and monotone:  raw <= center -> 0,  raw == threshold -> 0.5,
    raw >= extreme -> 1.  The three anchors are percentiles of the detector's
    scores on a CLEAN calibration period (see the model card). This is an
    anomaly EVIDENCE score, NOT a probability.
    """
    raw = np.asarray(raw, dtype=float)
    threshold = max(float(threshold), float(center) + 1e-9)
    extreme = max(float(extreme), threshold + 1e-9)
    lo = 0.5 * (raw - center) / (threshold - center)
    hi = 0.5 + 0.5 * (raw - threshold) / (extreme - threshold)
    out = np.clip(np.where(raw <= threshold, lo, hi), 0.0, 1.0)
    return float(out) if out.ndim == 0 else out
