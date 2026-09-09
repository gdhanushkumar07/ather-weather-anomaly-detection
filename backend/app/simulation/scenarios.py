"""
ATHER Test Lab — Predefined Fault-Injection Scenarios
======================================================
Ten ready-to-run scenarios (Phase 8 of the Test Lab spec). Each scenario
defines a sequence of synthetic observations (and, where relevant, synthetic
neighbor readings) plus an "expected bucket" used ONLY to compute the
PASS / DIFFERENT-FROM-EXPECTED comparison shown to the user.

IMPORTANT: the expected bucket is a hypothesis label for the test-result
comparison. It is NEVER used to fabricate the actual diagnostic result — the
real result always comes from running these observations through the real
ATHER AnomalyDetector (see service.py). If the real engine disagrees with the
hypothesis, the Test Lab must say so honestly rather than forcing a PASS.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ScenarioStep:
    temperature_c: Optional[float] = None
    pressure_hpa:  Optional[float] = None
    humidity_pct:  Optional[float] = None


@dataclass
class NeighborOffset:
    """A synthetic neighbor station relative to the target, at a fixed small
    lat/lon offset, carrying its own observation sequence (same length as the
    target's steps, or a single static reading repeated for every step)."""
    lat_offset: float
    lon_offset: float
    steps: List[ScenarioStep]


@dataclass
class Scenario:
    id: str
    name: str
    description: str
    steps: List[ScenarioStep]
    interval_minutes: float = 10.0
    neighbors: List[NeighborOffset] = field(default_factory=list)
    # Hypothesis only — see module docstring.
    expected_bucket: str = "LIKELY_SENSOR_ANOMALY"
    expected_root_cause_hint: str = ""


# Default baseline used when no real station is selected to inherit from.
DEFAULT_BASELINE = ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0)


def _flat(value: float, n: int, field_name: str) -> List[ScenarioStep]:
    return [ScenarioStep(**{field_name: value}) for _ in range(n)]


SCENARIOS: Dict[str, Scenario] = {
    "TEMPERATURE_SPIKE": Scenario(
        id="TEMPERATURE_SPIKE",
        name="Temperature Spike",
        description="A sudden, physically implausible jump in a single reading after several stable baseline readings.",
        steps=[
            ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0),
            ScenarioStep(temperature_c=32.1, pressure_hpa=1013.0, humidity_pct=55.0),
            ScenarioStep(temperature_c=31.9, pressure_hpa=1013.0, humidity_pct=55.0),
            # +11.5C jump: a dramatic, clearly anomalous spike, but deliberately
            # kept under BOTH the hard temperature veto bound (50C) AND the
            # wet-bulb survivability veto (35C, which a large temp+humidity
            # combination can trip well below 50C) so this scenario cleanly
            # exercises the temporal/spatial SPIKE evidence path rather than
            # the physics-impossibility veto path (that combination is covered
            # separately by IMPOSSIBLE_HUMIDITY / PRESSURE_SPIKE / COMBINED_SENSOR_FAILURE).
            ScenarioStep(temperature_c=43.5, pressure_hpa=1013.0, humidity_pct=55.0),
        ],
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="SENSOR_SPIKE / SINGLE_CHANNEL_FAULT",
    ),
    "FROZEN_TEMPERATURE_SENSOR": Scenario(
        id="FROZEN_TEMPERATURE_SENSOR",
        name="Frozen Temperature Sensor",
        description="The same exact temperature value repeated across many consecutive observations (stuck ADC / sensor lockup).",
        steps=_flat(32.1, 14, "temperature_c"),
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="FROZEN_SENSOR",
    ),
    "TEMPERATURE_SENSOR_DRIFT": Scenario(
        id="TEMPERATURE_SENSOR_DRIFT",
        name="Temperature Sensor Drift",
        description=(
            "A slow, monotonic upward creep in temperature (+0.4C every ~10 minutes) "
            "consistent with calibration drift rather than a sudden fault. The CUSUM "
            "drift detector needs a meaningful run of samples before a conclusion is "
            "possible — this scenario runs 20 observations so the real accumulation is visible."
        ),
        steps=[
            # Small realistic jitter on pressure/humidity so they don't
            # incidentally read as a SEPARATE frozen-sensor fault — this
            # scenario is specifically about the temperature channel's drift.
            ScenarioStep(
                temperature_c=round(32.0 + 0.4 * i, 1),
                pressure_hpa=round(1013.0 + 0.05 * ((i % 5) - 2), 2),
                humidity_pct=round(55.0 + 0.1 * ((i % 3) - 1), 2),
            )
            for i in range(20)
        ],
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="CALIBRATION_DRIFT",
    ),
    "IMPOSSIBLE_HUMIDITY": Scenario(
        id="IMPOSSIBLE_HUMIDITY",
        name="Impossible Humidity",
        description="Relative humidity reported above 100% — a physically impossible value that must fail data-quality/physics validation, not be treated as valid weather.",
        steps=[ScenarioStep(temperature_c=30.0, pressure_hpa=1012.0, humidity_pct=135.0)],
        expected_bucket="DATA_QUALITY_VIOLATION",
        expected_root_cause_hint="Physics veto (impossible humidity)",
    ),
    "PRESSURE_SPIKE": Scenario(
        id="PRESSURE_SPIKE",
        name="Pressure Spike",
        description="A single implausible barometric pressure reading against an otherwise stable series.",
        steps=[
            ScenarioStep(temperature_c=28.0, pressure_hpa=p, humidity_pct=60.0)
            for p in [1012.0, 1012.0, 1013.0, 1014.0, 1075.0, 1013.0]
        ],
        # The 1075 hPa reading itself violates the hard physical bound (a
        # transient physics veto — visible in the observations list at the
        # step it occurs), but the sequence recovers to a normal 1013 hPa by
        # the final reading. The FINAL diagnosis is therefore correctly
        # temporal-evidence-driven (a sensor spike that already resolved),
        # not a standing physics violation.
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="SENSOR_SPIKE (transient physics veto visible mid-sequence)",
    ),
    "MISSING_TELEMETRY": Scenario(
        id="MISSING_TELEMETRY",
        name="Missing Telemetry",
        description="Only one channel is reported and there is no observation history — ATHER must report insufficient evidence, not fabricate a fault.",
        steps=[ScenarioStep(temperature_c=29.0, pressure_hpa=None, humidity_pct=None)],
        # A single valid, unremarkable channel with no history is correctly
        # NORMAL overall (physics passes, nothing anomalous was observed) —
        # the mission-critical property is that per-LAYER diagnostics show
        # INSUFFICIENT_DATA for temporal/multivariate/spatial/sensor_health,
        # and that root cause is NEVER a fabricated hardware fault.
        expected_bucket="NORMAL",
        expected_root_cause_hint="NORMAL overall; temporal/multivariate/spatial/sensor_health report INSUFFICIENT_DATA",
    ),
    "MULTIVARIATE_INCONSISTENCY": Scenario(
        id="MULTIVARIATE_INCONSISTENCY",
        name="Multivariate Inconsistency",
        description="Temperature, pressure, and humidity are each individually plausible, but the joint combination (high heat with near-saturated humidity) is physically rare. Kept below the wet-bulb survivability veto so this isolates the MULTIVARIATE layer's joint-state check specifically.",
        steps=[
            ScenarioStep(temperature_c=30.0, pressure_hpa=1013.0, humidity_pct=60.0),
            ScenarioStep(temperature_c=31.5, pressure_hpa=1012.0, humidity_pct=70.0),
            ScenarioStep(temperature_c=33.0, pressure_hpa=1013.0, humidity_pct=96.0),
        ],
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="Multivariate (Clausius-Clapeyron) inconsistency",
    ),
    "SPATIAL_OUTLIER": Scenario(
        id="SPATIAL_OUTLIER",
        name="Spatial Outlier",
        description="The target station reports 45°C while nearby AWS stations all report 31-34°C — a single-station divergence with no regional support. Kept under the physics hard-veto bound so this scenario cleanly isolates SPATIAL evidence rather than also tripping a physics veto (that combination is covered by COMBINED_SENSOR_FAILURE).",
        steps=[ScenarioStep(temperature_c=45.0, pressure_hpa=1013.0, humidity_pct=45.0)],
        neighbors=[
            NeighborOffset(0.3, 0.2, [ScenarioStep(temperature_c=31.0, pressure_hpa=1013.0, humidity_pct=48.0)]),
            NeighborOffset(-0.25, 0.35, [ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=47.0)]),
            NeighborOffset(0.4, -0.3, [ScenarioStep(temperature_c=33.0, pressure_hpa=1012.0, humidity_pct=46.0)]),
            NeighborOffset(-0.35, -0.2, [ScenarioStep(temperature_c=34.0, pressure_hpa=1013.0, humidity_pct=45.0)]),
        ],
        expected_bucket="LIKELY_SENSOR_ANOMALY",
        expected_root_cause_hint="SINGLE_CHANNEL_FAULT (spatial outlier)",
    ),
    "REGIONAL_WEATHER_EVENT": Scenario(
        id="REGIONAL_WEATHER_EVENT",
        name="Regional Weather Event",
        description=(
            "The target station jumps +6C in one interval — enough to trip the TEMPORAL "
            "layer on its own — but every nearby station jumps by a similar amount at the "
            "same time, so the SPATIAL layer finds the target fully consistent with its "
            "regional neighbors. This is the key distinguishing pattern for a genuine "
            "weather event rather than an isolated sensor fault."
        ),
        steps=[
            ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0),
            ScenarioStep(temperature_c=38.0, pressure_hpa=1011.0, humidity_pct=48.0),
        ],
        neighbors=[
            NeighborOffset(0.3, 0.2, [
                ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0),
                ScenarioStep(temperature_c=38.5, pressure_hpa=1011.0, humidity_pct=49.0),
            ]),
            NeighborOffset(-0.25, 0.3, [
                ScenarioStep(temperature_c=33.0, pressure_hpa=1013.0, humidity_pct=54.0),
                ScenarioStep(temperature_c=39.0, pressure_hpa=1011.0, humidity_pct=48.0),
            ]),
            NeighborOffset(0.35, -0.3, [
                ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=56.0),
                ScenarioStep(temperature_c=38.0, pressure_hpa=1011.0, humidity_pct=49.0),
            ]),
            NeighborOffset(-0.3, -0.25, [
                ScenarioStep(temperature_c=34.0, pressure_hpa=1013.0, humidity_pct=53.0),
                ScenarioStep(temperature_c=40.0, pressure_hpa=1011.0, humidity_pct=47.0),
            ]),
        ],
        expected_bucket="POSSIBLE_WEATHER_EVENT",
        expected_root_cause_hint="GENUINE_EXTREME_WEATHER / POSSIBLE_WEATHER_CHANGE",
    ),
    "COMBINED_SENSOR_FAILURE": Scenario(
        id="COMBINED_SENSOR_FAILURE",
        name="Combined Sensor Failure",
        description=(
            "Temperature spike, extreme humidity inconsistency, and a temporal "
            "discontinuity occur together with NO regional support from neighbors. This "
            "combination is severe enough to also trip the physics wet-bulb survivability "
            "veto — the strongest possible multi-layer agreement that something is wrong."
        ),
        steps=[
            ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0),
            ScenarioStep(temperature_c=32.1, pressure_hpa=1013.0, humidity_pct=54.0),
            ScenarioStep(temperature_c=40.0, pressure_hpa=1013.0, humidity_pct=90.0),
        ],
        neighbors=[
            NeighborOffset(0.3, 0.2, [ScenarioStep(temperature_c=32.0, pressure_hpa=1013.0, humidity_pct=55.0)] * 3),
            NeighborOffset(-0.25, 0.3, [ScenarioStep(temperature_c=33.0, pressure_hpa=1013.0, humidity_pct=54.0)] * 3),
        ],
        expected_bucket="DATA_QUALITY_VIOLATION",
        expected_root_cause_hint="Physics veto (wet-bulb) + temporal + multivariate + spatial all agreeing",
    ),
}


def list_scenarios() -> List[Dict[str, Any]]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "step_count": len(s.steps),
            "expected_bucket": s.expected_bucket,
            "expected_root_cause_hint": s.expected_root_cause_hint,
        }
        for s in SCENARIOS.values()
    ]


def get_scenario(scenario_id: str) -> Optional[Scenario]:
    return SCENARIOS.get(scenario_id)
