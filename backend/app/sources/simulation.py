"""
SimulationAdapter — realistic SIMULATED_AWS telemetry + fault injection.

WHY THIS EXISTS: no public real-time API exists for IMD AWS data, and the
WeatherUnion catalogue in this repository carries locations only. For a
demonstrable end-to-end system, this adapter generates telemetry for the
REAL WeatherUnion AWS locations. Every observation is tagged
source=SIMULATED_AWS and the UI labels it as simulated everywhere.

Physical model (per station, time t):
  • temperature: daily mean + 4 °C diurnal sine peaking ~15:00 local SOLAR
    time, anchored to the station's cached Open-Meteo reference value
  • humidity: derived from temperature and a slowly varying DEW POINT, so
    T / RH / Td stay psychrometrically consistent (Layer 3 relies on this)
  • pressure: MSL reference + semidiurnal atmospheric tide
  • wind: reference speed modulated diurnally, AR(1) gusts
  • a spatially coherent regional anomaly per 1° cell (AR(1), τ = 3 h), so
    neighbours move together like real weather
  • fixed per-station microclimate offsets (±0.6 °C, ±0.3 hPa) and
    measurement noise, quantised to realistic sensor resolution
    (T 0.1 °C, RH 0.1 %, P 0.01 hPa digital barometer, wind 0.1 km/h)

Faults (FaultBook) are applied on top of the clean signal, so a detection is
always an engine verdict about a known, injected ground truth.
"""
import hashlib
import math
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.pipeline.models import ObservationIn
from engine.layer4_spatial import haversine_distance_km

from .base import OBSERVATION, SourceAdapter

SIM_SOURCE = "SIMULATED_AWS"

RESOLUTION = {"temperature": 0.1, "humidity": 0.1, "pressure": 0.01, "wind_speed": 0.1, "wind_direction": 1.0,
              "dew_point": 0.1}

# ── fault catalogue ─────────────────────────────────────────────────────
SEVERITIES = ("low", "medium", "high")

FAULT_TYPES: Dict[str, Dict[str, Any]] = {
    "spike": {
        "label": "Sudden spike / step change",
        "parameters": ["temperature", "humidity", "pressure"],
        "expected_layers": ["L2", "L4"],
        "expected_interpretation": "likely_sensor_fault",
        "description": "Isolated step offset on one channel. Neighbours are unaffected, so L4 isolates the station.",
        "magnitude": {"temperature": (5.0, 9.0, 15.0), "humidity": (-25.0, -40.0, -60.0), "pressure": (4.0, 8.0, 15.0)},
    },
    "stuck": {
        "label": "Stuck sensor",
        "parameters": ["temperature", "humidity", "pressure"],
        "expected_layers": ["L2"],
        "expected_interpretation": "likely_sensor_fault",
        "description": "The channel freezes at its current value. L2 persistence needs the frozen run to span the configured minimum time.",
    },
    "drift": {
        "label": "Gradual calibration drift",
        "parameters": ["temperature", "humidity", "pressure"],
        "expected_layers": ["L4", "L5", "L2"],
        "expected_interpretation": "likely_sensor_fault",
        "description": "A linearly growing bias. CUSUM (L5) and the widening gap to neighbours (L4) catch it before a threshold would.",
        "magnitude": {"temperature": (1.5, 3.0, 6.0), "humidity": (6.0, 12.0, 24.0), "pressure": (1.5, 3.0, 6.0)},  # per hour
    },
    "impossible_rh": {
        "label": "Physically impossible RH",
        "parameters": ["humidity"],
        "expected_layers": ["L1"],
        "expected_interpretation": "likely_sensor_fault",
        "description": "Relative humidity above 100 % — a hard physics veto regardless of weather.",
        "magnitude": {"humidity": (103.0, 115.0, 140.0)},
    },
    "t_rh_inconsistency": {
        "label": "Temperature / humidity inconsistency",
        "parameters": ["humidity"],
        "expected_layers": ["L1"],
        "expected_interpretation": "likely_sensor_fault",
        "description": ("The hygrometer's reported dew point rises above the measured air temperature — the "
                        "thermometer and hygrometer disagree in a thermodynamically impossible way."),
        "magnitude": {"dew_point": (1.5, 3.0, 5.0)},
    },
    "missing": {
        "label": "Missing parameter",
        "parameters": ["temperature", "humidity", "pressure"],
        "expected_layers": [],
        "expected_interpretation": "degraded data",
        "description": "The channel stops reporting. The station keeps transmitting other parameters and is marked degraded.",
    },
    "dropout": {
        "label": "Communication dropout",
        "parameters": [],
        "expected_layers": [],
        "expected_interpretation": "communication_issue",
        "description": "The station stops transmitting entirely. The freshness monitor marks it stale, then opens a communication incident.",
    },
    "regional_event": {
        "label": "Regional weather event (control)",
        "parameters": [],
        "expected_layers": ["L2"],
        "expected_interpretation": "likely_weather_event",
        "description": "A gust-front passage cools every station within the radius at once. L2 fires, but L4 finds neighbours agree — ATHER should call it weather, not a sensor fault.",
        "magnitude": {"temperature": (-3.5, -6.0, -9.0), "pressure": (1.0, 2.0, 3.0), "wind_speed": (10.0, 25.0, 45.0)},
        "radius_km": (25.0, 40.0, 60.0),
    },
}


@dataclass
class InjectedFault:
    fault_id: str
    station_id: str
    fault_type: str
    parameter: Optional[str]
    severity: str
    started_at: float
    duration_s: float
    radius_km: Optional[float] = None
    center: Optional[Tuple[float, float]] = None
    state: str = "ACTIVE"
    anchor: Dict[str, float] = field(default_factory=dict)
    affected_station_ids: List[str] = field(default_factory=list)
    created_by: str = "operator"

    @property
    def ends_at(self) -> float:
        return self.started_at + self.duration_s

    def active_at(self, t: float) -> bool:
        return self.state == "ACTIVE" and self.started_at <= t < self.ends_at

    def meta(self) -> Dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "fault_type": self.fault_type,
            "label": FAULT_TYPES[self.fault_type]["label"],
            "parameter": self.parameter,
            "severity": self.severity,
            "started_at": datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
            "origin_station_id": self.station_id,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["label"] = FAULT_TYPES[self.fault_type]["label"]
        d["started_at_iso"] = datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat()
        d["ends_at_iso"] = datetime.fromtimestamp(self.ends_at, tz=timezone.utc).isoformat()
        d["expected_layers"] = FAULT_TYPES[self.fault_type]["expected_layers"]
        d["expected_interpretation"] = FAULT_TYPES[self.fault_type]["expected_interpretation"]
        return d


class FaultBook:
    """Thread-safe registry of injected faults (API threads write, the
    generator reads)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._faults: Dict[str, InjectedFault] = {}

    def inject(
        self,
        station_id: str,
        fault_type: str,
        parameter: Optional[str],
        severity: str,
        duration_s: float,
        started_at: Optional[float] = None,
        station_latlon: Optional[Tuple[float, float]] = None,
        radius_km: Optional[float] = None,
    ) -> InjectedFault:
        spec = FAULT_TYPES.get(fault_type)
        if not spec:
            raise ValueError(f"Unknown fault type '{fault_type}'. Known: {sorted(FAULT_TYPES)}")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        if spec["parameters"]:
            parameter = parameter or spec["parameters"][0]
            if parameter not in spec["parameters"]:
                raise ValueError(f"{fault_type} supports parameters {spec['parameters']}")
        else:
            parameter = None
        if not (30 <= duration_s <= 24 * 3600):
            raise ValueError("duration must be between 30 seconds and 24 hours")
        if fault_type == "regional_event":
            radius_km = radius_km or spec["radius_km"][SEVERITIES.index(severity)]
        f = InjectedFault(
            fault_id="flt_" + uuid.uuid4().hex[:10],
            station_id=station_id,
            fault_type=fault_type,
            parameter=parameter,
            severity=severity,
            started_at=started_at if started_at is not None else time.time(),
            duration_s=float(duration_s),
            radius_km=radius_km,
            center=station_latlon,
        )
        with self._lock:
            self._faults[f.fault_id] = f
        return f

    def cancel(self, fault_id: str) -> Optional[InjectedFault]:
        with self._lock:
            f = self._faults.get(fault_id)
            if f and f.state == "ACTIVE":
                f.state = "CANCELLED"
            return f

    def expire(self, now: float) -> List[InjectedFault]:
        """Marks faults past their end time EXPIRED; returns the newly expired."""
        out = []
        with self._lock:
            for f in self._faults.values():
                if f.state == "ACTIVE" and now >= f.ends_at:
                    f.state = "EXPIRED"
                    out.append(f)
        return out

    def list(self, active_only: bool = False) -> List[InjectedFault]:
        with self._lock:
            items = list(self._faults.values())
        items.sort(key=lambda f: f.started_at, reverse=True)
        return [f for f in items if f.state == "ACTIVE"] if active_only else items[:50]

    def for_station(self, station_id: str, lat: float, lon: float, t: float) -> List[InjectedFault]:
        with self._lock:
            items = list(self._faults.values())
        out = []
        for f in items:
            if not f.active_at(t):
                continue
            if f.fault_type == "regional_event" and f.center:
                if haversine_distance_km(lat, lon, f.center[0], f.center[1]) <= (f.radius_km or 0):
                    out.append(f)
            elif f.station_id == station_id:
                out.append(f)
        return out


# ── clean-signal generator ──────────────────────────────────────────────
def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _dew_point(t: float, rh: float) -> float:
    a, b = 17.62, 243.12
    rh = min(100.0, max(1.0, rh))
    g = math.log(rh / 100.0) + a * t / (b + t)
    return b * g / (a - g)


def _rh_from(t: float, td: float) -> float:
    a, b = 17.62, 243.12
    return 100.0 * math.exp(a * td / (b + td) - a * t / (b + t))


def _q(value: Optional[float], step: float) -> Optional[float]:
    if value is None:
        return None
    return round(round(value / step) * step, 4)


def _solar_hour(t: float, lon: float) -> float:
    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    return (dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + lon / 15.0) % 24.0


def _diurnal(h: float) -> float:
    return math.sin(2.0 * math.pi * (h - 9.0) / 24.0)


def _tide(h: float) -> float:
    return math.cos(2.0 * math.pi * (h - 10.0) / 12.0)


@dataclass
class SimStation:
    station_id: str
    name: str
    lat: float
    lon: float
    elevation: float
    t_mean: float
    td_mean: float
    p_base: float
    wind_mean: float
    wind_dir: float
    precip: float
    offset_t: float
    offset_td: float
    offset_p: float


class SyntheticNetwork:
    DIURNAL_AMPLITUDE_C = 4.0
    TIDE_AMPLITUDE_HPA = 1.1
    TAU_S = 3 * 3600.0

    def __init__(self, stations: List[SimStation], seed: int = 7):
        self.stations = {s.station_id: s for s in stations}
        self.rng = random.Random(seed)
        # Smooth synoptic field: a few large-scale waves (wavelength ≥ 600 km)
        # with AR(1) amplitudes, so stations 20 km apart see almost the same
        # regional anomaly — like real weather, unlike per-cell noise.
        self._modes = []
        for var, sigma in (("t", 0.8), ("td", 0.8), ("p", 0.6)):
            for _ in range(4):
                wl_km = self.rng.uniform(600.0, 1500.0)
                theta = self.rng.uniform(0, 2 * math.pi)
                k = 2 * math.pi / (wl_km / 111.0)
                self._modes.append({"var": var, "kx": k * math.cos(theta), "ky": k * math.sin(theta),
                                    "phi": self.rng.uniform(0, 2 * math.pi), "a": 0.0, "sigma": sigma / math.sqrt(2)})
        self._regional_cache: Dict[str, Dict[str, float]] = {}
        self._wind_ar: Dict[str, float] = {}
        self._last_t: Optional[float] = None

    def _advance_regional(self, t: float) -> None:
        dt = 60.0 if self._last_t is None else max(1.0, t - self._last_t)
        self._last_t = t
        r = math.exp(-dt / self.TAU_S)
        k = math.sqrt(max(0.0, 1.0 - r * r))
        for m in self._modes:
            m["a"] = r * m["a"] + k * self.rng.gauss(0, m["sigma"])
        self._regional_cache = {}

    def _cell(self, s: SimStation) -> Dict[str, float]:
        cached = self._regional_cache.get(s.station_id)
        if cached is not None:
            return cached
        out = {"t": 0.0, "td": 0.0, "p": 0.0}
        for m in self._modes:
            out[m["var"]] += m["a"] * math.cos(m["kx"] * s.lon + m["ky"] * s.lat + m["phi"])
        self._regional_cache[s.station_id] = out
        return out

    @staticmethod
    def from_station_dicts(stations: List[Dict[str, Any]], reference_lookup) -> "SyntheticNetwork":
        out = []
        for s in stations:
            ref = reference_lookup(s) or {}
            lat, lon = float(s["latitude"]), float(s["longitude"])
            t_ref = ref.get("temperature")
            rh_ref = ref.get("humidity")
            t_ref = 28.0 if t_ref is None else float(t_ref)
            rh_ref = 65.0 if rh_ref is None else float(rh_ref)
            ts = ref.get("timestamp")
            try:
                t_obs = datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc).timestamp() if ts else time.time()
            except ValueError:
                t_obs = time.time()
            h_ref = _solar_hour(t_obs, lon)
            t_mean = t_ref - SyntheticNetwork.DIURNAL_AMPLITUDE_C * _diurnal(h_ref)
            td = _dew_point(t_ref, rh_ref)
            p_ref = ref.get("pressure")
            p_ref = 1009.0 if p_ref is None or p_ref < 900 else float(p_ref)
            p_base = p_ref - SyntheticNetwork.TIDE_AMPLITUDE_HPA * _tide(h_ref)
            r = random.Random(_seed("offsets", s["id"]))
            out.append(SimStation(
                station_id=s["id"], name=s.get("name", s["id"]), lat=lat, lon=lon,
                elevation=float(s.get("elevation") or 0.0),
                t_mean=t_mean, td_mean=td, p_base=p_base,
                wind_mean=float(ref.get("windSpeed") or 8.0), wind_dir=float(ref.get("windDirectionDeg") or 240.0),
                precip=float(ref.get("precipitation") or 0.0),
                offset_t=r.uniform(-0.6, 0.6), offset_td=r.uniform(-0.8, 0.8), offset_p=r.uniform(-0.3, 0.3),
            ))
        return SyntheticNetwork(out)

    def clean(self, s: SimStation, t: float) -> Dict[str, Optional[float]]:
        h = _solar_hour(t, s.lon)
        reg = self._cell(s)
        temp = s.t_mean + self.DIURNAL_AMPLITUDE_C * _diurnal(h) + s.offset_t + reg["t"] + self.rng.gauss(0, 0.05)
        td = s.td_mean + s.offset_td + reg["td"] + self.rng.gauss(0, 0.08)
        td = min(td, temp - 0.3)
        rh = _rh_from(temp, td)
        pres = s.p_base + self.TIDE_AMPLITUDE_HPA * _tide(h) + s.offset_p + reg["p"] + self.rng.gauss(0, 0.03)
        ar = 0.85 * self._wind_ar.get(s.station_id, 0.0) + self.rng.gauss(0, 1.2)
        self._wind_ar[s.station_id] = ar
        wind = max(0.0, s.wind_mean * (1.0 + 0.3 * _diurnal(h)) + ar)
        wdir = (s.wind_dir + 12.0 * ar) % 360.0
        rain = 0.0
        if s.precip > 0 and self.rng.random() < 0.3:
            rain = round(self.rng.choice((0.2, 0.2, 0.4, 0.6)), 1)
        return {"temperature": temp, "humidity": rh, "pressure": pres, "wind_speed": wind,
                "wind_direction": wdir, "rainfall": rain, "dew_point": None}

    def generate(self, t: float, faults: Optional[FaultBook] = None,
                 station_ids: Optional[List[str]] = None) -> Dict[str, Tuple[Optional[Dict[str, Optional[float]]], List[Dict[str, Any]]]]:
        """Returns {station_id: (values | None if dropped out, [fault meta])}."""
        self._advance_regional(t)
        out = {}
        for sid in (station_ids or list(self.stations)):
            s = self.stations[sid]
            values = self.clean(s, t)
            metas: List[Dict[str, Any]] = []
            dropped = False
            active = faults.for_station(sid, s.lat, s.lon, t) if faults is not None else []
            for f in active:
                dropped = apply_fault(f, s, values, t) or dropped
                metas.append(f.meta())
            # The station reports the dew point its hygrometer derives from the
            # (possibly faulty) T and RH — unless the fault is in that derivation.
            if not any(f.fault_type == "t_rh_inconsistency" for f in active):
                tt, rr = values.get("temperature"), values.get("humidity")
                values["dew_point"] = _dew_point(tt, rr) if tt is not None and rr is not None and 0 < rr <= 100 else None
            if dropped:
                out[sid] = (None, metas)
                continue
            for k, step in RESOLUTION.items():
                values[k] = _q(values.get(k), step)
            out[sid] = (values, metas)
        return out


def apply_fault(f: InjectedFault, s: SimStation, v: Dict[str, Optional[float]], t: float) -> bool:
    """Mutates v in place. Returns True if the station is silent (dropout)."""
    i = SEVERITIES.index(f.severity)
    mag = FAULT_TYPES[f.fault_type].get("magnitude", {})
    p = f.parameter
    elapsed_h = (t - f.started_at) / 3600.0
    if f.fault_type == "dropout":
        return True
    if f.fault_type == "missing":
        v[p] = None
    elif f.fault_type == "stuck":
        key = f"{s.station_id}:{p}"
        if key not in f.anchor and v.get(p) is not None:
            f.anchor[key] = _q(v[p], RESOLUTION[p])
        v[p] = f.anchor.get(key)
    elif f.fault_type == "spike":
        if v.get(p) is not None:
            v[p] = v[p] + mag[p][i]
    elif f.fault_type == "drift":
        if v.get(p) is not None:
            v[p] = v[p] + mag[p][i] * elapsed_h
    elif f.fault_type == "impossible_rh":
        v["humidity"] = mag["humidity"][i]
    elif f.fault_type == "t_rh_inconsistency":
        if v.get("temperature") is not None:
            v["dew_point"] = v["temperature"] + mag["dew_point"][i]
    elif f.fault_type == "regional_event":
        # Abrupt gust-front onset, gradual recovery over the last 40 % of the event.
        frac_left = (f.ends_at - t) / f.duration_s
        scale = 1.0 if frac_left > 0.4 else max(0.0, frac_left / 0.4)
        jitter = 0.85 + 0.3 * (_seed(f.fault_id, s.station_id) % 1000) / 1000.0
        if v.get("temperature") is not None and v.get("humidity") is not None:
            td = _dew_point(v["temperature"], v["humidity"])  # moist outflow keeps its dew point
            v["temperature"] = v["temperature"] + mag["temperature"][i] * scale * jitter
            rh = _rh_from(v["temperature"], min(td, v["temperature"] - 0.2))
            # A saturated hygrometer still fluctuates (±0.5 %), it never flat-lines.
            v["humidity"] = min(100.0, rh + random.gauss(0.0, 0.5))
        if v.get("pressure") is not None:
            v["pressure"] = v["pressure"] + mag["pressure"][i] * scale * jitter
        if v.get("wind_speed") is not None:
            v["wind_speed"] = v["wind_speed"] + mag["wind_speed"][i] * scale * jitter
        if s.station_id not in f.affected_station_ids:
            f.affected_station_ids.append(s.station_id)
    return False


def expected_time_to_detection(fault_type: str, cadence_s: float, frozen_min_span_min: float) -> str:
    if fault_type in ("spike", "impossible_rh", "t_rh_inconsistency", "regional_event"):
        return f"next observation (≤ {int(cadence_s)} s)"
    if fault_type == "stuck":
        return f"≥ {int(frozen_min_span_min)} min (time-based persistence test)"
    if fault_type == "drift":
        return "several observations — depends on drift rate vs. neighbour spread"
    if fault_type == "missing":
        return f"next observation (≤ {int(cadence_s)} s) — station marked degraded"
    if fault_type == "dropout":
        return f"stale after {int(3 * cadence_s)} s, incident after {int(5 * cadence_s)} s"
    return "—"


# ── adapter ─────────────────────────────────────────────────────────────
class SimulationAdapter(SourceAdapter):
    name = "simulation"
    label = "ATHER simulated AWS feed"
    kind = OBSERVATION
    simulated = True

    def __init__(self, station_service, faults: FaultBook, interval_s: float = 60.0,
                 max_stations: Optional[int] = None, reference_lookup=None):
        self.cadence_s = interval_s
        super().__init__()
        self.stations_svc = station_service
        self.faults = faults
        self.max_stations = max_stations
        self.reference_lookup = reference_lookup or (lambda s: None)
        self.network: Optional[SyntheticNetwork] = None
        self.status.note = (f"Simulated telemetry for real WeatherUnion AWS locations, one observation per "
                            f"station every {int(interval_s)} s. Not measured data.")

    def catalogue(self) -> List[Dict[str, Any]]:
        stations = [s for s in list(self.stations_svc._stations.values())
                    if s.get("localityId") and s.get("country") == "India"
                    and s.get("latitude") is not None and s.get("longitude") is not None]
        stations.sort(key=lambda s: s["id"])
        return stations[: self.max_stations] if self.max_stations else stations

    def ensure_network(self) -> SyntheticNetwork:
        if self.network is None:
            self.network = SyntheticNetwork.from_station_dicts(self.catalogue(), self.reference_lookup)
        return self.network

    def station_ids(self) -> List[str]:
        return list(self.ensure_network().stations)

    async def poll(self) -> List[ObservationIn]:
        net = self.ensure_network()
        now = float(int(time.time()))
        observed = datetime.fromtimestamp(now, tz=timezone.utc)
        items = []
        for sid, (values, metas) in net.generate(now, self.faults).items():
            if values is None:
                continue  # communication dropout: nothing transmitted
            meta = {"injected_fault": metas[0] if len(metas) == 1 else metas} if metas else {}
            items.append(ObservationIn(
                station_id=sid, observed_at=observed, source=SIM_SOURCE, adapter=self.name,
                meta=meta, **values,
            ))
        return items
